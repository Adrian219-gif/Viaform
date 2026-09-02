"""Offline regressions for the two-layer programme cache."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402
from app.programme_cache import (  # noqa: E402
    ProgrammeCache,
    normalized_programme_identity,
    programme_cache_key,
)


NOW = datetime.now(timezone.utc)


def target(programme: str = "MSc Computer Science", year: int = 2027) -> application.TargetProgram:
    return application.TargetProgram(
        university="Example University",
        program=programme,
        official_program_url=f"https://example.edu/{programme.replace(' ', '-').lower()}",
        official_domain="example.edu",
        intended_entry_year=year,
        intended_entry_term="fall",
    )


def timeline_request(
    programme: str = "MSc Computer Science", year: int = 2027
) -> application.ApplicationTimelineRequest:
    selected = target(programme, year)
    return application.ApplicationTimelineRequest(
        university=selected.university,
        program_name=selected.program,
        official_program_url=selected.official_program_url,
        intended_entry_year=selected.intended_entry_year,
        intended_entry_term=selected.intended_entry_term,
    )


def requirements_fixture(
    selected: application.TargetProgram,
    text: str = "Official transcript is required.",
) -> application.TargetProgramRequirementsReview:
    item = application.RequirementItem(
        category="materials",
        requirement=text,
        requirement_zh="必须提交成绩单。",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url=selected.official_program_url,
        source_cycle="2027-28",
        temporal_applicability="target_cycle_confirmed",
        temporal_note="Officially confirmed for the target cycle.",
    )
    return application.requirements_review_from_extraction(
        selected,
        application.RequirementsExtraction(requirements=[item]),
    )


def timeline_fixture(text: str = "2026-12-01") -> application.ApplicationTimeline:
    return application.ApplicationTimeline(
        admission_cycle="Fall 2027",
        application_open_date="2026-09",
        application_open_source_url="https://example.edu/apply",
        application_deadlines=[
            application.ApplicationDeadline(
                label="Final deadline",
                type="final",
                date=text,
                source_url="https://example.edu/apply",
            )
        ],
        rolling_admission=False,
        rolling_admission_source_url="https://example.edu/apply",
        status="complete",
    )


def cache_for(root: Path, name: str = "runtime") -> ProgrammeCache:
    return ProgrammeCache(root / f"{name}.sqlite", root / "seed")


def write_seed(
    cache: ProgrammeCache,
    kind: str,
    identity: dict,
    checked_at: str,
    payload: dict,
) -> Path:
    key = programme_cache_key(identity)
    cache.write_runtime(kind, key, checked_at, payload)
    return cache.export_runtime_to_seed(kind, key, identity)


async def check_requirements_cache_flow(root: Path) -> None:
    cache = cache_for(root)
    selected = target()
    live_result = requirements_fixture(selected)
    live = AsyncMock(return_value=live_result)
    with patch.object(application, "retrieve_target_program_requirements", live):
        first = await application.retrieve_target_program_requirements_cached(selected, cache=cache)
        second = await application.retrieve_target_program_requirements_cached(selected, cache=cache)
    assert first.cache_source == "live"
    assert second.cache_source == "runtime_cache"
    assert live.await_count == 1, "second identical request must make zero additional DeepSeek calls"


async def check_seed_and_precedence(root: Path) -> None:
    selected = target()
    identity = application.target_program_cache_identity(selected)
    key = programme_cache_key(identity)
    seed_builder = cache_for(root, "seed-builder")
    seed_payload = requirements_fixture(selected, "Seed transcript requirement.").model_dump(mode="json")
    write_seed(seed_builder, "requirements", identity, NOW.isoformat(), seed_payload)

    seed_only = cache_for(root, "seed-miss")
    live = AsyncMock()
    with patch.object(application, "retrieve_target_program_requirements", live):
        seeded = await application.retrieve_target_program_requirements_cached(selected, cache=seed_only)
    assert seeded.cache_source == "seed"
    assert live.await_count == 0

    runtime_payload = requirements_fixture(selected, "Runtime transcript requirement.").model_dump(mode="json")
    seed_only.write_runtime("requirements", key, NOW.isoformat(), runtime_payload)
    with patch.object(application, "retrieve_target_program_requirements", live):
        preferred = await application.retrieve_target_program_requirements_cached(selected, cache=seed_only)
    assert preferred.cache_source == "runtime_cache"
    assert preferred.categories[5].requirements[0].requirement.startswith("Runtime")


async def check_expiry_identity_force_and_failure(root: Path) -> None:
    cache = cache_for(root)
    selected = target()
    identity = application.target_program_cache_identity(selected)
    key = programme_cache_key(identity)
    old = (NOW - timedelta(days=8)).isoformat()
    old_payload = requirements_fixture(selected, "Expired requirement.").model_dump(mode="json")
    cache.write_runtime("requirements", key, old, old_payload)
    cache.export_runtime_to_seed("requirements", key, identity)

    live = AsyncMock(return_value=requirements_fixture(selected, "Fresh live requirement."))
    with patch.object(application, "retrieve_target_program_requirements", live):
        refreshed = await application.retrieve_target_program_requirements_cached(selected, cache=cache)
    assert refreshed.cache_source == "live"
    assert live.await_count == 1

    other_programme = target("MSc Data Science")
    other_cycle = target(year=2028)
    live = AsyncMock(side_effect=[requirements_fixture(other_programme), requirements_fixture(other_cycle)])
    with patch.object(application, "retrieve_target_program_requirements", live):
        await application.retrieve_target_program_requirements_cached(other_programme, cache=cache)
        await application.retrieve_target_program_requirements_cached(other_cycle, cache=cache)
    assert live.await_count == 2, "different programme and cycle must both miss"

    forced_live = AsyncMock(return_value=requirements_fixture(selected, "Forced refresh."))
    with patch.object(application, "retrieve_target_program_requirements", forced_live):
        forced = await application.retrieve_target_program_requirements_cached(
            selected, cache=cache, force_refresh=True
        )
    assert forced.cache_source == "live"
    assert forced_live.await_count == 1

    failing_cache = cache_for(root, "failure")
    failure = RuntimeError("fixture live failure")
    with patch.object(
        application, "retrieve_target_program_requirements", AsyncMock(side_effect=failure)
    ):
        try:
            await application.retrieve_target_program_requirements_cached(selected, cache=failing_cache)
        except RuntimeError:
            pass
        else:
            raise AssertionError("live failure must propagate")
    assert failing_cache.read_runtime("requirements", key) is None


async def check_timeline_round_trip(root: Path) -> None:
    cache = cache_for(root)
    request = timeline_request()
    live = AsyncMock(return_value=timeline_fixture())
    with patch.object(application, "retrieve_application_timeline", live):
        first = await application.retrieve_application_timeline_cached(request, cache=cache)
        second = await application.retrieve_application_timeline_cached(request, cache=cache)
    assert live.await_count == 1
    assert second.model_dump() == first.model_dump()

    forced_live = AsyncMock(return_value=timeline_fixture("2026-12-15"))
    with patch.object(application, "retrieve_application_timeline", forced_live):
        forced = await application.retrieve_application_timeline_cached(
            request, cache=cache, force_refresh=True
        )
    assert forced.application_deadlines[0].date == "2026-12-15"
    assert forced_live.await_count == 1


async def check_canonical_equivalent_requirements_hit(root: Path) -> None:
    cache = cache_for(root)
    old_target = application.TargetProgram(
        university="University of Oxford",
        program="MSc Advanced Computer Science",
        official_program_url=(
            "https://www.ox.ac.uk/admissions/graduate/courses/"
            "msc-advanced-computer-science/?utm_source=fixture#requirements"
        ),
        official_domain="ox.ac.uk",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )
    current_target = application.TargetProgram(
        university="  UNIVERSITY   OF OXFORD ",
        program="MSc in Advanced Computer Science",
        official_program_url=(
            "https://www.cs.ox.ac.uk/admissions/graduate/cs-advanced-msc/"
        ),
        official_domain="www.cs.ox.ac.uk",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )
    old_identity = application.target_program_cache_identity(old_target)
    old_cache_key = programme_cache_key(old_identity)
    cache.runtime_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(cache.runtime_db)) as connection:
        connection.execute(
            """
            CREATE TABLE programme_cache (
                cache_kind TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                cache_schema_version INTEGER NOT NULL DEFAULT 1,
                checked_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (cache_kind, cache_key)
            )
            """
        )
        legacy_review = requirements_fixture(old_target)
        connection.execute(
            "INSERT INTO programme_cache VALUES (?, ?, ?, ?, ?)",
            (
                "requirements",
                old_cache_key,
                2,
                legacy_review.checked_at,
                legacy_review.model_dump_json(),
            ),
        )

    unexpected_live = AsyncMock(
        side_effect=AssertionError("canonical-equivalent programme must hit runtime cache")
    )
    with patch.object(application, "retrieve_target_program_requirements", unexpected_live):
        cached = await application.retrieve_target_program_requirements_cached(
            current_target,
            cache=cache,
        )
    assert cached.cache_source == "runtime_cache"
    assert cached.target_program == current_target
    assert unexpected_live.await_count == 0

    different_programme = current_target.model_copy(
        update={"program": "MSc Mathematics and Foundations of Computer Science"}
    )
    different_cycle = current_target.model_copy(update={"intended_entry_year": 2028})
    misses = AsyncMock(
        side_effect=[
            requirements_fixture(different_programme),
            requirements_fixture(different_cycle),
        ]
    )
    with patch.object(application, "retrieve_target_program_requirements", misses):
        await application.retrieve_target_program_requirements_cached(
            different_programme, cache=cache
        )
        await application.retrieve_target_program_requirements_cached(
            different_cycle, cache=cache
        )
    assert misses.await_count == 2


def check_round_trip_and_export(root: Path) -> None:
    cache = cache_for(root)
    selected = target()
    identity = application.target_program_cache_identity(selected)
    key = programme_cache_key(identity)
    requirements = requirements_fixture(selected)
    cache.write_runtime(
        "requirements", key, requirements.checked_at, requirements.model_dump(mode="json")
    )
    record = cache.read_runtime("requirements", key)
    assert record is not None
    restored = application.TargetProgramRequirementsReview.model_validate(record.payload)
    original_item = requirements.categories[5].requirements[0]
    restored_item = restored.categories[5].requirements[0]
    assert restored_item.model_dump() == original_item.model_dump()

    output_path = cache.export_runtime_to_seed("requirements", key, identity)
    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert document["cache_key"] == key
    seed_record = cache.read_seed("requirements", key)
    assert seed_record is not None
    assert application.TargetProgramRequirementsReview.model_validate(seed_record.payload)


async def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        await check_requirements_cache_flow(root / "flow")
        await check_seed_and_precedence(root / "seed")
        await check_expiry_identity_force_and_failure(root / "rules")
        await check_timeline_round_trip(root / "timeline")
        await check_canonical_equivalent_requirements_hit(root / "canonical")
        check_round_trip_and_export(root / "export")
    print("programme cache regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
