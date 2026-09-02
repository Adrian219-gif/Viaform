"""Deterministic semantic baseline for successful Oxford and KTH retrievals."""

from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "requirements_capability_baseline.json"


def review_for(case: dict):
    target = main.TargetProgram(**case["target"])
    items = [main.RequirementItem(**item) for item in case["requirements"]]
    return main.requirements_review_from_extraction(
        target,
        main.RequirementsExtraction(requirements=items),
    )


def flattened(review):
    return [item for category in review.categories for item in category.requirements]


def require_semantic(items, *, category, markers, stage, importance="required", official=None):
    matches = [
        item
        for item in items
        if item.category == category
        and all(marker.casefold() in item.requirement.casefold() for marker in markers)
    ]
    assert matches, f"missing {category} semantic markers={markers}"
    assert any(item.applicability_stage == stage for item in matches)
    assert any(item.importance == importance for item in matches)
    assert all(item.source_url for item in matches), f"source URL missing for markers={markers}"
    if official is True:
        assert any(item.verification_status == "official_verified" for item in matches)
    if official is False:
        assert any(item.verification_status == "model_memory_unverified" for item in matches)


def check_oxford(case: dict) -> None:
    review = review_for(case)
    items = flattened(review)
    assert len(items) == case["observed_count_reference"]
    require_semantic(items, category="academic", markers=["degree", "biology"], stage="pre_admission", official=False)
    require_semantic(items, category="language", markers=["7.0", "6.5"], stage="conditional_admission", official=False)
    require_semantic(items, category="materials", markers=["transcript"], stage="pre_admission", official=False)
    require_semantic(items, category="materials", markers=["cv"], stage="pre_admission", official=False)
    require_semantic(items, category="materials", markers=["research proposal"], stage="pre_admission", official=False)
    require_semantic(items, category="materials", markers=["three references"], stage="pre_admission", official=False)
    require_semantic(items, category="other", markers=["supervisor"], stage="pre_admission", importance="recommended", official=False)
    require_semantic(items, category="other", markers=["prs status"], stage="in_program", official=True)
    require_semantic(items, category="other", markers=["25,000", "thesis"], stage="in_program", official=True)
    formal_text = " ".join(
        item["requirement"].casefold() for item in main.formal_gap_requirements(review)
    )
    assert "prs status" not in formal_text
    assert "25,000" not in formal_text
    print("PASS Oxford MSc by Research in Biology semantic capability baseline")


def check_kth(case: dict) -> None:
    review = review_for(case)
    items = flattened(review)
    assert len(items) == case["observed_count_reference"]
    require_semantic(items, category="academic", markers=["180 ects"], stage="pre_admission", official=True)
    require_semantic(items, category="course", markers=["28.5 ects", "calculus", "linear algebra", "discrete mathematics"], stage="pre_admission", official=True)
    require_semantic(items, category="course", markers=["22.5 ects", "object oriented", "algorithms", "complexity"], stage="pre_admission", official=True)
    require_semantic(items, category="language", markers=["ielts 6.5"], stage="pre_admission", official=True)
    for markers in (["transcript"], ["cv"], ["less than 500 words"], ["two letters"], ["summary sheet"]):
        require_semantic(items, category="materials", markers=list(markers), stage="pre_admission", official=True)
    formal_text = " ".join(
        item["requirement"].casefold() for item in main.formal_gap_requirements(review)
    )
    assert "after enrolment" not in formal_text
    print("PASS KTH Computer Science semantic capability baseline")


def run() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    check_oxford(payload["oxford_msc_by_research_biology_fall_2027"])
    check_kth(payload["kth_computer_science_fall_2027"])
    print("requirements capability baselines: all checks passed")


if __name__ == "__main__":
    run()
