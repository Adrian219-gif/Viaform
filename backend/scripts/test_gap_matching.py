"""Deterministic regression coverage for the adaptive Gap MVP."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import (  # noqa: E402
    GapConstraintOption,
    GapDeterministicConstraint,
    GapEvidenceNeed,
    GapEvidenceParseRequest,
    GapPlannedRequirement,
    GapPlannerQuestion,
    RequirementCategoryReview,
    RequirementItem,
    TargetProgram,
    TargetProgramRequirementsReview,
    UserEvidence,
    UserProfile,
    evaluate_deterministic_requirement,
    formal_gap_requirements,
    merge_reusable_evidence,
    parse_gap_evidence,
)
from app import main as application  # noqa: E402


TARGET = TargetProgram(
    university="Regression University",
    program="Regression MSc",
    official_program_url="https://example.edu/programme",
    official_domain="example.edu",
)


def planned_requirement(
    requirement: str,
    category: str,
    kind: str,
    options: list[GapConstraintOption],
    importance: str = "required",
    verification_status: str = "official_verified",
) -> GapPlannedRequirement:
    return GapPlannedRequirement(
        requirement_id=f"{category}:0",
        category=category,
        requirement=requirement,
        importance=importance,
        requirement_verification_status=verification_status,
        source_url=(
            "https://example.edu/programme"
            if verification_status == "official_verified"
            else None
        ),
        matchable=True,
        match_strategy="deterministic",
        evidence_needs=[],
        constraint=GapDeterministicConstraint(kind=kind, options=options),
    )


def parse_one(key: str, evidence_type: str, answer: str) -> UserEvidence:
    question = GapPlannerQuestion(
        question_id=f"q:{key}",
        question="test",
        evidence_keys=[key],
    )
    result = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question,
            evidence_needs=[
                GapEvidenceNeed(key=key, evidence_type=evidence_type, label=key)
            ],
            answer=answer,
        )
    )
    return result.evidence[0]


async def check_ai_reference_interview() -> None:
    review = TargetProgramRequirementsReview(
        target_program=TARGET,
        checked_at="2026-08-24T00:00:00Z",
        categories=[
            RequirementCategoryReview(
                category="language",
                coverage="model_memory_unverified",
                requirements=[
                    RequirementItem(
                        category="language",
                        requirement="IELTS overall >= 7.0",
                        requirement_zh="雅思总分不低于 7.0",
                        importance="required",
                        source_level="unknown",
                        source_type="model_memory",
                        verification_status="model_memory_unverified",
                    )
                ],
            )
        ],
    )
    planner_output = {
        "requirements": [
            {
                "requirement_id": "language:0",
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": "ielts",
                        "evidence_type": "language_score",
                        "label": "IELTS 成绩",
                    }
                ],
                "constraint": {
                    "kind": "score",
                    "relation": "all",
                    "options": [{"key": "ielts", "kind": "score", "minimum": 7.0}],
                },
            }
        ],
        "questions": [
            {
                "question_id": "q:language:0",
                "question": "你目前有 IELTS 成绩吗？",
                "evidence_keys": ["ielts"],
            }
        ],
    }
    original_call = application.call_deepseek

    async def fake_call(*args: object, **kwargs: object) -> str:
        return json.dumps(planner_output, ensure_ascii=False)

    try:
        application.call_deepseek = fake_call
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
                user_profile=UserProfile(),
            )
        )
        assert plan.requirements[0].requirement_verification_status == "model_memory_unverified"
        assert len(plan.questions) == 1 and "AI 参考" in plan.questions[0].question

        known_ielts = parse_one("ielts", "language_score", "IELTS 6.5")
        ask_once_plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
                user_profile=UserProfile(),
                user_evidence=[known_ielts],
            )
        )
        assert not ask_once_plan.questions
    finally:
        application.call_deepseek = original_call


def main() -> None:
    language = planned_requirement(
        "IELTS overall >= 7.0 and each component >= 6.5",
        "language",
        "score",
        [GapConstraintOption(key="ielts", minimum=7.0, component_minimum=6.5)],
    )
    ielts = parse_one(
        "ielts",
        "language_score",
        "IELTS overall 7.0，L 7.5，R 7.0，W 6.0，S 7.0",
    )
    result = evaluate_deterministic_requirement(language, {"ielts": ielts})
    assert result[0] == "partial" and "writing" in result[2]

    language_or = language.model_copy(
        update={
            "requirement": "IELTS >= 7.0 or TOEFL >= 100",
            "constraint": GapDeterministicConstraint(
                kind="score",
                relation="any",
                options=[
                    GapConstraintOption(key="ielts", minimum=7.0),
                    GapConstraintOption(key="toefl", minimum=100),
                ],
            ),
        }
    )
    no_ielts = parse_one("ielts", "language_score", "我没有 IELTS 成绩")
    unknown_toefl = parse_one("toefl", "language_score", "TOEFL 分数不记得")
    assert evaluate_deterministic_requirement(
        language_or,
        {"ielts": no_ielts, "toefl": unknown_toefl},
    )[0] == "unknown"
    toefl_105 = parse_one("toefl", "language_score", "TOEFL 105")
    assert evaluate_deterministic_requirement(
        language_or,
        {"ielts": no_ielts, "toefl": toefl_105},
    )[0] == "met"

    unknown_ielts = parse_one("ielts", "language_score", "我不记得 IELTS 小分")
    assert unknown_ielts.availability == "unknown"
    assert evaluate_deterministic_requirement(language, {"ielts": unknown_ielts})[0] == "unknown"

    portfolio_requirement = planned_requirement(
        "Portfolio required",
        "materials",
        "material_boolean",
        [GapConstraintOption(key="materials.portfolio")],
    )
    portfolio = parse_one("materials.portfolio", "material_status", "作品集还没有准备")
    assert portfolio.availability == "known_negative"
    assert evaluate_deterministic_requirement(
        portfolio_requirement, {"materials.portfolio": portfolio}
    )[0] == "not_met"

    no_probability = parse_one("courses", "courses", "我没修过概率论")
    assert no_probability.availability == "known_negative"

    recommendation_requirement = planned_requirement(
        "2 recommendation letters required",
        "materials",
        "material_quantity",
        [
            GapConstraintOption(
                key="materials.recommendations",
                required_quantity=2,
                unit="封",
            )
        ],
    )
    recommenders = parse_one(
        "materials.recommendations",
        "material_quantity",
        "目前有 1 位推荐人",
    )
    recommendation_result = evaluate_deterministic_requirement(
        recommendation_requirement,
        {"materials.recommendations": recommenders},
    )
    assert recommendation_result[0] == "partial" and "1" in recommendation_result[2]

    preferred_gre = planned_requirement(
        "GRE >= 320 preferred",
        "standardized_test",
        "score",
        [GapConstraintOption(key="gre", minimum=320)],
        importance="preferred",
    )
    gre_315 = parse_one("gre", "standardized_score", "GRE 315")
    assert evaluate_deterministic_requirement(
        preferred_gre, {"gre": gre_315}
    )[0] == "partial"

    gpa_requirement = planned_requirement(
        "GPA >= 3.5/4.0",
        "academic",
        "score",
        [GapConstraintOption(key="gpa", minimum=3.5, scale=4.0)],
    )
    average_only = parse_one("gpa", "academic_score", "我的平均分是 86/100")
    assert average_only.availability == "unknown"
    assert evaluate_deterministic_requirement(gpa_requirement, {"gpa": average_only})[0] == "unknown"

    course_unknown = parse_one(
        "courses",
        "courses",
        "我学过类似课程，但不记得具体内容",
    )
    assert course_unknown.availability == "unknown"

    review = TargetProgramRequirementsReview(
        target_program=TARGET,
        checked_at="2026-08-24T00:00:00Z",
        categories=[
            RequirementCategoryReview(
                category="standardized_test",
                coverage="model_memory_unverified",
                requirements=[
                    RequirementItem(
                        category="standardized_test",
                        requirement="GRE may be expected",
                        importance="unknown",
                        source_level="unknown",
                        source_type="model_memory",
                        verification_status="model_memory_unverified",
                    )
                ],
            ),
            RequirementCategoryReview(
                category="materials",
                coverage="official_verified",
                requirements=[
                    RequirementItem(
                        category="materials",
                        requirement="Portfolio required",
                        importance="required",
                        source_level="program",
                        source_type="official_retrieval",
                        verification_status="official_verified",
                        source_url="https://example.edu/programme",
                    )
                ],
            ),
        ],
    )
    formal = formal_gap_requirements(review)
    assert len(formal) == 2
    assert {
        item["requirement_verification_status"] for item in formal
    } == {"official_verified", "model_memory_unverified"}

    ai_language = planned_requirement(
        "IELTS overall >= 7.0",
        "language",
        "score",
        [GapConstraintOption(key="ielts", minimum=7.0)],
        verification_status="model_memory_unverified",
    )
    ielts_65 = parse_one("ielts", "language_score", "IELTS 6.5")
    ai_gap = evaluate_deterministic_requirement(ai_language, {"ielts": ielts_65})
    assert ai_gap[0] == "not_met" and "0.5" in ai_gap[2]

    existing = merge_reusable_evidence(
        UserProfile(),
        [
            UserEvidence(
                evidence_type="language_score",
                key="ielts",
                value={"score": 7.0},
                raw_answer="IELTS 7.0",
                availability="known",
                updated_at="2026-08-24T00:00:00Z",
            )
        ],
    )
    assert [item.key for item in existing].count("ielts") == 1
    asyncio.run(check_ai_reference_interview())
    print("gap matching deterministic regressions: all checks passed")


if __name__ == "__main__":
    main()
