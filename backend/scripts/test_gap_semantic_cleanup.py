"""Offline regressions for Gap semantic filtering and canonical evidence reuse."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


TARGET = application.TargetProgram(
    university="Example University",
    program="Example MSc",
    official_program_url="https://example.edu/programme",
    official_domain="example.edu",
    intended_entry_year=2027,
    intended_entry_term="fall",
)


def item(category: str, text: str, temporal: str = "undated"):
    return application.RequirementItem(
        category=category,
        requirement=text,
        importance="required" if category != "other" else "unknown",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        source_cycle="2026-27" if temporal == "previous_cycle" else None,
        temporal_applicability=temporal,
    )


def review() -> application.TargetProgramRequirementsReview:
    categories = []
    source = {
        "language": [
            item("language", "IELTS 7.5 overall with at least 7.0 in each component is required.")
        ],
        "materials": [
            item(
                "materials",
                "Applications must be submitted through the graduate application form, "
                "which requires official academic transcripts; an application fee applies.",
                "unknown",
            ),
            item(
                "materials",
                "Evidence of English language proficiency is required.",
                "unknown",
            ),
        ],
        "other": [
            item(
                "other",
                "The programme is full-time and requires attendance on campus.",
                "previous_cycle",
            ),
            item("other", "A non-refundable application fee applies."),
        ],
    }
    for category in (
        "academic",
        "course",
        "language",
        "standardized_test",
        "experience",
        "materials",
        "other",
    ):
        requirements = source.get(category, [])
        categories.append(
            application.RequirementCategoryReview(
                category=category,
                coverage="official_verified" if requirements else "not_found",
                requirements=requirements,
            )
        )
    return application.TargetProgramRequirementsReview(
        target_program=TARGET,
        checked_at="2026-08-30T00:00:00Z",
        categories=categories,
    )


async def check_filter_split_and_reuse() -> None:
    formal = application.formal_gap_requirements(review())
    by_id = {entry["requirement_id"]: entry for entry in formal}
    assert by_id["materials:0:transcript"]["gap_eligibility"] == "matchable"
    assert by_id["materials:0:transcript"]["category"] == "materials"
    assert "transcript" in by_id["materials:0:transcript"]["requirement"].casefold()
    assert by_id["materials:0:process"]["gap_eligibility"] == "application_process"
    assert by_id["materials:1"]["gap_eligibility"] == "duplicate_language_reference"
    assert by_id["other:0"]["gap_eligibility"] == "programme_information"
    assert by_id["other:1"]["gap_eligibility"] == "application_process"

    output = {
        "requirements": [
            {
                "requirement_id": "language:0",
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {"key": "language.ielts", "evidence_type": "language_score", "label": "IELTS"}
                ],
                "constraint": {
                    "kind": "score",
                    "relation": "all",
                    "options": [
                        {
                            "key": "language.ielts",
                            "kind": "score",
                            "minimum": 7.5,
                            "component_minimum": 7.0,
                        }
                    ],
                },
            },
            {
                "requirement_id": "materials:0:transcript",
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": "materials.transcript",
                        "evidence_type": "material_status",
                        "label": "成绩单",
                    }
                ],
                "constraint": {
                    "kind": "material_boolean",
                    "options": [
                        {"key": "materials.transcript", "kind": "material_boolean"}
                    ],
                },
            },
            *[
                {
                    "requirement_id": requirement_id,
                    "matchable": True,
                    "match_strategy": "semantic",
                    "evidence_needs": [
                        {
                            "key": "language.ielts" if requirement_id == "materials:1" else f"generic.{requirement_id}",
                            "evidence_type": "language_score" if requirement_id == "materials:1" else "generic",
                        }
                    ],
                }
                for requirement_id in (
                    "materials:0:process",
                    "materials:1",
                    "other:0",
                    "other:1",
                )
            ],
        ],
        "questions": [
            {"question_id": "q:language", "question": "IELTS?", "evidence_keys": ["language.ielts"]},
            {"question_id": "q:language-duplicate", "question": "English proof?", "evidence_keys": ["ielts"]},
            {"question_id": "q:transcript", "question": "Transcript?", "evidence_keys": ["materials.transcript"]},
            *[
                {
                    "question_id": f"q:{requirement_id}",
                    "question": "Informational?",
                    "evidence_keys": [f"generic.{requirement_id}"],
                }
                for requirement_id in ("materials:0:process", "other:0", "other:1")
            ],
        ],
    }
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(output)

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review(),
            )
        )
    finally:
        application.call_deepseek = original

    planned = {entry.requirement_id: entry for entry in plan.requirements}
    assert planned["language:0"].evidence_needs[0].key == "ielts"
    assert planned["materials:0:transcript"].user_matchable
    for requirement_id in (
        "materials:0:process",
        "materials:1",
        "other:0",
        "other:1",
    ):
        assert not planned[requirement_id].user_matchable
        assert planned[requirement_id].evidence_needs == []
    assert plan.questions[0].evidence_keys == ["ielts"]
    assert len(plan.questions[1].evidence_keys) == 1
    assert plan.questions[1].evidence_keys[0].startswith("material_item.")

    ielts = application.UserEvidence(
        evidence_type="language_score",
        key="language.ielts",
        value={
            "score": 7.5,
            "subscores": {
                "listening": 7.5,
                "reading": 7.5,
                "writing": 7.5,
                "speaking": 7.5,
            },
        },
        raw_answer="IELTS 7.5，四项都是7.5",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    transcript = application.UserEvidence(
        evidence_type="material_status",
        key="materials.transcript",
        value={"status": False},
        raw_answer="暂时没有成绩单",
        availability="known_negative",
        updated_at="2026-08-30T00:00:00Z",
    )
    analysis = await application.analyze_gap(
        application.GapAnalysisRequest(
            target_program=TARGET,
            plan=plan,
            user_evidence=[ielts, transcript],
        )
    )
    assert {result.requirement_id for result in analysis.results} == {
        "language:0",
        "materials:0:transcript",
    }
    assert {entry.requirement_id for entry in analysis.informational_requirements} == {
        "materials:0:process",
        "materials:1",
        "other:0",
        "other:1",
    }


def check_statement_alias_merge() -> None:
    merged = application.merge_reusable_evidence(
        application.UserProfile(),
        [
            application.UserEvidence(
                evidence_type="material_status",
                key="statement_of_purpose",
                value={"status": True},
                raw_answer="SOP 已准备",
                availability="known",
                updated_at="2026-08-30T00:00:00Z",
            )
        ],
    )
    assert len(merged) == 1
    assert merged[0].key == "materials.personal_statement"
    assert application.active_gap_reason_code("unknown", False) == "user_evidence_missing"
    assert (
        application.active_gap_reason_code("unknown", True)
        == "semantic_evidence_insufficient"
    )


def materials_review(*requirements: str) -> application.TargetProgramRequirementsReview:
    categories = []
    for category in (
        "academic",
        "course",
        "language",
        "standardized_test",
        "experience",
        "materials",
        "other",
    ):
        items = [item("materials", requirement) for requirement in requirements] if category == "materials" else []
        categories.append(
            application.RequirementCategoryReview(
                category=category,
                coverage="official_verified" if items else "not_found",
                requirements=items,
            )
        )
    return application.TargetProgramRequirementsReview(
        target_program=TARGET,
        checked_at="2026-08-30T00:00:00Z",
        categories=categories,
    )


async def check_core_requirement_precedes_timeline_suffix() -> None:
    recommendation_text = (
        "Letters of recommendation are required as part of the MSR application; "
        "they cannot be updated after the application deadline."
    )
    formal = application.formal_gap_requirements(
        materials_review(
            recommendation_text,
            "Applications close on December 9.",
            "Materials cannot be updated after the deadline.",
            "Transcripts are required; they cannot be updated after the application deadline.",
            "A CV is required; it must be submitted before the application deadline.",
        )
    )
    by_id = {entry["requirement_id"]: entry for entry in formal}
    assert by_id["materials:0:recommendations"]["gap_eligibility"] == "matchable"
    assert by_id["materials:0:recommendations"]["category"] == "materials"
    assert by_id["materials:0:recommendations"]["importance"] == "required"
    assert by_id["materials:0:process"]["gap_eligibility"] == "timeline"
    assert by_id["materials:1"]["gap_eligibility"] == "timeline"
    assert by_id["materials:2"]["gap_eligibility"] == "application_process"
    assert by_id["materials:3:transcript"]["gap_eligibility"] == "matchable"
    assert by_id["materials:4:cv"]["gap_eligibility"] == "matchable"

    output = {
        "requirements": [
            {
                "requirement_id": "materials:0:recommendations",
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": "materials.recommendations",
                        "evidence_type": "material_status",
                        "value_kind": "boolean",
                        "label": "推荐信",
                    }
                ],
                "constraint": {
                    "kind": "material_boolean",
                    "relation": "all",
                    "options": [
                        {
                            "key": "materials.recommendations",
                            "kind": "material_boolean",
                        }
                    ],
                },
            },
            {
                "requirement_id": "materials:0:process",
                "matchable": False,
                "informational_reason": "timeline",
                "evidence_needs": [],
            },
        ],
        "questions": [],
    }
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(output)

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=materials_review(recommendation_text),
            )
        )
    finally:
        application.call_deepseek = original

    planned = {entry.requirement_id: entry for entry in plan.requirements}
    recommendation = planned["materials:0:recommendations"]
    assert recommendation.user_matchable
    assert recommendation.evidence_needs
    assert recommendation.evidence_needs[0].evidence_type == "material_quantity"
    recommendation_questions = [
        question
        for question in plan.questions
        if question.requirement_id == "materials:0:recommendations"
    ]
    assert len(recommendation_questions) == 1
    assert recommendation_questions[0].control_type == "number"
    assert recommendation_questions[0].expected_evidence_keys == [
        recommendation.evidence_needs[0].key
    ]


async def main() -> None:
    check_statement_alias_merge()
    await check_filter_split_and_reuse()
    await check_core_requirement_precedes_timeline_suffix()
    print("gap semantic cleanup regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
