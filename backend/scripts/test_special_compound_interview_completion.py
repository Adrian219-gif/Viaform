from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import main as application


def target() -> application.TargetProgram:
    return application.TargetProgram(
        university="KTH Royal Institute of Technology",
        program="MSc Computer Science",
        official_program_url="https://www.kth.se/en/studies/master/computer-science",
        official_domain="kth.se",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )


def requirement(text: str) -> application.RequirementItem:
    return application.RequirementItem(
        category="course",
        requirement=text,
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url=target().official_program_url,
        temporal_applicability="undated",
        applicability_stage="pre_admission",
    )


def review() -> application.TargetProgramRequirementsReview:
    return application.requirements_review_from_extraction(
        target(),
        application.RequirementsExtraction(
            requirements=[
                requirement(
                    "Mathematics: four different subjects totalling 28.5 ECTS credits, which must "
                    "include a course in Calculus in one variable, a course in Linear Algebra, "
                    "a course in Probability Theory and Statistics, and a course in Discrete Mathematics."
                ),
                requirement(
                    "Computer Science: three different subjects totalling 22.5 ECTS, which must "
                    "include Object Oriented Programming, Algorithms and Data Structures, "
                    "and Algorithmic Complexity."
                ),
            ]
        ),
    )


MATH = [
    "Calculus in one variable",
    "Linear Algebra",
    "Probability Theory and Statistics",
    "Discrete Mathematics",
]
CS = ["Object Oriented Programming", "Algorithms and Data Structures", "Algorithmic Complexity"]


def extraction(*, include_math_credit: bool = True) -> application.SpecialTargetedExtractionOutput:
    groups = [
        application.SpecialPrerequisiteGroupExtraction(
            requirement_id=requirement_id,
            relation="all_of",
            courses=[
                application.SpecialPrerequisiteCourseExtraction(
                    prerequisite_kind="concrete_course", canonical_label=label
                )
                for label in labels
            ],
        )
        for requirement_id, labels in (("course:0", MATH), ("course:1", CS))
    ]
    credits = [
        application.SpecialAggregateCourseCreditExtraction(
            requirement_id="course:1",
            required_quantity=22.5,
            unit="ECTS",
            label="Computer Science prerequisite courses total",
        )
    ]
    if include_math_credit:
        credits.insert(
            0,
            application.SpecialAggregateCourseCreditExtraction(
                requirement_id="course:0",
                required_quantity=28.5,
                unit="ECTS",
                label="Mathematics prerequisite courses total",
            ),
        )
    return application.SpecialTargetedExtractionOutput(
        prerequisite_groups=groups,
        aggregate_course_credits=credits,
    )


def special_plan(*, include_math_credit: bool = True, evidence=None):
    request = application.SpecialInterviewPlanRequest(
        target_program=target(),
        requirements_review=review(),
        user_evidence=evidence or [],
    )
    return application.build_special_interview_plan_from_extraction(
        request,
        application.trusted_reviewed_requirements(request.requirements_review),
        extraction(include_math_credit=include_math_credit),
        llm_requests=1,
    )


def collapsed_extraction() -> application.SpecialTargetedExtractionOutput:
    return application.SpecialTargetedExtractionOutput(
        prerequisite_groups=[
            application.SpecialPrerequisiteGroupExtraction(
                requirement_id="course:0",
                relation="all_of",
                courses=[
                    application.SpecialPrerequisiteCourseExtraction(
                        prerequisite_kind="course_category",
                        category_label="Mathematics",
                        minimum_courses=4,
                    )
                ],
            ),
            application.SpecialPrerequisiteGroupExtraction(
                requirement_id="course:1",
                relation="all_of",
                courses=[
                    application.SpecialPrerequisiteCourseExtraction(
                        prerequisite_kind="course_category",
                        category_label="Computer Science",
                        minimum_courses=3,
                    )
                ],
            ),
        ],
        aggregate_course_credits=extraction().aggregate_course_credits,
    )


def course_answers(plan):
    return [
        application.SpecialInterviewAnswer(
            evidence_key=item.evidence_key,
            item_id=item.item_id,
            canonical_label=item.canonical_label or item.category_label or "",
            item_type="prerequisite_course",
            prerequisite_kind=item.prerequisite_kind,
            availability="known",
            requirement_id=group.source.requirement_id,
        )
        for group in plan.prerequisite_groups
        for item in group.courses
    ]


def credit_answer(item, availability="known", quantity=None):
    return application.SpecialInterviewAnswer(
        evidence_key=item.evidence_key,
        item_id=item.item_id,
        canonical_label=item.label,
        item_type="aggregate_course_credit",
        availability=availability,
        requirement_id=item.requirement_id,
        quantity=quantity,
        unit=item.unit,
        required_quantity=item.required_quantity,
    )


def planner_output():
    requirements = []
    for requirement_id, required_quantity in (("course:0", 28.5), ("course:1", 22.5)):
        requirements.append(
            application.GapPlannerRequirementLLMDraft(
                requirement_id=requirement_id,
                matchable=True,
                match_strategy="deterministic",
                evidence_needs=[
                    application.GapPlannerEvidenceNeedDraft(
                        key="courses.total_credits",
                        evidence_type="courses",
                        value_kind="numeric",
                        label="Total prerequisite credits",
                    )
                ],
                constraint=application.GapDeterministicConstraint(
                    kind="course_credit",
                    relation="all",
                    options=[
                        application.GapConstraintOption(
                            key="courses.total_credits",
                            kind="course_credit",
                            required_quantity=required_quantity,
                            unit="ECTS",
                        )
                    ],
                ),
            )
        )
    return application.GapPlannerLLMOutput(requirements=requirements, questions=[])


async def build_gap(plan, evidence):
    async def fake_deepseek(**_kwargs):
        return application.DeepSeekTextResult(
            content=planner_output().model_dump_json(), stop_reason="end_turn"
        )

    with patch.object(application, "call_deepseek", fake_deepseek):
        return await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=target(),
                requirements_review=review(),
                user_evidence=evidence,
                authoritative_prerequisite_plan=plan.authoritative_prerequisite_plan,
                authoritative_course_credit_plan=plan.authoritative_course_credit_plan,
            )
        )


async def analyze(plan, evidence):
    return await application.analyze_gap(
        application.GapAnalysisRequest(
            target_program=target(), plan=plan, user_evidence=evidence
        )
    )


async def run() -> None:
    passed = []

    request = application.SpecialInterviewPlanRequest(
        target_program=target(), requirements_review=review(), user_evidence=[]
    )
    granular = application.build_special_interview_plan_from_extraction(
        request,
        application.trusted_reviewed_requirements(request.requirements_review),
        collapsed_extraction(),
        llm_requests=1,
    )
    granular_by_requirement = {
        group.source.requirement_id: group for group in granular.prerequisite_groups
    }
    math_group = granular_by_requirement["course:0"]
    assert math_group.relation == "all_of"
    assert [item.canonical_label for item in math_group.courses] == MATH
    assert all(item.prerequisite_kind == "concrete_course" for item in math_group.courses)
    assert not any(item.prerequisite_kind == "course_category" for item in math_group.courses)
    assert any(
        item.requirement_id == "course:0"
        and item.required_quantity == 28.5
        and item.unit == "ECTS"
        for item in granular.aggregate_course_credits
    )
    passed.append("collapsed KTH Mathematics expands to 4 concrete courses plus 28.5 ECTS")

    cs_group = granular_by_requirement["course:1"]
    assert cs_group.relation == "all_of"
    assert [item.canonical_label for item in cs_group.courses] == CS
    assert all(item.prerequisite_kind == "concrete_course" for item in cs_group.courses)
    assert not any(item.prerequisite_kind == "course_category" for item in cs_group.courses)
    assert any(
        item.requirement_id == "course:1"
        and item.required_quantity == 22.5
        and item.unit == "ECTS"
        for item in granular.aggregate_course_credits
    )
    passed.append("collapsed KTH Computer Science expands to 3 concrete courses plus 22.5 ECTS")

    assert application.explicit_mandatory_course_names(
        "At least two Mathematics electives are required.", expected_count=2
    ) == []
    passed.append("true category requirement without named mandatory courses is unchanged")
    category_extraction = application.SpecialTargetedExtractionOutput(
        prerequisite_groups=[
            application.SpecialPrerequisiteGroupExtraction(
                requirement_id="course:0",
                relation="all_of",
                courses=[
                    application.SpecialPrerequisiteCourseExtraction(
                        prerequisite_kind="course_category",
                        category_label="Systems",
                        minimum_courses=2,
                    )
                ],
            )
        ]
    )
    category_request = application.SpecialInterviewPlanRequest(
        target_program=target(), requirements_review=review()
    )
    category_plan = application.build_special_interview_plan_from_extraction(
        category_request,
        application.trusted_reviewed_requirements(category_request.requirements_review),
        category_extraction,
        llm_requests=1,
    )
    category_item = category_plan.prerequisite_groups[0].courses[0]
    category_base = dict(
        evidence_key=category_item.evidence_key,
        item_id=category_item.item_id,
        canonical_label="Systems",
        item_type="prerequisite_course",
        prerequisite_kind="course_category",
        minimum_courses=2,
        requirement_id="course:0",
    )
    try:
        await application.special_interview_evidence_submit_endpoint(
            application.SpecialInterviewEvidenceSubmitRequest(
                target_program=target(),
                answers=[application.SpecialInterviewAnswer(
                    **category_base, availability="known", user_course_names=[]
                )],
            )
        )
    except application.HTTPException as error:
        assert error.status_code == 422
    else:
        raise AssertionError("known course category without enough names must fail")
    for availability in ("known_negative", "unknown"):
        response = await application.special_interview_evidence_submit_endpoint(
            application.SpecialInterviewEvidenceSubmitRequest(
                target_program=target(),
                answers=[application.SpecialInterviewAnswer(
                    **category_base, availability=availability
                )],
            )
        )
        assert response.evidence[0].availability == availability
    passed.append("backend course-category completion contract matches frontend")

    plan = special_plan()
    assert plan.remaining_item_count == 9
    assert plan.extraction_llm_requests == 1
    passed.append("KTH 7 prerequisite + 2 aggregate count")

    one_credit = special_plan(include_math_credit=False)
    assert one_credit.remaining_item_count == 8
    passed.append("7 prerequisite + 1 aggregate count")

    math_credit, cs_credit = plan.aggregate_course_credits
    assert math_credit.evidence_key != cs_credit.evidence_key
    assert math_credit.evidence_key.startswith("programme_course_credit_response:")
    passed.append("aggregate keys are programme and requirement scoped")

    answers = [
        *course_answers(plan),
        credit_answer(math_credit, quantity=30),
        credit_answer(cs_credit, availability="unknown"),
    ]
    submitted = await application.special_interview_evidence_submit_endpoint(
        application.SpecialInterviewEvidenceSubmitRequest(
            target_program=target(), answers=answers
        )
    )
    assert submitted.parser_calls == 0 and submitted.llm_requests == 0
    passed.append("typed aggregate submit uses zero parser and LLM calls")

    gap = await build_gap(plan, submitted.evidence)
    by_id = {item.requirement_id: item for item in gap.requirements}
    assert by_id["course:0"].constraint.options[0].key == math_credit.evidence_key
    assert by_id["course:1"].constraint.options[0].key == cs_credit.evidence_key
    assert all(
        option.key != "courses.total_credits"
        for planned in by_id.values()
        for option in planned.constraint.options
    )
    result = await analyze(gap, submitted.evidence)
    results = {item.requirement_id: item for item in result.results}
    assert results["course:0"].status == "met"
    assert results["course:1"].status == "unknown"
    passed.append("Math known never cross-matches unknown CS aggregate")

    cs_unknown = next(item for item in submitted.evidence if item.key == cs_credit.evidence_key)
    for quantity, expected in ((22.5, "met"), (30, "met"), (20, "partial")):
        known = cs_unknown.model_copy(
            update={
                "availability": "known",
                "value": {**cs_unknown.value, "quantity": quantity},
                "raw_answer": f"{quantity:g} ECTS",
            }
        )
        updated = [item for item in submitted.evidence if item.key != cs_credit.evidence_key] + [known]
        evaluated = await analyze(gap, updated)
        status = {item.requirement_id: item.status for item in evaluated.results}["course:1"]
        assert status == expected, (quantity, status)
    passed.append("existing course-credit comparator handles equal, over, and under threshold")

    reused = special_plan(evidence=submitted.evidence)
    assert reused.aggregate_course_credits == []
    assert reused.remaining_item_count == 0
    passed.append("exact scoped aggregate evidence is reusable")

    invalid_base = {
        "evidence_key": cs_credit.evidence_key,
        "item_id": cs_credit.item_id,
        "canonical_label": cs_credit.label,
        "item_type": "aggregate_course_credit",
        "availability": "known",
        "requirement_id": cs_credit.requirement_id,
        "unit": cs_credit.unit,
        "required_quantity": cs_credit.required_quantity,
    }
    for payload in (invalid_base, {**invalid_base, "quantity": -1}):
        try:
            application.SpecialInterviewAnswer.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError("invalid aggregate numeric answer must be rejected")
    passed.append("missing and negative numeric quantities are rejected")

    for item in passed:
        print(f"PASS {item}")
    print(f"PASS special compound interview completion regressions: {len(passed)}/{len(passed)}")


if __name__ == "__main__":
    asyncio.run(run())
