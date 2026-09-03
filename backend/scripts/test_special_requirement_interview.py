from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import main as application


def target() -> application.TargetProgram:
    return application.TargetProgram(
        university="Example University",
        program="MSc Example",
        official_program_url="https://example.edu/msc",
        official_domain="example.edu",
        confirmation_status="confirmed",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )


def requirement(text: str, *, status: str = "official_verified") -> application.RequirementItem:
    return application.RequirementItem(
        category="course" if "course" in text.casefold() else "other",
        requirement=text,
        importance="required",
        source_level="program",
        source_type="user_supplied" if status == "user_supplied" else "official_retrieval",
        verification_status=status,
        source_url="https://example.edu/msc",
        temporal_applicability="undated",
    )


def review(items: list[application.RequirementItem]) -> application.TargetProgramRequirementsReview:
    categories = []
    for category in application.REQUIREMENT_CATEGORIES:
        matches = [item for item in items if item.category == category]
        categories.append(
            application.RequirementCategoryReview(
                category=category,
                coverage="official_verified" if matches else "not_found",
                requirements=matches,
            )
        )
    return application.TargetProgramRequirementsReview(
        target_program=target(), checked_at="2026-09-01T00:00:00Z", categories=categories
    )


def plan(
    extraction: application.SpecialTargetedExtractionOutput,
    items: list[application.RequirementItem],
    evidence: list[application.UserEvidence] | None = None,
) -> application.SpecialInterviewPlan:
    request = application.SpecialInterviewPlanRequest(
        target_program=target(), requirements_review=review(items), user_evidence=evidence or []
    )
    trusted = application.trusted_reviewed_requirements(request.requirements_review)
    return application.build_special_interview_plan_from_extraction(
        request, trusted, extraction, llm_requests=1
    )


def group(relation: str = "all_of", labels: list[str] | None = None):
    return application.SpecialPrerequisiteGroupExtraction(
        requirement_id="course:0",
        relation=relation,
        courses=[
            application.SpecialPrerequisiteCourseExtraction(
                prerequisite_kind="concrete_course", canonical_label=label
            )
            for label in (labels or ["Linear Algebra"])
        ],
    )


def evidence(label: str, availability: str = "known") -> application.UserEvidence:
    item_id = application.authoritative_prerequisite_item_id(
        "course:0", "concrete_course", label
    )
    return application.UserEvidence(
        evidence_type="prerequisite_course",
        key=application.programme_course_evidence_key(target(), "course:0", item_id),
        value={
            "canonical_label": label,
            "requirement_id": "course:0",
            "item_id": item_id,
            "prerequisite_kind": "concrete_course",
            "reusable": False,
        },
        raw_answer="fixture",
        availability=availability,
        updated_at="2026-09-01T00:00:00Z",
    )


def run() -> None:
    passed: list[str] = []
    base_items = [requirement("Required course background")]

    empty = plan(application.SpecialTargetedExtractionOutput(), [requirement("IELTS, GPA and recommendation letters are required")])
    assert empty.remaining_item_count == 0
    passed.append("01 standard-profile-only extraction skips interview")

    three = plan(application.SpecialTargetedExtractionOutput(prerequisite_groups=[group(labels=["Linear Algebra", "Probability", "Algorithms"])]), base_items)
    assert [item.canonical_label for item in three.prerequisite_groups[0].courses] == ["Linear Algebra", "Probability", "Algorithms"]
    passed.append("02 prerequisite courses are grouped")

    assert plan(application.SpecialTargetedExtractionOutput(prerequisite_groups=[group("all_of", ["Linear Algebra", "Probability"])]), base_items).prerequisite_groups[0].relation == "all_of"
    passed.append("03 all_of relation preserved")

    one = plan(application.SpecialTargetedExtractionOutput(prerequisite_groups=[group("one_of", ["Linear Algebra", "Discrete Mathematics"])]), base_items)
    assert one.prerequisite_groups[0].relation == "one_of"
    passed.append("04 one_of relation preserved")

    one_known = plan(application.SpecialTargetedExtractionOutput(prerequisite_groups=[group("one_of", ["Linear Algebra", "Discrete Mathematics"])]), base_items, [evidence("Linear Algebra")])
    assert one_known.prerequisite_groups == []
    passed.append("05 one_of positive reusable fact satisfies group")

    partial_all = plan(application.SpecialTargetedExtractionOutput(prerequisite_groups=[group("all_of", ["Linear Algebra", "Probability"])]), base_items, [evidence("Linear Algebra")])
    assert [item.canonical_label for item in partial_all.prerequisite_groups[0].courses] == ["Probability"]
    passed.append("06 all_of only retains unanswered facts")

    submitted_plan = plan(
        application.SpecialTargetedExtractionOutput(
            prerequisite_groups=[group(labels=["Linear Algebra", "Probability", "Algorithms"])]
        ),
        base_items,
    )
    submitted_courses = submitted_plan.prerequisite_groups[0].courses
    submitted = asyncio.run(application.special_interview_evidence_submit_endpoint(application.SpecialInterviewEvidenceSubmitRequest(target_program=target(), answers=[
        application.SpecialInterviewAnswer(evidence_key=submitted_courses[0].evidence_key, item_id=submitted_courses[0].item_id, canonical_label="Linear Algebra", item_type="prerequisite_course", prerequisite_kind="concrete_course", availability="known", requirement_id="course:0", user_course_name="Matrix Algebra"),
        application.SpecialInterviewAnswer(evidence_key=submitted_courses[1].evidence_key, item_id=submitted_courses[1].item_id, canonical_label="Probability", item_type="prerequisite_course", prerequisite_kind="concrete_course", availability="known_negative", requirement_id="course:0"),
        application.SpecialInterviewAnswer(evidence_key=submitted_courses[2].evidence_key, item_id=submitted_courses[2].item_id, canonical_label="Algorithms", item_type="prerequisite_course", prerequisite_kind="concrete_course", availability="unknown", requirement_id="course:0"),
    ])))
    assert [item.availability for item in submitted.evidence] == ["known", "known_negative", "unknown"] and submitted.evidence[0].value["user_course_name"] == "Matrix Algebra"
    passed.append("07 typed tri-state evidence is stored correctly")

    assert submitted_courses[0].item_id == application.authoritative_prerequisite_item_id("course:0", "concrete_course", "Linear Algebra")
    passed.append("08 backend creates stable requirement-scoped item id")

    assert application.special_evidence_key("prerequisite_course", "Advanced Linear Algebra") != application.special_evidence_key("prerequisite_course", "Linear Algebra")
    passed.append("09 important course qualifiers remain distinct")

    captured: dict[str, object] = {"calls": 0}
    original_call = application.call_deepseek
    async def fake_call(**kwargs):
        captured["calls"] = int(captured["calls"]) + 1
        captured["messages"] = kwargs["messages"]
        return application.DeepSeekTextResult(content='{"prerequisite_groups":[],"objective_special_requirements":[]}')
    application.call_deepseek = fake_call
    try:
        asyncio.run(application.extract_special_requirements_once(application.trusted_reviewed_requirements(review([requirement("Tuition, deadline, intake and duration")]))))
    finally:
        application.call_deepseek = original_call
    prompt = json.dumps(captured["messages"], ensure_ascii=False)
    assert captured["calls"] == 1 and "学费" in prompt and "deadline" in prompt and "不输出" in prompt
    passed.append("10 one batch prompt excludes administrative facts")

    assert "related discipline" in prompt and "不输出" in prompt
    passed.append("11 subjective related discipline is excluded by contract")

    assert "relevant experience" in prompt and "不输出" in prompt
    passed.append("12 subjective experience is excluded by contract")

    special = plan(application.SpecialTargetedExtractionOutput(objective_special_requirements=[application.SpecialObjectiveRequirementExtraction(requirement_id="other:0", canonical_label="Certificate X", special_type="certificate")]), [requirement("Certificate X is required")])
    assert special.objective_special_requirements[0].expected_answer_type == "ternary"
    passed.append("13 objective certificate becomes ternary item")

    trusted = application.trusted_reviewed_requirements(review([
        requirement("Trusted official"),
        requirement("User supplied", status="user_supplied"),
        requirement("Unverified memory", status="model_memory_unverified"),
    ]))
    assert {item["verification_status"] for item in trusted} == {"official_verified", "user_supplied"}
    passed.append("14 unverified model-memory requirement is filtered before LLM")

    invented = plan(application.SpecialTargetedExtractionOutput(prerequisite_groups=[application.SpecialPrerequisiteGroupExtraction(requirement_id="course:999", relation="all_of", courses=[application.SpecialPrerequisiteCourseExtraction(prerequisite_kind="concrete_course", canonical_label="Calculus")])]), base_items)
    assert invented.remaining_item_count == 0
    passed.append("15 invented requirement_id is dropped")

    parsed = application.parse_special_targeted_extraction(json.dumps({"prerequisite_groups": [{"requirement_id": "course:0", "relation": "all_of", "courses": [{"prerequisite_kind": "concrete_course", "canonical_label": "Algorithms"}]}, {"requirement_id": "course:0", "relation": "broken", "courses": []}], "objective_special_requirements": [{"requirement_id": "other:0", "canonical_label": ""}]}))
    assert len(parsed.prerequisite_groups) == 1 and parsed.objective_special_requirements == []
    passed.append("16 malformed item does not discard valid siblings")

    assert "question" not in application.SpecialTargetedExtractionOutput.model_json_schema().get("properties", {})
    passed.append("17 extraction schema has no question field")

    assert submitted.parser_calls == 0 and submitted.llm_requests == 0
    passed.append("18 typed clicks use zero parser and LLM calls")

    concrete = application.SpecialPrerequisiteCourseExtraction(
        prerequisite_kind="concrete_course", canonical_label="Linear Algebra"
    )
    assert concrete.canonical_label == "Linear Algebra" and concrete.category_label is None
    passed.append("19 concrete course schema")

    def category_item(label: str, minimum: int = 1):
        return application.SpecialPrerequisiteCourseExtraction(
            prerequisite_kind="course_category",
            category_label=label,
            minimum_courses=minimum,
        )

    systems_extraction = application.SpecialTargetedExtractionOutput(
        prerequisite_groups=[application.SpecialPrerequisiteGroupExtraction(
            requirement_id="course:0", relation="all_of", courses=[category_item("Systems")]
        )]
    )
    systems_plan = plan(systems_extraction, base_items)
    systems_item = systems_plan.prerequisite_groups[0].courses[0]
    assert systems_item.category_label == "Systems" and systems_item.canonical_label is None
    assert "one from the available" not in (systems_item.category_label or "").casefold()
    passed.append("20 Systems phrase normalized to course category")

    foundations = category_item("Theoretical Foundations")
    assert foundations.category_label == "Theoretical Foundations"
    passed.append("21 Theoretical Foundations category")

    ai_category = category_item("Artificial Intelligence")
    assert ai_category.category_label == "Artificial Intelligence"
    passed.append("22 Artificial Intelligence category")

    math_item = category_item("Mathematics", 2)
    assert math_item.minimum_courses == 2
    passed.append("23 explicit minimum course count preserved")

    math_extraction = application.SpecialTargetedExtractionOutput(
        prerequisite_groups=[application.SpecialPrerequisiteGroupExtraction(
            requirement_id="course:0", relation="all_of", courses=[math_item]
        )]
    )
    math_plan = plan(math_extraction, base_items)
    math_course = math_plan.prerequisite_groups[0].courses[0]
    math_submit = asyncio.run(application.special_interview_evidence_submit_endpoint(
        application.SpecialInterviewEvidenceSubmitRequest(
            target_program=target(),
            answers=[application.SpecialInterviewAnswer(
                evidence_key=math_course.evidence_key,
                item_id=math_course.item_id,
                canonical_label="Mathematics",
                item_type="prerequisite_course",
                prerequisite_kind="course_category",
                minimum_courses=2,
                availability="known",
                requirement_id="course:0",
                user_course_names=["Calculus", "Linear Algebra"],
            )],
        )
    ))
    assert math_submit.evidence[0].value["matched_user_courses"] == ["Calculus", "Linear Algebra"]
    assert not any(item.evidence_type == "user_course" for item in math_submit.evidence)
    passed.append("24 category course names remain scoped inside the item response")

    assert not any(item.key == "course_category:systems" for item in math_submit.evidence)
    assert math_submit.evidence[0].key.startswith("programme_course_response:")
    assert math_submit.evidence[0].value["reusable"] is False
    passed.append("25 category satisfied state is requirement scoped")

    systems_submit = asyncio.run(application.special_interview_evidence_submit_endpoint(
        application.SpecialInterviewEvidenceSubmitRequest(
            target_program=target(),
            answers=[application.SpecialInterviewAnswer(
                evidence_key=systems_item.evidence_key,
                item_id=systems_item.item_id,
                canonical_label="Systems",
                item_type="prerequisite_course",
                prerequisite_kind="course_category",
                minimum_courses=1,
                availability="known",
                requirement_id="course:0",
                user_course_names=["Operating Systems"],
            )],
        )
    ))
    other_target = target().model_copy(update={"program": "MSc Other Programme", "official_program_url": "https://example.edu/other"})
    other_request = application.SpecialInterviewPlanRequest(
        target_program=other_target,
        requirements_review=review(base_items),
        user_evidence=systems_submit.evidence,
    )
    other_plan = application.build_special_interview_plan_from_extraction(
        other_request,
        application.trusted_reviewed_requirements(other_request.requirements_review),
        systems_extraction,
        llm_requests=1,
    )
    assert other_plan.remaining_item_count == 1
    assert other_plan.prerequisite_groups[0].courses[0].suggested_user_courses == []
    passed.append("26 category does not auto-satisfy another programme")

    assert plan(application.SpecialTargetedExtractionOutput(prerequisite_groups=[group(labels=["Linear Algebra"])]), base_items, [evidence("Linear Algebra")]).remaining_item_count == 0
    other_target = target().model_copy(update={"program": "MSc Other Programme", "official_program_url": "https://example.edu/other"})
    other_linear_request = application.SpecialInterviewPlanRequest(
        target_program=other_target,
        requirements_review=review(base_items),
        user_evidence=[evidence("Linear Algebra")],
    )
    other_linear_plan = application.build_special_interview_plan_from_extraction(
        other_linear_request,
        application.trusted_reviewed_requirements(other_linear_request.requirements_review),
        application.SpecialTargetedExtractionOutput(prerequisite_groups=[group(labels=["Linear Algebra"])]),
        llm_requests=1,
    )
    assert other_linear_plan.remaining_item_count == 1
    passed.append("27 concrete course ask-once is limited to the same programme")

    assert application.special_evidence_key("prerequisite_course", "Advanced Linear Algebra") != application.special_evidence_key("prerequisite_course", "Linear Algebra")
    passed.append("28 advanced qualifier does not reuse base course")

    mixed_relations = application.SpecialTargetedExtractionOutput(prerequisite_groups=[
        application.SpecialPrerequisiteGroupExtraction(requirement_id="course:0", relation="all_of", courses=[category_item("Systems")]),
        application.SpecialPrerequisiteGroupExtraction(requirement_id="course:0", relation="one_of", courses=[category_item("Artificial Intelligence"), concrete]),
    ])
    relation_plan = plan(mixed_relations, base_items)
    assert [item.relation for item in relation_plan.prerequisite_groups] == ["all_of", "one_of"]
    passed.append("29 all_of and one_of remain unchanged")

    extraction_schema = application.SpecialTargetedExtractionOutput.model_json_schema()
    assert "question" not in extraction_schema.get("properties", {})
    passed.append("30 extraction still has no question")

    assert "course_category" in prompt and "minimum_courses" in prompt and "绝不能把整句话" in prompt
    assert "aggregate_course_credits" in prompt and "required_quantity" in prompt
    passed.append("31 targeted prompt defines category granularity")

    assert len(passed) == 31
    for item in passed:
        print(f"PASS {item}")
    print("PASS special requirement interview regressions: 31/31")


if __name__ == "__main__":
    run()
