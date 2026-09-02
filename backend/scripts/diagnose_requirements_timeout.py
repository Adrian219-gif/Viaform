"""Observe one Requirements endpoint call without changing retrieval behaviour.

This diagnostic runner monkey-patches timers around the existing call chain. It
does not alter prompts, cache policy, timeout values, or response handling.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402


CASES = {
    "oxford": main.TargetProgram(
        university="University of Oxford",
        program="MSc by Research in Biology",
        official_program_url=(
            "https://www.ox.ac.uk/admissions/graduate/courses/msc-research-biology"
        ),
        official_domain="www.ox.ac.uk",
        intended_entry_year=2027,
        intended_entry_term="fall",
    ),
    "kth": main.TargetProgram(
        university="KTH Royal Institute of Technology",
        program="Master's Programme in Computer Science",
        official_program_url="https://www.kth.se/en/studies/master/computer-science",
        official_domain="www.kth.se",
        intended_entry_year=2027,
        intended_entry_term="fall",
    ),
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _tool_audit(payload: Dict[str, Any]) -> Dict[str, Any]:
    content = payload.get("content") if isinstance(payload, dict) else []
    blocks = content if isinstance(content, list) else []
    queries: List[str] = []
    urls: List[str] = []
    result_counts: List[int] = []

    def walk(value: Any, parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).casefold()
                if lowered in {"query", "search_query"} and isinstance(item, str):
                    queries.append(item)
                if lowered in {"url", "source_url"} and isinstance(item, str):
                    urls.append(item)
                if lowered in {"results", "search_results"} and isinstance(item, list):
                    result_counts.append(len(item))
                walk(item, lowered)
        elif isinstance(value, list):
            for item in value:
                walk(item, parent_key)

    walk(blocks)
    block_types = [
        str(block.get("type") or "unknown")
        for block in blocks
        if isinstance(block, dict)
    ]
    final_text = "\n".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    block_summaries = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        summary: Dict[str, Any] = {
            "index": index,
            "type": str(block.get("type") or "unknown"),
            "keys": sorted(str(key) for key in block),
            "serialized_chars": len(json.dumps(block, ensure_ascii=False)),
        }
        for field in ("text", "thinking", "input", "content"):
            value = block.get(field)
            if value is not None:
                summary[f"{field}_chars"] = len(
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False)
                )
        block_summaries.append(summary)
    return {
        "stop_reason": payload.get("stop_reason"),
        "usage": _jsonable(payload.get("usage")),
        "content_block_types": block_types,
        "content_block_summaries": block_summaries,
        "tool_block_count": sum("tool" in item.casefold() for item in block_types),
        "web_search_block_count": sum("web_search" in item.casefold() for item in block_types),
        "queries": list(dict.fromkeys(queries)),
        "result_counts": result_counts,
        "source_urls": list(dict.fromkeys(urls)),
        "final_text_length": len(final_text),
    }


async def run(case_name: str, force_refresh: bool) -> Dict[str, Any]:
    target = CASES[case_name]
    observations: Dict[str, Any] = {
        "case": case_name,
        "target_program": target.model_dump(mode="json"),
        "force_refresh": force_refresh,
        "configured_timeouts_seconds": {
            "frontend": 390,
            "requirements_endpoint_total": main.REQUIREMENTS_TOTAL_TIMEOUT_SECONDS,
            "web_search_http": main.WEB_SEARCH_TIMEOUT_SECONDS,
            "official_page_fetch": main.OFFICIAL_PROGRAM_PAGE_TIMEOUT_SECONDS,
        },
        "configured_output_tokens": {
            "requirements_web_search": 14000,
            "direct_fetch_extraction": 7000,
        },
        "events": [],
    }
    events: List[Dict[str, Any]] = observations["events"]

    original_post = httpx.AsyncClient.post
    original_get = httpx.AsyncClient.get
    original_read_runtime = main.PROGRAMME_CACHE.read_runtime
    original_read_seed = main.PROGRAMME_CACHE.read_seed
    original_write_runtime = main.PROGRAMME_CACHE.write_runtime
    original_web_search = main.call_deepseek_web_search
    original_fetch = main.fetch_official_program_page_text
    original_normalize = main.normalize_extracted_applicability_stages
    original_review = main.requirements_review_from_extraction

    async def observed_post(client: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any):
        started = time.monotonic()
        request_json = kwargs.get("json")
        is_search = str(url).endswith("/anthropic/v1/messages")
        event: Dict[str, Any] = {
            "phase": "deepseek_web_search_http" if is_search else "http_post",
            "url": str(url),
        }
        if is_search and isinstance(request_json, dict):
            messages = request_json.get("messages") or []
            prompt = "\n".join(
                str(message.get("content") or "")
                for message in messages
                if isinstance(message, dict)
            )
            event.update(
                {
                    "model": request_json.get("model"),
                    "max_tokens": request_json.get("max_tokens"),
                    "prompt_chars": len(prompt),
                    "prompt_utf8_bytes": len(prompt.encode("utf-8")),
                    "prompt_contains_exact_url": target.official_program_url in prompt,
                    "prompt_contains_entry_requirements": "entry requirements" in prompt.casefold(),
                    "prompt_contains_admissions": "admissions" in prompt.casefold(),
                    "prompt_contains_how_to_apply": "how to apply" in prompt.casefold(),
                    "prompt_contains_supporting_documents": "supporting documents" in prompt.casefold(),
                    "configured_search_max_uses": (
                        ((request_json.get("tools") or [{}])[0]).get("max_uses")
                    ),
                }
            )
        try:
            response = await original_post(client, url, *args, **kwargs)
            event["elapsed_seconds"] = round(time.monotonic() - started, 3)
            event["http_status"] = response.status_code
            if is_search:
                try:
                    event["response_audit"] = _tool_audit(response.json())
                except (ValueError, TypeError):
                    event["response_json_parseable"] = False
            events.append(event)
            return response
        except BaseException as error:
            event["elapsed_seconds"] = round(time.monotonic() - started, 3)
            event["error_type"] = type(error).__name__
            event["cancelled"] = isinstance(error, asyncio.CancelledError)
            events.append(event)
            raise

    async def observed_get(client: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any):
        started = time.monotonic()
        event: Dict[str, Any] = {"phase": "official_page_http_get", "url": str(url)}
        try:
            response = await original_get(client, url, *args, **kwargs)
            event.update(
                {
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "http_status": response.status_code,
                    "location": response.headers.get("location"),
                    "content_chars": len(response.text),
                    "content_bytes": len(response.content),
                }
            )
            events.append(event)
            return response
        except BaseException as error:
            event["elapsed_seconds"] = round(time.monotonic() - started, 3)
            event["error_type"] = type(error).__name__
            events.append(event)
            raise

    def timed_sync(phase: str, function: Any):
        def wrapper(*args: Any, **kwargs: Any):
            started = time.monotonic()
            value = function(*args, **kwargs)
            event: Dict[str, Any] = {
                "phase": phase,
                "elapsed_seconds": round(time.monotonic() - started, 6),
            }
            if phase.startswith("cache_read"):
                event["hit"] = value is not None
            events.append(event)
            return value

        return wrapper

    async def observed_web_search(*args: Any, **kwargs: Any):
        started = time.monotonic()
        try:
            value = await original_web_search(*args, **kwargs)
            events.append(
                {
                    "phase": "deepseek_web_search_total",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "outcome": "success",
                }
            )
            return value
        except BaseException as error:
            events.append(
                {
                    "phase": "deepseek_web_search_total",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "outcome": type(error).__name__,
                }
            )
            raise

    async def observed_fetch(url: str):
        started = time.monotonic()
        try:
            value = await original_fetch(url)
            events.append(
                {
                    "phase": "official_page_fetch_total",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "extracted_text_chars": len(value),
                    "outcome": "success",
                }
            )
            return value
        except BaseException as error:
            events.append(
                {
                    "phase": "official_page_fetch_total",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "outcome": type(error).__name__,
                }
            )
            raise

    httpx.AsyncClient.post = observed_post
    httpx.AsyncClient.get = observed_get
    main.PROGRAMME_CACHE.read_runtime = timed_sync("cache_read_runtime", original_read_runtime)
    main.PROGRAMME_CACHE.read_seed = timed_sync("cache_read_seed", original_read_seed)
    main.PROGRAMME_CACHE.write_runtime = timed_sync("cache_write_runtime", original_write_runtime)
    main.call_deepseek_web_search = observed_web_search
    main.fetch_official_program_page_text = observed_fetch
    main.normalize_extracted_applicability_stages = timed_sync(
        "requirements_applicability_normalization", original_normalize
    )
    main.requirements_review_from_extraction = timed_sync(
        "requirements_grouping_and_review", original_review
    )

    started = time.monotonic()
    try:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://diagnostic.local") as client:
            response = await client.post(
                f"/target-programs/requirements?force_refresh={str(force_refresh).lower()}",
                json=target.model_dump(mode="json"),
            )
        observations["endpoint"] = {
            "status": response.status_code,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "detail": response.json().get("detail") if response.status_code != 200 else None,
        }
        if response.status_code == 200:
            payload = response.json()
            observations["result"] = {
                "cache_source": payload.get("cache_source"),
                "checked_at": payload.get("checked_at"),
                "requirement_count": sum(
                    len(category.get("requirements") or [])
                    for category in payload.get("categories") or []
                ),
            }
    finally:
        httpx.AsyncClient.post = original_post
        httpx.AsyncClient.get = original_get
        main.PROGRAMME_CACHE.read_runtime = original_read_runtime
        main.PROGRAMME_CACHE.read_seed = original_read_seed
        main.PROGRAMME_CACHE.write_runtime = original_write_runtime
        main.call_deepseek_web_search = original_web_search
        main.fetch_official_program_page_text = original_fetch
        main.normalize_extracted_applicability_stages = original_normalize
        main.requirements_review_from_extraction = original_review
    return observations


def main_cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run(args.case, args.force_refresh))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main_cli()
