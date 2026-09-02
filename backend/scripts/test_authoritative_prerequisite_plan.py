from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import main as application


def target(program: str = "MSc Machine Learning", url: str = "https://example.edu/ml"):
    return application.TargetProgram(
        university="Example University",
        program=program,
        official_program_url=url,
        official_domain="example.edu",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )


def review(selected_target: application.TargetProgram, text: str):
    requirement = application.RequirementItem(
        category="course",
        requirement=text,
        requirement_zh=text,
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url=selected_target.official_program_url,
        temporal_applicability="undated",
        applicability_stage="pre_admission",
    )
    return application.requirements_review_from_extraction(
        selected_target,
        application.RequirementsExtraction(requirements=[requirement]),
    )


def extraction(
    labels: list[str],
    *,
    kinds: dict[str, str] | None = None,
    relation: str = "all_of",
):
    kinds = kinds or {}
    return application.SpecialTargetedExtractionOutput(
        prerequisite_groups=[
            application.SpecialPrerequisiteGroupExtraction(
                requirement_id="course:0",
                relation=relation,
                courses=[
                    application.SpecialPrerequisiteCourseExtraction(
                        prerequisite_kind=kinds.get(label, "concrete_course"),
                        canonical_label=(
                            label if kinds.get(label, "concrete_course") == "concrete_course" else None
                        ),
                        category_label=(
                            label if kinds.get(label) == "course_category" else None
                        ),
                        minimum_courses=(1 if kinds.get(label) == "course_category" else None),
                    )
                    for label in labels
                ],
            )
        ]
    )


def special_plan(
    selected_target: application.TargetProgram,
    selected_review: application.TargetProgramRequirementsReview,
    selected_extraction: application.SpecialTargetedExtractionOutput,
    evidence: list[application.UserEvidence] | None = None,
):
    request = application.SpecialInterviewPlanRequest(
        target_program=selected_target,
        requirements_review=selected_review,
        user_evidence=evidence or [],
    )
    return application.build_special_interview_plan_from_extraction(
        request,
        application.trusted_reviewed_requirements(selected_review),
        selected_extraction,
        llm_requests=1,
    )


async def submit_courses(
    selected_target: application.TargetProgram,
    plan: application.SpecialInterviewPlan,
    availability: dict[str, application.EvidenceAvailability],
    *,
    category_names: dict[str, list[str]] | None = None,
):
    category_names = category_names or {}
    items = [item for group in plan.prerequisite_groups for item in group.courses]
    response = await application.special_interview_evidence_submit_endpoint(
        application.SpecialInterviewEvidenceSubmitRequest(
            target_program=selected_target,
            answers=[
                application.SpecialInterviewAnswer(
                    evidence_key=item.evidence_key,
                    item_id=item.item_id,
                    canonical_label=item.canonical_label or item.category_label or "",
                    item_type="prerequisite_course",
                    prerequisite_kind=item.prerequisite_kind,
                    minimum_courses=item.minimum_courses,
                    availability=availability[item.canonical_label or item.category_label or ""],
                    requirement_id="course:0",
                    user_course_names=category_names.get(
                        item.canonical_label or item.category_label or "", []
                    ),
                )
                for item in items
            ],
        )
    )
    return response.evidence


def planner_output(*, rogue_labels: list[str] | None = None, credits: float | None = None):
    rogue_labels = rogue_labels or []
    credit_key = "courses.total_credits"
    return application.GapPlannerLLMOutput(
        requirements=[
            application.GapPlannerRequirementLLMDraft(
                requirement_id="course:0",
                matchable=True,
                match_strategy="deterministic",
                evidence_needs=(
                    [
                        application.GapPlannerEvidenceNeedDraft(
                            key=credit_key,
                            evidence_type="courses",
                            value_kind="numeric",
                            label="Total prerequisite credits",
                        )
                    ]
                    if credits is not None
                    else []
                ),
                constraint=application.GapDeterministicConstraint(
                    kind="course_credit" if credits is not None else "none",
                    relation="all",
                    options=(
                        [
                            application.GapConstraintOption(
                                key=credit_key,
                                kind="course_credit",
                                required_quantity=credits,
                                unit="ECTS",
                            )
                        ]
                        if credits is not None
                        else []
                    ),
                ),
                course_requirements=[
                    application.GapCourseRequirement(
                        item_id=f"UNKNOWN-{index}",
                        evidence_key=application.special_evidence_key(
                            "prerequisite_course", label
                        ),
                        course_name=label,
                        canonical_label=label,
                        prerequisite_kind="concrete_course",
                    )
                    for index, label in enumerate(rogue_labels)
                ],
            )
        ],
        questions=[],
    )


async def build_gap(
    selected_target: application.TargetProgram,
    selected_review: application.TargetProgramRequirementsReview,
    plan: application.SpecialInterviewPlan,
    evidence: list[application.UserEvidence],
    *,
    output: application.GapPlannerLLMOutput | None = None,
):
    output = output or planner_output()

    async def fake_deepseek(**_kwargs):
        return application.DeepSeekTextResult(
            content=output.model_dump_json(), stop_reason="end_turn"
        )

    request = application.GapPlanRequest(
        target_program=selected_target,
        requirements_review=selected_review,
        user_evidence=evidence,
        authoritative_prerequisite_plan=plan.authoritative_prerequisite_plan,
    )
    with patch.object(application, "call_deepseek", fake_deepseek):
        return await application.build_gap_plan(request)


async def analyze(selected_target, gap_plan, evidence):
    response = await application.analyze_gap(
        application.GapAnalysisRequest(
            target_program=selected_target,
            plan=gap_plan,
            user_evidence=evidence,
        )
    )
    return response.results[0]


async def run():
    passed: list[str] = []
    selected_target = target()
    text = "The bachelor's degree must include SF1625 Calculus in One Variable."
    selected_review = review(selected_target, text)
    selected_extraction = extraction(["SF1625 Calculus in One Variable"])
    initial = special_plan(selected_target, selected_review, selected_extraction)
    item = initial.authoritative_prerequisite_plan[0].items[0]
    evidence = await submit_courses(
        selected_target, initial, {item.display_label: "known"}
    )

    # A: same programme/cycle rematerializes the same id/key and skips the question.
    refreshed = special_plan(
        selected_target, selected_review, selected_extraction, evidence
    )
    assert refreshed.remaining_item_count == 0
    assert refreshed.authoritative_prerequisite_plan[0].items[0].item_id == item.item_id
    gap = await build_gap(selected_target, selected_review, refreshed, evidence)
    assert gap.requirements[0].course_requirements[0].evidence_key == evidence[0].key, {
        "planned": gap.requirements[0].course_requirements[0].model_dump(),
        "evidence": evidence[0].model_dump(),
    }
    result = await analyze(selected_target, gap, evidence)
    assert result.status == "met" and "修过" in result.user_evidence, result.model_dump()
    passed.append("A same-programme persistence and Gap read")

    # B/M/N: LLM title drift and invented identity are ignored; Backend plan wins.
    rogue = planner_output(rogue_labels=["Calculus in One Variable"])
    with patch.object(
        application,
        "normalize_course_requirements",
        side_effect=AssertionError("authoritative flow must not normalize LLM course items"),
    ):
        drift_gap = await build_gap(
            selected_target, selected_review, refreshed, evidence, output=rogue
        )
    assert [course.item_id for course in drift_gap.requirements[0].course_requirements] == [item.item_id]
    assert all(course.authoritative for course in drift_gap.requirements[0].course_requirements)
    assert (await analyze(selected_target, drift_gap, evidence)).status == "met"
    passed.extend([
        "B code/title drift does not change lookup",
        "M planner-created unknown item is ignored",
        "N Gap does not rebuild authoritative courses",
    ])

    # C/D: tri-state remains distinct and is read directly by the scoped key.
    negative = [evidence[0].model_copy(update={"availability": "known_negative", "raw_answer": "没修过"})]
    unknown = [evidence[0].model_copy(update={"availability": "unknown", "raw_answer": "不确定"})]
    negative_result = await analyze(selected_target, gap, negative)
    unknown_result = await analyze(selected_target, gap, unknown)
    assert negative_result.status == "not_met" and "没修过" in negative_result.user_evidence
    assert unknown_result.status == "unknown" and "不确定" in unknown_result.user_evidence
    passed.extend(["C known_negative becomes completed=false", "D unknown remains unknown"])

    # E/F: identical names and old global evidence never satisfy another programme.
    other_target = target("MSc Other", "https://example.edu/other")
    other_review = review(other_target, text)
    other_plan = special_plan(other_target, other_review, selected_extraction, evidence)
    assert other_plan.remaining_item_count == 1
    legacy = application.UserEvidence(
        evidence_type="prerequisite_course",
        key="prerequisite_course:sf1625_calculus_in_one_variable",
        value={"canonical_label": item.display_label},
        raw_answer="修过",
        availability="known",
        updated_at="2026-09-01T00:00:00Z",
    )
    legacy_plan = special_plan(other_target, other_review, selected_extraction, [legacy])
    assert legacy_plan.remaining_item_count == 1
    passed.extend(["E same-name course is isolated across programmes", "F legacy global evidence is ignored"])

    # G/H: categories use the same programme-scoped rule and persist only locally.
    category_extraction = extraction(
        ["Systems"], kinds={"Systems": "course_category"}
    )
    category_plan = special_plan(selected_target, selected_review, category_extraction)
    category_evidence = await submit_courses(
        selected_target,
        category_plan,
        {"Systems": "known"},
        category_names={"Systems": ["Operating Systems"]},
    )
    assert special_plan(
        selected_target, selected_review, category_extraction, category_evidence
    ).remaining_item_count == 0
    assert special_plan(
        other_target, other_review, category_extraction, category_evidence
    ).remaining_item_count == 1
    assert not any(item.evidence_type == "user_course" for item in category_evidence)
    passed.extend(["G category is isolated across programmes", "H category persists in the same programme"])

    # I: replacing the same scoped answer immediately changes Gap output.
    assert (await analyze(selected_target, gap, negative)).status == "not_met"
    passed.append("I latest scoped answer is used without a derived cache")

    # J: real KTH shape uses exact authoritative ids for all six items.
    kth_labels = [
        "SF1624 Algebra and Geometry",
        "SF1625 Calculus in One Variable",
        "SF1626 Calculus in Several Variables",
        "SF1920 Probability Theory and Statistics",
        "DD1337 Programming",
        "DD1338 Algorithms and Data Structures",
    ]
    kth_text = "Coursework corresponding to: " + ", ".join(kth_labels)
    kth_review = review(selected_target, kth_text)
    kth_extraction = extraction(kth_labels)
    kth_plan = special_plan(selected_target, kth_review, kth_extraction)
    kth_answers = {label: "known" for label in kth_labels}
    kth_answers["SF1626 Calculus in Several Variables"] = "known_negative"
    kth_evidence = await submit_courses(selected_target, kth_plan, kth_answers)
    kth_gap = await build_gap(
        selected_target,
        kth_review,
        kth_plan,
        kth_evidence,
        output=planner_output(rogue_labels=[label.split(" ", 1)[1] for label in kth_labels]),
    )
    assert {
        course.item_id for course in kth_gap.requirements[0].course_requirements
    } == {
        item.item_id for item in kth_plan.authoritative_prerequisite_plan[0].items
    }
    kth_result = await analyze(selected_target, kth_gap, kth_evidence)
    assert kth_result.status == "partial"
    kth_evidence_parts = kth_result.user_evidence.split("；")
    assert kth_evidence_parts.count("修过") == 5
    assert kth_evidence_parts.count("没修过") == 1
    passed.append("J KTH real shape reads all answers by item id")

    # K: credit remains an independent missing fact.
    credit_gap = await build_gap(
        selected_target,
        kth_review,
        kth_plan,
        kth_evidence,
        output=planner_output(credits=28.5),
    )
    credit_result = await analyze(selected_target, credit_gap, kth_evidence)
    assert credit_result.status == "unknown"
    assert "未提供" in credit_result.user_evidence
    assert "修过" in credit_result.user_evidence
    passed.append("K course answers do not infer ECTS")

    # L: extraction order does not participate in item identity.
    reordered = special_plan(
        selected_target,
        kth_review,
        extraction(list(reversed(kth_labels))),
    )
    first_ids = {
        item.display_label: item.item_id
        for item in kth_plan.authoritative_prerequisite_plan[0].items
    }
    second_ids = {
        item.display_label: item.item_id
        for item in reordered.authoritative_prerequisite_plan[0].items
    }
    assert first_ids == second_ids
    passed.append("L extraction order does not change item ids")

    assert len(passed) == 14
    for line in passed:
        print(f"PASS {line}")
    print("PASS authoritative prerequisite plan regressions: A-N")


if __name__ == "__main__":
    asyncio.run(run())
