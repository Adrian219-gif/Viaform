"""Offline regression for the outer Requirements deadline and cache safety."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402
from app.programme_cache import ProgrammeCache, programme_cache_key  # noqa: E402


def target() -> main.TargetProgram:
    return main.TargetProgram(
        university="University of Oxford",
        program="MSc by Research in Biology",
        official_program_url=(
            "https://www.ox.ac.uk/admissions/graduate/courses/msc-research-biology"
        ),
        official_domain="www.ox.ac.uk",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )


def successful_review() -> main.TargetProgramRequirementsReview:
    item = main.RequirementItem(
        category="academic",
        requirement="Applicants must hold a relevant bachelor's degree.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url=target().official_program_url,
        temporal_applicability="undated",
        applicability_stage="pre_admission",
    )
    return main.requirements_review_from_extraction(
        target(), main.RequirementsExtraction(requirements=[item])
    )


async def check_normal_completion() -> None:
    async def completes(*args, **kwargs):
        await asyncio.sleep(0.005)
        return successful_review()

    with patch.object(main, "REQUIREMENTS_TOTAL_TIMEOUT_SECONDS", 0.05), patch.object(
        main, "retrieve_target_program_requirements_cached", side_effect=completes
    ):
        result = await main.target_program_requirements_endpoint(target(), force_refresh=False)
    assert sum(len(category.requirements) for category in result.categories) == 1
    print("PASS normal inner operation completes before outer deadline")


async def check_old_boundary_no_longer_cancels() -> None:
    # Scaled equivalent: old 120s = 0.012s, new 360s = 0.036s.
    async def exceeds_old_boundary(*args, **kwargs):
        await asyncio.sleep(0.018)
        return successful_review()

    with patch.object(main, "REQUIREMENTS_TOTAL_TIMEOUT_SECONDS", 0.036), patch.object(
        main,
        "retrieve_target_program_requirements_cached",
        side_effect=exceeds_old_boundary,
    ):
        result = await main.target_program_requirements_endpoint(target(), force_refresh=False)
    assert result.target_program.program == target().program
    print("PASS request beyond old 120s equivalent succeeds within new total budget")


async def check_inner_timeout_is_observable() -> None:
    async def inner_timeout(*args, **kwargs):
        await asyncio.sleep(0.015)
        raise HTTPException(
            status_code=504,
            detail="DeepSeek Web Search timed out. Please retry.",
        )

    with patch.object(main, "REQUIREMENTS_TOTAL_TIMEOUT_SECONDS", 0.05), patch.object(
        main,
        "retrieve_target_program_requirements_cached",
        side_effect=inner_timeout,
    ):
        try:
            await main.target_program_requirements_endpoint(target(), force_refresh=False)
        except HTTPException as error:
            assert error.status_code == 504
            assert error.detail == "DeepSeek Web Search timed out. Please retry."
        else:
            raise AssertionError("inner timeout was not propagated")
    print("PASS inner timeout remains observable before outer deadline")


async def check_true_outer_deadline() -> None:
    target = main.TargetProgram(
        university="University of Oxford",
        program="MSc by Research in Biology",
        official_program_url=(
            "https://www.ox.ac.uk/admissions/graduate/courses/msc-research-biology"
        ),
        official_domain="www.ox.ac.uk",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )
    cancelled = asyncio.Event()

    async def never_finishes(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(main, "REQUIREMENTS_TOTAL_TIMEOUT_SECONDS", 0.01), patch.object(
        main,
        "retrieve_target_program_requirements_cached",
        side_effect=never_finishes,
    ), patch.object(main.PROGRAMME_CACHE, "write_runtime") as write_runtime:
        try:
            await main.target_program_requirements_endpoint(target, force_refresh=False)
        except HTTPException as error:
            assert error.status_code == 504
            assert error.detail == "项目要求获取超时，请重试。"
        else:
            raise AssertionError("outer deadline did not return HTTP 504")

    assert cancelled.is_set(), "wait_for did not cancel the in-flight retrieval"
    assert write_runtime.call_count == 0
    print("PASS: outer deadline returns 504, cancels retrieval, and writes no cache")


async def check_cache_write_contract() -> None:
    checked_at = datetime.now(timezone.utc).isoformat()
    review = successful_review().model_copy(update={"checked_at": checked_at})

    async def success(_target):
        return review

    async def failure(_target):
        raise HTTPException(status_code=504, detail="inner timeout")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cache = ProgrammeCache(root / "runtime.sqlite", root / "seed")
        identity = main.target_program_cache_identity(target())
        cache_key = programme_cache_key(identity)
        with patch.object(main, "retrieve_target_program_requirements", success):
            result = await main.retrieve_target_program_requirements_cached(
                target(), force_refresh=True, cache=cache
            )
        assert result.cache_source == "live"
        assert cache.read_runtime("requirements", cache_key) is not None

        second_cache = ProgrammeCache(root / "failure.sqlite", root / "failure-seed")
        with patch.object(main, "retrieve_target_program_requirements", failure):
            try:
                await main.retrieve_target_program_requirements_cached(
                    target(), force_refresh=True, cache=second_cache
                )
            except HTTPException as error:
                assert error.status_code == 504
            else:
                raise AssertionError("failure was unexpectedly cached")
        assert second_cache.read_runtime("requirements", cache_key) is None
    print("PASS success writes runtime cache and failure writes no partial cache")


def check_configured_deadline_hierarchy() -> None:
    frontend_source = (
        BACKEND_DIR.parent / "frontend" / "src" / "app" / "page.tsx"
    ).read_text(encoding="utf-8")
    assert "const REQUIREMENTS_RETRIEVAL_TIMEOUT_MS = 390_000;" in frontend_source
    assert main.WEB_SEARCH_TIMEOUT_SECONDS == 180.0
    assert main.REQUIREMENTS_TOTAL_TIMEOUT_SECONDS == 360.0
    assert 390.0 > main.REQUIREMENTS_TOTAL_TIMEOUT_SECONDS
    assert main.REQUIREMENTS_TOTAL_TIMEOUT_SECONDS > main.WEB_SEARCH_TIMEOUT_SECONDS
    print("PASS DeepSeek < Backend < Frontend timeout hierarchy")


async def run() -> None:
    check_configured_deadline_hierarchy()
    await check_normal_completion()
    await check_old_boundary_no_longer_cancels()
    await check_inner_timeout_is_observable()
    await check_true_outer_deadline()
    await check_cache_write_contract()
    print("requirements timeout orchestration: all checks passed")


if __name__ == "__main__":
    asyncio.run(run())
