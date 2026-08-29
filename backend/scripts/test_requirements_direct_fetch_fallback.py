"""Narrow official programme page fallback regressions."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


RCA = application.TargetProgram(
    university="Royal College of Art",
    program="Painting MA",
    official_program_url="https://www.rca.ac.uk/study/programme-finder/painting-ma/",
    official_domain="rca.ac.uk",
)
OXFORD = application.TargetProgram(
    university="University of Oxford",
    program="MSc Advanced Computer Science",
    official_program_url=(
        "https://www.ox.ac.uk/admissions/graduate/courses/"
        "msc-advanced-computer-science"
    ),
    official_domain="ox.ac.uk",
)


class FakeWebSearchResponse:
    is_error = False

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def fake_web_search_client(payload: dict, calls: dict):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            pass

        async def post(self, *args, **kwargs):
            assert kwargs["json"]["max_tokens"] == 14000
            assert kwargs["json"]["tools"][0]["max_uses"] == 2
            calls["search"] += 1
            return FakeWebSearchResponse(payload)

    return FakeAsyncClient


async def check_no_final_text_uses_direct_fetch() -> None:
    original_client = application.httpx.AsyncClient
    original_fetch = application.fetch_official_program_page_text
    original_deepseek = application.call_deepseek
    original_api_key = os.environ.get("DEEPSEEK_API_KEY")
    calls = {"search": 0, "fetch": 0, "extract": 0}
    payload = {
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "content": [{"type": "server_tool_use", "name": "web_search"}],
    }

    async def fake_fetch(url: str) -> str:
        calls["fetch"] += 1
        assert url == RCA.official_program_url
        return "Painting MA. A portfolio is required."

    async def fake_deepseek(*args, **kwargs):
        calls["extract"] += 1
        return json.dumps(
            {
                "requirements": [
                    {
                        "category": "materials",
                        "requirement": "A portfolio is required.",
                        "requirement_zh": "必须提交作品集。",
                        "importance": "required",
                        "source_level": "program",
                        "source_type": "official_retrieval",
                        "verification_status": "official_verified",
                        "source_url": RCA.official_program_url,
                        "source_cycle": None,
                        "temporal_applicability": "undated",
                        "temporal_note": None,
                    }
                ]
            }
        )

    application.httpx.AsyncClient = fake_web_search_client(payload, calls)
    application.fetch_official_program_page_text = fake_fetch
    application.call_deepseek = fake_deepseek
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    try:
        review = await application.retrieve_target_program_requirements(RCA)
    finally:
        application.httpx.AsyncClient = original_client
        application.fetch_official_program_page_text = original_fetch
        application.call_deepseek = original_deepseek
        if original_api_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = original_api_key

    assert calls == {"search": 1, "fetch": 1, "extract": 1}
    assert sum(len(category.requirements) for category in review.categories) == 1


async def check_schema_error_does_not_use_direct_fetch() -> None:
    original_client = application.httpx.AsyncClient
    original_fetch = application.fetch_official_program_page_text
    original_api_key = os.environ.get("DEEPSEEK_API_KEY")
    calls = {"search": 0, "fetch": 0}
    payload = {
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "content": [
            {
                "type": "text",
                "text": json.dumps({"requirements": [{"category": "invalid"}]}),
            }
        ],
    }

    async def unexpected_fetch(*args, **kwargs):
        calls["fetch"] += 1
        raise AssertionError("schema errors must not enter direct-fetch fallback")

    application.httpx.AsyncClient = fake_web_search_client(payload, calls)
    application.fetch_official_program_page_text = unexpected_fetch
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    try:
        try:
            await application.retrieve_target_program_requirements(RCA)
        except application.HTTPException as error:
            assert error.status_code == 502
            assert error.detail == "DeepSeek Web Search returned malformed program_requirements data"
        else:
            raise AssertionError("schema validation error should remain an HTTP 502")
    finally:
        application.httpx.AsyncClient = original_client
        application.fetch_official_program_page_text = original_fetch
        if original_api_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = original_api_key

    assert calls == {"search": 1, "fetch": 0}


async def check_search_contract_failure_uses_direct_fetch() -> None:
    original_search = application.call_deepseek_web_search
    original_fetch = application.fetch_official_program_page_text
    original_deepseek = application.call_deepseek
    calls = {"search": 0, "fetch": 0, "extract": 0}
    prompts = {}

    async def fake_search(*args, **kwargs):
        calls["search"] += 1
        assert kwargs["max_search_uses"] == 2
        assert kwargs["max_output_tokens"] == 14000
        prompts["search"] = args[0]
        return application.RequirementsWebSearchOutput(requirements=[])

    async def fake_fetch(url: str) -> str:
        calls["fetch"] += 1
        assert url == RCA.official_program_url
        return (
            "Painting MA Entry requirements. Submit a portfolio, a 300-word personal "
            "statement, and an introduction video of no more than two minutes."
        )

    async def fake_deepseek(*args, **kwargs):
        calls["extract"] += 1
        prompt = kwargs["messages"][1]["content"]
        prompts["fallback"] = prompt
        assert "OFFICIAL PROGRAMME PAGE TEXT" in prompt
        assert "Do not use Web Search" in prompt
        return json.dumps(
            {
                "requirements": [
                    {
                        "category": "materials",
                        "requirement": "A portfolio is required.",
                        "requirement_zh": "必须提交作品集。",
                        "importance": "required",
                        "source_level": "unknown",
                        "source_type": "model_memory",
                        "verification_status": "model_memory_unverified",
                        "source_url": None,
                        "source_cycle": None,
                        "temporal_applicability": "unknown",
                        "temporal_note": "Cycle could not be confirmed.",
                    }
                ]
            },
            ensure_ascii=False,
        )

    application.call_deepseek_web_search = fake_search
    application.fetch_official_program_page_text = fake_fetch
    application.call_deepseek = fake_deepseek
    try:
        review = await application.retrieve_target_program_requirements(RCA)
    finally:
        application.call_deepseek_web_search = original_search
        application.fetch_official_program_page_text = original_fetch
        application.call_deepseek = original_deepseek

    assert calls == {"search": 1, "fetch": 1, "extract": 1}
    priority_markers = [
        "required eligibility and required application materials first",
        "conditional-required items",
        "recommended or preferred items",
        "administrative or contextual information",
    ]
    parity_markers = [
        *priority_markers,
        "importance must be exactly one of: required, recommended, preferred, unknown",
        "conditional_required is not a valid importance value",
        "For a conditional Requirement, output importance=required",
        "preserve the complete applicability condition in the requirement text",
        "transcripts, degree certificates, CVs or resumes",
        "references or recommendation letters",
        "statements, portfolios or work samples",
        "identification documents",
        "programme-specific forms, sheets, or questionnaires",
        "Do not merge or omit separate required materials",
        "There is no numeric item limit for required or conditional-required Requirements",
        "must not be returned as Requirements",
        "TEMPORAL APPLICABILITY CONTRACT",
        "temporal_applicability=target_cycle_confirmed",
        "temporal_applicability=undated",
        "temporal_applicability=previous_cycle",
        "temporal_applicability=not_yet_published",
        "temporal_applicability=unknown",
        "Official provenance and temporal applicability are orthogonal",
    ]
    for prompt in prompts.values():
        assert all(marker in prompt for marker in parity_markers)
        assert [prompt.index(marker) for marker in priority_markers] == sorted(
            prompt.index(marker) for marker in priority_markers
        )
    assert "Return at most twelve concise" not in prompts["fallback"]
    materials = next(
        category for category in review.categories if category.category == "materials"
    )
    assert materials.coverage == "official_verified"
    assert len(materials.requirements) == 1
    item = materials.requirements[0]
    assert item.source_url == RCA.official_program_url
    assert item.source_level == "program"
    assert item.source_type == "official_retrieval"
    assert item.verification_status == "official_verified"


async def check_successful_search_does_not_use_fallback() -> None:
    original_search = application.call_deepseek_web_search
    original_fetch = application.fetch_official_program_page_text
    original_deepseek = application.call_deepseek
    calls = {"search": 0, "fetch": 0, "extract": 0}

    async def fake_search(*args, **kwargs):
        calls["search"] += 1
        return application.RequirementsWebSearchOutput(
            requirements=[
                application.RequirementItem(
                    category="academic",
                    requirement="A first-class degree is required.",
                    requirement_zh="要求一等学位。",
                    importance="required",
                    source_level="program",
                    source_type="official_retrieval",
                    verification_status="official_verified",
                    source_url=OXFORD.official_program_url,
                    temporal_applicability="undated",
                )
            ],
            search_audit=application.RequirementsSearchAudit(
                search_attempts_completed=2,
                programme_page_checked=True,
                sections_checked=["Entry requirements"],
            ),
        )

    async def unexpected_fetch(*args, **kwargs):
        calls["fetch"] += 1
        raise AssertionError("direct-fetch fallback must not run")

    async def unexpected_deepseek(*args, **kwargs):
        calls["extract"] += 1
        raise AssertionError("fallback extraction must not run")

    application.call_deepseek_web_search = fake_search
    application.fetch_official_program_page_text = unexpected_fetch
    application.call_deepseek = unexpected_deepseek
    try:
        review = await application.retrieve_target_program_requirements(OXFORD)
    finally:
        application.call_deepseek_web_search = original_search
        application.fetch_official_program_page_text = original_fetch
        application.call_deepseek = original_deepseek

    assert calls == {"search": 1, "fetch": 0, "extract": 0}
    assert sum(len(category.requirements) for category in review.categories) == 1


async def main() -> None:
    await check_no_final_text_uses_direct_fetch()
    await check_search_contract_failure_uses_direct_fetch()
    await check_successful_search_does_not_use_fallback()
    await check_schema_error_does_not_use_direct_fetch()
    print("requirements direct-fetch fallback regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
