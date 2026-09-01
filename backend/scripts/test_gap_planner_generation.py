"""Offline regressions for Gap Planner JSON generation and payload trimming."""

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
    university="Fixture University",
    program="Fixture Programme",
    official_program_url="https://example.edu/programme",
    official_domain="example.edu",
    intended_entry_year=2027,
    intended_entry_term="fall",
)


def review() -> application.TargetProgramRequirementsReview:
    requirement = application.RequirementItem(
        category="materials",
        requirement="A fixture document is required.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        source_cycle="2027",
        temporal_applicability="target_cycle_confirmed",
    )
    return application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )


def valid_output() -> str:
    return json.dumps(
        {
            "requirements": [
                {
                    "requirement_id": "materials:0",
                    "matchable": True,
                    "match_strategy": "deterministic",
                    "evidence_needs": [
                        {
                            "key": "materials.fixture_document",
                            "evidence_type": "material_status",
                            "value_kind": "boolean",
                            "label": "Fixture document",
                        }
                    ],
                    "constraint": {
                        "kind": "material_boolean",
                        "relation": "all",
                        "options": [
                            {
                                "key": "materials.fixture_document",
                                "kind": "material_boolean",
                            }
                        ],
                    },
                }
            ],
            "questions": [
                {
                    "question_id": "q:fixture",
                    "prompt": "是否已准备该材料？",
                    "expected_evidence_keys": ["materials.fixture_document"],
                    "control_type": "boolean",
                    "fields": [
                        {
                            "field_id": "ready",
                            "label": "准备状态",
                            "evidence_key": "materials.fixture_document",
                            "value_path": "status",
                        }
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )


def assert_failure_kind(
    result: application.DeepSeekTextResult,
    expected: str,
) -> None:
    try:
        application.parse_gap_planner_output(result)
    except application.GapPlannerOutputError as error:
        assert error.kind == expected
    else:
        raise AssertionError(f"expected {expected}")


def check_parse_classification() -> None:
    assert_failure_kind(
        application.DeepSeekTextResult(
            content='{"requirements":[{"requirement_id":"materials:0","matchable":true,"evidence_needs":[{"key":"materials.fixture',
            stop_reason="length",
            output_tokens=7000,
        ),
        "generation_incomplete",
    )
    assert_failure_kind(
        application.DeepSeekTextResult(
            content='{"requirements": definitely-not-json}',
            stop_reason="stop",
        ),
        "malformed_json",
    )
    assert_failure_kind(
        application.DeepSeekTextResult(
            content=json.dumps(
                {
                    "requirements": [
                        {"requirement_id": "materials:0"}
                    ],
                    "questions": [],
                }
            ),
            stop_reason="stop",
        ),
        "schema_validation_error",
    )
    parsed = application.parse_gap_planner_output(
        application.DeepSeekTextResult(content=valid_output(), stop_reason="stop")
    )
    assert parsed.requirements[0].requirement_id == "materials:0"


def check_evidence_value_kind_contract() -> None:
    classification = application.GapPlannerEvidenceNeedDraft(
        key="degree_classification",
        evidence_type="academic_score",
        value_kind="categorical",
    )
    assert classification.value_kind == "categorical"
    assert application.validated_evidence_value_kind(
        "degree_classification", "academic_score", "numeric"
    ) == "categorical"
    assert application.validated_evidence_value_kind(
        "gpa", "academic_score", "numeric"
    ) == "numeric"
    assert application.validated_evidence_value_kind(
        "average_score", "academic_score", "numeric"
    ) == "numeric"
    assert application.validated_evidence_value_kind(
        "materials.fixture_document", "material_status", "text"
    ) == "boolean"
    assert application.validated_evidence_value_kind(
        "generic.unclassified", "generic", "date"
    ) == "date"

    try:
        application.GapPlannerEvidenceNeedDraft(
            key="generic.invalid",
            evidence_type="generic",
            value_kind="number_group",
        )
    except application.ValidationError:
        pass
    else:
        raise AssertionError("invalid value_kind must fail schema validation")


def check_language_proof_kind_contract() -> None:
    ielts = application.GapPlannerEvidenceNeedDraft(
        key="ielts",
        evidence_type="language_score",
        value_kind="numeric",
        proof_kind="scored_test",
    )
    assert ielts.proof_kind == "scored_test"
    assert application.validated_language_proof_kind("ielts", "certificate") == "scored_test"
    assert application.validated_language_proof_kind("toefl", None) == "scored_test"
    assert application.validated_language_proof_kind(
        "education.language_medium", "certificate"
    ) == "medium_of_instruction"
    assert application.validated_language_proof_kind(
        "language.accepted_certificate", "certificate"
    ) == "certificate"

    non_language = application.GapPlannerEvidenceNeedDraft(
        key="materials.cv",
        evidence_type="material_status",
        value_kind="boolean",
    )
    assert non_language.proof_kind is None

    try:
        application.GapPlannerEvidenceNeedDraft(
            key="language.invalid",
            evidence_type="generic",
            value_kind="text",
            proof_kind="score_form",
        )
    except application.ValidationError:
        pass
    else:
        raise AssertionError("invalid proof_kind must fail schema validation")


def check_course_requirements_contract() -> None:
    names = [
        "Calculus",
        "Linear Algebra",
        "Probability and Statistics",
        "Discrete Mathematics",
    ]
    needs = [
        application.GapEvidenceNeed(
            key=f"courses.required_{index}",
            evidence_type="courses",
            value_kind="text",
        )
        for index, _ in enumerate(names)
    ]
    items = [
        application.GapCourseRequirement(
            evidence_key=needs[index].key,
            course_name=name,
            group_label="Mathematics",
        )
        for index, name in enumerate(names)
    ]
    normalized = application.normalize_course_requirements(
        "course:0", items, needs
    )
    assert [item.course_name for item in normalized] == names
    assert [item.group_label for item in normalized] == ["Mathematics"] * 4

    constraint = application.GapDeterministicConstraint(
        kind="course_credit",
        relation="all",
        options=[
            application.GapConstraintOption(
                key="courses.total_credits",
                kind="course_credit",
                required_quantity=28.5,
                unit="ECTS",
            )
        ],
    )
    assert len(normalized) == 4
    assert constraint.options[0].required_quantity == 28.5
    assert constraint.options[0].unit == "ECTS"

    assert application.normalize_course_requirements("course:1", [], needs) == []
    examples_only = application.GapPlannerRequirementLLMDraft(
        requirement_id="course:examples",
        matchable=True,
        evidence_needs=[],
        course_requirements=[],
    )
    assert examples_only.course_requirements == []

    required_ab = application.GapPlannerRequirementLLMDraft(
        requirement_id="course:required",
        matchable=True,
        evidence_needs=[
            {"key": "courses.a", "evidence_type": "courses", "value_kind": "text"},
            {"key": "courses.b", "evidence_type": "courses", "value_kind": "text"},
        ],
        course_requirements=[
            {"evidence_key": "courses.a", "course_name": "A"},
            {"evidence_key": "courses.b", "course_name": "B"},
        ],
    )
    assert [item.course_name for item in required_ab.course_requirements] == ["A", "B"]

    duplicate_and_cross_owned = application.normalize_course_requirements(
        "course:2",
        [
            application.GapCourseRequirement(evidence_key="courses.required_0", course_name="Calculus"),
            application.GapCourseRequirement(evidence_key="courses.required_1", course_name="  calculus  "),
            application.GapCourseRequirement(evidence_key="courses.other_requirement", course_name="Algorithms"),
        ],
        needs,
    )
    assert [(item.evidence_key, item.course_name) for item in duplicate_and_cross_owned] == [
        ("courses.required_0", "Calculus")
    ]

    malformed = application.GapPlannerRequirementLLMDraft(
        requirement_id="course:malformed",
        matchable=True,
        course_requirements=[
            {"evidence_key": "courses.a", "course_name": ""},
            {"evidence_key": "courses.a", "course_name": "A", "minimum_credits": "not-a-number"},
        ],
    )
    assert malformed.course_requirements == []


def check_conditional_metadata_contract() -> None:
    needs = [
        application.GapEvidenceNeed(
            key="education.selected_track",
            evidence_type="generic",
            value_kind="categorical",
        )
    ]
    explicit = application.normalize_conditional_metadata(
        "course:conditional",
        "If selecting the Interaction Design track, HCI is required.",
        application.GapConditionalMetadata(
            is_conditional=True,
            condition_text="If selecting the Interaction Design track",
            controlling_evidence_keys=[
                "education.selected_track",
                "education.selected_track",
                "education.other_requirement_track",
            ],
            predicates=[
                application.GapConditionalPredicate(
                    evidence_key="education.selected_track",
                    operator="equals",
                    expected_values=["Interaction Design"],
                ),
                application.GapConditionalPredicate(
                    evidence_key="education.other_requirement_track",
                    operator="equals",
                    expected_values=["Other"],
                ),
            ],
        ),
        needs,
    )
    assert explicit.is_conditional is True
    assert explicit.condition_text == "If selecting the Interaction Design track"
    assert explicit.controlling_evidence_keys == ["education.selected_track"]
    assert [item.model_dump() for item in explicit.predicates] == [
        {
            "evidence_key": "education.selected_track",
            "operator": "equals",
            "expected_values": ["Interaction Design"],
        }
    ]

    unconditional = application.normalize_conditional_metadata(
        "academic:unconditional",
        "A degree is required.",
        application.GapConditionalMetadata(),
        needs,
    )
    assert unconditional.model_dump() == {
        "is_conditional": False,
        "condition_text": None,
        "controlling_evidence_keys": [],
        "predicate_relation": "all",
        "predicates": [],
    }

    preferred = application.GapPlannerRequirementLLMDraft(
        requirement_id="experience:preferred",
        matchable=True,
        informational_reason="Research experience is preferred.",
    )
    assert preferred.conditional.is_conditional is False

    inconsistent_unconditional = application.normalize_conditional_metadata(
        "academic:inconsistent",
        "A degree is required.",
        application.GapConditionalMetadata(
            is_conditional=False,
            condition_text="Model supplied an invalid condition",
            controlling_evidence_keys=["education.selected_track"],
        ),
        needs,
    )
    assert inconsistent_unconditional == application.GapConditionalMetadata()

    missing_text = application.normalize_conditional_metadata(
        "course:missing-text",
        "If selecting the Interaction Design track, HCI is required.",
        application.GapConditionalMetadata(
            is_conditional=True,
            controlling_evidence_keys=["education.selected_track"],
        ),
        needs,
    )
    assert missing_text == application.GapConditionalMetadata()


def check_conditional_requirement_scope() -> None:
    general_materials = {
        "transcript": "An official transcript is required.",
        "cv": "A CV is required.",
        "recommendations": "Recommendation letters are required.",
        "personal_statement": "A personal statement is required.",
    }
    leaked_metadata = application.GapConditionalMetadata(
        is_conditional=True,
        condition_text="Only current CMU senior students may use the Accelerated pathway",
        controlling_evidence_keys=["education.degree"],
        predicates=[
            application.GapConditionalPredicate(
                evidence_key="education.degree",
                operator="equals",
                expected_values=["Current CMU senior"],
            )
        ],
    )
    for material, requirement_text in general_materials.items():
        normalized = application.normalize_conditional_metadata(
            f"materials:general:{material}",
            requirement_text,
            leaked_metadata,
            [
                application.GapEvidenceNeed(
                    key=f"materials.{material}",
                    evidence_type=(
                        "material_quantity"
                        if material == "recommendations"
                        else "material_status"
                    ),
                    value_kind=(
                        "numeric" if material == "recommendations" else "boolean"
                    ),
                )
            ],
        )
        assert normalized == application.GapConditionalMetadata()
        general_requirement = application.GapPlannedRequirement(
            requirement_id=f"materials:general:{material}",
            matchable=True,
            user_matchable=True,
            match_strategy="deterministic",
            evidence_needs=[],
            conditional=normalized,
            category="materials",
            requirement=requirement_text,
            importance="required",
            requirement_verification_status="official_verified",
            temporal_applicability="undated",
        )
        assert application.resolve_conditional_state(general_requirement, {}) == "not_conditional"

    pathway_need = application.GapEvidenceNeed(
        key="application.pathway",
        evidence_type="generic",
        value_kind="categorical",
    )
    pathway_metadata = application.normalize_conditional_metadata(
        "materials:accelerated",
        (
            "For the Accelerated Graduate Program pathway, only current CMU senior "
            "students must submit an SOP, Resume, and three recommendations; GRE and "
            "TOEFL are not required."
        ),
        application.GapConditionalMetadata(
            is_conditional=True,
            condition_text="For the Accelerated Graduate Program pathway",
            controlling_evidence_keys=["application.pathway"],
            predicates=[
                application.GapConditionalPredicate(
                    evidence_key="application.pathway",
                    operator="equals",
                    expected_values=["Accelerated Graduate Program"],
                )
            ],
        ),
        [pathway_need],
    )
    assert pathway_metadata.is_conditional is True
    pathway_requirement = application.GapPlannedRequirement(
        requirement_id="materials:accelerated",
        matchable=True,
        user_matchable=True,
        match_strategy="deterministic",
        evidence_needs=[pathway_need],
        conditional=pathway_metadata,
        category="materials",
        requirement=(
            "For the Accelerated Graduate Program pathway, only current CMU senior "
            "students must submit an SOP, Resume, and three recommendations."
        ),
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    assert application.resolve_conditional_state(pathway_requirement, {}) == "pending"

    scoped_review = application.TargetProgramRequirementsReview(
        target_program=TARGET,
        checked_at="2026-08-31T00:00:00Z",
        categories=[
            application.RequirementCategoryReview(
                category=category,
                coverage=("official_verified" if category == "materials" else "not_found"),
                requirements=(
                    [
                        application.RequirementItem(
                            category="materials",
                            requirement=text,
                            importance="required",
                            source_level="program",
                            source_type="official_retrieval",
                            verification_status="official_verified",
                            source_url="https://example.edu/programme",
                            temporal_applicability="undated",
                        )
                        for text in [
                            *general_materials.values(),
                            pathway_requirement.requirement,
                        ]
                    ]
                    if category == "materials"
                    else []
                ),
            )
            for category in (
                "academic",
                "course",
                "language",
                "standardized_test",
                "experience",
                "materials",
                "other",
            )
        ],
    )
    formal = application.formal_gap_requirements(scoped_review)
    assert len(formal) == 5
    assert [item["requirement"] for item in formal[:4]] == list(general_materials.values())
    assert "Accelerated Graduate Program" in formal[4]["requirement"]


def check_special_internal_route_scope_contract() -> None:
    positive = [
        "Available only to current University X undergraduate students.",
        "This accelerated BS/MS route is open only to current University X seniors.",
        "This route is reserved for internal progression applicants.",
    ]
    negative = [
        "Applicants may choose the Data Science pathway.",
        "The programme offers a 4+1 curriculum.",
        "If selecting Interaction Design track, HCI is required.",
        "The Accelerated pathway has a separate curriculum.",
    ]
    assert all(
        application.requirement_route_scope(text) == "special_internal"
        for text in positive
    )
    assert all(
        application.requirement_route_scope(text) == "standard"
        for text in negative
    )


async def check_named_route_scope_propagation() -> None:
    eligibility_text = (
        "The Accelerated Graduate Program is available only to current "
        "Carnegie Mellon undergraduate senior students."
    )
    accelerated_components = (
        "For the Accelerated Graduate Program pathway, the application components "
        "are a Statement of Purpose, Resume, Unofficial transcript, and three "
        "Recommendation Letters; there is no application fee."
    )
    general_materials = [
        "An official transcript is required for the general MSR application.",
        "A CV is required for the general MSR application.",
        "Letters of recommendation are required for the general MSR application.",
    ]
    same_url = "https://example.edu/msr"
    extraction = application.RequirementsExtraction(
        requirements=[
            application.RequirementItem(
                category="academic",
                requirement=eligibility_text,
                importance="required",
                source_level="program",
                source_type="official_retrieval",
                verification_status="official_verified",
                source_url=same_url,
                temporal_applicability="undated",
            ),
            *[
                application.RequirementItem(
                    category="materials",
                    requirement=text,
                    importance="required",
                    source_level="program",
                    source_type="official_retrieval",
                    verification_status="official_verified",
                    source_url=same_url,
                    temporal_applicability="undated",
                )
                for text in [*general_materials, accelerated_components]
            ],
            application.RequirementItem(
                category="other",
                requirement="Applicants may choose the Data Science pathway.",
                importance="unknown",
                source_level="program",
                source_type="official_retrieval",
                verification_status="official_verified",
                source_url=same_url,
                temporal_applicability="undated",
            ),
            application.RequirementItem(
                category="course",
                requirement=(
                    "If selecting Interaction Design track, Human-Computer "
                    "Interaction is required."
                ),
                importance="required",
                source_level="program",
                source_type="official_retrieval",
                verification_status="official_verified",
                source_url=same_url,
                temporal_applicability="undated",
            ),
        ]
    )
    review = application.requirements_review_from_extraction(TARGET, extraction)
    formal = application.formal_gap_requirements(review)
    by_id = {item["requirement_id"]: item for item in formal}
    general_ids = {"materials:0", "materials:1", "materials:2"}
    accelerated_ids = {
        f"materials:3:{suffix}"
        for suffix in (
            "transcript",
            "cv",
            "recommendations",
            "personal_statement",
            "process",
        )
    }

    assert by_id["academic:0"]["route_scope"] == "special_internal"
    assert by_id["academic:0"]["route_scope_source"] == "current_requirement"
    assert all(by_id[item_id]["route_scope"] == "standard" for item_id in general_ids)
    assert all(by_id[item_id]["route_scope"] == "special_internal" for item_id in accelerated_ids)
    assert all(
        by_id[item_id]["route_scope_source"] == "parent"
        for item_id in accelerated_ids
        if item_id != "materials:3:process"
    )
    assert by_id["materials:3:process"]["route_scope_source"] == "named_route"
    assert by_id["other:0"]["route_scope"] == "standard"
    assert by_id["course:0"]["route_scope"] == "standard"
    assert application.named_application_route_identities(eligibility_text) == {
        "accelerated graduate"
    }
    assert application.named_application_route_identities(accelerated_components) == {
        "accelerated graduate"
    }

    key_by_id = {
        "materials:0": "materials.transcript",
        "materials:1": "materials.cv",
        "materials:2": "materials.recommendations",
    }
    output = {
        "requirements": [
            {
                "requirement_id": requirement_id,
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": key,
                        "evidence_type": "material_status",
                        "value_kind": "boolean",
                        "label": key,
                    }
                ],
                "constraint": {
                    "kind": "material_boolean",
                    "relation": "all",
                    "options": [{"key": key, "kind": "material_boolean"}],
                },
            }
            for requirement_id, key in key_by_id.items()
        ]
        + [
            {
                "requirement_id": requirement_id,
                "matchable": False,
                "informational_reason": "fixture does not exercise this requirement",
                "evidence_needs": [],
            }
            for requirement_id in ("other:0", "course:0")
        ],
        "questions": [],
    }
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        payload = json.loads(
            kwargs["messages"][1]["content"]
            .split("Planner Input：", 1)[1]
            .split("\n输出 JSON Schema", 1)[0]
        )
        assert {item["requirement_id"] for item in payload["requirements"]} == (
            general_ids | {"other:0", "course:0"}
        )
        return application.DeepSeekTextResult(
            content=json.dumps(output, ensure_ascii=False),
            stop_reason="stop",
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
            )
        )
    finally:
        application.call_deepseek = original

    planned_by_id = {item.requirement_id: item for item in plan.requirements}
    assert all(
        planned_by_id[item_id].route_scope == "special_internal"
        for item_id in accelerated_ids | {"academic:0"}
    )
    question_types = [
        need.material_type
        for question in plan.questions
        if question.requirement_id in general_ids
        for need in planned_by_id[question.requirement_id].evidence_needs
        if need.key in question.expected_evidence_keys
    ]
    assert question_types.count("transcript") == 1
    assert question_types.count("cv") == 1
    assert question_types.count("recommendation_letters") == 1
    assert all(question.requirement_id in general_ids for question in plan.questions)


async def check_cmu_special_internal_route_exclusion() -> None:
    general_texts = [
        "An official transcript is required for the general MSR application.",
        "A CV is required for the general MSR application.",
        "Recommendation letters are required for the general MSR application.",
        "A personal statement is required for the general MSR application.",
    ]
    accelerated_text = (
        "For the Accelerated Graduate Program pathway, available only to current "
        "Carnegie Mellon undergraduate senior students, the application components "
        "are a Statement of Purpose, Resume, Unofficial transcript, and three "
        "Recommendation Letters; there is no application fee."
    )
    source_url = "https://example.edu/msr"
    extraction = application.RequirementsExtraction(
        requirements=[
            application.RequirementItem(
                category="materials",
                requirement=text,
                importance="required",
                source_level="program",
                source_type="official_retrieval",
                verification_status="official_verified",
                source_url=source_url,
                temporal_applicability="undated",
            )
            for text in [*general_texts, accelerated_text]
        ]
    )
    review = application.requirements_review_from_extraction(TARGET, extraction)
    assert review.categories[5].requirements[-1].requirement == accelerated_text
    formal = application.formal_gap_requirements(review)
    by_id = {item["requirement_id"]: item for item in formal}
    general_ids = {f"materials:{index}" for index in range(4)}
    accelerated_ids = {
        f"materials:4:{suffix}"
        for suffix in (
            "transcript",
            "cv",
            "recommendations",
            "personal_statement",
            "process",
        )
    }
    assert general_ids <= set(by_id)
    assert accelerated_ids <= set(by_id)
    assert all(by_id[item_id]["route_scope"] == "standard" for item_id in general_ids)
    assert all(
        by_id[item_id]["route_scope"] == "special_internal"
        for item_id in accelerated_ids
    )
    assert all(
        by_id[item_id]["excluded_reason"]
        == "unsupported_special_internal_route"
        for item_id in accelerated_ids
    )
    assert all(
        by_id[item_id]["route_scope_source"] == "parent"
        for item_id in accelerated_ids
        if item_id != "materials:4:process"
    )
    assert all(
        by_id[item_id]["source_url"] == source_url for item_id in set(by_id)
    )

    key_by_id = {
        "materials:0": "materials.transcript",
        "materials:1": "materials.cv",
        "materials:2": "materials.recommendations",
        "materials:3": "materials.personal_statement",
    }
    output = {
        "requirements": [
            {
                "requirement_id": requirement_id,
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": key,
                        "evidence_type": (
                            "material_quantity"
                            if key == "materials.recommendations"
                            else "material_status"
                        ),
                        "value_kind": (
                            "numeric"
                            if key == "materials.recommendations"
                            else "boolean"
                        ),
                        "label": key,
                    }
                ],
                "constraint": {
                    "kind": (
                        "material_quantity"
                        if key == "materials.recommendations"
                        else "material_boolean"
                    ),
                    "relation": "all",
                    "options": [
                        {
                            "key": key,
                            "kind": (
                                "material_quantity"
                                if key == "materials.recommendations"
                                else "material_boolean"
                            ),
                            "required_quantity": (
                                1 if key == "materials.recommendations" else None
                            ),
                        }
                    ],
                },
            }
            for requirement_id, key in key_by_id.items()
        ],
        "questions": [],
    }
    calls = 0
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        nonlocal calls
        calls += 1
        payload = json.loads(kwargs["messages"][1]["content"].split("Planner Input：", 1)[1].split("\n输出 JSON Schema", 1)[0])
        assert {
            item["requirement_id"] for item in payload["requirements"]
        } == general_ids
        return application.DeepSeekTextResult(
            content=json.dumps(output, ensure_ascii=False),
            stop_reason="stop",
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
            )
        )
    finally:
        application.call_deepseek = original

    assert calls == 1
    planned_by_id = {item.requirement_id: item for item in plan.requirements}
    assert set(planned_by_id) == general_ids | accelerated_ids
    assert all(
        planned_by_id[item_id].route_scope == "standard" for item_id in general_ids
    )
    assert all(
        planned_by_id[item_id].route_scope == "special_internal"
        and planned_by_id[item_id].excluded_reason
        == "unsupported_special_internal_route"
        and not planned_by_id[item_id].evidence_needs
        for item_id in accelerated_ids
    )
    assert all(question.requirement_id in general_ids for question in plan.questions)

    gap = await application.analyze_gap(
        application.GapAnalysisRequest(target_program=TARGET, plan=plan)
    )
    assert {item.requirement_id for item in gap.results} == general_ids
    assert all(
        item.requirement_id not in accelerated_ids
        for item in gap.informational_requirements
    )
    selected = application.select_planning_gaps(gap.results)
    assert all(item["requirement_id"] in general_ids for item in selected)


async def check_split_parent_applicability_inheritance() -> None:
    texts = [
        "An official transcript is required for the general MSR application.",
        "A CV is required for the general MSR application.",
        "Recommendation letters are required for the general MSR application.",
        "A personal statement is required for the general MSR application.",
        (
            "For the Accelerated Graduate Program pathway, the application components "
            "are a Statement of Purpose, Resume, Unofficial transcript, and three "
            "Recommendation Letters; there is no application fee."
        ),
    ]
    extraction = application.RequirementsExtraction(
        requirements=[
            application.RequirementItem(
                category="materials",
                requirement=text,
                importance="required",
                source_level="program",
                source_type="official_retrieval",
                verification_status="official_verified",
                source_url=(
                    "https://example.edu/accelerated"
                    if "Accelerated" in text
                    else "https://example.edu/msr"
                ),
                temporal_applicability="undated",
            )
            for text in texts
        ]
    )
    scoped_review = application.requirements_review_from_extraction(TARGET, extraction)
    formal = application.formal_gap_requirements(scoped_review)
    by_id = {item["requirement_id"]: item for item in formal}
    accelerated_children = {
        f"materials:4:{material}"
        for material in ("transcript", "cv", "recommendations", "personal_statement")
    }
    assert accelerated_children <= set(by_id)
    for child_id in accelerated_children:
        assert by_id[child_id]["parent_requirement_id"] == "materials:4"
        assert by_id[child_id]["inherits_parent_applicability"] is True
        assert by_id[child_id]["parent_has_explicit_conditional_scope"] is True
        assert "Accelerated Graduate Program" in by_id[child_id]["parent_requirement_text"]

    material_key_by_general_id = {
        "materials:0": "materials.transcript",
        "materials:1": "materials.cv",
        "materials:2": "materials.recommendations",
        "materials:3": "materials.personal_statement",
    }
    material_key_by_child_suffix = {
        "transcript": "materials.transcript",
        "cv": "materials.cv",
        "recommendations": "materials.recommendations",
        "personal_statement": "materials.personal_statement",
    }
    drafts = []
    for formal_item in formal:
        requirement_id = formal_item["requirement_id"]
        if requirement_id == "materials:4:process":
            drafts.append(
                {
                    "requirement_id": requirement_id,
                    "matchable": False,
                    "match_strategy": "semantic",
                    "evidence_needs": [
                        {
                            "key": "application.pathway",
                            "evidence_type": "generic",
                            "value_kind": "categorical",
                            "label": "Application pathway",
                        }
                    ],
                    "conditional": {
                        "is_conditional": True,
                        "condition_text": "For the Accelerated Graduate Program pathway",
                        "controlling_evidence_keys": ["application.pathway"],
                        "predicate_relation": "all",
                        "predicates": [
                            {
                                "evidence_key": "application.pathway",
                                "operator": "equals",
                                "expected_values": ["Accelerated Graduate Program"],
                            }
                        ],
                    },
                }
            )
            continue
        material_key = material_key_by_general_id.get(requirement_id)
        if material_key is None and requirement_id in accelerated_children:
            material_key = material_key_by_child_suffix[requirement_id.rsplit(":", 1)[-1]]
        drafts.append(
            {
                "requirement_id": requirement_id,
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": material_key,
                        "evidence_type": "material_status",
                        "value_kind": "boolean",
                        "label": material_key,
                    }
                ],
                "constraint": {
                    "kind": "material_boolean",
                    "relation": "all",
                    "options": [{"key": material_key, "kind": "material_boolean"}],
                },
                "conditional": {"is_conditional": False},
            }
        )

    output = {
        "requirements": drafts,
        "questions": [
            {
                "question_id": "q:accelerated-pathway",
                "requirement_id": "materials:4:transcript",
                "prompt": "请选择申请路径。",
                "expected_evidence_keys": ["application.pathway"],
                "control_type": "single_select",
                "options": [
                    {
                        "value": "accelerated",
                        "label": "Accelerated Graduate Program",
                        "evidence_key": "application.pathway",
                        "evidence_value": {"description": "Accelerated Graduate Program"},
                    },
                    {
                        "value": "general",
                        "label": "General MSR",
                        "evidence_key": "application.pathway",
                        "evidence_value": {"description": "General MSR"},
                    },
                ],
            }
        ],
    }
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return application.DeepSeekTextResult(
            content=json.dumps(output, ensure_ascii=False),
            stop_reason="stop",
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=scoped_review,
            )
        )
    finally:
        application.call_deepseek = original

    planned_by_id = {item.requirement_id: item for item in plan.requirements}
    for requirement_id in material_key_by_general_id:
        assert planned_by_id[requirement_id].conditional_state == "not_conditional"
        assert planned_by_id[requirement_id].conditional_scope_source == "none"
    for child_id in accelerated_children:
        child = planned_by_id[child_id]
        assert child.conditional_state == "pending"
        assert child.conditional_scope_source == "parent"
        assert child.parent_requirement_id == "materials:4"
        assert child.conditional.predicates[0].evidence_key == "application.pathway"
    material_question_ids = {
        question.requirement_id
        for question in plan.questions
        if question.question_id.startswith("policy:materials:")
    }
    assert material_question_ids == set(material_key_by_general_id), [
        (question.question_id, question.requirement_id)
        for question in plan.questions
    ]
    assert not accelerated_children.intersection(material_question_ids)


async def check_canonical_value_kind_wins_in_final_plan() -> None:
    requirement = application.RequirementItem(
        category="academic",
        requirement="A degree classification is required.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    academic_review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    output = {
        "requirements": [
            {
                "requirement_id": "academic:0",
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": "degree_classification",
                        "evidence_type": "academic_score",
                        "value_kind": "numeric",
                        "label": "Degree classification",
                    }
                ],
                "constraint": {
                    "kind": "none",
                    "relation": "all",
                    "options": [{"key": "degree_classification", "kind": "none"}],
                },
            }
        ],
        "questions": [
            {
                "question_id": "q:classification",
                "requirement_id": "academic:0",
                "prompt": "请选择你的学位等级。",
                "expected_evidence_keys": ["degree_classification"],
                "control_type": "single_select",
                "options": [
                    {
                        "value": "fixture",
                        "label": "Fixture classification",
                        "evidence_key": "degree_classification",
                        "evidence_value": {"description": "Fixture classification"},
                    }
                ],
            }
        ],
    }
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return application.DeepSeekTextResult(
            content=json.dumps(output, ensure_ascii=False),
            stop_reason="stop",
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=academic_review,
            )
        )
    finally:
        application.call_deepseek = original
    assert plan.requirements[0].evidence_needs[0].value_kind == "categorical"


async def check_canonical_proof_kind_wins_in_final_plan() -> None:
    requirement = application.RequirementItem(
        category="language",
        requirement="IELTS with an overall score of 7.0 is accepted.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    language_review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    output = {
        "requirements": [
            {
                "requirement_id": "language:0",
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": "ielts",
                        "evidence_type": "language_score",
                        "value_kind": "numeric",
                        "proof_kind": "certificate",
                        "label": "IELTS",
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
                "question_id": "q:ielts",
                "requirement_id": "language:0",
                "prompt": "请提供 IELTS 总分。",
                "expected_evidence_keys": ["ielts"],
                "control_type": "number",
                "fields": [
                    {"field_id": "ielts-score", "label": "IELTS 总分", "evidence_key": "ielts", "value_path": "score"}
                ],
            }
        ],
    }
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return application.DeepSeekTextResult(
            content=json.dumps(output, ensure_ascii=False),
            stop_reason="stop",
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=language_review,
            )
        )
    finally:
        application.call_deepseek = original
    assert plan.requirements[0].evidence_needs[0].proof_kind == "scored_test"


def check_payload_does_not_include_question_ui_metadata() -> None:
    formal = application.formal_gap_requirements(review())
    evidence = application.UserEvidence(
        evidence_type="material_status",
        key="materials.fixture_document",
        value={"status": True},
        raw_answer="sensitive free text that must not be copied",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    payload = application.gap_planner_prompt_payload(
        application.GapPlanRequest(
            target_program=TARGET,
            requirements_review=review(),
            user_evidence=[evidence],
        ),
        formal,
        [evidence],
    )
    serialized = json.dumps(payload)
    for forbidden in (
        "control_type",
        "options",
        "fields",
        "validation",
        "allow_other",
        "allow_unknown",
        "raw_answer",
        "updated_at",
        "source_requirement_ids",
    ):
        assert forbidden not in serialized

    planned = application.GapPlannedRequirement(
        requirement_id="materials:0",
        matchable=True,
        user_matchable=True,
        match_strategy="semantic",
        evidence_needs=[
            application.GapEvidenceNeed(
                key="materials.fixture_document",
                evidence_type="material_status",
                required_fields=["status"],
            )
        ],
        category="materials",
        requirement="A fixture document is required.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="target_cycle_confirmed",
    )
    semantic_payload = application.semantic_gap_task_payload(planned, [evidence])
    assert set(semantic_payload) == {
        "requirement_id",
        "category",
        "requirement",
        "importance",
        "user_evidence",
        "constraint",
        "temporal_applicability",
        "requirement_verification_status",
    }
    assert set(semantic_payload["user_evidence"][0]) == {
        "evidence_type",
        "key",
        "value",
        "availability",
    }


async def check_narrow_retry_contract() -> None:
    original = application.call_deepseek
    calls = []

    async def malformed_then_valid(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return application.DeepSeekTextResult(
                content='{"requirements": definitely-not-json}',
                stop_reason="stop",
                input_tokens=1000,
                output_tokens=100,
            )
        return application.DeepSeekTextResult(
            content=valid_output(),
            stop_reason="stop",
            input_tokens=1000,
            output_tokens=500,
        )

    application.call_deepseek = malformed_then_valid
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review(),
            )
        )
    finally:
        application.call_deepseek = original
    assert len(calls) == 2
    assert [call["max_tokens"] for call in calls] == [
        application.GAP_PLANNER_INITIAL_MAX_OUTPUT_TOKENS,
        application.GAP_PLANNER_RETRY_MAX_OUTPUT_TOKENS,
    ]
    assert plan.requirements
    assert plan.questions

    length_calls = []

    async def truncated_then_valid(*args, **kwargs):
        length_calls.append(kwargs)
        if len(length_calls) == 1:
            return application.DeepSeekTextResult(
                content='{"requirements": [{"requirement_id": "materials:0"',
                stop_reason="length",
                input_tokens=1000,
                output_tokens=application.GAP_PLANNER_INITIAL_MAX_OUTPUT_TOKENS,
            )
        return application.DeepSeekTextResult(
            content=valid_output(),
            stop_reason="stop",
            input_tokens=1000,
            output_tokens=500,
        )

    application.call_deepseek = truncated_then_valid
    try:
        length_plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review(),
            )
        )
    finally:
        application.call_deepseek = original
    assert [call["max_tokens"] for call in length_calls] == [10_000, 12_000]
    assert length_calls[1]["max_tokens"] > length_calls[0]["max_tokens"]
    assert length_plan.requirements

    schema_calls = 0

    async def invalid_schema(*args, **kwargs):
        nonlocal schema_calls
        schema_calls += 1
        return application.DeepSeekTextResult(
            content=json.dumps(
                {
                    "requirements": [{"requirement_id": "materials:0"}],
                    "questions": [],
                }
            ),
            stop_reason="stop",
        )

    application.call_deepseek = invalid_schema
    try:
        try:
            await application.build_gap_plan(
                application.GapPlanRequest(
                    target_program=TARGET,
                    requirements_review=review(),
                )
            )
        except application.HTTPException as error:
            assert error.status_code == 502
        else:
            raise AssertionError("schema validation error must fail")
    finally:
        application.call_deepseek = original
    assert schema_calls == 1


async def main() -> None:
    check_parse_classification()
    check_evidence_value_kind_contract()
    check_language_proof_kind_contract()
    check_course_requirements_contract()
    check_conditional_metadata_contract()
    check_conditional_requirement_scope()
    check_special_internal_route_scope_contract()
    await check_named_route_scope_propagation()
    await check_cmu_special_internal_route_exclusion()
    await check_split_parent_applicability_inheritance()
    await check_canonical_value_kind_wins_in_final_plan()
    await check_canonical_proof_kind_wins_in_final_plan()
    check_payload_does_not_include_question_ui_metadata()
    await check_narrow_retry_contract()
    print("gap planner generation regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
