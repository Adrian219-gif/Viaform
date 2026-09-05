"""Isolated DeepSeek Responses experiment; never imports Viaform application code.

Run with the existing backend environment. Results are written only when --output
is supplied. Baselines are loaded AFTER inference and never enter API payloads.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, ValidationError

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "kth": {
        "university": "KTH Royal Institute of Technology",
        "programme": "Master's Programme in Computer Science",
        "url": "https://www.kth.se/en/studies/master/computer-science",
        "domain": "kth.se",
    },
    "oxford": {
        "university": "University of Oxford",
        "programme": "MSc Advanced Computer Science",
        "url": "https://www.ox.ac.uk/admissions/graduate/courses/msc-advanced-computer-science",
        "domain": "ox.ac.uk",
    },
}


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["academic", "course", "language", "standardized_test", "experience", "materials", "other"]
    requirement: str
    importance: Literal["required", "recommended", "preferred", "unknown"]
    status: Literal["confirmed", "unknown"]
    source_url: Optional[str]
    evidence_excerpt: Optional[str]
    programme_applicability: Literal["explicit_programme", "programme_linked_general", "unknown"]
    source_cycle: Optional[str]
    temporal_applicability: Literal["target_cycle_confirmed", "previous_cycle", "undated", "unknown"]
    uncertainty: Optional[str]


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    university: str
    programme: str
    requested_admission_cycle: str
    observed_admission_cycle: Optional[str]
    cycle_status: Literal["confirmed", "previous_cycle_only", "unknown"]
    requirements: List[Requirement]
    unknowns: List[str]


STOPPING_CRITERION = (
    "仅使用 KTH 官方来源。找到 exact programme-level page 后，自主搜索并提取当前目标申请周期的申请要求和申请材料。"
    "一旦现有官方来源已经足以覆盖主要 Requirements，就立即停止继续搜索。"
    "不要为了重复确认已经得到官方证据支持的事实继续搜索。"
    "无法确认的信息返回 unknown，不要猜测。"
)


SOFT_SEARCH_BUDGET = "本次任务中 Web Search 工具调用总计最多 4 次。请自行决定搜索 query 和路径，并在信息足够时提前停止。"


def payload(case: dict, model: str, stopping_criterion: bool = False, soft_max_four: bool = False) -> dict:
    # Programme identity only: no baseline requirements, thresholds, or gold facts.
    prompt = (
        f"Today is {datetime.now(timezone.utc).date()}. Retrieve admission requirements "
        f"for {case['university']}, {case['programme']}, requested entry Fall 2027 "
        f"(academic year 2027-28). Starting official programme URL: {case['url']}. "
        f"Use built-in web search autonomously. Accept evidence only from {case['domain']} "
        "or its subdomains. Return only requirements applicable to this exact programme, "
        "not nearby degrees or generic university rules without explicit programme linkage. "
        "Cover all applicable eligibility, prerequisites, tests and application materials; "
        "retain exact thresholds, quantities, alternatives, exemptions and conditions. "
        "Exclude degree-completion requirements and marketing content. For each item give "
        "its official source URL and a short supporting excerpt. Distinguish source admission "
        "cycle from the requested cycle; never silently promote previous-cycle or undated "
        "evidence to confirmed Fall 2027 rules. When evidence or applicability cannot be "
        "confirmed, report unknown explicitly, without guessing or relying on model memory. "
        "Unknown items may have null source_url; they are not accepted factual requirements. "
        "Return JSON conforming to the supplied schema."
    )
    return {
        "model": model,
        "input": prompt + ("\n\n" + STOPPING_CRITERION if stopping_criterion else "") + ("\n\n" + SOFT_SEARCH_BUDGET if soft_max_four else ""),
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "reasoning": {"effort": "high"},
        "max_output_tokens": 20000,
        "text": {"format": {"type": "json_schema", "name": "programme_requirements", "schema": Requirements.model_json_schema()}},
    }


def is_official(url: str | None, domain: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (host == domain or host.endswith("." + domain))


def run_case(name: str, model: str, key: str, timeout: float, stopping_criterion: bool = False, soft_max_four: bool = False) -> dict:
    case = CASES[name]
    request = payload(case, model, stopping_criterion, soft_max_four)
    result = {"case": name, "request_payload": request, "deepseek_http_requests": 1,
              "server_model_call_count": None, "web_search_call_count": None, "usage": None}
    started = time.perf_counter()
    try:
        # No retries, custom tools, direct fetch, or application/cache imports.
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post("https://api.deepseek.com/responses", json=request,
                                   headers={"Authorization": f"Bearer {key}"})
        result["total_seconds"] = round(time.perf_counter() - started, 3)
        result["http_status"] = response.status_code
        if response.status_code != 200:
            result["error"] = response.text[:2000].replace(key, "[REDACTED]")
            return result
        body = response.json()
        # Do not persist or print reasoning text. Keep final answer/tool telemetry only.
        output = body.get("output", [])
        result["output_item_types"] = [item.get("type") for item in output]
        result["message_content_types"] = [
            [part.get("type") for part in item.get("content", [])]
            for item in output if item.get("type") == "message"
        ]
        calls = [item for item in output if item.get("type") == "web_search_call"]
        result.update(response_id=body.get("id"), response_status=body.get("status"),
                      usage=body.get("usage"), web_search_call_count=len(calls),
                      web_search_calls=calls, incomplete_details=body.get("incomplete_details"))
        messages = ["".join(part.get("text", "") for part in item.get("content", [])
                             if part.get("type") == "output_text")
                    for item in output if item.get("type") == "message"]
        result["message_texts"] = messages
        answer = messages[-1] if messages else ""
        result["output_text"] = answer
        try:
            parsed = Requirements.model_validate_json(answer)
        except ValidationError as error:
            result.update(schema_valid=False, validation_error=str(error))
            return result
        result["schema_valid"] = True
        result["result"] = parsed.model_dump()
        factual = [r for r in parsed.requirements if r.status == "confirmed"]
        accepted = [r for r in factual if is_official(r.source_url, case["domain"])
                    and r.programme_applicability != "unknown"]
        result["metrics"] = {
            "returned_count": len(parsed.requirements), "confirmed_count": len(factual),
            "accepted_count": len(accepted), "unknown_count": len(parsed.requirements) - len(factual),
            "official_domain_rate": sum(is_official(r.source_url, case["domain"]) for r in factual) / len(factual) if factual else None,
            "programme_applicability_self_reported_rate": sum(r.programme_applicability != "unknown" for r in factual) / len(factual) if factual else None,
            "cycle_correctness": "requires_independent_source_review",
            "correctness": "requires_independent_source_review",
            "completeness": "requires_posthoc_baseline_and_source_review",
        }
    except Exception as error:
        result["total_seconds"] = round(time.perf_counter() - started, 3)
        result["error"] = f"{type(error).__name__}: {error}".replace(key, "[REDACTED]")
    return result


def forensic_output(result: dict) -> dict:
    """Post-hoc inspection only: recovered JSON never counts as schema success."""
    text = result.get("output_text", "")
    candidates = []
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
            parsed = Requirements.model_validate(value)
        except (ValueError, ValidationError):
            continue
        candidates.append(parsed)
    if len(candidates) != 1:
        return {"candidate_objects": len(candidates), "result": None}
    parsed = candidates[0]
    factual = [item for item in parsed.requirements if item.status == "confirmed"]
    return {
        "candidate_objects": 1,
        "note": "Recovered for evaluation only; does not change original schema_valid verdict. " + (
            "output_text is the final assistant message; message boundaries were preserved."
            if "message_texts" in result else
            "First-run output_text aggregates assistant messages; message boundaries were not preserved."
        ),
        "result": parsed.model_dump(),
        "returned_count": len(parsed.requirements),
        "confirmed_count": len(factual),
        "official_domain_rate": sum(is_official(item.source_url, CASES[result['case']]['domain']) for item in factual) / len(factual) if factual else None,
    }


def posthoc_baselines() -> dict:
    # Intentionally called only after all model requests have finished.
    fixture = json.loads((ROOT / "backend/scripts/fixtures/requirements_capability_baseline.json").read_text(encoding="utf-8"))
    report = (ROOT / "docs/evals/mvp_eval_report.md").read_text(encoding="utf-8")
    sections = {}
    for name, case_id in (("kth", "CORE-005"), ("oxford", "CORE-002")):
        marker = f"### {case_id} —"
        if marker in report:
            sections[name] = report.split(marker, 1)[1].split("### ", 1)[0]
    return {"kth_fixture": fixture["kth_computer_science_fall_2027"], "historical_report_sections": sections,
            "caveat": "Oxford Biology fixture is excluded: wrong programme. Historical snapshots are not current ground truth. No fresh production workflow run; provider-internal model rounds are undisclosed."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["kth", "oxford", "both"], default="both")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stopping-criterion", action="store_true", help="Append user-specified KTH stopping principle only")
    parser.add_argument("--soft-max-four", action="store_true", help="Append user-specified soft budget; no server-side enforcement")
    parser.add_argument("--evaluate-report", type=Path, help="Offline forensic review only; no API request")
    args = parser.parse_args()
    if args.soft_max_four and (args.case != "kth" or not args.stopping_criterion):
        parser.error("--soft-max-four requires --case kth --stopping-criterion")
    if args.stopping_criterion and args.case != "kth":
        parser.error("--stopping-criterion requires --case kth")
    if args.evaluate_report:
        report = json.loads(args.evaluate_report.read_text(encoding="utf-8"))
        for result in report["results"]:
            result["posthoc_output_audit"] = forensic_output(result)
        output = args.output or args.evaluate_report
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"AUDITED {output.resolve()}")
        return
    key = os.getenv("DEEPSEEK_API_KEY") or dotenv_values(ROOT / "backend/.env").get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY is required")
    results = []
    for name in (CASES if args.case == "both" else [args.case]):
        print(f"START {name}", flush=True)
        result = run_case(name, args.model, key, args.timeout, args.stopping_criterion, args.soft_max_four)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k not in {"request_payload", "output_text", "message_texts", "result", "web_search_calls"}}, ensure_ascii=False), flush=True)
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "results": results, "posthoc_baselines": posthoc_baselines()}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"REPORT {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
