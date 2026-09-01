"""Offline regressions for Candidate University / Programme Discovery caches."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402
from app.programme_cache import (  # noqa: E402
    CACHE_TTL,
    PROGRAMME_POOL_TTL,
    ProgrammeCache,
    university_cache_key,
)


NOW = datetime.now(timezone.utc)


def cache_for(root: Path) -> ProgrammeCache:
    return ProgrammeCache(root / "programme_cache.sqlite", root / "seed")


def university(name: str = "Example University") -> application.CandidateUniversity:
    return application.CandidateUniversity(
        university=name,
        country="United Kingdom",
        ranking=1,
        rank_display="1",
        rank_min=1,
        rank_max=1,
        ranking_system="QS",
        ranking_basis="overall",
        ranking_edition=2027,
        ranking_source_url="https://www.topuniversities.com/",
        school_official_url=f"https://{name.replace(' ', '').lower()}.example/",
    )


def request(
    school: application.CandidateUniversity,
    direction: str = "Computer Science",
) -> application.UniversityProgramRequest:
    return application.UniversityProgramRequest(
        university=school,
        target=application.ExploreTargetRequest(
            mode="explore",
            countries=["United Kingdom"],
            target_major=direction,
            ranking=application.RankingScope(type="QS", min=1, max=20),
        ),
    )


def candidate(
    school: application.CandidateUniversity,
    name: str,
) -> application.CandidateProgram:
    return application.CandidateProgram(
        university=school.university,
        program=name,
        country=school.country,
        ranking=school.ranking,
        ranking_system="QS",
        ranking_edition=school.ranking_edition,
        ranking_source_url=school.ranking_source_url,
        official_program_url=f"{school.school_official_url}programmes/{name.replace(' ', '-').lower()}",
        degree_type="MSc",
        relevance_reason=f"Relevant to {name}",
    )


def live_result(
    school: application.CandidateUniversity,
    names: list[str],
) -> application.CandidateProgramResult:
    return application.CandidateProgramResult(
        candidates=[candidate(school, name) for name in names]
    )


async def check_university_url_cache(root: Path) -> None:
    cache = cache_for(root)
    school = university()
    searched_school = school.model_copy(
        update={"school_official_url": "https://official.example.edu/"}
    )
    live = AsyncMock(return_value=[searched_school])
    uncached = school.model_copy(update={"school_official_url": None})
    with patch.object(application, "enrich_school_official_urls", live):
        first = await application.enrich_school_official_urls_cached([uncached], cache=cache)
        second = await application.enrich_school_official_urls_cached([uncached], cache=cache)
    assert first[0].school_official_url == "https://official.example.edu/"
    assert second[0].school_official_url == "https://official.example.edu/"
    assert live.await_count == 1, "same school URL lookup must make zero additional calls"

    key = university_cache_key(school.university, school.country)
    forced_school = searched_school.model_copy(
        update={"school_official_url": "https://forced-official.example.edu/"}
    )
    forced_live = AsyncMock(return_value=[forced_school])
    with patch.object(application, "enrich_school_official_urls", forced_live):
        forced = await application.enrich_school_official_urls_cached(
            [uncached], cache=cache, force_refresh=True
        )
    assert forced_live.await_count == 1
    assert forced[0].school_official_url == "https://forced-official.example.edu/"

    cache.mark_university_official_url_invalid(key)
    refreshed_school = searched_school.model_copy(
        update={"school_official_url": "https://new-official.example.edu/"}
    )
    invalid_refresh = AsyncMock(return_value=[refreshed_school])
    with patch.object(application, "enrich_school_official_urls", invalid_refresh):
        refreshed = await application.enrich_school_official_urls_cached([uncached], cache=cache)
    assert invalid_refresh.await_count == 1
    assert refreshed[0].school_official_url == "https://new-official.example.edu/"


async def check_fresh_pool_and_school_isolation(root: Path) -> None:
    cache = cache_for(root)
    first_school = university("First University")
    second_school = university("Second University")
    first_live = AsyncMock(return_value=live_result(first_school, ["Computer Science MSc"]))
    with patch.object(application, "discover_candidate_programs", first_live):
        first = await application.discover_candidate_programs_cached(
            request(first_school), cache=cache
        )
        second = await application.discover_candidate_programs_cached(
            request(first_school), cache=cache
        )
    assert [item.program for item in first.candidates] == ["Computer Science MSc"]
    assert [item.program for item in second.candidates] == ["Computer Science MSc"]
    assert first_live.await_count == 1, "fresh pool hit must make zero additional calls"

    other_live = AsyncMock(return_value=live_result(second_school, ["Data Science MSc"]))
    with patch.object(application, "discover_candidate_programs", other_live):
        other = await application.discover_candidate_programs_cached(
            request(second_school), cache=cache
        )
    assert other_live.await_count == 1
    assert [item.program for item in other.candidates] == ["Data Science MSc"]


async def check_direction_reuse_and_relevance(root: Path) -> None:
    cache = cache_for(root)
    school = university("Direction University")
    live = AsyncMock(
        return_value=live_result(
            school,
            ["Computer Science MSc", "Data Science MSc", "Artificial Intelligence MSc"],
        )
    )
    with patch.object(application, "discover_candidate_programs", live):
        await application.discover_candidate_programs_cached(
            request(school, "Computer Science"), cache=cache
        )
        data_result = await application.discover_candidate_programs_cached(
            request(school, "Data Science"), cache=cache
        )
    assert live.await_count == 1, "different directions must reuse one fresh school pool"
    assert data_result.candidates[0].program == "Data Science MSc"


async def check_stale_background_merge(root: Path) -> None:
    cache = cache_for(root)
    school = university("Merge University")
    initial_request = request(school)
    key = university_cache_key(school.university, school.country)
    old = (NOW - timedelta(days=181)).isoformat()
    initial = live_result(school, ["A MSc", "B MSc", "C MSc", "D MSc"])
    cache.merge_programme_pool(
        key,
        school.university,
        [item.model_dump(mode="json") for item in initial.candidates],
        {"source": "fixture", "queries": [application.normalized_programme_query(initial_request.target)]},
        refreshed_at=old,
    )

    refresh_live = AsyncMock(
        return_value=live_result(school, ["A MSc", "C MSc", "D MSc", "E MSc"])
    )
    tasks = BackgroundTasks()
    with patch.object(application, "discover_candidate_programs", refresh_live):
        immediate = await application.discover_candidate_programs_cached(
            initial_request,
            cache=cache,
            background_tasks=tasks,
        )
        assert refresh_live.await_count == 0, "stale pool must be returned before refresh runs"
        assert immediate.refresh_scheduled
        assert [item.program for item in immediate.candidates] == [
            "A MSc",
            "B MSc",
            "C MSc",
            "D MSc",
        ]
        await tasks()
    assert refresh_live.await_count == 1
    merged = cache.read_programme_pool(key)
    assert {item.programme for item in merged.programmes} == {
        "A MSc",
        "B MSc",
        "C MSc",
        "D MSc",
        "E MSc",
    }, "refresh miss must not delete B"


async def check_force_refresh_and_cache_independence(root: Path) -> None:
    cache = cache_for(root)
    school = university("Force University")
    selected_request = request(school)
    first_live = AsyncMock(return_value=live_result(school, ["A MSc", "B MSc"]))
    with patch.object(application, "discover_candidate_programs", first_live):
        await application.discover_candidate_programs_cached(selected_request, cache=cache)
    forced_live = AsyncMock(return_value=live_result(school, ["A MSc", "C MSc"]))
    with patch.object(application, "discover_candidate_programs", forced_live):
        forced = await application.discover_candidate_programs_cached(
            selected_request,
            cache=cache,
            force_refresh=True,
        )
    assert forced_live.await_count == 1
    assert {item.program for item in forced.candidates} == {"A MSc", "B MSc", "C MSc"}

    identity = application.normalized_programme_identity(
        university=school.university,
        programme="A MSc",
        official_program_url=forced.candidates[0].official_program_url,
        intended_entry_year=2027,
        intended_entry_term="fall",
    )
    requirements_key = application.programme_cache_key(identity)
    checked_at = NOW.isoformat()
    payload = {"fixture": "requirements"}
    cache.write_runtime("requirements", requirements_key, checked_at, payload)
    cache.write_runtime("timeline", requirements_key, checked_at, {"fixture": "timeline"})
    assert cache.read_runtime("requirements", requirements_key) is not None
    assert cache.read_runtime("timeline", requirements_key) is not None
    assert CACHE_TTL == timedelta(days=7)
    assert PROGRAMME_POOL_TTL == timedelta(days=180)


async def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        await check_university_url_cache(root / "url")
        await check_fresh_pool_and_school_isolation(root / "pool")
        await check_direction_reuse_and_relevance(root / "direction")
        await check_stale_background_merge(root / "merge")
        await check_force_refresh_and_cache_independence(root / "force")
    print("discovery cache regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
