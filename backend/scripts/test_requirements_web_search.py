"""Live Phase B regression checks for Target Program Requirements retrieval."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import TargetProgram, retrieve_target_program_requirements  # noqa: E402
from report_output import print_json_report  # noqa: E402


CASES = [
    TargetProgram(
        university="KTH Royal Institute of Technology",
        program="MSc Computer Science",
        official_program_url=(
            "https://www.kth.se/en/studies/master/computer-science/"
            "entry-requirements-computer-science-1.419975"
        ),
        official_domain="kth.se",
    ),
    TargetProgram(
        university="University of California, Berkeley",
        program="EECS - Computer Science MS",
        official_program_url=(
            "https://grad.berkeley.edu/program/eecs-computer-science-ms/"
        ),
        official_domain="grad.berkeley.edu",
    ),
    TargetProgram(
        university="Royal College of Art",
        program="Painting MA",
        official_program_url=(
            "https://www.rca.ac.uk/study/programme-finder/painting-ma/"
        ),
        official_domain="rca.ac.uk",
    ),
    TargetProgram(
        university="Imperial College London",
        program="Applied Machine Learning MSc",
        official_program_url=(
            "https://www.imperial.ac.uk/study/courses/postgraduate-taught/"
            "applied-machine-learning/"
        ),
        official_domain="imperial.ac.uk",
    ),
    TargetProgram(
        university="University of Oxford",
        program="MSc Advanced Computer Science",
        official_program_url=(
            "https://www.ox.ac.uk/admissions/graduate/courses/"
            "msc-advanced-computer-science"
        ),
        official_domain="ox.ac.uk",
    ),
    TargetProgram(
        university="University of Oxford",
        program="Master of Fine Art (MFA)",
        official_program_url=(
            "https://www.ox.ac.uk/admissions/graduate/courses/mfa-fine-art"
        ),
        official_domain="ox.ac.uk",
    ),
    TargetProgram(
        university="Technische Universität Wien",
        program="Logic and Artificial Intelligence",
        official_program_url=(
            "https://informatics.tuwien.ac.at/master/"
            "logic-and-artificial-intelligence/"
        ),
        official_domain="tuwien.ac.at",
    ),
]


def assert_rca_painting_requirements(items: list[dict]) -> None:
    assert items, "RCA Painting MA returned an empty Requirements array"
    text_by_category = {
        category: " ".join(
            item["requirement"].casefold()
            for item in items
            if item["category"] == category
        )
        for category in ("academic", "materials", "language")
    }
    assert any(
        marker in text_by_category["academic"]
        for marker in ("ba", "undergraduate", "degree")
    ), "RCA Painting MA academic degree requirement was not retrieved"
    for marker in ("portfolio", "personal statement", "video"):
        assert marker in text_by_category["materials"], (
            f"RCA Painting MA {marker} requirement was not retrieved"
        )
    assert any(
        marker in text_by_category["language"]
        for marker in ("english", "ielts")
    ), "RCA Painting MA English requirement was not retrieved"


def assert_oxford_advanced_cs_requirements(items: list[dict]) -> None:
    assert items, "Oxford Advanced Computer Science returned an empty Requirements array"
    programme_items = [
        item for item in items
        if item["source_url"]
        and "ox.ac.uk" in item["source_url"]
        and item["source_level"] == "program"
    ]
    assert programme_items, (
        "Oxford Advanced Computer Science returned no programme-level Requirements"
    )
    academic_text = " ".join(
        item["requirement"].casefold()
        for item in programme_items
        if item["category"] == "academic"
    )
    assert any(
        marker in academic_text
        for marker in (
            "degree",
            "first-class",
            "upper second",
            "computer science",
            "mathemat",
        )
    ), "Oxford Advanced Computer Science academic entry requirement was not retrieved"
    supporting_text = " ".join(
        item["requirement"].casefold()
        for item in programme_items
        if item["category"] in {"language", "materials"}
    )
    assert any(
        marker in supporting_text
        for marker in (
            "english",
            "ielts",
            "toefl",
            "transcript",
            "statement",
            "reference",
            "cv",
        )
    ), "Oxford Advanced Computer Science supporting requirement was not retrieved"


def assert_required_official_material(
    items: list[dict],
    *,
    marker: str,
    case_label: str,
) -> None:
    matches = [
        item
        for item in items
        if item["category"] == "materials"
        and marker in item["requirement"].casefold()
    ]
    assert matches, f"{case_label} required {marker} was not retrieved"
    assert any(item["importance"] == "required" for item in matches), (
        f"{case_label} {marker} was not marked required"
    )
    assert any(
        item["verification_status"] == "official_verified"
        and item["source_type"] == "official_retrieval"
        and item["source_level"] != "unknown"
        and item["source_url"]
        for item in matches
    ), f"{case_label} {marker} had no official source"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    reports = []
    requested_case = " ".join(sys.argv[1:]).strip().casefold()
    selected_cases = [
        target
        for target in CASES
        if not requested_case
        or requested_case in f"{target.university} {target.program}".casefold()
    ]
    for target in selected_cases:
        started_at = time.perf_counter()
        try:
            review = await retrieve_target_program_requirements(target)
            items = [
                item.model_dump()
                for category in review.categories
                for item in category.requirements
            ]
            report = {
                "university": target.university,
                "program": target.program,
                "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                "deepseek_web_search_workflows": 1,
                "web_search_max_uses": 2,
                "returned_requirement_count": len(items),
                "empty_result": not items,
                "coverage": {
                    category.category: category.coverage
                    for category in review.categories
                },
                "official_evidence_urls": sorted(
                    {
                        item["source_url"]
                        for item in items
                        if item["verification_status"] == "official_verified"
                        and item["source_url"]
                    }
                ),
                "requirements": items,
            }
            if target.university == "Royal College of Art" and target.program == "Painting MA":
                try:
                    assert_rca_painting_requirements(items)
                except AssertionError as error:
                    report["regression_error"] = str(error)
            if (
                target.university == "University of Oxford"
                and target.program == "MSc Advanced Computer Science"
            ):
                try:
                    assert_oxford_advanced_cs_requirements(items)
                except AssertionError as error:
                    report["regression_error"] = str(error)
            if target.university == "KTH Royal Institute of Technology":
                try:
                    assert_required_official_material(
                        items,
                        marker="summary sheet",
                        case_label="KTH MSc Computer Science",
                    )
                except AssertionError as error:
                    report["regression_error"] = str(error)
            if target.university == "University of California, Berkeley":
                try:
                    assert_required_official_material(
                        items,
                        marker="transcript",
                        case_label="Berkeley EECS Computer Science MS",
                    )
                except AssertionError as error:
                    report["regression_error"] = str(error)
            reports.append(report)
        except Exception as error:  # keep live cases independent for diagnostics
            reports.append(
                {
                    "university": target.university,
                    "program": target.program,
                    "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    print_json_report(reports)
    if any(report.get("error") or report.get("regression_error") for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
