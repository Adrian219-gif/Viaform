"""Adaptive Interview evidence-slot completeness regressions."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402
from app.main import (  # noqa: E402
    Education,
    GapConstraintOption,
    GapDeterministicConstraint,
    GapEvidenceNeed,
    GapEvidenceParseRequest,
    GapPlanRequest,
    GapPlannerQuestion,
    GapPlannedRequirement,
    RequirementCategoryReview,
    RequirementItem,
    TargetProgram,
    TargetProgramRequirementsReview,
    UserEvidence,
    UserProfile,
    evaluate_deterministic_requirement,
    parse_gap_evidence,
)


def check_ielts_missing_listening_requires_follow_up() -> None:
    question = GapPlannerQuestion(
        question_id="q:ielts",
        question="请提供 IELTS 总分和四项小分。",
        evidence_keys=["ielts"],
    )
    need = GapEvidenceNeed(
        key="ielts",
        evidence_type="language_score",
        label="IELTS 成绩",
        required_fields=["score", "listening", "reading", "writing", "speaking"],
    )
    partial = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question,
            evidence_needs=[need],
            answer="IELTS overall 7.5，Reading 8，Writing 7，Speaking 7",
        )
    )
    assert partial.evidence[0].availability == "known"
    assert partial.missing_slots == ["ielts.listening"]
    assert partial.slot_states["ielts.listening"] == "missing"
    assert partial.slot_states["ielts.score"] == "known"
    assert partial.follow_up_question and "听力" in partial.follow_up_question

    complete = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question,
            evidence_needs=[need],
            existing_evidence=partial.evidence,
            answer="Listening 7.5",
        )
    )
    assert not complete.missing_slots
    assert all(state == "known" for state in complete.slot_states.values())
    value = complete.evidence[0].value
    assert value["score"] == 7.5
    assert value["subscores"] == {
        "listening": 7.5,
        "reading": 8.0,
        "writing": 7.0,
        "speaking": 7.0,
    }


def check_compound_material_answer() -> None:
    keys = [
        "materials.cv",
        "materials.personal_statement",
        "materials.transcript",
        "materials.degree_certificate",
        "materials.recommendations",
    ]
    result = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q:materials",
                question="这些申请材料目前分别准备好了吗？",
                evidence_keys=keys,
            ),
            evidence_needs=[
                GapEvidenceNeed(
                    key=key,
                    evidence_type="material_status",
                    label=key,
                    required_fields=["status"],
                )
                for key in keys
            ],
            answer="除了推荐信都有",
        )
    )
    assert not result.missing_slots, result
    availability = {item.key: item.availability for item in result.evidence}
    assert availability == {
        "materials.cv": "known",
        "materials.personal_statement": "known",
        "materials.transcript": "known",
        "materials.degree_certificate": "known",
        "materials.recommendations": "known_negative",
    }


def alternative_score_need(key: str, minimum: float) -> GapEvidenceNeed:
    return GapEvidenceNeed(
        key=key,
        evidence_type="language_score",
        label=key.upper(),
        required_fields=["score"],
        evidence_group="language:0:alternatives",
        group_relation="any",
        minimum=minimum,
    )


def check_satisfied_alternative_stops_follow_up() -> None:
    needs = [alternative_score_need("ielts", 7.0), alternative_score_need("toefl", 100)]
    result = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q:language",
                question="请提供 IELTS 或 TOEFL 成绩。",
                evidence_keys=["ielts", "toefl"],
            ),
            evidence_needs=needs,
            answer="IELTS 7.5",
        )
    )
    assert not result.missing_slots
    assert result.follow_up_question is None
    assert result.satisfied_evidence_groups == ["language:0:alternatives"]
    assert [item.key for item in result.evidence] == ["ielts"]


def check_academic_alternative_stops_follow_up() -> None:
    group = "academic:0:alternatives"
    needs = [
        GapEvidenceNeed(
            key="academic.degree_classification",
            evidence_type="generic",
            label="学位等级",
            required_fields=["description"],
            evidence_group=group,
            group_relation="any",
        ),
        GapEvidenceNeed(
            key="gpa",
            evidence_type="academic_score",
            label="GPA",
            required_fields=["score", "scale"],
            evidence_group=group,
            group_relation="any",
            minimum=3.5,
        ),
    ]
    result = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q:academic-alternative",
                question="请提供你的学位等级（或 GPA）。",
                evidence_keys=[need.key for need in needs],
            ),
            evidence_needs=needs,
            answer="二等一学位",
        )
    )
    assert not result.missing_slots
    assert result.follow_up_question is None
    assert result.satisfied_evidence_groups == [group]
    assert len(result.evidence) == 1
    assert result.evidence[0].key == "academic.degree_classification"
    assert result.evidence[0].availability == "known"


def check_academic_any_group_contextual_parsing() -> None:
    group = "academic:contextual:alternatives"
    needs = [
        GapEvidenceNeed(
            key="degree_classification",
            evidence_type="generic",
            label="学位等级",
            required_fields=["description"],
            evidence_group=group,
            group_relation="any",
        ),
        GapEvidenceNeed(
            key="gpa",
            evidence_type="academic_score",
            label="GPA",
            required_fields=["score"],
            evidence_group=group,
            group_relation="any",
        ),
        GapEvidenceNeed(
            key="average_score",
            evidence_type="academic_score",
            label="平均分",
            required_fields=["score"],
            evidence_group=group,
            group_relation="any",
        ),
    ]
    question = GapPlannerQuestion(
        question_id="q:academic-contextual",
        question="请问您的学位等级或 GPA/平均分是多少？",
        evidence_keys=[need.key for need in needs],
    )

    for answer in ("二等二", "First Class", "2:1"):
        result = parse_gap_evidence(
            GapEvidenceParseRequest(
                question=question,
                evidence_needs=needs,
                answer=answer,
            )
        )
        assert not result.missing_slots
        assert result.follow_up_question is None
        assert result.satisfied_evidence_groups == [group]
        assert len(result.evidence) == 1
        assert result.evidence[0].key == "degree_classification"
        assert result.evidence[0].availability == "known"
        assert result.evidence[0].value == {"description": answer}

    for answer in ("87分", "平均分87", "均分87"):
        result = parse_gap_evidence(
            GapEvidenceParseRequest(
                question=question,
                evidence_needs=needs,
                answer=answer,
            )
        )
        assert not result.missing_slots
        assert result.satisfied_evidence_groups == [group]
        assert len(result.evidence) == 1
        assert result.evidence[0].key == "average_score"
        assert result.evidence[0].availability == "known"
        assert result.evidence[0].value == {"score": 87.0}

    gpa = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question,
            evidence_needs=needs,
            answer="GPA 3.7",
        )
    )
    assert not gpa.missing_slots
    assert gpa.satisfied_evidence_groups == [group]
    assert len(gpa.evidence) == 1
    assert gpa.evidence[0].key == "gpa"
    assert gpa.evidence[0].value == {"score": 3.7}

    ambiguous = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question,
            evidence_needs=needs,
            answer="4",
        )
    )
    assert not ambiguous.evidence
    assert ambiguous.missing_slots == ["gpa.score", "average_score.score"]
    assert ambiguous.follow_up_question == "请确认这个数字属于 GPA（绩点）还是百分制平均分？"
    assert ambiguous.slot_states == {
        "gpa.score": "missing",
        "average_score.score": "missing",
    }

    existing = UserEvidence(
        evidence_type="generic",
        key="degree_classification",
        value={"description": "二等二"},
        raw_answer="二等二",
        availability="known",
        updated_at="2026-08-30T00:00:00+00:00",
    )
    already_satisfied = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question,
            evidence_needs=needs,
            answer="4",
            existing_evidence=[existing],
        )
    )
    assert not already_satisfied.missing_slots
    assert already_satisfied.follow_up_question is None
    assert already_satisfied.satisfied_evidence_groups == [group]


def check_compound_numeric_and_experience_answer() -> None:
    needs = [
        GapEvidenceNeed(
            key="gpa",
            evidence_type="academic_score",
            label="GPA 分制",
            required_fields=["scale"],
        ),
        GapEvidenceNeed(
            key="experience",
            evidence_type="experience",
            label="相关经历",
            required_fields=["description"],
        ),
    ]
    question = GapPlannerQuestion(
        question_id="q:gpa-scale-experience",
        question="请补充 GPA 总分和相关经历。",
        evidence_keys=[need.key for need in needs],
    )
    for answer in ("4，没相关经验", "总分4，无相关经验"):
        result = parse_gap_evidence(
            GapEvidenceParseRequest(
                question=question,
                evidence_needs=needs,
                answer=answer,
            )
        )
        assert not result.missing_slots
        assert result.follow_up_question is None
        evidence = {item.key: item for item in result.evidence}
        assert evidence["gpa"].availability == "known"
        assert evidence["gpa"].value == {"scale": 4.0}
        assert evidence["experience"].availability == "known_negative"
        assert result.slot_states == {
            "gpa.scale": "known",
            "experience.description": "known_negative",
        }


def check_negative_missing_alternative_is_terminal() -> None:
    for answer in ("没有", "暂时没有"):
        result = parse_gap_evidence(
            GapEvidenceParseRequest(
                question=GapPlannerQuestion(
                    question_id="q:toefl",
                    question="请问你有 TOEFL 成绩吗？",
                    evidence_keys=["toefl"],
                ),
                evidence_needs=[alternative_score_need("toefl", 100)],
                answer=answer,
            )
        )
        assert not result.missing_slots
        assert result.follow_up_question is None
        assert result.evidence[0].availability == "known_negative"
        assert result.slot_states == {"toefl.score": "known_negative"}


def check_all_alternatives_negative_reaches_not_met() -> None:
    needs = [alternative_score_need("ielts", 7.0), alternative_score_need("toefl", 100)]
    parsed = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q:language",
                question="请提供 IELTS 或 TOEFL 成绩。",
                evidence_keys=["ielts", "toefl"],
            ),
            evidence_needs=needs,
            answer="都没有",
        )
    )
    assert not parsed.missing_slots
    assert parsed.follow_up_question is None
    assert all(item.availability == "known_negative" for item in parsed.evidence)
    planned = GapPlannedRequirement(
        requirement_id="language:0",
        category="language",
        requirement="IELTS >= 7.0 OR TOEFL >= 100",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
        matchable=True,
        match_strategy="deterministic",
        evidence_needs=needs,
        constraint=GapDeterministicConstraint(
            kind="score",
            relation="any",
            options=[
                GapConstraintOption(key="ielts", minimum=7.0),
                GapConstraintOption(key="toefl", minimum=100),
            ],
        ),
    )
    evidence_by_key = {item.key: item for item in parsed.evidence}
    assert evaluate_deterministic_requirement(planned, evidence_by_key)[0] == "not_met"


def education_request(answer: str):
    keys = ["education.university", "education.major"]
    return parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q:education",
                question="请提供本科院校和本科专业。",
                evidence_keys=keys,
            ),
            evidence_needs=[
                GapEvidenceNeed(
                    key="education.university",
                    evidence_type="education_university",
                    label="本科院校",
                    required_fields=["description"],
                ),
                GapEvidenceNeed(
                    key="education.major",
                    evidence_type="education_major",
                    label="本科专业",
                    required_fields=["description"],
                ),
            ],
            answer=answer,
        )
    )


def check_education_pure_value_answers() -> None:
    for answer, expected in (
        ("KTH CS", ("KTH", "CS")),
        ("宁波诺丁汉 cs", ("宁波诺丁汉", "cs")),
        ("宁波诺丁汉大学 计算机专业", ("宁波诺丁汉大学", "计算机专业")),
    ):
        result = education_request(answer)
        assert not result.missing_slots
        evidence = {item.key: item for item in result.evidence}
        assert evidence["education.university"].availability == "known"
        assert evidence["education.major"].availability == "known"
        assert evidence["education.university"].value == expected[0]
        assert evidence["education.major"].value == expected[1]


def check_one_education_field_only() -> None:
    result = education_request("宁波诺丁汉大学")
    assert [item.key for item in result.evidence] == ["education.university"]
    assert result.missing_slots == ["education.major.description"]
    assert result.slot_states == {
        "education.university.description": "known",
        "education.major.description": "missing",
    }
    assert result.follow_up_question and "本科专业" in result.follow_up_question
    assert "本科院校" not in result.follow_up_question


def check_single_major_short_answer_converges() -> None:
    result = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q:education-major",
                question="本科专业是什么？",
                evidence_keys=["education.major"],
            ),
            evidence_needs=[
                GapEvidenceNeed(
                    key="education.major",
                    evidence_type="education_major",
                    label="本科专业",
                    required_fields=["description"],
                )
            ],
            answer="数学",
        )
    )
    assert not result.missing_slots
    assert result.follow_up_question is None
    assert len(result.evidence) == 1
    assert result.evidence[0].key == "education.major"
    assert result.evidence[0].availability == "known"
    assert result.evidence[0].value == "数学"
    assert result.slot_states == {"education.major.description": "known"}


def check_explicit_unknown_education() -> None:
    for answer in ("不知道", "不记得", "不清楚"):
        result = education_request(answer)
        assert not result.missing_slots
        assert result.follow_up_question is None
        assert len(result.evidence) == 2
        assert all(item.availability == "unknown" for item in result.evidence)
        assert all(state == "unknown" for state in result.slot_states.values())


def core_005_course_needs() -> list[GapEvidenceNeed]:
    return [
        GapEvidenceNeed(
            key=key,
            evidence_type="courses",
            label=label,
            required_fields=["description"],
        )
        for key, label in (
            ("courses.math_calculus", "Calculus in one variable"),
            ("courses.linear_algebra", "Linear Algebra"),
            ("courses.probability_statistics", "Probability and Statistics"),
            ("courses.discrete_mathematics", "Discrete Mathematics"),
            ("courses.math_total_credits", "Total mathematics credits"),
        )
    ]


def check_core_005_course_slots_converge() -> None:
    needs = core_005_course_needs()
    question = GapPlannerQuestion(
        question_id="q_math_courses",
        question="请说明修读过的数学课程和总学分。",
        evidence_keys=[need.key for need in needs],
    )
    first = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question,
            evidence_needs=needs,
            answer=(
                "学过 Algorithms、Data Structures、Discrete Mathematics、Linear Algebra、"
                "Calculus、Probability、Operating Systems、Computer Networks 和 Machine Learning。"
            ),
        )
    )
    evidence = {item.key: item for item in first.evidence}
    assert set(evidence) == {
        "courses.math_calculus",
        "courses.linear_algebra",
        "courses.probability_statistics",
        "courses.discrete_mathematics",
    }
    assert all(item.availability == "known" for item in evidence.values())
    assert first.missing_slots == ["courses.math_total_credits.description"]
    assert first.follow_up_question
    assert "courses.math_calculus" not in first.follow_up_question

    final = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=question.model_copy(
                update={"evidence_keys": ["courses.math_total_credits"]}
            ),
            evidence_needs=[needs[-1]],
            existing_evidence=first.evidence,
            answer="数学总学分不记得。",
        )
    )
    assert not final.missing_slots
    assert final.follow_up_question is None
    assert final.evidence[0].key == "courses.math_total_credits"
    assert final.evidence[0].availability == "unknown"


def check_course_slots_keep_independent_terminal_states() -> None:
    needs = core_005_course_needs()
    parsed = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q_math_courses_partial",
                question="请说明这些课程情况。",
                evidence_keys=[need.key for need in needs],
            ),
            evidence_needs=needs,
            answer=(
                "学过 Calculus 和 Linear Algebra，没有 Probability；"
                "Discrete Mathematics 不记得。"
            ),
        )
    )
    states = {item.key: item.availability for item in parsed.evidence}
    assert states == {
        "courses.math_calculus": "known",
        "courses.linear_algebra": "known",
        "courses.probability_statistics": "known_negative",
        "courses.discrete_mathematics": "unknown",
    }
    assert parsed.missing_slots == ["courses.math_total_credits.description"]


async def check_profile_education_is_reused() -> None:
    target = TargetProgram(
        university="Example University",
        program="Example MSc",
        official_program_url="https://example.edu/program",
        official_domain="example.edu",
    )
    review = TargetProgramRequirementsReview(
        target_program=target,
        checked_at="2026-08-27T00:00:00Z",
        categories=[
            RequirementCategoryReview(
                category="academic",
                coverage="official_verified",
                requirements=[
                    RequirementItem(
                        category="academic",
                        requirement="A relevant university and major are required.",
                        importance="required",
                        source_level="program",
                        source_type="official_retrieval",
                        verification_status="official_verified",
                        temporal_applicability="undated",
                    )
                ],
            )
        ],
    )
    output = {
        "requirements": [
            {
                "requirement_id": "academic:0",
                "matchable": True,
                "evidence_needs": [
                    {"key": "education.university", "evidence_type": "education_university"},
                    {"key": "education.major", "evidence_type": "education_major"},
                ],
            }
        ],
        "questions": [
            {
                "question_id": "q:academic:0",
                "question": "请提供本科院校和专业。",
                "evidence_keys": ["education.university", "education.major"],
            }
        ],
    }
    original = application.call_deepseek

    async def fake_call(*args, **kwargs):
        return json.dumps(output, ensure_ascii=False)

    application.call_deepseek = fake_call
    try:
        plan = await application.build_gap_plan(
            GapPlanRequest(
                target_program=target,
                requirements_review=review,
                user_profile=UserProfile(
                    education=Education(
                        university="宁波诺丁汉大学",
                        major="计算机科学",
                    )
                ),
            )
        )
    finally:
        application.call_deepseek = original
    reusable = {item.key: item for item in plan.reusable_evidence}
    assert reusable["education.university"].availability == "known"
    assert reusable["education.major"].availability == "known"
    assert all(need.already_known for need in plan.requirements[0].evidence_needs)
    assert not plan.questions


def check_ielts_collective_subscores_converge() -> None:
    need = GapEvidenceNeed(
        key="language.ielts",
        evidence_type="language_score",
        label="IELTS",
        required_fields=["score", "listening", "reading", "writing", "speaking"],
        minimum=7.5,
        component_minimum=7.0,
    )
    first = parse_gap_evidence(
        GapEvidenceParseRequest(
            question=GapPlannerQuestion(
                question_id="q:ielts",
                question="请提供 IELTS 成绩。",
                evidence_keys=["language.ielts"],
            ),
            evidence_needs=[need],
            answer="雅思7.5",
        )
    )
    assert first.evidence[0].key == "ielts"
    assert first.evidence[0].value == {"score": 7.5}
    assert first.missing_slots == [
        "ielts.listening",
        "ielts.reading",
        "ielts.writing",
        "ielts.speaking",
    ]

    for answer in ("都是7.5", "全部7.5", "四项都是7.5"):
        completed = parse_gap_evidence(
            GapEvidenceParseRequest(
                question=GapPlannerQuestion(
                    question_id="q:ielts:components",
                    question=first.follow_up_question or "请补充四项小分。",
                    evidence_keys=["ielts"],
                ),
                evidence_needs=[need],
                existing_evidence=first.evidence,
                answer=answer,
            )
        )
        assert completed.missing_slots == []
        assert completed.follow_up_question is None
        assert completed.evidence[0].value == {
            "score": 7.5,
            "subscores": {
                "listening": 7.5,
                "reading": 7.5,
                "writing": 7.5,
                "speaking": 7.5,
            },
        }


def main() -> None:
    check_ielts_missing_listening_requires_follow_up()
    check_compound_material_answer()
    check_satisfied_alternative_stops_follow_up()
    check_academic_alternative_stops_follow_up()
    check_academic_any_group_contextual_parsing()
    check_compound_numeric_and_experience_answer()
    check_negative_missing_alternative_is_terminal()
    check_all_alternatives_negative_reaches_not_met()
    check_education_pure_value_answers()
    check_one_education_field_only()
    check_single_major_short_answer_converges()
    check_explicit_unknown_education()
    check_core_005_course_slots_converge()
    check_course_slots_keep_independent_terminal_states()
    check_ielts_collective_subscores_converge()
    asyncio.run(check_profile_education_is_reused())
    print("adaptive evidence completeness regressions: all checks passed")


if __name__ == "__main__":
    main()
