"""Deterministic regression checks for bounded Requirements Retrieval I/O."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx
from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


TARGET = application.TargetProgram(
    university="Example University",
    program="MSc Example",
    official_program_url="https://example.edu/programme",
    official_domain="example.edu",
    confirmation_status="confirmed",
)
SITE = application.VerifiedOfficialDomain(
    university=TARGET.university,
    official_domain="example.edu",
    official_url="https://example.edu/",
    evidence_type="result_url",
    evidence_source_url="https://example.edu/",
)


async def empty_search(
    target_program: application.TargetProgram,
    allowed_domains: set[str],
    direct_evidence: application.RequirementEvidenceItem | None,
) -> application.RequirementsWebSearchResult:
    return application.RequirementsWebSearchResult(
        web_search_used=True,
        structured_output=application.RequirementsExtraction(requirements=[]),
    )


async def check_direct_fetch_success_is_used() -> None:
    originals = {
        "resolve": application.resolve_official_domain,
        "affiliated": application.get_verified_affiliated_domains,
        "fetch": application.fetch_program_requirements_page,
        "search": application.deepseek_requirements_web_search,
        "fallback": application.run_reference_fallback,
    }
    expected = application.RequirementEvidenceItem(
        url=TARGET.official_program_url,
        resolved_url=TARGET.official_program_url,
        title="MSc Example",
        content="Entry requirement: an academic degree is required.",
        source_level="program",
        evidence_type="direct_program_page",
    )
    search_calls: list[application.RequirementEvidenceItem | None] = []

    async def resolve(_: str) -> application.VerifiedOfficialDomain:
        return SITE

    async def fast_fetch(*_: object) -> application.RequirementEvidenceItem:
        return expected

    async def capture_search(
        target_program: application.TargetProgram,
        allowed_domains: set[str],
        direct_evidence: application.RequirementEvidenceItem | None,
    ) -> application.RequirementsWebSearchResult:
        search_calls.append(direct_evidence)
        return await empty_search(target_program, allowed_domains, direct_evidence)

    async def empty_fallback(*_: object) -> tuple:
        return application.RequirementsWebSearchResult(), [], [], 0, 0

    try:
        application.resolve_official_domain = resolve
        application.get_verified_affiliated_domains = lambda *_: []
        application.fetch_program_requirements_page = fast_fetch
        application.deepseek_requirements_web_search = capture_search
        application.run_reference_fallback = empty_fallback
        await application.retrieve_target_program_requirements(TARGET)
        assert search_calls == [expected]
    finally:
        application.resolve_official_domain = originals["resolve"]
        application.get_verified_affiliated_domains = originals["affiliated"]
        application.fetch_program_requirements_page = originals["fetch"]
        application.deepseek_requirements_web_search = originals["search"]
        application.run_reference_fallback = originals["fallback"]


async def check_direct_fetch_timeout_continues() -> None:
    originals = {
        "resolve": application.resolve_official_domain,
        "affiliated": application.get_verified_affiliated_domains,
        "fetch": application.fetch_program_requirements_page,
        "search": application.deepseek_requirements_web_search,
        "fallback": application.run_reference_fallback,
        "timeout": application.REQUIREMENTS_DIRECT_FETCH_TIMEOUT_SECONDS,
    }
    search_calls: list[application.RequirementEvidenceItem | None] = []

    async def resolve(_: str) -> application.VerifiedOfficialDomain:
        return SITE

    async def slow_fetch(*_: object) -> application.RequirementEvidenceItem:
        await asyncio.sleep(0.1)
        raise AssertionError("direct fetch should have been cancelled")

    async def capture_search(
        target_program: application.TargetProgram,
        allowed_domains: set[str],
        direct_evidence: application.RequirementEvidenceItem | None,
    ) -> application.RequirementsWebSearchResult:
        search_calls.append(direct_evidence)
        return await empty_search(target_program, allowed_domains, direct_evidence)

    async def empty_fallback(*_: object) -> tuple:
        return application.RequirementsWebSearchResult(), [], [], 0, 0

    try:
        application.resolve_official_domain = resolve
        application.get_verified_affiliated_domains = lambda *_: []
        application.fetch_program_requirements_page = slow_fetch
        application.deepseek_requirements_web_search = capture_search
        application.run_reference_fallback = empty_fallback
        application.REQUIREMENTS_DIRECT_FETCH_TIMEOUT_SECONDS = 0.01
        review = await application.retrieve_target_program_requirements(TARGET)
        assert len(review.categories) == 7
        assert search_calls == [None]
    finally:
        application.resolve_official_domain = originals["resolve"]
        application.get_verified_affiliated_domains = originals["affiliated"]
        application.fetch_program_requirements_page = originals["fetch"]
        application.deepseek_requirements_web_search = originals["search"]
        application.run_reference_fallback = originals["fallback"]
        application.REQUIREMENTS_DIRECT_FETCH_TIMEOUT_SECONDS = originals["timeout"]


class FakeAsyncClient:
    delays: dict[str, float] = {}

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str) -> httpx.Response:
        await asyncio.sleep(self.delays.get(url, 0.0))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<html><title>Official requirement</title><main>"
                "<h1>Entry requirements</h1><p>An academic degree is required.</p>"
                "</main></html>"
            ),
            request=httpx.Request("GET", url),
        )


async def check_lazy_budgets() -> None:
    original_client = application.httpx.AsyncClient
    per_url = application.REQUIREMENTS_LAZY_FETCH_TIMEOUT_SECONDS
    stage = application.REQUIREMENTS_LAZY_STAGE_TIMEOUT_SECONDS
    fast = "https://example.edu/fast"
    slow = "https://example.edu/slow"
    try:
        application.httpx.AsyncClient = FakeAsyncClient
        application.REQUIREMENTS_LAZY_FETCH_TIMEOUT_SECONDS = 0.02
        application.REQUIREMENTS_LAZY_STAGE_TIMEOUT_SECONDS = 0.2
        FakeAsyncClient.delays = {fast: 0.0, slow: 0.1}
        fetched, attempted, timed_out, _ = await application.fetch_requirement_evidence_pages(
            [fast, slow],
            {fast: "program", slow: "university"},
            {"example.edu"},
            set(),
        )
        assert attempted == 2 and fast in fetched and slow not in fetched
        assert timed_out == 1

        application.REQUIREMENTS_LAZY_FETCH_TIMEOUT_SECONDS = 1.0
        application.REQUIREMENTS_LAZY_STAGE_TIMEOUT_SECONDS = 0.02
        FakeAsyncClient.delays = {fast: 0.2, slow: 0.2}
        started = time.perf_counter()
        fetched, attempted, timed_out, elapsed = await application.fetch_requirement_evidence_pages(
            [fast, slow],
            {fast: "program", slow: "university"},
            {"example.edu"},
            set(),
        )
        wall_elapsed = time.perf_counter() - started
        assert attempted == 2 and not fetched and timed_out == 2
        assert elapsed < 0.15 and wall_elapsed < 0.15
    finally:
        application.httpx.AsyncClient = original_client
        application.REQUIREMENTS_LAZY_FETCH_TIMEOUT_SECONDS = per_url
        application.REQUIREMENTS_LAZY_STAGE_TIMEOUT_SECONDS = stage


async def check_endpoint_total_timeout() -> None:
    original_retrieve = application.retrieve_target_program_requirements
    original_timeout = application.REQUIREMENTS_TOTAL_TIMEOUT_SECONDS

    async def blocked(_: application.TargetProgram) -> application.TargetProgramRequirementsReview:
        await asyncio.sleep(0.1)
        raise AssertionError("total timeout should cancel retrieval")

    try:
        application.retrieve_target_program_requirements = blocked
        application.REQUIREMENTS_TOTAL_TIMEOUT_SECONDS = 0.01
        try:
            await application.target_program_requirements_endpoint(TARGET)
        except HTTPException as error:
            assert error.status_code == 504
            assert error.detail == "项目要求获取超时，请重试。"
        else:
            raise AssertionError("endpoint did not enforce its total timeout")
    finally:
        application.retrieve_target_program_requirements = original_retrieve
        application.REQUIREMENTS_TOTAL_TIMEOUT_SECONDS = original_timeout


async def run() -> None:
    await check_direct_fetch_success_is_used()
    await check_direct_fetch_timeout_continues()
    await check_lazy_budgets()
    await check_endpoint_total_timeout()
    print("requirements timeout regressions: all deterministic checks passed")


if __name__ == "__main__":
    asyncio.run(run())
