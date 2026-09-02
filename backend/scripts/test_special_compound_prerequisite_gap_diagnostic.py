"""Diagnostic regression for Special Interview -> compound prerequisite Gap mapping.

This intentionally records the current observed behavior without changing product logic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


def target(
    program: str = "MSc Example Programme",
    url: str = "https://www.kth.se/example",
) -> application.TargetProgram:
    return application.TargetProgram(
        university="KTH Royal Institute of Technology",
        program=program,
        official_program_url=url,
        official_domain="kth.se",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )


def reviewed_requirement(
    text: str,
    selected_target: application.TargetProgram | None = None,
) -> application.TargetProgramRequirementsReview:
    selected_target = selected_target or target()
    item = application.RequirementItem(
        category="course",
        requirement=text,
        requirement_zh=text,
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url=selected_target.official_program_url,
        source_cycle=None,
        temporal_applicability="undated",
        applicability_stage="pre_admission",
    )
    return application.requirements_review_from_extraction(
        selected_target, application.RequirementsExtraction(requirements=[item])
    )


async def submit_special_courses(
    labels: list[str],
    *,
    names: dict[str, str] | None = None,
    availability: dict[str, application.EvidenceAvailability] | None = None,
) -> list[application.UserEvidence]:
    names = names or {}
    availability = availability or {}
    return [
        application.UserEvidence(
            evidence_type="prerequisite_course",
            key=application.special_evidence_key("prerequisite_course", label),
            value={
                "canonical_label": label,
                "prerequisite_kind": "concrete_course",
                "user_course_name": names.get(label),
                "matched_user_courses": [],
            },
            raw_answer={
                "known": "修过",
                "known_negative": "没修过",
                "unknown": "不确定",
            }[availability.get(label, "known")],
            availability=availability.get(label, "known"),
            updated_at="2026-09-01T00:00:00Z",
            source_requirement_ids=["course:0"],
        )
        for label in labels
    ]


async def submit_course_category(
    selected_target: application.TargetProgram,
    requirement_id: str,
    label: str,
    *,
    availability: application.EvidenceAvailability = "known",
    matched_courses: list[str] | None = None,
) -> application.UserEvidence:
    key = application.special_course_category_context_key(
        selected_target, requirement_id, label
    )
    return application.UserEvidence(
        evidence_type="prerequisite_course",
        key=key,
        value={
            "canonical_label": label,
            "prerequisite_kind": "course_category",
            "category_label": label,
            "matched_user_courses": matched_courses or [],
        },
        raw_answer={
            "known": "修过",
            "known_negative": "没修过",
            "unknown": "不确定",
        }[availability],
        availability=availability,
        updated_at="2026-09-01T00:00:00Z",
        source_requirement_ids=[requirement_id],
    )


def planner_output(
    labels: list[str],
    total_credit_key: str,
    required_credits: float,
    group_label: str,
    *,
    prerequisite_kinds: dict[str, str] | None = None,
    evidence_keys: dict[str, str] | None = None,
) -> application.GapPlannerLLMOutput:
    prerequisite_kinds = prerequisite_kinds or {}
    evidence_keys = evidence_keys or {}
    special_keys = [
        evidence_keys.get(
            label,
            application.special_evidence_key("prerequisite_course", label),
        )
        for label in labels
    ]
    return application.GapPlannerLLMOutput(
        requirements=[
            application.GapPlannerRequirementLLMDraft(
                requirement_id="course:0",
                matchable=True,
                match_strategy="deterministic",
                evidence_needs=[
                    *[
                        application.GapPlannerEvidenceNeedDraft(
                            key=key,
                            evidence_type="courses",
                            value_kind="boolean",
                            label=label,
                        )
                        for key, label in zip(special_keys, labels)
                    ],
                    application.GapPlannerEvidenceNeedDraft(
                        key=total_credit_key,
                        evidence_type="courses",
                        value_kind="numeric",
                        label=f"{group_label} total credits",
                    ),
                ],
                constraint=application.GapDeterministicConstraint(
                    kind="course_credit",
                    relation="all",
                    options=[
                        application.GapConstraintOption(
                            key=total_credit_key,
                            kind="course_credit",
                            required_quantity=required_credits,
                            unit="ECTS",
                        )
                    ],
                ),
                course_requirements=[
                    application.GapCourseRequirement(
                        evidence_key=key,
                        course_name=label,
                        canonical_label=label,
                        prerequisite_kind=prerequisite_kinds.get(
                            label, "concrete_course"
                        ),
                        group_label=group_label,
                    )
                    for key, label in zip(special_keys, labels)
                ],
            )
        ],
        questions=[],
    )


def course_only_planner_output(
    labels: list[str],
    *,
    requirement_id: str = "course:0",
) -> application.GapPlannerLLMOutput:
    keys = [
        application.special_evidence_key("prerequisite_course", label)
        for label in labels
    ]
    return application.GapPlannerLLMOutput(
        requirements=[
            application.GapPlannerRequirementLLMDraft(
                requirement_id=requirement_id,
                matchable=True,
                match_strategy="deterministic",
                evidence_needs=[
                    application.GapPlannerEvidenceNeedDraft(
                        key=key,
                        evidence_type="courses",
                        value_kind="boolean",
                        label=label,
                    )
                    for key, label in zip(keys, labels)
                ],
                constraint=application.GapDeterministicConstraint(
                    kind="none",
                    relation="all",
                    options=[],
                ),
                course_requirements=[
                    application.GapCourseRequirement(
                        evidence_key=key,
                        course_name=label,
                        canonical_label=label,
                        prerequisite_kind="concrete_course",
                        group_label="Mathematics and Computer Science",
                    )
                    for key, label in zip(keys, labels)
                ],
            )
        ],
        questions=[],
    )


async def build_plan(
    review: application.TargetProgramRequirementsReview,
    evidence: list[application.UserEvidence],
    output: application.GapPlannerLLMOutput,
    selected_target: application.TargetProgram | None = None,
) -> tuple[application.GapPlan, dict]:
    selected_target = selected_target or target()
    request = application.GapPlanRequest(
        target_program=selected_target,
        requirements_review=review,
        user_evidence=evidence,
    )
    formal = application.formal_gap_requirements(review)
    reusable = application.merge_reusable_evidence(request.user_profile, evidence)
    payload = application.gap_planner_prompt_payload(request, formal, reusable)

    async def fake_deepseek(**_kwargs):
        return application.DeepSeekTextResult(
            content=output.model_dump_json(),
            stop_reason="end_turn",
        )

    with patch.object(application, "call_deepseek", fake_deepseek):
        plan = await application.build_gap_plan(request)
    return plan, payload


async def analyze(
    plan: application.GapPlan,
    evidence: list[application.UserEvidence],
    selected_target: application.TargetProgram | None = None,
) -> application.GapResult:
    selected_target = selected_target or target()
    response = await application.analyze_gap(
        application.GapAnalysisRequest(
            target_program=selected_target,
            plan=plan,
            user_evidence=evidence,
        )
    )
    assert len(response.results) == 1
    return response.results[0]


async def run_case(
    *,
    requirement_text: str,
    labels: list[str],
    total_credit_key: str,
    required_credits: float,
    group_label: str,
    names: dict[str, str] | None = None,
    availability: dict[str, application.EvidenceAvailability] | None = None,
    prerequisite_kinds: dict[str, str] | None = None,
    evidence_keys: dict[str, str] | None = None,
    supplied_evidence: list[application.UserEvidence] | None = None,
    selected_target: application.TargetProgram | None = None,
) -> tuple[list[application.UserEvidence], application.GapPlan, dict, application.GapResult]:
    selected_target = selected_target or target()
    evidence = supplied_evidence or await submit_special_courses(
        labels, names=names, availability=availability
    )
    plan, payload = await build_plan(
        reviewed_requirement(requirement_text, selected_target),
        evidence,
        planner_output(
            labels,
            total_credit_key,
            required_credits,
            group_label,
            prerequisite_kinds=prerequisite_kinds,
            evidence_keys=evidence_keys,
        ),
        selected_target,
    )
    result = await analyze(plan, evidence, selected_target)
    return evidence, plan, payload, result


async def run() -> None:
    math_labels = [
        "Calculus in one variable",
        "Linear Algebra",
        "Probability Theory and Statistics",
        "Discrete Mathematics",
    ]
    math_requirement = (
        "Mathematics: four different subjects totaling 28.5 ECTS, including "
        "Calculus in one variable, Linear Algebra, Probability Theory and Statistics, "
        "and Discrete Mathematics."
    )

    evidence_a, plan_a, payload_a, result_a = await run_case(
        requirement_text=math_requirement,
        labels=math_labels,
        total_credit_key="courses.math_total_credits",
        required_credits=28.5,
        group_label="Mathematics",
    )
    assert all(item.availability == "known" for item in evidence_a)
    assert all(item.value["user_course_name"] is None for item in evidence_a)
    assert all(item.key.startswith("prerequisite_course:") for item in evidence_a)
    payload_keys = {
        item["key"] for item in payload_a["canonical_user_evidence"]
    }
    assert not ({item.key for item in evidence_a} & payload_keys)

    planned_a = plan_a.requirements[0]
    scoped_keys = {
        application.course_requirement_evidence_key(item.item_id)
        for item in planned_a.course_requirements
    }
    reusable_keys = {item.key for item in plan_a.reusable_evidence}
    runtime_a = application.runtime_course_evidence_view(
        target(), plan_a.requirements, {item.key: item for item in evidence_a}
    )
    assert not scoped_keys & reusable_keys
    assert all(runtime_a[key].value["completed"] is True for key in scoped_keys)
    assert not any("course-checklist" in question.question_id for question in plan_a.questions)
    assert result_a.status == "unknown"
    assert result_a.reason_code == "user_evidence_missing"
    assert "未提供" in result_a.user_evidence
    assert result_a.user_evidence.count("修过") == 4
    assert result_a.user_evidence.count("未提供") == 1

    names = {
        "Calculus in one variable": "Calculus I",
        "Linear Algebra": "Linear Algebra",
        "Probability Theory and Statistics": "Probability and Statistics",
        "Discrete Mathematics": "Discrete Mathematics",
    }
    evidence_b, _plan_b, _payload_b, result_b = await run_case(
        requirement_text=math_requirement,
        labels=math_labels,
        total_credit_key="courses.math_total_credits",
        required_credits=28.5,
        group_label="Mathematics",
        names=names,
    )
    assert all(item.value["user_course_name"] for item in evidence_b)
    assert (result_b.status, result_b.reason_code, result_b.user_evidence) == (
        result_a.status,
        result_a.reason_code,
        result_a.user_evidence,
    )

    evidence_c, plan_c, _payload_c, result_c = await run_case(
        requirement_text=math_requirement,
        labels=math_labels,
        total_credit_key="courses.math_total_credits",
        required_credits=28.5,
        group_label="Mathematics",
        availability={"Linear Algebra": "known_negative"},
    )
    evidence_d, plan_d, _payload_d, result_d = await run_case(
        requirement_text=math_requirement,
        labels=math_labels,
        total_credit_key="courses.math_total_credits",
        required_credits=28.5,
        group_label="Mathematics",
        availability={"Linear Algebra": "unknown"},
    )
    linear_c = next(item for item in evidence_c if item.value["canonical_label"] == "Linear Algebra")
    linear_d = next(item for item in evidence_d if item.value["canonical_label"] == "Linear Algebra")
    assert linear_c.availability == "known_negative"
    assert linear_d.availability == "unknown"
    linear_c_item = next(
        item for item in plan_c.requirements[0].course_requirements
        if item.course_name == "Linear Algebra"
    )
    linear_d_item = next(
        item for item in plan_d.requirements[0].course_requirements
        if item.course_name == "Linear Algebra"
    )
    runtime_c = application.runtime_course_evidence_view(
        target(), plan_c.requirements, {item.key: item for item in evidence_c}
    )
    runtime_d = application.runtime_course_evidence_view(
        target(), plan_d.requirements, {item.key: item for item in evidence_d}
    )
    scoped_c = runtime_c[application.course_requirement_evidence_key(linear_c_item.item_id)]
    scoped_d = runtime_d[application.course_requirement_evidence_key(linear_d_item.item_id)]
    assert scoped_c.availability == "known_negative" and scoped_c.value["completed"] is False
    assert scoped_d.availability == "unknown" and scoped_d.value["completed"] is None
    assert result_c.status == "unknown" and "没修过" in result_c.user_evidence
    assert result_d.status == "unknown" and "不确定" in result_d.user_evidence

    # E: exact canonical keys only; an advanced course must not satisfy the base course.
    advanced_evidence = await submit_special_courses(["Advanced Linear Algebra"])
    runtime_e = application.runtime_course_evidence_view(
        target(), [planned_a], {item.key: item for item in advanced_evidence}
    )
    linear_a_item = next(
        item for item in planned_a.course_requirements
        if item.course_name == "Linear Algebra"
    )
    assert application.course_requirement_evidence_key(linear_a_item.item_id) not in runtime_e

    # F/L: a concrete canonical fact is reusable across programmes and always read live.
    second_target = target(
        "MSc Second Programme", "https://www.kth.se/second-programme"
    )
    runtime_f = application.runtime_course_evidence_view(
        second_target, [planned_a], {item.key: item for item in evidence_a}
    )
    linear_scoped_key = application.course_requirement_evidence_key(
        linear_a_item.item_id
    )
    assert runtime_f[linear_scoped_key].value["completed"] is True
    changed_linear = next(
        item for item in evidence_a
        if item.value["canonical_label"] == "Linear Algebra"
    ).model_copy(update={"availability": "known_negative", "raw_answer": "没修过"})
    changed_canonical = {
        item.key: (changed_linear if item.key == changed_linear.key else item)
        for item in evidence_a
    }
    runtime_l = application.runtime_course_evidence_view(
        second_target, [planned_a], changed_canonical
    )
    assert runtime_l[linear_scoped_key].value["completed"] is False
    assert linear_scoped_key not in changed_canonical
    changed_result = await analyze(
        plan_a, list(changed_canonical.values()), second_target
    )
    assert "没修过" in changed_result.user_evidence

    # G/H/K: course-category facts are scoped to the exact programme + requirement.
    category_label = "Systems"
    category_a_key = application.special_course_category_context_key(
        target(), "course:0", category_label
    )
    category_evidence_a = await submit_course_category(
        target(),
        "course:0",
        category_label,
        matched_courses=["Operating Systems"],
    )
    category_item = application.GapCourseRequirement(
        item_id=application.course_requirement_item_id("course:0", category_label),
        evidence_key=category_a_key,
        course_name=category_label,
        canonical_label=category_label,
        prerequisite_kind="course_category",
    )
    category_need = application.GapEvidenceNeed(
        key=application.course_requirement_evidence_key(category_item.item_id),
        evidence_type="courses",
        value_kind="boolean",
        label=category_label,
        required_fields=["completed"],
        evidence_group="course:0",
    )
    category_requirement = planned_a.model_copy(
        update={
            "course_requirements": [category_item],
            "evidence_needs": [category_need],
            "constraint": application.GapDeterministicConstraint(),
        }
    )
    runtime_h = application.runtime_course_evidence_view(
        target(), [category_requirement], {category_evidence_a.key: category_evidence_a}
    )
    category_scoped_key = application.course_requirement_evidence_key(
        category_item.item_id
    )
    assert runtime_h[category_scoped_key].value["completed"] is True
    runtime_g = application.runtime_course_evidence_view(
        second_target,
        [category_requirement],
        {category_evidence_a.key: category_evidence_a},
    )
    assert category_scoped_key not in runtime_g
    category_b_key = application.special_course_category_context_key(
        second_target, "course:0", category_label
    )
    _evidence_k, plan_k, _payload_k, _result_k = await run_case(
        requirement_text="One Systems category course is required.",
        labels=[category_label],
        total_credit_key="courses.systems_total_credits",
        required_credits=1,
        group_label="Computer Science",
        prerequisite_kinds={category_label: "course_category"},
        evidence_keys={category_label: category_b_key},
        supplied_evidence=[category_evidence_a],
        selected_target=second_target,
    )
    assert any("course-checklist" in question.question_id for question in plan_k.questions)

    cs_labels = [
        "Object Oriented Programming",
        "Algorithms and Data Structures",
        "One in-depth Computer Science course",
    ]
    cs_concrete = await submit_special_courses(cs_labels[:2])
    cs_category_label = cs_labels[2]
    cs_category_key = application.special_course_category_context_key(
        target(), "course:0", cs_category_label
    )
    cs_category = await submit_course_category(
        target(),
        "course:0",
        cs_category_label,
        matched_courses=["Advanced Algorithms"],
    )
    evidence_cs, plan_cs, payload_cs, result_cs = await run_case(
        requirement_text=(
            "Computer Science / Technology: three different subjects totaling 22.5 ECTS, "
            "including Object Oriented Programming, Algorithms and Data Structures, and one "
            "in-depth course."
        ),
        labels=cs_labels,
        total_credit_key="courses.cs_total_credits",
        required_credits=22.5,
        group_label="Computer Science / Technology",
        prerequisite_kinds={cs_category_label: "course_category"},
        evidence_keys={cs_category_label: cs_category_key},
        supplied_evidence=[*cs_concrete, cs_category],
    )
    assert not ({item.key for item in evidence_cs} & {
        item["key"] for item in payload_cs["canonical_user_evidence"]
    })
    assert not {
        application.course_requirement_evidence_key(item.item_id)
        for item in plan_cs.requirements[0].course_requirements
    } & {item.key for item in plan_cs.reusable_evidence}
    assert result_cs.status == "unknown"
    assert result_cs.reason_code == "user_evidence_missing"
    assert result_cs.user_evidence.count("未提供") == 1
    assert result_cs.user_evidence.count("修过") == 3
    assert not any("course-checklist" in question.question_id for question in plan_cs.questions)

    # M: production-shaped KTH Machine Learning course codes expose the exact-key
    # identity boundary. The Special Interview preserves course code + title, while
    # a Gap Planner course item that drops the code produces a different canonical
    # key and cannot be bridged by the exact resolver.
    kth_target = target(
        "Master's Programme in Machine Learning",
        "https://www.kth.se/en/studies/master/machine-learning",
    )
    kth_requirement = (
        "The bachelor's degree must include mathematics and computer science coursework "
        "at a level at least corresponding to the following KTH courses: SF1624 Algebra "
        "and Geometry, SF1625 Calculus in One Variable, SF1626 Calculus in Several "
        "Variables, SF1920 Probability Theory and Statistics, DD1337 Programming, and "
        "DD1338 Algorithms and Data Structures."
    )
    kth_special_labels = [
        "SF1624 Algebra and Geometry",
        "SF1625 Calculus in One Variable",
        "SF1626 Calculus in Several Variables",
        "SF1920 Probability Theory and Statistics",
        "DD1337 Programming",
        "DD1338 Algorithms and Data Structures",
    ]
    kth_gap_labels_without_codes = [
        "Algebra and Geometry",
        "Calculus in One Variable",
        "Calculus in Several Variables",
        "Probability Theory and Statistics",
        "Programming",
        "Algorithms and Data Structures",
    ]
    kth_availability = {
        "SF1626 Calculus in Several Variables": "known_negative",
    }
    kth_names = {
        "SF1920 Probability Theory and Statistics": (
            "Probability Theory and Statistics"
        ),
        "DD1337 Programming": "Introduction to Programming",
    }
    kth_evidence = await submit_special_courses(
        kth_special_labels,
        names=kth_names,
        availability=kth_availability,
    )
    kth_review = reviewed_requirement(kth_requirement, kth_target)
    kth_plan_mismatch, kth_payload = await build_plan(
        kth_review,
        kth_evidence,
        course_only_planner_output(kth_gap_labels_without_codes),
        kth_target,
    )
    kth_planned_mismatch = kth_plan_mismatch.requirements[0]
    kth_by_label = {
        item.value["canonical_label"]: item for item in kth_evidence
    }
    sf1625_evidence = kth_by_label["SF1625 Calculus in One Variable"]
    sf1626_evidence = kth_by_label["SF1626 Calculus in Several Variables"]
    assert sf1625_evidence.key == (
        "prerequisite_course:sf1625_calculus_in_one_variable"
    )
    assert sf1625_evidence.availability == "known"
    assert sf1625_evidence.value["user_course_name"] is None
    assert sf1625_evidence.value["prerequisite_kind"] == "concrete_course"
    assert sf1625_evidence.source_requirement_ids == ["course:0"]
    assert sf1626_evidence.availability == "known_negative"
    assert not ({
        item.key for item in kth_evidence
    } & {
        item["key"] for item in kth_payload["canonical_user_evidence"]
    })

    sf1625_gap_item = next(
        item
        for item in kth_planned_mismatch.course_requirements
        if item.course_name == "Calculus in One Variable"
    )
    sf1625_lookup_key = application.special_evidence_key(
        "prerequisite_course",
        sf1625_gap_item.canonical_label or sf1625_gap_item.course_name,
    )
    assert sf1625_gap_item.canonical_label == "Calculus in One Variable"
    assert sf1625_gap_item.prerequisite_kind == "concrete_course"
    assert sf1625_lookup_key == "prerequisite_course:calculus_in_one_variable"
    assert sf1625_lookup_key != sf1625_evidence.key
    assert len(kth_planned_mismatch.course_requirements) == 6
    assert all(
        item.prerequisite_kind == "concrete_course"
        for item in kth_planned_mismatch.course_requirements
    )

    kth_runtime_mismatch = application.runtime_course_evidence_view(
        kth_target,
        kth_plan_mismatch.requirements,
        {item.key: item for item in kth_evidence},
    )
    kth_scoped_keys = {
        application.course_requirement_evidence_key(item.item_id)
        for item in kth_planned_mismatch.course_requirements
    }
    assert not kth_scoped_keys & set(kth_runtime_mismatch)
    kth_result_mismatch = await analyze(
        kth_plan_mismatch,
        kth_evidence,
        kth_target,
    )
    assert kth_result_mismatch.status == "unknown"
    assert kth_result_mismatch.reason_code == "user_evidence_missing"
    assert kth_result_mismatch.user_evidence.count("未提供") == 6

    # The same submitted evidence resolves when the Gap course identity preserves
    # the exact code + title label. This proves persistence, availability semantics,
    # and user_course_name are not the failing boundaries in this fixture.
    kth_plan_aligned, _kth_payload_aligned = await build_plan(
        kth_review,
        kth_evidence,
        course_only_planner_output(kth_special_labels),
        kth_target,
    )
    kth_runtime_aligned = application.runtime_course_evidence_view(
        kth_target,
        kth_plan_aligned.requirements,
        {item.key: item for item in kth_evidence},
    )
    kth_aligned_by_name = {
        item.course_name: kth_runtime_aligned[
            application.course_requirement_evidence_key(item.item_id)
        ]
        for item in kth_plan_aligned.requirements[0].course_requirements
    }
    assert kth_aligned_by_name[
        "SF1625 Calculus in One Variable"
    ].value["completed"] is True
    assert kth_aligned_by_name[
        "SF1626 Calculus in Several Variables"
    ].value["completed"] is False
    assert kth_aligned_by_name[
        "SF1920 Probability Theory and Statistics"
    ].value["completed"] is True
    kth_result_aligned = await analyze(
        kth_plan_aligned,
        kth_evidence,
        kth_target,
    )
    assert kth_result_aligned.status == "partial"
    assert "没修过" in kth_result_aligned.user_evidence
    assert "修过" in kth_result_aligned.user_evidence

    print(
        "CASE A",
        {"status": result_a.status, "reason_code": result_a.reason_code, "user_evidence": result_a.user_evidence},
    )
    print(
        "CASE B",
        {"status": result_b.status, "reason_code": result_b.reason_code, "user_evidence": result_b.user_evidence},
    )
    print(
        "CASE C",
        {"stored_linear_algebra": linear_c.availability, "status": result_c.status, "reason_code": result_c.reason_code},
    )
    print(
        "CASE D",
        {"stored_linear_algebra": linear_d.availability, "status": result_d.status, "reason_code": result_d.reason_code},
    )
    print(
        "CS",
        {"status": result_cs.status, "reason_code": result_cs.reason_code, "user_evidence": result_cs.user_evidence},
    )
    print(
        "KTH REALISTIC IDENTITY MISMATCH",
        {
            "sf1625_evidence_key": sf1625_evidence.key,
            "sf1625_gap_canonical_label": sf1625_gap_item.canonical_label,
            "sf1625_resolver_lookup_key": sf1625_lookup_key,
            "normalized_course_item_count": len(
                kth_planned_mismatch.course_requirements
            ),
            "mismatch_status": kth_result_mismatch.status,
            "mismatch_user_evidence": kth_result_mismatch.user_evidence,
            "aligned_status": kth_result_aligned.status,
            "sf1626_aligned_completed": kth_aligned_by_name[
                "SF1626 Calculus in Several Variables"
            ].value["completed"],
        },
    )
    print("PASS A/B concrete course validity is independent of user_course_name")
    print("PASS C/D known_negative and unknown remain distinct")
    print("PASS E/F exact concrete keys reuse safely across programmes")
    print("PASS G/H course categories resolve only in the current programme scope")
    print("PASS I compound CS requirement resolves courses while credits remain missing")
    print("PASS J/K question convergence respects concrete reuse and category scope")
    print("PASS L runtime view reads the latest canonical evidence without persistence")
    print("PASS M KTH course-code identity mismatch is reproduced without fuzzy matching")


if __name__ == "__main__":
    asyncio.run(run())
