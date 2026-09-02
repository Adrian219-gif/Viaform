"""Offline regressions for admission-stage Requirement applicability."""

from __future__ import annotations

import asyncio
import gc
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402
from app.programme_cache import ProgrammeCache, programme_cache_key  # noqa: E402


def target() -> application.TargetProgram:
    return application.TargetProgram(
        university="Carnegie Mellon University",
        program="MS Computer Science",
        official_program_url="https://www.cs.cmu.edu/academics/masters/programs/ms-in-computer-science",
        official_domain="cs.cmu.edu",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )


def requirement(
    text: str,
    stage: application.RequirementApplicabilityStage,
    *,
    category: application.RequirementCategory = "other",
) -> application.RequirementItem:
    return application.RequirementItem(
        category=category,
        requirement=text,
        requirement_zh=text,
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url=target().official_program_url,
        source_cycle=None,
        temporal_applicability="undated",
        applicability_stage=stage,
    )


def review(items: list[application.RequirementItem]):
    return application.requirements_review_from_extraction(
        target(), application.RequirementsExtraction(requirements=items)
    )


def check_schema_and_downstream_gate() -> None:
    items = [
        requirement(
            "Pass 96-108 units in qualifying master's courses.", "in_program", category="course"
        ),
        requirement(
            "Pass one course from the available Systems courses.", "in_program", category="course"
        ),
        requirement("Maintain a 3.0 QPA while enrolled.", "in_program", category="academic"),
        requirement("Applicants must hold a bachelor's degree.", "pre_admission", category="academic"),
        requirement(
            "Applicants must have completed Linear Algebra before admission.",
            "pre_admission",
            category="course",
        ),
        requirement("Minimum undergraduate GPA 3.0.", "pre_admission", category="academic"),
        requirement("Submit a CV / Resume.", "pre_admission", category="materials"),
        requirement(
            "English proficiency is required for applicants who were not taught in English.",
            "conditional_admission",
            category="language",
        ),
        requirement(
            "GRE scores are waived for Carnegie Mellon graduates.",
            "conditional_admission",
            category="standardized_test",
        ),
        requirement("Scholarships are not offered.", "informational"),
        requirement("Tuition is charged per semester.", "informational"),
        requirement("The programme duration is two years.", "informational"),
        requirement("A further requirement applies.", "unclear"),
    ]
    reviewed = review(items)
    preserved = [
        item
        for category in reviewed.categories
        for item in category.requirements
    ]
    assert len(preserved) == len(items)
    assert any(
        item.verification_status == "official_verified"
        and item.applicability_stage == "in_program"
        for item in preserved
    ), "official provenance and admission stage must remain independent"

    formal = application.formal_gap_requirements(reviewed)
    assert formal
    assert {item["applicability_stage"] for item in formal} == {"pre_admission"}
    formal_text = {item["requirement"] for item in formal}
    assert "Applicants must hold a bachelor's degree." in formal_text
    assert "Applicants must have completed Linear Algebra before admission." in formal_text
    assert "Minimum undergraduate GPA 3.0." in formal_text
    assert "Submit a CV / Resume." in formal_text
    assert not any("96-108" in text for text in formal_text)
    assert not any("Systems courses" in text for text in formal_text)
    assert not any("3.0 QPA" in text for text in formal_text)
    assert not any("Scholarships" in text for text in formal_text)

    special_input = application.trusted_reviewed_requirements(reviewed)
    assert special_input
    assert {item["applicability_stage"] for item in special_input} == {"pre_admission"}
    assert not any("waived" in item["requirement"] for item in special_input)
    assert not any("English proficiency is required for" in item["requirement"] for item in special_input)

    omitted = application.RequirementItem(
        category="other",
        requirement="A requirement whose stage was omitted by the model.",
        requirement_zh=None,
        importance="unknown",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url=target().official_program_url,
        source_cycle=None,
        temporal_applicability="undated",
    )
    normalized_omitted = application.normalize_extracted_applicability_stages([omitted])[0]
    assert normalized_omitted.applicability_stage == "unclear"
    assert application.formal_gap_requirements(review([normalized_omitted])) == []
    print("PASS applicability schema preserves review data and gates Gap/Special Interview")


async def check_search_and_direct_fetch_prompt_contract() -> None:
    captured_search: dict[str, object] = {}

    async def fake_search(prompt, output_model, **kwargs):
        captured_search.update(prompt=prompt, output_model=output_model, kwargs=kwargs)
        return application.RequirementsWebSearchOutput(
            requirements=[requirement("Applicants must hold a bachelor's degree.", "pre_admission", category="academic")],
            search_audit=application.RequirementsSearchAudit(
                search_attempts_completed=1,
                programme_page_checked=True,
                sections_checked=["Admissions"],
            ),
        )

    with patch.object(application, "call_deepseek_web_search", fake_search):
        await application.retrieve_target_program_requirements(target())
    prompt = str(captured_search["prompt"])
    assert "What must an applicant satisfy or submit" in prompt
    assert "admission requirements / application requirements / eligibility" in prompt
    assert "program requirements as the primary admission query" in prompt
    assert "determine WHEN" in prompt
    assert "Program Requirements or Requirements is not proof" in prompt
    assert "pass 96-108 units" in prompt
    assert "applicability_stage" in prompt
    assert captured_search["kwargs"]["max_search_uses"] == 2

    captured_direct: dict[str, object] = {}

    async def fake_fetch(_url: str) -> str:
        return "Admissions: Applicants must hold a bachelor's degree."

    async def fake_deepseek(*, messages, **kwargs):
        captured_direct.update(messages=messages, kwargs=kwargs)
        return application.RequirementsExtraction(
            requirements=[requirement("Applicants must hold a bachelor's degree.", "pre_admission", category="academic")]
        ).model_dump_json()

    with patch.object(application, "fetch_official_program_page_text", fake_fetch), patch.object(
        application, "call_deepseek", fake_deepseek
    ):
        await application.extract_requirements_from_official_program_page(target())
    direct_prompt = str(captured_direct["messages"][1]["content"])
    assert "determine WHEN" in direct_prompt
    assert "applicability_stage" in direct_prompt
    assert "pass 96-108 units" in direct_prompt
    print("PASS Search and direct-fetch prompts share the admission-stage contract")


def check_requirements_cache_version() -> None:
    checked_at = datetime.now(timezone.utc).isoformat()
    selected = target()
    identity = application.target_program_cache_identity(selected)
    key = programme_cache_key(identity)
    payload = review([requirement("Submit a CV.", "pre_admission", category="materials")]).model_dump(mode="json")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cache = ProgrammeCache(root / "runtime.sqlite", root / "seed")
        with cache._connect() as connection:
            connection.execute(
                "INSERT INTO programme_cache "
                "(cache_kind, cache_key, semantic_key, cache_schema_version, checked_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("requirements", key, None, 1, checked_at, json.dumps(payload)),
            )
        assert cache.read_runtime("requirements", key) is None
        cache.write_runtime("requirements", key, checked_at, payload)
        assert cache.read_runtime("requirements", key) is not None

        seed_path = root / "seed" / f"{key}.json"
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cache_key": key,
                    "identity": identity,
                    "requirements": {"checked_at": checked_at, "payload": payload},
                }
            ),
            encoding="utf-8",
        )
        assert cache.read_seed("requirements", key) is None
        del connection
        gc.collect()
    print("PASS legacy Requirements runtime/seed cache versions are invalidated")


def run() -> None:
    check_schema_and_downstream_gate()
    asyncio.run(check_search_and_direct_fetch_prompt_contract())
    check_requirements_cache_version()
    print("requirement applicability-stage regressions: all checks passed")


if __name__ == "__main__":
    run()
