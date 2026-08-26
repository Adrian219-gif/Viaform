"""Regression checks for bounded Target Program Confirmation."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main


UNIVERSITY = "Regression University"
PROGRAM = "MSc Computer Science"
PROGRAM_URL = "https://programs.example.edu/msc-computer-science"


def official_site() -> main.VerifiedOfficialDomain:
    return main.VerifiedOfficialDomain(
        university=UNIVERSITY,
        official_domain="example.edu",
        official_url="https://www.example.edu/",
        evidence_type="result_url",
        evidence_source_url="https://www.example.edu/",
    )


def confirmed_program(url: str = PROGRAM_URL) -> main.TargetProgram:
    return main.TargetProgram(
        university=UNIVERSITY,
        program=PROGRAM,
        official_program_url=url,
        official_domain="example.edu",
    )


async def run() -> None:
    original_db = main.OFFICIAL_DOMAIN_CACHE_DB
    original_resolve = main.resolve_official_domain
    original_verify = main.verify_target_program_url
    original_tavily = main.tavily_search
    original_confirm = main.confirm_target_program
    original_timeout = main.TARGET_PROGRAM_CONFIRMATION_TIMEOUT_SECONDS

    with tempfile.TemporaryDirectory() as temporary_directory:
        main.OFFICIAL_DOMAIN_CACHE_DB = Path(temporary_directory) / "cache.sqlite"
        try:
            # Discovery-created trusted record must bypass every network path.
            main.cache_verified_programme(
                confirmed_program(),
                evidence_type="candidate_discovery_web_search",
            )

            async def forbidden(*args, **kwargs):
                raise AssertionError("cache hit must not call retrieval or verification")

            main.resolve_official_domain = forbidden
            main.verify_target_program_url = forbidden
            main.tavily_search = forbidden
            started = time.perf_counter()
            cached = await main.confirm_target_program(
                main.TargetProgramConfirmationRequest(
                    university=UNIVERSITY,
                    program=PROGRAM,
                    official_program_url=PROGRAM_URL,
                )
            )
            assert cached.official_program_url == PROGRAM_URL
            assert time.perf_counter() - started < 0.1

            # A new manual URL has no trusted record and still uses the existing verifier.
            verify_calls = []

            async def resolve(*args, **kwargs):
                return official_site()

            async def verify(university, program, url, domain, *args, **kwargs):
                verify_calls.append(url)
                return confirmed_program(url), "confirmed"

            main.resolve_official_domain = resolve
            main.verify_target_program_url = verify
            manual_url = "https://programs.example.edu/manual-programme"
            manual = await main.confirm_target_program(
                main.TargetProgramConfirmationRequest(
                    university=UNIVERSITY,
                    official_program_url=manual_url,
                )
            )
            assert manual.official_program_url == manual_url
            assert verify_calls == [manual_url]

            # A third-party manual URL remains rejected before programme verification.
            try:
                await main.confirm_target_program(
                    main.TargetProgramConfirmationRequest(
                        university=UNIVERSITY,
                        official_program_url="https://third-party.example/programme",
                    )
                )
            except HTTPException as error:
                assert error.status_code == 422
            else:
                raise AssertionError("third-party manual URL was not rejected")

            # Exact-search fallback verifies at most three candidates concurrently.
            fallback_calls = []

            async def tavily(*args, **kwargs):
                return [
                    {
                        "title": f"Programme {index}",
                        "url": f"https://example.edu/programme-{index}",
                        "content": "Master of Science programme",
                    }
                    for index in range(8)
                ]

            async def bounded_verify(university, program, url, domain, *args, **kwargs):
                fallback_calls.append(url)
                await asyncio.sleep(0.02)
                if url.endswith("programme-1"):
                    return confirmed_program(url), "confirmed"
                return None, "invalid"

            main.tavily_search = tavily
            main.verify_target_program_url = bounded_verify
            fallback = await main.confirm_target_program(
                main.TargetProgramConfirmationRequest(
                    university=UNIVERSITY,
                    program="Another MSc",
                )
            )
            assert fallback.official_program_url.endswith("programme-1")
            assert len(fallback_calls) <= main.TARGET_PROGRAM_FALLBACK_VERIFY_LIMIT

            # The endpoint applies one absolute budget to the whole workflow.
            async def slow_confirmation(*args, **kwargs):
                await asyncio.sleep(0.1)
                return confirmed_program()

            main.confirm_target_program = slow_confirmation
            main.TARGET_PROGRAM_CONFIRMATION_TIMEOUT_SECONDS = 0.01
            try:
                await main.confirm_target_program_endpoint(
                    main.TargetProgramConfirmationRequest(
                        university=UNIVERSITY,
                        program="Timeout MSc",
                    )
                )
            except HTTPException as error:
                assert error.status_code == 504
                assert error.detail == "项目确认超时，请重试。"
            else:
                raise AssertionError("confirmation workflow did not time out")
        finally:
            main.OFFICIAL_DOMAIN_CACHE_DB = original_db
            main.resolve_official_domain = original_resolve
            main.verify_target_program_url = original_verify
            main.tavily_search = original_tavily
            main.confirm_target_program = original_confirm
            main.TARGET_PROGRAM_CONFIRMATION_TIMEOUT_SECONDS = original_timeout

    print("target program confirmation regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(run())
