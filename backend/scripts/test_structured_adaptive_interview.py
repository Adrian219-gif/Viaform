"""Offline regressions for AI-generated question schemas and typed evidence."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


TARGET = application.TargetProgram(
    university="Schema University",
    program="Schema MSc",
    official_program_url="https://example.edu/programme",
    official_domain="example.edu",
)


def need(
    key: str,
    evidence_type: str,
    *,
    required_fields: List[str],
    group: Optional[str] = None,
    relation: str = "all",
) -> application.GapEvidenceNeed:
    return application.GapEvidenceNeed(
        key=key,
        evidence_type=evidence_type,
        label=key,
        required_fields=required_fields,
        evidence_group=group,
        group_relation=relation,
    )


def submit(
    question: application.GapPlannerQuestion,
    needs: List[application.GapEvidenceNeed],
    *,
    values=None,
    selected=None,
    terminal=None,
    existing=None,
) -> application.GapEvidenceParseResponse:
    return application.submit_structured_evidence(
        application.GapStructuredEvidenceRequest(
            question=question,
            evidence_needs=needs,
            existing_evidence=existing or [],
            answer=application.GapStructuredAnswer(
                values=values or {},
                selected_options=selected or [],
                terminal_state=terminal,
            ),
        )
    )


def check_dynamic_single_select() -> None:
    classification = need(
        "degree_classification",
        "academic_score",
        required_fields=["description"],
    )
    question = application.GapPlannerQuestion(
        question_id="q:classification",
        prompt="请选择该 Requirement 接受的学位等级。",
        expected_evidence_keys=["degree_classification"],
        control_type="single_select",
        options=[
            {
                "value": "fixture-level-a",
                "label": "Fixture Level A",
                "evidence_key": "degree_classification",
                "evidence_value": {"description": "Fixture Level A"},
            },
            {
                "value": "fixture-level-b",
                "label": "Fixture Level B",
                "evidence_key": "degree_classification",
                "evidence_value": {"description": "Fixture Level B"},
            },
        ],
    )
    result = submit(question, [classification], selected=["fixture-level-a"])
    assert result.parser_calls == 0
    assert result.missing_slots == []
    assert result.evidence[0].value == {"description": "Fixture Level A"}


def check_categorical_academic_schema_and_fallback_wording() -> None:
    constraint = application.GapDeterministicConstraint(
        kind="score",
        relation="any",
        options=[
            application.GapConstraintOption(
                key="degree_classification",
                kind="score",
            ),
            application.GapConstraintOption(
                key="gpa",
                kind="score",
                minimum=3.5,
            ),
        ],
    )
    classification = need(
        "degree_classification",
        "academic_score",
        required_fields=[],
        group="academic:any",
        relation="any",
    )
    gpa = need(
        "gpa",
        "academic_score",
        required_fields=[],
        group="academic:any",
        relation="any",
    )
    classification.required_fields = application.required_fields_for_evidence_need(
        classification,
        constraint,
    )
    gpa.required_fields = application.required_fields_for_evidence_need(gpa, constraint)
    assert classification.evidence_type == "academic_score"
    assert classification.required_fields == ["description"]
    assert gpa.required_fields == ["score", "scale"]

    question = application.GapPlannerQuestion(
        question_id="q:categorical-academic",
        prompt="请选择符合你的学位等级。",
        expected_evidence_keys=["degree_classification"],
        control_type="single_select",
        options=[
            {
                "value": "fixture-level",
                "label": "Fixture Level",
                "evidence_key": "degree_classification",
                "evidence_value": {"description": "Fixture Level"},
            }
        ],
    )
    normalized = application.normalize_question_schema(
        question,
        ["degree_classification", "gpa"],
        {"degree_classification": classification, "gpa": gpa},
        {},
    )
    assert normalized.control_type == "single_select"
    assert normalized.schema_status == "valid"
    assert normalized.group_relation == "any"

    invalid = application.GapPlannerQuestion(
        question_id="q:categorical-invalid",
        prompt="Internal prompt",
        expected_evidence_keys=["degree_classification"],
        control_type="number",
        fields=[
            {
                "field_id": "wrong-score",
                "label": "Wrong score",
                "evidence_key": "degree_classification",
                "value_path": "score",
            }
        ],
    )
    rejected = application.normalize_question_schema(
        invalid,
        ["degree_classification"],
        {"degree_classification": classification},
        {},
    )
    assert rejected.control_type == "number"
    assert rejected.schema_status == "invalid"
    assert rejected.schema_error_code == "invalid_value_path"
    assert rejected.generation_diagnostics.initial_failure_stage == "initial_schema_invalid"
    assert rejected.generation_diagnostics.initial_schema["control_type"] == "number"


def check_real_academic_any_structured_convergence() -> None:
    group = "academic:1:alternatives"
    needs = [
        need(
            "degree_classification",
            "academic_score",
            required_fields=["description"],
            group=group,
            relation="any",
        ),
        need(
            "gpa",
            "academic_score",
            required_fields=["score"],
            group=group,
            relation="any",
        ),
        need(
            "average_score",
            "academic_score",
            required_fields=["score"],
            group=group,
            relation="any",
        ),
    ]
    needs_by_key = {item.key: item for item in needs}

    classification_question = application.normalize_question_schema(
        application.GapPlannerQuestion(
            question_id="q:academic:1:classification",
            requirement_id="academic:1",
            prompt="请选择你的学位等级。",
            expected_evidence_keys=["degree_classification"],
            control_type="single_select",
            options=[
                {
                    "value": "fixture-classification",
                    "label": "二等二",
                    "evidence_key": "degree_classification",
                    "evidence_value": {"description": "二等二"},
                }
            ],
        ),
        ["degree_classification", "gpa", "average_score"],
        needs_by_key,
        {},
    )
    classification_result = submit(
        classification_question,
        needs,
        selected=["fixture-classification"],
    )
    assert classification_question.question_id == "q:academic:1:classification"
    assert classification_question.requirement_id == "academic:1"
    assert classification_question.evidence_group == group
    assert classification_question.group_relation == "any"
    assert classification_question.control_type == "single_select"
    assert classification_result.evidence[0].key == "degree_classification"
    assert classification_result.evidence[0].value == {"description": "二等二"}
    assert classification_result.evidence[0].availability == "known"
    assert classification_result.slot_states == {
        "degree_classification.description": "known"
    }
    assert classification_result.satisfied_evidence_groups == [group]
    assert classification_result.missing_slots == []
    assert classification_result.follow_up_question is None

    for key, value in (("gpa", 3.7), ("average_score", 87)):
        numeric_question = application.normalize_question_schema(
            application.GapPlannerQuestion(
                question_id=f"q:academic:1:{key}",
                requirement_id="academic:1",
                prompt="请输入你的成绩。",
                expected_evidence_keys=[key],
                control_type="number",
                fields=[
                    {
                        "field_id": f"{key}-score",
                        "label": "成绩",
                        "evidence_key": key,
                        "value_path": "score",
                    }
                ],
            ),
            ["degree_classification", "gpa", "average_score"],
            needs_by_key,
            {},
        )
        result = submit(
            numeric_question,
            needs,
            values={f"{key}-score": value},
        )
        assert numeric_question.control_type == "number"
        assert result.evidence[0].key == key
        assert result.evidence[0].value == {"score": value}
        assert result.evidence[0].availability == "known"
        assert result.satisfied_evidence_groups == [group]
        assert result.missing_slots == []
        assert result.follow_up_question is None


def check_number_and_number_group() -> None:
    score_need = need("score.fixture", "academic_score", required_fields=["score"])
    number = application.GapPlannerQuestion(
        question_id="q:number",
        prompt="请输入数值。",
        expected_evidence_keys=["score.fixture"],
        control_type="number",
        fields=[
            {
                "field_id": "score",
                "label": "分数",
                "evidence_key": "score.fixture",
                "value_path": "score",
            }
        ],
        validation={"minimum": 0, "maximum": 100},
    )
    number_result = submit(number, [score_need], values={"score": 87})
    assert number_result.parser_calls == 0
    assert number_result.evidence[0].value == {"score": 87}

    grouped_need = need(
        "test.fixture",
        "language_score",
        required_fields=["score", "listening", "reading"],
    )
    grouped = application.GapPlannerQuestion(
        question_id="q:number-group",
        prompt="请输入 Requirement 中要求的各项数值。",
        expected_evidence_keys=["test.fixture"],
        control_type="number_group",
        fields=[
            {"field_id": path, "label": path, "evidence_key": "test.fixture", "value_path": path}
            for path in ("score", "listening", "reading")
        ],
    )
    grouped_result = submit(
        grouped,
        [grouped_need],
        values={"score": 8, "listening": 8, "reading": 7.5},
    )
    assert grouped_result.parser_calls == 0
    assert grouped_result.evidence[0].value == {
        "score": 8,
        "subscores": {"listening": 8, "reading": 7.5},
    }


def check_score_group_terminal_actions() -> None:
    score_need = need(
        "test.fixture",
        "language_score",
        required_fields=["score", "listening", "reading", "writing", "speaking"],
    )
    generated = application.GapPlannerQuestion(
        question_id="q:score-terminal",
        prompt="Provide the available test score fields.",
        expected_evidence_keys=["test.fixture"],
        control_type="number_group",
        fields=[
            {
                "field_id": path,
                "label": path,
                "evidence_key": "test.fixture",
                "value_path": path,
            }
            for path in ("score", "listening", "reading", "writing", "speaking")
        ],
        allow_unknown=False,
        allow_negative=False,
    )
    question = application.normalize_question_schema(
        generated,
        ["test.fixture"],
        {"test.fixture": score_need},
        {},
    )
    assert question.allow_unknown is True
    assert question.allow_negative is True

    negative = submit(question, [score_need], terminal="known_negative")
    assert negative.parser_calls == 0
    assert negative.evidence[0].key == "test.fixture"
    assert negative.evidence[0].availability == "known_negative"
    assert negative.evidence[0].value is None
    assert negative.missing_slots == []
    assert negative.follow_up_question is None

    unknown = submit(question, [score_need], terminal="unknown")
    assert unknown.parser_calls == 0
    assert unknown.evidence[0].availability == "unknown"
    assert unknown.missing_slots == []
    assert unknown.follow_up_question is None

    zero_need = need("score.zero", "language_score", required_fields=["score"])
    zero_question = application.GapPlannerQuestion(
        question_id="q:score-zero",
        prompt="Provide the numeric score.",
        expected_evidence_keys=["score.zero"],
        control_type="number",
        fields=[
            {
                "field_id": "score",
                "label": "Score",
                "evidence_key": "score.zero",
                "value_path": "score",
            }
        ],
    )
    zero = submit(zero_question, [zero_need], values={"score": 0})
    assert zero.parser_calls == 0
    assert zero.evidence[0].availability == "known"
    assert zero.evidence[0].value == {"score": 0}

    legacy_zero = application.parse_gap_evidence(
        application.GapEvidenceParseRequest(
            question=zero_question.model_copy(update={"control_type": "text_fallback"}),
            evidence_needs=[zero_need],
            answer="0",
        )
    )
    assert legacy_zero.evidence[0].availability == "known"
    assert legacy_zero.evidence[0].value == {"score": 0.0}


def check_deterministic_language_score_forms() -> None:
    for key in ("ielts", "toefl"):
        score_need = need(
            key,
            "language_score",
            required_fields=["score", "listening", "reading", "writing", "speaking"],
            group="language:fixture:alternatives",
            relation="any",
        )
        paths = (
            ("score", "listening", "reading", "writing", "speaking")
            if key == "ielts"
            else ("score", "reading", "listening", "speaking", "writing")
        )
        question = application.GapPlannerQuestion(
            question_id=f"q:{key}:score-form",
            requirement_id="language:fixture",
            prompt=f"Provide {key} scores.",
            expected_evidence_keys=[key],
            allowed_evidence_keys=[key],
            evidence_group="language:fixture:alternatives",
            group_relation="any",
            control_type="number_group",
            fields=[
                {
                    "field_id": f"{key}-{path}",
                    "label": path,
                    "evidence_key": key,
                    "value_path": path,
                }
                for path in paths
            ],
        )
        values = {f"{key}-{path}": 7.5 if key == "ielts" else 25 for path in paths}
        result = submit(question, [score_need], values=values)
        assert result.parser_calls == 0
        assert result.missing_slots == []
        assert result.evidence[0].key == key
        assert result.evidence[0].availability == "known"
        assert set(result.evidence[0].value["subscores"]) == {
            "listening", "reading", "writing", "speaking"
        }

        for terminal in ("known_negative", "unknown"):
            terminal_result = submit(question, [score_need], terminal=terminal)
            assert terminal_result.parser_calls == 0
            assert terminal_result.missing_slots == []
            assert terminal_result.evidence[0].key == key
            assert terminal_result.evidence[0].availability == terminal


def check_language_proof_selector_handoff() -> None:
    group = "language:fixture:alternatives"
    needs = [
        need("ielts", "language_score", required_fields=["score", "listening", "reading", "writing", "speaking"], group=group, relation="any"),
        need("toefl", "language_score", required_fields=["score", "reading", "listening", "speaking", "writing"], group=group, relation="any"),
        need("education.language_medium", "generic", required_fields=["description"], group=group, relation="any"),
    ]
    mixed = application.GapPlannerQuestion(
        question_id="q:language:selector",
        requirement_id="language:0",
        prompt="请选择你可使用的语言证明。",
        expected_evidence_keys=[item.key for item in needs],
        group_relation="any",
        control_type="single_select",
        options=[
            {"value": "ielts", "label": "IELTS", "evidence_key": "ielts"},
            {"value": "toefl", "label": "TOEFL", "evidence_key": "toefl"},
            {"value": "english-medium", "label": "本科教学语言为英语", "evidence_key": "education.language_medium"},
        ],
        fields=[
            {"field_id": "ielts-score", "label": "IELTS 总分", "evidence_key": "ielts", "value_path": "score"},
            {"field_id": "toefl-score", "label": "TOEFL 总分", "evidence_key": "toefl", "value_path": "score"},
            {"field_id": "medium-status", "label": "本科教学语言为英语", "evidence_key": "education.language_medium", "value_path": "status"},
        ],
    )
    normalized = application.normalize_question_schema(
        mixed,
        [item.key for item in needs],
        {item.key: item for item in needs},
        {},
    )
    assert normalized.schema_status == "valid"
    assert normalized.control_type == "single_select"
    assert normalized.group_relation == "any"
    assert normalized.fields == []
    assert {option.evidence_key for option in normalized.options} == {
        "ielts", "toefl", "education.language_medium"
    }
    medium_option = next(option for option in normalized.options if option.evidence_key == "education.language_medium")
    assert medium_option.evidence_value == {"description": "本科教学语言为英语"}
    assert "status" not in medium_option.evidence_value

    medium_result = submit(normalized, needs, selected=["english-medium"])
    assert medium_result.parser_calls == 0
    assert medium_result.missing_slots == []
    assert medium_result.evidence[0].key == "education.language_medium"
    assert medium_result.evidence[0].value == {"description": "本科教学语言为英语"}


def check_backend_academic_question_policy() -> None:
    def planned(requirement_id, needs, relation="all"):
        return application.GapPlannedRequirement(
            requirement_id=requirement_id,
            matchable=True,
            user_matchable=True,
            match_strategy="deterministic",
            evidence_needs=needs,
            constraint=application.GapDeterministicConstraint(relation=relation),
            category="academic",
            requirement="Fixture academic requirement.",
            importance="required",
            requirement_verification_status="official_verified",
            temporal_applicability="undated",
        )

    classification = need(
        "degree_classification", "academic_score",
        required_fields=["description"], group="academic:classification", relation="all",
    )
    classification.value_kind = "categorical"
    questions, covered = application.build_backend_academic_questions(
        [planned("academic:classification", [classification])], {}
    )
    assert covered == {"degree_classification"}
    assert len(questions) == 1
    classification_question = questions[0]
    assert classification_question.control_type == "single_select"
    assert classification_question.fields == []
    assert [option.label for option in classification_question.options] == [
        "First", "2:1 / Upper Second", "2:2 / Lower Second", "Third", "Other"
    ]
    classification_result = submit(
        classification_question, [classification], selected=["upper_second"]
    )
    assert classification_result.parser_calls == 0
    assert classification_result.evidence[0].value == {"description": "2:1"}

    group = "academic:numeric:alternatives"
    gpa = need(
        "gpa", "academic_score", required_fields=["score", "scale"],
        group=group, relation="any",
    )
    average = need(
        "average_score", "academic_score", required_fields=["score", "scale"],
        group=group, relation="any",
    )
    gpa.value_kind = average.value_kind = "numeric"
    numeric_questions, _ = application.build_backend_academic_questions(
        [planned("academic:numeric", [gpa, average], relation="any")], {}
    )
    assert len(numeric_questions) == 1
    numeric = numeric_questions[0]
    assert numeric.control_type == "number_group"
    assert {(field.evidence_key, field.value_path) for field in numeric.fields} == {
        ("gpa", "score"), ("gpa", "scale"),
        ("average_score", "score"), ("average_score", "scale"),
    }
    gpa_only = submit(
        numeric, [gpa, average], values={"gpa-score": 3.7, "gpa-scale": 4.0}
    )
    average_only = submit(
        numeric, [gpa, average],
        values={"average_score-score": 87, "average_score-scale": 100},
    )
    both = submit(
        numeric, [gpa, average],
        values={
            "gpa-score": 3.7, "gpa-scale": 4.0,
            "average_score-score": 87, "average_score-scale": 100,
        },
    )
    assert gpa_only.missing_slots == []
    assert average_only.missing_slots == []
    assert both.missing_slots == []
    assert {item.key for item in both.evidence} == {"gpa", "average_score"}
    empty = submit(numeric, [gpa, average], values={})
    assert empty.evidence == []
    assert all(item.value != 0 for item in empty.evidence)

    mixed_questions, _ = application.build_backend_academic_questions(
        [planned("academic:mixed", [classification, gpa])], {}
    )
    assert {question.control_type for question in mixed_questions} == {
        "single_select", "number_group"
    }
    assert all(
        not (
            "degree_classification" in question.allowed_evidence_keys
            and "gpa" in question.allowed_evidence_keys
        )
        for question in mixed_questions
    )

    single_gpa_questions, _ = application.build_backend_academic_questions(
        [planned("academic:gpa-only", [gpa])], {}
    )
    assert len(single_gpa_questions) == 1
    assert single_gpa_questions[0].allowed_evidence_keys == ["gpa"]
    assert {field.evidence_key for field in single_gpa_questions[0].fields} == {"gpa"}

    known_classification = classification.model_copy(update={"already_known": True})
    known_questions, _ = application.build_backend_academic_questions(
        [planned("academic:known-classification", [known_classification])], {}
    )
    assert known_questions == []
    known_gpa = gpa.model_copy(update={"already_known": True})
    known_any_questions, _ = application.build_backend_academic_questions(
        [planned("academic:known-any", [known_gpa, average], relation="any")], {}
    )
    assert known_any_questions == []


def check_backend_language_question_policy() -> None:
    group = "language:policy:alternatives"
    ielts = need(
        "ielts", "language_score",
        required_fields=["score", "listening", "reading", "writing", "speaking"],
        group=group, relation="any",
    )
    toefl = need(
        "toefl", "language_score",
        required_fields=["score", "listening", "reading", "writing", "speaking"],
        group=group, relation="any",
    )
    medium = need(
        "education.language_medium", "generic",
        required_fields=["description"], group=group, relation="any",
    )
    ielts.proof_kind = "scored_test"
    toefl.proof_kind = "scored_test"
    medium.proof_kind = "medium_of_instruction"
    planned = application.GapPlannedRequirement(
        requirement_id="language:policy",
        matchable=True,
        user_matchable=True,
        match_strategy="deterministic",
        evidence_needs=[ielts, toefl, medium],
        constraint=application.GapDeterministicConstraint(relation="any"),
        category="language",
        requirement="Fixture accepts three language proof branches.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    questions, covered = application.build_backend_language_questions([planned], {})
    assert covered == {"ielts", "toefl", "education.language_medium"}
    assert len(questions) == 1
    selector = questions[0]
    assert selector.control_type == "single_select"
    assert selector.fields == []
    assert selector.group_relation == "any"
    assert [(option.evidence_key, option.label) for option in selector.options] == [
        ("ielts", "IELTS"),
        ("toefl", "TOEFL"),
        ("education.language_medium", "英语授课证明"),
    ]
    medium_result = submit(selector, [ielts, toefl, medium], selected=["education.language_medium"])
    assert medium_result.parser_calls == 0
    assert medium_result.missing_slots == []
    assert medium_result.evidence[0].value == {"description": "英语授课证明"}

    partial = application.UserEvidence(
        evidence_type="language_score",
        key="ielts",
        value={"score": 7.5},
        raw_answer="IELTS overall 7.5",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    partial_questions, partial_covered = application.build_backend_language_questions(
        [planned], {"ielts": partial}
    )
    assert partial_covered == covered
    assert len(partial_questions) == 1
    assert [option.evidence_key for option in partial_questions[0].options] == ["ielts"]
    assert partial_questions[0].expected_evidence_keys == ["ielts"]

    complete = partial.model_copy(
        update={
            "value": {
                "score": 7.5,
                "subscores": {
                    "listening": 7.5,
                    "reading": 7.5,
                    "writing": 7.5,
                    "speaking": 7.5,
                },
            }
        }
    )
    complete_questions, complete_covered = application.build_backend_language_questions(
        [planned], {"ielts": complete}
    )
    assert complete_questions == []
    assert complete_covered == covered

    unsupported = need(
        "language.fixture_certificate", "generic",
        required_fields=["description"], group=group, relation="any",
    )
    unsupported.proof_kind = "certificate"
    unsupported_plan = planned.model_copy(
        update={"evidence_needs": [ielts, unsupported]}
    )
    fallback_questions, fallback_covered = application.build_backend_language_questions(
        [unsupported_plan], {}
    )
    assert fallback_questions == []
    assert fallback_covered == set()


def check_backend_course_question_policy() -> None:
    requirement_id = "courses:policy"
    assert application.course_requirement_item_id(requirement_id, " Calculus ") == (
        application.course_requirement_item_id(requirement_id, "calculus")
    )
    assert application.course_requirement_item_id(requirement_id, "Calculus") != (
        application.course_requirement_item_id("courses:other", "Calculus")
    )
    names = [
        "Calculus",
        "Linear Algebra",
        "Probability and Statistics",
        "Discrete Mathematics",
    ]
    course_items = [
        application.GapCourseRequirement(
            item_id=application.course_requirement_item_id(requirement_id, name),
            evidence_key="courses.math_background",
            course_name=name,
        )
        for name in names
    ]
    item_needs = [
        application.GapEvidenceNeed(
            key=application.course_requirement_evidence_key(item.item_id),
            evidence_type="courses",
            value_kind="boolean",
            label=item.course_name,
            required_fields=["completed"],
            evidence_group=requirement_id,
        )
        for item in course_items
    ]
    credit_need = application.GapEvidenceNeed(
        key="courses.math_total_credits",
        evidence_type="courses",
        value_kind="numeric",
        label="数学相关课程",
        required_fields=["quantity"],
        evidence_group=requirement_id,
        required_quantity=28.5,
        unit="ECTS",
    )
    planned = application.GapPlannedRequirement(
        requirement_id=requirement_id,
        matchable=True,
        user_matchable=True,
        match_strategy="deterministic",
        evidence_needs=[*item_needs, credit_need],
        constraint=application.GapDeterministicConstraint(
            kind="course_credit",
            relation="all",
            options=[
                application.GapConstraintOption(
                    key=credit_need.key,
                    kind="course_credit",
                    required_quantity=28.5,
                    unit="ECTS",
                )
            ],
        ),
        course_requirements=course_items,
        category="course",
        requirement="Four courses and 28.5 ECTS are required.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    questions, covered = application.build_backend_course_questions([planned], {})
    assert len(questions) == 2
    checklist = next(question for question in questions if question.control_type == "boolean_group")
    credit = next(question for question in questions if question.control_type == "number")
    assert len(checklist.fields) == 4
    assert checklist.allow_unknown is False
    assert checklist.allow_negative is False
    answers = {
        checklist.fields[0].field_id: True,
        checklist.fields[1].field_id: True,
        checklist.fields[2].field_id: False,
        checklist.fields[3].field_id: True,
    }
    submitted = submit(checklist, item_needs, values=answers)
    assert submitted.parser_calls == 0
    assert len(submitted.evidence) == 4
    assert [item.value["completed"] for item in submitted.evidence] == [True, True, False, True]
    assert all(item.availability == "known" for item in submitted.evidence)
    assert len({item.value["item_id"] for item in submitted.evidence}) == 4
    assert all(item.value["requirement_id"] == requirement_id for item in submitted.evidence)

    partial = submit(
        checklist,
        item_needs,
        values={checklist.fields[0].field_id: True, checklist.fields[1].field_id: False},
    )
    assert set(partial.missing_slots) == {
        f"{item_needs[2].key}.completed",
        f"{item_needs[3].key}.completed",
    }
    known_item = submitted.evidence[0]
    known_questions, _ = application.build_backend_course_questions(
        [planned], {known_item.key: known_item}
    )
    known_checklist = next(
        question for question in known_questions if question.control_type == "boolean_group"
    )
    assert known_item.key not in known_checklist.expected_evidence_keys
    assert len(known_checklist.fields) == 3

    credit_result = submit(
        credit,
        [credit_need],
        values={credit.fields[0].field_id: 24},
    )
    assert credit_result.parser_calls == 0
    assert credit_result.evidence[0].value == {
        "requirement_id": requirement_id,
        "label": "数学相关课程",
        "quantity": 24.0,
        "unit": "ECTS",
    }
    assert "quantity" not in submitted.evidence[0].value
    partial_status = application.evaluate_deterministic_requirement(
        planned,
        {item.key: item for item in [*submitted.evidence, *credit_result.evidence]},
    )
    assert partial_status[0] == "partial"
    all_completed = [
        item.model_copy(update={"value": {**item.value, "completed": True}})
        for item in submitted.evidence
    ]
    enough_credit = submit(
        credit,
        [credit_need],
        values={credit.fields[0].field_id: 30},
    )
    met_status = application.evaluate_deterministic_requirement(
        planned,
        {item.key: item for item in [*all_completed, *enough_credit.evidence]},
    )
    assert met_status[0] == "met"
    empty_credit = submit(credit, [credit_need], values={})
    assert empty_credit.evidence == []
    credit_known_questions, _ = application.build_backend_course_questions(
        [planned], {credit_need.key: credit_result.evidence[0]}
    )
    assert all(question.control_type != "number" for question in credit_known_questions)

    credit_only = planned.model_copy(
        update={"course_requirements": [], "evidence_needs": [credit_need]}
    )
    credit_only_questions, credit_only_covered = application.build_backend_course_questions(
        [credit_only], {}
    )
    assert len(credit_only_questions) == 1
    assert credit_only_questions[0].control_type == "number"
    assert all(question.control_type != "boolean_group" for question in credit_only_questions)
    assert credit_only_covered == {credit_need.key}
    assert covered.issuperset({need.key for need in item_needs} | {credit_need.key})

    item_with_credit = course_items[0].model_copy(
        update={"minimum_credits": 6, "unit": "ECTS"}
    )
    scoped_credit_need = application.GapEvidenceNeed(
        key=application.course_requirement_credit_evidence_key(item_with_credit.item_id),
        evidence_type="courses",
        value_kind="numeric",
        label=item_with_credit.course_name,
        required_fields=["quantity"],
        evidence_group=requirement_id,
        required_quantity=6,
        unit="ECTS",
    )
    item_credit_plan = planned.model_copy(
        update={
            "course_requirements": [item_with_credit],
            "evidence_needs": [item_needs[0], scoped_credit_need],
            "constraint": application.GapDeterministicConstraint(),
        }
    )
    item_credit_questions, _ = application.build_backend_course_questions(
        [item_credit_plan], {}
    )
    assert {question.control_type for question in item_credit_questions} == {
        "boolean_group", "number"
    }
    item_credit_question = next(
        question for question in item_credit_questions if question.control_type == "number"
    )
    assert item_credit_question.expected_evidence_keys == [scoped_credit_need.key]

    try:
        submit(checklist, item_needs, terminal="unknown")
    except application.HTTPException as error:
        assert error.status_code == 422
    else:
        raise AssertionError("course checklist must not accept unknown terminal state")


def check_backend_gre_question_policy() -> None:
    requirement_id = "standardized_test:gre-policy"
    gre = application.GapEvidenceNeed(
        key="gre",
        evidence_type="standardized_score",
        value_kind="numeric",
        label="GRE",
        required_fields=["verbal", "quantitative", "analytical_writing"],
        evidence_group=requirement_id,
    )
    constraint = application.GapDeterministicConstraint(
        kind="score",
        relation="all",
        options=[
            application.GapConstraintOption(
                key="gre", kind="score", component="quantitative", minimum=165
            )
        ],
    )
    planned = application.GapPlannedRequirement(
        requirement_id=requirement_id,
        matchable=True,
        user_matchable=True,
        match_strategy="deterministic",
        evidence_needs=[gre],
        constraint=constraint,
        category="standardized_test",
        requirement="GRE scores are required.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    questions, covered = application.build_backend_gre_questions([planned], {})
    assert covered == {"gre"}
    assert len(questions) == 1
    form = questions[0]
    assert form.control_type == "number_group"
    assert [field.value_path for field in form.fields] == [
        "verbal", "quantitative", "analytical_writing"
    ]
    submitted = submit(
        form,
        [gre],
        values={
            "gre-verbal": 160,
            "gre-quantitative": 166,
            "gre-analytical_writing": 4.5,
        },
    )
    assert submitted.parser_calls == 0
    assert submitted.evidence[0].value == {
        "verbal": 160.0,
        "quantitative": 166.0,
        "analytical_writing": 4.5,
    }

    partial = application.UserEvidence(
        evidence_type="standardized_score",
        key="gre",
        value={"quantitative": 166},
        raw_answer="Quantitative Reasoning: 166",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    partial_questions, _ = application.build_backend_gre_questions(
        [planned], {"gre": partial}
    )
    assert [field.value_path for field in partial_questions[0].fields] == [
        "verbal", "analytical_writing"
    ]
    full_questions, _ = application.build_backend_gre_questions(
        [planned], {"gre": submitted.evidence[0]}
    )
    assert full_questions == []

    quant_only = gre.model_copy(update={"required_fields": ["quantitative"]})
    quant_plan = planned.model_copy(update={"evidence_needs": [quant_only]})
    quant_questions, _ = application.build_backend_gre_questions([quant_plan], {})
    assert len(quant_questions) == 1
    assert quant_questions[0].control_type == "number"
    assert [field.value_path for field in quant_questions[0].fields] == ["quantitative"]
    untouched = submit(quant_questions[0], [quant_only], values={})
    assert untouched.evidence == []

    met = application.evaluate_deterministic_requirement(
        quant_plan,
        {
            "gre": application.UserEvidence(
                evidence_type="standardized_score",
                key="gre",
                value={"quantitative": 166},
                raw_answer="Quantitative Reasoning: 166",
                availability="known",
                updated_at="2026-08-30T00:00:00Z",
            )
        },
    )
    assert met[0] == "met"
    below = application.evaluate_deterministic_requirement(
        quant_plan,
        {
            "gre": application.UserEvidence(
                evidence_type="standardized_score",
                key="gre",
                value={"quantitative": 164},
                raw_answer="Quantitative Reasoning: 164",
                availability="known",
                updated_at="2026-08-30T00:00:00Z",
            )
        },
    )
    assert below[0] == "not_met"

    gmat = application.GapEvidenceNeed(
        key="gmat",
        evidence_type="standardized_score",
        value_kind="numeric",
        label="GMAT",
        required_fields=["score"],
    )
    gmat_plan = planned.model_copy(update={"evidence_needs": [gmat]})
    gmat_questions, gmat_covered = application.build_backend_gre_questions(
        [gmat_plan], {}
    )
    assert gmat_questions == []
    assert gmat_covered == set()


def check_backend_materials_question_policy() -> None:
    requirement_id = "materials:policy"
    material_needs = []
    for material_type, label in (
        ("cv", "CV"),
        ("transcript", "Transcript"),
        ("personal_statement", "Motivation Letter"),
    ):
        item_id = application.material_policy_item_id(requirement_id, material_type)
        material_needs.append(
            application.GapEvidenceNeed(
                key=application.material_policy_evidence_key(item_id),
                evidence_type="material_status",
                value_kind="boolean",
                label=label,
                required_fields=["status"],
                evidence_group=requirement_id,
                material_type=material_type,
                item_id=item_id,
            )
        )
    recommendation_item_id = application.material_policy_item_id(
        requirement_id, "recommendation_letters"
    )
    recommendation = application.GapEvidenceNeed(
        key=application.material_policy_evidence_key(
            recommendation_item_id, quantity=True
        ),
        evidence_type="material_quantity",
        value_kind="numeric",
        label="Recommendation Letters",
        required_fields=["quantity"],
        evidence_group=requirement_id,
        required_quantity=3,
        unit="letters",
        material_type="recommendation_letters",
        item_id=recommendation_item_id,
    )
    options = [
        application.GapConstraintOption(key=item.key, kind="material_boolean")
        for item in material_needs
    ] + [
        application.GapConstraintOption(
            key=recommendation.key,
            kind="material_quantity",
            required_quantity=3,
            unit="letters",
        )
    ]
    planned = application.GapPlannedRequirement(
        requirement_id=requirement_id,
        matchable=True,
        user_matchable=True,
        match_strategy="deterministic",
        evidence_needs=[*material_needs, recommendation],
        constraint=application.GapDeterministicConstraint(
            kind="none", relation="all", options=options
        ),
        category="materials",
        requirement="CV, transcript, motivation letter, and three recommendations are required.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    questions, covered = application.build_backend_material_questions([planned], {})
    assert covered == {item.key for item in [*material_needs, recommendation]}
    assert [question.control_type for question in questions] == [
        "boolean_group", "number"
    ]
    checklist, count_question = questions
    assert {field.label for field in checklist.fields} == {
        "CV", "Transcript", "Motivation Letter"
    }
    assert checklist.allow_unknown is False
    assert checklist.allow_negative is False
    assert count_question.allow_unknown is False
    assert count_question.allow_negative is False
    assert all("portfolio" not in field.label.casefold() for field in checklist.fields)

    checklist_result = submit(
        checklist,
        [*material_needs, recommendation],
        values={
            material_needs[0].item_id: True,
            material_needs[1].item_id: False,
            material_needs[2].item_id: True,
        },
    )
    assert checklist_result.parser_calls == 0
    assert all(item.availability == "known" for item in checklist_result.evidence)
    values = {item.key: item.value for item in checklist_result.evidence}
    assert values[material_needs[0].key]["available"] is True
    assert values[material_needs[1].key]["available"] is False
    assert all(value["requirement_id"] == requirement_id for value in values.values())

    partial_questions, _ = application.build_backend_material_questions(
        [planned], {material_needs[0].key: checklist_result.evidence[0]}
    )
    partial_checklist = next(
        question for question in partial_questions if question.control_type == "boolean_group"
    )
    assert {field.evidence_key for field in partial_checklist.fields} == {
        material_needs[1].key, material_needs[2].key
    }
    complete_questions, _ = application.build_backend_material_questions(
        [planned], {item.key: item for item in checklist_result.evidence}
    )
    assert all(question.control_type != "boolean_group" for question in complete_questions)

    empty_count = submit(count_question, [*material_needs, recommendation], values={})
    assert empty_count.evidence == []
    count_result = submit(
        count_question,
        [*material_needs, recommendation],
        values={count_question.fields[0].field_id: 2},
    )
    assert count_result.evidence[0].value["quantity"] == 2
    assert count_result.evidence[0].value["material_type"] == "recommendation_letters"
    assert application.evaluate_deterministic_requirement(
        planned,
        {
            **{item.key: item for item in checklist_result.evidence},
            recommendation.key: count_result.evidence[0],
        },
    )[0] != "met"

    preferred_status = application.evaluate_constraint_option(
        options[1],
        "none",
        {material_needs[1].key: checklist_result.evidence[1]},
        "preferred",
    )
    assert preferred_status[0] == "partial"

    special = application.GapEvidenceNeed(
        key="materials.programme_specific_summary_sheet",
        evidence_type="material_status",
        value_kind="boolean",
        label="Programme Summary Sheet",
        required_fields=["status"],
    )
    special_plan = planned.model_copy(
        update={
            "evidence_needs": [special],
            "constraint": application.GapDeterministicConstraint(),
        }
    )
    special_questions, special_covered = application.build_backend_material_questions(
        [special_plan], {}
    )
    assert special_questions == []
    assert special_covered == set()


def check_backend_other_question_policy() -> None:
    requirement_id = "other:policy"
    descriptors = [
        ("Summary Sheet", "boolean", []),
        ("Programme-specific count", "numeric", []),
        ("Selected track", "single_select", ["Track A", "Track B", "Track C"]),
        ("Selected themes", "multi_select", ["Theme A", "Theme B", "Theme C"]),
        ("Application reference number", "short_text", []),
    ]
    other_items = []
    needs = []
    for label, value_kind, options in descriptors:
        item_id = application.other_policy_item_id(requirement_id, label)
        evidence_key = application.other_policy_evidence_key(item_id)
        other_items.append(
            application.GapOtherItem(
                source_evidence_key=f"generic.{item_id}",
                label=label,
                value_kind=value_kind,
                options=options,
                item_id=item_id,
                evidence_key=evidence_key,
            )
        )
        needs.append(
            application.GapEvidenceNeed(
                key=evidence_key,
                evidence_type="generic",
                value_kind=(
                    "boolean" if value_kind == "boolean"
                    else "numeric" if value_kind == "numeric"
                    else "categorical" if value_kind in {"single_select", "multi_select"}
                    else "text"
                ),
                label=label,
                required_fields=[
                    "status" if value_kind == "boolean"
                    else "quantity" if value_kind == "numeric"
                    else "description"
                ],
                evidence_group=requirement_id,
                item_id=item_id,
                other_value_kind=value_kind,
                other_options=options,
            )
        )
    planned = application.GapPlannedRequirement(
        requirement_id=requirement_id,
        matchable=True,
        user_matchable=True,
        match_strategy="semantic",
        evidence_needs=needs,
        other_items=other_items,
        constraint=application.GapDeterministicConstraint(),
        category="other",
        requirement=(
            "Complete the Summary Sheet and provide a programme-specific count. "
            "Select one track: Track A, Track B, or Track C. Select any themes: "
            "Theme A, Theme B, Theme C. Provide the application reference number."
        ),
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    questions, covered = application.build_backend_other_questions([planned], {})
    assert covered == {need.key for need in needs}
    assert [question.control_type for question in questions] == [
        "boolean", "number", "single_select", "multi_select", "short_text"
    ]
    assert all(not question.allow_unknown for question in questions)
    assert all(not question.allow_negative for question in questions)
    assert all(not question.allow_other for question in questions)

    boolean_result = submit(
        questions[0], needs, values={questions[0].fields[0].field_id: False}
    )
    assert boolean_result.parser_calls == 0
    assert boolean_result.evidence[0].availability == "known"
    assert boolean_result.evidence[0].value["value"] is False
    boolean_gap = application.evaluate_constraint_option(
        application.GapConstraintOption(
            key=needs[0].key, kind="material_boolean"
        ),
        "none",
        {needs[0].key: boolean_result.evidence[0]},
        "required",
    )
    assert boolean_gap[0] == "not_met"

    empty_numeric = submit(questions[1], needs, values={})
    assert empty_numeric.evidence == []
    numeric_result = submit(
        questions[1], needs, values={questions[1].fields[0].field_id: 0}
    )
    assert numeric_result.evidence[0].value["value"] == 0
    numeric_gap = application.evaluate_constraint_option(
        application.GapConstraintOption(
            key=needs[1].key,
            kind="material_quantity",
            required_quantity=1,
        ),
        "none",
        {needs[1].key: numeric_result.evidence[0]},
        "required",
    )
    assert numeric_gap[0] == "not_met"

    single_result = submit(
        questions[2], needs, selected=["Track B"]
    )
    assert single_result.evidence[0].value["value"] == "Track B"
    multi_result = submit(
        questions[3], needs, selected=["Theme A", "Theme C"]
    )
    assert multi_result.evidence[0].value["value"] == ["Theme A", "Theme C"]
    text_result = submit(
        questions[4], needs, values={questions[4].fields[0].field_id: "REF-123"}
    )
    assert text_result.parser_calls == 0
    assert text_result.evidence[0].value["value"] == "REF-123"
    empty_text = submit(questions[4], needs, values={})
    assert empty_text.evidence == []

    known_questions, _ = application.build_backend_other_questions(
        [planned],
        {
            boolean_result.evidence[0].key: boolean_result.evidence[0],
            numeric_result.evidence[0].key: numeric_result.evidence[0],
            single_result.evidence[0].key: single_result.evidence[0],
            multi_result.evidence[0].key: multi_result.evidence[0],
            text_result.evidence[0].key: text_result.evidence[0],
        },
    )
    assert known_questions == []

    source_need = application.GapEvidenceNeed(
        key="generic.track",
        evidence_type="generic",
        value_kind="categorical",
        label="Track",
    )
    unsupported = application.normalize_other_descriptors(
        "other:unsupported",
        "Select one track: Track A or Track B.",
        [
            application.GapOtherEvidenceDescriptor(
                source_evidence_key="generic.track",
                label="Track",
                value_kind="single_select",
                options=["Track A", "Invented Track"],
            )
        ],
        [source_need],
    )
    assert unsupported == []
    malformed = application.GapPlannerLLMOutput.model_validate(
        {
            "requirements": [
                {
                    "requirement_id": "other:unsupported",
                    "matchable": True,
                    "other_items": [
                        {
                            "source_evidence_key": "generic.track",
                            "label": "Track",
                            "value_kind": "unsupported_widget",
                        }
                    ],
                }
            ]
        }
    )
    assert malformed.requirements[0].other_items == []

    fallback_plan = planned.model_copy(update={"other_items": []})
    fallback_questions, fallback_covered = application.build_backend_other_questions(
        [fallback_plan], {}
    )
    assert fallback_questions == []
    assert fallback_covered == set()


def check_backend_experience_question_policy() -> None:
    requirement_id = "experience:policy"
    experience = application.GapEvidenceNeed(
        key="experience",
        evidence_type="experience",
        value_kind="text",
        label="相关经验",
        required_fields=["has_experience", "experience_types", "duration", "unit"],
        evidence_group=requirement_id,
    )
    planned = application.GapPlannedRequirement(
        requirement_id=requirement_id,
        matchable=True,
        user_matchable=True,
        match_strategy="semantic",
        evidence_needs=[experience],
        constraint=application.GapDeterministicConstraint(),
        category="experience",
        requirement="Relevant experience is preferred.",
        importance="preferred",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    questions, covered = application.build_backend_experience_questions([planned], {})
    assert covered == {"experience"}
    assert len(questions) == 1
    form = questions[0]
    assert form.control_type == "experience_form"
    assert form.allow_unknown is False
    assert form.allow_negative is False
    assert {option.value for option in form.options} == {
        "experience:work", "experience:internship", "experience:research",
        "experience:project", "experience:other", "experience:none",
        "unit:months", "unit:years",
    }
    result = submit(
        form,
        [experience],
        selected=["experience:research", "experience:internship", "unit:months"],
        values={"experience-duration": 18},
    )
    assert result.parser_calls == 0
    assert result.evidence[0].value == {
        "requirement_id": requirement_id,
        "has_experience": True,
        "experience_types": ["research", "internship"],
        "duration": {"quantity": 18.0, "unit": "months"},
    }
    none_result = submit(
        form, [experience], selected=["experience:none"]
    )
    assert none_result.evidence[0].availability == "known"
    assert none_result.evidence[0].value == {
        "requirement_id": requirement_id,
        "has_experience": False,
        "experience_types": [],
        "duration": None,
    }
    assert none_result.missing_slots == []
    try:
        submit(
            form,
            [experience],
            selected=["experience:none", "experience:research"],
        )
    except application.HTTPException as error:
        assert error.status_code == 422
    else:
        raise AssertionError("no experience must be mutually exclusive")

    types_only = application.UserEvidence(
        evidence_type="experience",
        key="experience",
        value={
            "requirement_id": requirement_id,
            "has_experience": True,
            "experience_types": ["research"],
            "duration": None,
        },
        raw_answer="研究经历",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    duration_questions, _ = application.build_backend_experience_questions(
        [planned], {"experience": types_only}
    )
    duration_form = duration_questions[0]
    assert duration_form.fields[0].field_id == "experience-duration"
    assert all(not option.value.startswith("experience:") for option in duration_form.options)

    duration_only = application.UserEvidence(
        evidence_type="experience",
        key="experience",
        value={
            "requirement_id": requirement_id,
            "duration": {"quantity": 18, "unit": "months"},
        },
        raw_answer="18 months",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    type_questions, _ = application.build_backend_experience_questions(
        [planned], {"experience": duration_only}
    )
    type_form = type_questions[0]
    assert type_form.fields == []
    assert all(not option.value.startswith("unit:") for option in type_form.options)
    complete_questions, _ = application.build_backend_experience_questions(
        [planned], {"experience": result.evidence[0]}
    )
    assert complete_questions == []

    no_threshold = application.evaluate_deterministic_requirement(
        planned, {"experience": none_result.evidence[0]}
    )
    assert no_threshold[0] == "unknown"

    threshold_plan = planned.model_copy(
        update={
            "importance": "required",
            "match_strategy": "hybrid",
            "constraint": application.GapDeterministicConstraint(
                kind="experience_duration",
                options=[
                    application.GapConstraintOption(
                        key="experience",
                        kind="experience_duration",
                        required_quantity=2,
                        unit="years",
                    )
                ],
            ),
        }
    )
    below = application.evaluate_deterministic_requirement(
        threshold_plan, {"experience": result.evidence[0]}
    )
    assert below[0] == "not_met"
    two_years = result.evidence[0].model_copy(
        update={
            "value": {
                **result.evidence[0].value,
                "duration": {"quantity": 24, "unit": "months"},
            }
        }
    )
    met = application.evaluate_deterministic_requirement(
        threshold_plan, {"experience": two_years}
    )
    assert met[0] == "met"


async def check_backend_academic_policy_overrides_llm_question() -> None:
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
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "academic:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "degree_classification",
                                "evidence_type": "academic_score",
                                "value_kind": "categorical",
                                "label": "学位等级",
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
                        "question_id": "q:wrong-numeric-classification",
                        "requirement_id": "academic:0",
                        "prompt": "请输入学位等级数值。",
                        "expected_evidence_keys": ["degree_classification"],
                        "control_type": "number",
                        "fields": [
                            {
                                "field_id": "wrong-score",
                                "label": "学位等级",
                                "evidence_key": "degree_classification",
                                "value_path": "score",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(target_program=TARGET, requirements_review=review)
        )
    finally:
        application.call_deepseek = original
    assert len(plan.questions) == 1
    assert plan.questions[0].question_id.startswith("policy:")
    assert plan.questions[0].control_type == "single_select"
    assert plan.questions[0].allowed_evidence_keys == ["degree_classification"]


async def check_backend_language_policy_overrides_llm_question() -> None:
    requirement = application.RequirementItem(
        category="language",
        requirement="IELTS or TOEFL is accepted.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
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
                                "proof_kind": "scored_test",
                                "label": "IELTS",
                            },
                            {
                                "key": "toefl",
                                "evidence_type": "language_score",
                                "value_kind": "numeric",
                                "proof_kind": "scored_test",
                                "label": "TOEFL",
                            },
                        ],
                        "constraint": {
                            "kind": "score",
                            "relation": "any",
                            "options": [
                                {"key": "ielts", "kind": "score", "minimum": 7},
                                {"key": "toefl", "kind": "score", "minimum": 100},
                            ],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:llm-language-scores",
                        "requirement_id": "language:0",
                        "prompt": "Enter both test scores.",
                        "expected_evidence_keys": ["ielts", "toefl"],
                        "control_type": "number_group",
                        "fields": [
                            {
                                "field_id": "ielts-score",
                                "label": "IELTS score",
                                "evidence_key": "ielts",
                                "value_path": "score",
                            },
                            {
                                "field_id": "toefl-score",
                                "label": "TOEFL score",
                                "evidence_key": "toefl",
                                "value_path": "score",
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(target_program=TARGET, requirements_review=review)
        )
    finally:
        application.call_deepseek = original
    assert len(plan.questions) == 1
    selector = plan.questions[0]
    assert selector.question_id.startswith("policy:")
    assert selector.control_type == "single_select"
    assert selector.fields == []
    assert {option.evidence_key for option in selector.options} == {"ielts", "toefl"}
    assert all(question.question_id != "q:llm-language-scores" for question in plan.questions)


async def check_backend_course_policy_overrides_llm_question() -> None:
    requirement = application.RequirementItem(
        category="course",
        requirement="Calculus and Linear Algebra plus 22.5 ECTS are required.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "course:0",
                        "matchable": True,
                        "match_strategy": "semantic",
                        "evidence_needs": [
                            {
                                "key": "courses.math_background",
                                "evidence_type": "courses",
                                "value_kind": "text",
                                "label": "Mathematics background",
                            },
                            {
                                "key": "courses.math_total_credits",
                                "evidence_type": "courses",
                                "value_kind": "numeric",
                                "label": "Mathematics credits",
                            },
                        ],
                        "constraint": {
                            "kind": "course_credit",
                            "relation": "all",
                            "options": [
                                {
                                    "key": "courses.math_total_credits",
                                    "kind": "course_credit",
                                    "required_quantity": 22.5,
                                    "unit": "ECTS",
                                }
                            ],
                        },
                        "course_requirements": [
                            {"evidence_key": "courses.math_background", "course_name": "Calculus"},
                            {"evidence_key": "courses.math_background", "course_name": "Linear Algebra"},
                        ],
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:llm-generic-courses",
                        "requirement_id": "course:0",
                        "prompt": "Describe your courses and credits.",
                        "expected_evidence_keys": [
                            "courses.math_background", "courses.math_total_credits"
                        ],
                        "control_type": "number_group",
                        "fields": [
                            {
                                "field_id": "llm-credit",
                                "label": "Credits",
                                "evidence_key": "courses.math_total_credits",
                                "value_path": "quantity",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(target_program=TARGET, requirements_review=review)
        )
    finally:
        application.call_deepseek = original
    assert plan.requirements[0].match_strategy == "deterministic"
    assert {question.control_type for question in plan.questions} == {
        "boolean_group", "number"
    }
    assert all(question.question_id.startswith("policy:") for question in plan.questions)
    assert all(question.question_id != "q:llm-generic-courses" for question in plan.questions)


async def check_backend_gre_policy_overrides_llm_question() -> None:
    requirement = application.RequirementItem(
        category="standardized_test",
        requirement="GRE Quantitative Reasoning of at least 165 is required.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "standardized_test:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "gre",
                                "evidence_type": "standardized_score",
                                "value_kind": "numeric",
                                "label": "GRE",
                            }
                        ],
                        "constraint": {
                            "kind": "score",
                            "relation": "all",
                            "options": [
                                {
                                    "key": "gre",
                                    "kind": "score",
                                    "component": "quantitative",
                                    "minimum": 165,
                                }
                            ],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:llm-custom-gre",
                        "requirement_id": "standardized_test:0",
                        "prompt": "Enter a GRE total score.",
                        "expected_evidence_keys": ["gre"],
                        "control_type": "number",
                        "fields": [
                            {
                                "field_id": "gre-total",
                                "label": "GRE total",
                                "evidence_key": "gre",
                                "value_path": "score",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(target_program=TARGET, requirements_review=review)
        )
    finally:
        application.call_deepseek = original
    assert len(plan.questions) == 1
    question = plan.questions[0]
    assert question.question_id.startswith("policy:")
    assert question.control_type == "number"
    assert [field.value_path for field in question.fields] == ["quantitative"]
    assert all(item.question_id != "q:llm-custom-gre" for item in plan.questions)


async def check_backend_experience_policy_overrides_llm_question() -> None:
    requirement = application.RequirementItem(
        category="experience",
        requirement="Relevant professional or research experience is preferred.",
        importance="preferred",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "experience:0",
                        "matchable": True,
                        "match_strategy": "semantic",
                        "evidence_needs": [
                            {
                                "key": "experience.relevant_projects",
                                "evidence_type": "experience",
                                "value_kind": "text",
                                "label": "Relevant experience",
                            }
                        ],
                        "constraint": {"kind": "none", "relation": "all", "options": []},
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:llm-generic-experience",
                        "requirement_id": "experience:0",
                        "prompt": "Describe and rate your experience.",
                        "expected_evidence_keys": ["experience.relevant_projects"],
                        "control_type": "multi_select",
                        "options": [
                            {
                                "value": "strong",
                                "label": "Strong",
                                "evidence_key": "experience.relevant_projects",
                                "evidence_value": {"description": "strong"},
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(target_program=TARGET, requirements_review=review)
        )
    finally:
        application.call_deepseek = original
    assert len(plan.questions) == 1
    question = plan.questions[0]
    assert question.question_id.startswith("policy:")
    assert question.control_type == "experience_form"
    assert question.allowed_evidence_keys == ["experience"]
    assert all(item.question_id != "q:llm-generic-experience" for item in plan.questions)
    assert plan.planning_llm_requests == 1


async def check_backend_other_policy_overrides_llm_question() -> None:
    requirement = application.RequirementItem(
        category="other",
        requirement="Applicants must complete the programme Summary Sheet.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "other:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "generic.summary_sheet",
                                "evidence_type": "generic",
                                "value_kind": "boolean",
                                "label": "Summary Sheet",
                            }
                        ],
                        "constraint": {
                            "kind": "material_boolean",
                            "relation": "all",
                            "options": [
                                {
                                    "key": "generic.summary_sheet",
                                    "kind": "material_boolean",
                                }
                            ],
                        },
                        "other_items": [
                            {
                                "source_evidence_key": "generic.summary_sheet",
                                "label": "Summary Sheet",
                                "value_kind": "boolean",
                                "options": [],
                            }
                        ],
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:llm-summary-sheet",
                        "requirement_id": "other:0",
                        "prompt": "Describe the Summary Sheet.",
                        "expected_evidence_keys": ["generic.summary_sheet"],
                        "control_type": "single_select",
                        "options": [
                            {
                                "value": "done",
                                "label": "Done",
                                "evidence_key": "generic.summary_sheet",
                                "evidence_value": {"description": "done"},
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(target_program=TARGET, requirements_review=review)
        )
    finally:
        application.call_deepseek = original
    assert len(plan.questions) == 1
    question = plan.questions[0]
    assert question.question_id.startswith("policy:")
    assert question.control_type == "boolean"
    assert all(item.question_id != "q:llm-summary-sheet" for item in plan.questions)
    assert len(plan.requirements[0].other_items) == 1
    assert plan.requirements[0].evidence_needs[0].key.startswith("other_item.")


def check_dynamic_multi_select() -> None:
    courses = need("courses.fixture", "courses", required_fields=["description"])
    question = application.GapPlannerQuestion(
        question_id="q:courses",
        prompt="请选择 Requirement 中列出的已修项目。",
        expected_evidence_keys=["courses.fixture"],
        control_type="multi_select",
        options=[
            {"value": "topic-a", "label": "Topic A", "evidence_key": "courses.fixture"},
            {"value": "topic-b", "label": "Topic B", "evidence_key": "courses.fixture"},
            {"value": "topic-c", "label": "Topic C", "evidence_key": "courses.fixture"},
        ],
        validation={"min_selections": 1},
    )
    result = submit(question, [courses], selected=["topic-a", "topic-c"])
    assert result.parser_calls == 0
    assert result.evidence[0].value["selected_values"] == ["topic-a", "topic-c"]
    assert result.missing_slots == []


def check_any_and_all_groups() -> None:
    any_needs = [
        need("alternative.a", "academic_score", required_fields=["description"], group="g:any", relation="any"),
        need("alternative.b", "academic_score", required_fields=["description"], group="g:any", relation="any"),
    ]
    any_question = application.GapPlannerQuestion(
        question_id="q:any",
        prompt="请选择可提供的替代证据。",
        expected_evidence_keys=["alternative.a", "alternative.b"],
        group_relation="any",
        control_type="single_select",
        options=[
            {"value": "a", "label": "Alternative A", "evidence_key": "alternative.a", "evidence_value": {"description": "A"}},
            {"value": "b", "label": "Alternative B", "evidence_key": "alternative.b", "evidence_value": {"description": "B"}},
        ],
    )
    any_result = submit(any_question, any_needs, selected=["a"])
    assert any_result.missing_slots == []
    assert any_result.satisfied_evidence_groups == ["g:any"]

    all_needs = [
        need("material.a", "material_status", required_fields=["status"], group="g:all"),
        need("material.b", "material_status", required_fields=["status"], group="g:all"),
    ]
    existing = application.UserEvidence(
        evidence_type="material_status",
        key="material.a",
        value={"status": True},
        raw_answer="A ready",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    all_question = application.GapPlannerQuestion(
        question_id="q:all",
        prompt="请补充仍缺失的字段。",
        expected_evidence_keys=["material.b"],
        group_relation="all",
        control_type="boolean",
        fields=[
            {"field_id": "b", "label": "Material B", "evidence_key": "material.b", "value_path": "status"}
        ],
    )
    all_result = submit(all_question, all_needs, values={"b": True}, existing=[existing])
    assert all_result.missing_slots == []

    partial_need = need(
        "numeric.partial",
        "language_score",
        required_fields=["score", "listening"],
    )
    partial_existing = application.UserEvidence(
        evidence_type="language_score",
        key="numeric.partial",
        value={"score": 7.5},
        raw_answer="overall 7.5",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    generated = application.GapPlannerQuestion(
        question_id="q:partial",
        prompt="补充缺失数值。",
        expected_evidence_keys=["numeric.partial"],
        control_type="number_group",
        fields=[
            {"field_id": "overall", "label": "Overall", "evidence_key": "numeric.partial", "value_path": "score"},
            {"field_id": "listening", "label": "Listening", "evidence_key": "numeric.partial", "value_path": "listening"},
        ],
    )
    normalized = application.normalize_question_schema(
        generated,
        ["numeric.partial"],
        {"numeric.partial": partial_need},
        {"numeric.partial": partial_existing},
    )
    assert [field.field_id for field in normalized.fields] == ["listening"]


def check_schema_satisfiability_and_any_convergence() -> None:
    all_needs = [
        need("all.a", "generic", required_fields=["description"], group="fixture:all", relation="all"),
        need("all.b", "generic", required_fields=["description"], group="fixture:all", relation="all"),
    ]
    incomplete_all = application.GapPlannerQuestion(
        question_id="q:incomplete-all",
        prompt="Complete both branches.",
        expected_evidence_keys=["all.a"],
        control_type="single_select",
        options=[
            {
                "value": "a",
                "label": "A",
                "evidence_key": "all.a",
                "evidence_value": {"description": "A"},
            }
        ],
    )
    rejected = application.normalize_question_schema(
        incomplete_all,
        ["all.a", "all.b"],
        {item.key: item for item in all_needs},
        {},
    )
    assert rejected.control_type == "single_select"
    assert rejected.schema_status == "invalid"
    assert rejected.schema_error_code == "unsatisfied_required_slots"
    assert rejected.allowed_evidence_keys == ["all.a", "all.b"]

    any_needs = [
        need("any.a", "generic", required_fields=["description"], group="fixture:any", relation="any"),
        need("any.b", "generic", required_fields=["description"], group="fixture:any", relation="any"),
    ]
    one_branch = application.GapPlannerQuestion(
        question_id="q:one-any-branch",
        prompt="Choose one accepted branch.",
        expected_evidence_keys=["any.a"],
        control_type="single_select",
        options=[
            {
                "value": "a",
                "label": "A",
                "evidence_key": "any.a",
                "evidence_value": {"description": "A"},
            }
        ],
    )
    normalized = application.normalize_question_schema(
        one_branch,
        ["any.a", "any.b"],
        {item.key: item for item in any_needs},
        {},
    )
    assert normalized.control_type == "single_select"
    assert normalized.group_relation == "any"
    assert normalized.allowed_evidence_keys == ["any.a", "any.b"]
    result = submit(normalized, any_needs, selected=["a"])
    assert result.missing_slots == []
    assert result.satisfied_evidence_groups == ["fixture:any"]

    sibling_follow_up = normalized.model_copy(
        update={
            "evidence_keys": ["any.b"],
            "expected_evidence_keys": ["any.b"],
        }
    )
    terminal_result = submit(
        sibling_follow_up,
        any_needs,
        terminal="known_negative",
    )
    assert terminal_result.evidence[0].key == "any.b"
    assert terminal_result.evidence[0].availability == "known_negative"
    assert terminal_result.missing_slots == ["any.a.description"]


def check_terminal_and_text_fallback() -> None:
    evidence_need = need("fixture.unknown", "generic", required_fields=["description"])
    question = application.GapPlannerQuestion(
        question_id="q:terminal",
        prompt="请选择状态。",
        expected_evidence_keys=["fixture.unknown"],
        control_type="single_select",
        options=[
            {"value": "known", "label": "Known", "evidence_key": "fixture.unknown"}
        ],
        allow_unknown=True,
    )
    for terminal in ("unknown", "known_negative"):
        result = submit(question, [evidence_need], terminal=terminal)
        assert result.parser_calls == 0
        assert result.missing_slots == []
        assert result.evidence[0].availability == terminal

    negative_disabled = question.model_copy(update={"allow_negative": False})
    try:
        submit(negative_disabled, [evidence_need], terminal="known_negative")
    except application.HTTPException as error:
        assert error.status_code == 422
    else:
        raise AssertionError("known_negative must respect allow_negative")

    fallback = application.GapPlannerQuestion(
        question_id="q:fallback",
        prompt="请补充说明。",
        expected_evidence_keys=["fixture.unknown"],
        control_type="text_fallback",
    )
    parsed = application.parse_gap_evidence(
        application.GapEvidenceParseRequest(
            question=fallback,
            evidence_needs=[evidence_need],
            answer="自由文本 fixture",
        )
    )
    assert parsed.parser_calls == 1
    assert parsed.evidence[0].availability == "known"


async def check_planner_schema_and_safety() -> None:
    requirement = application.RequirementItem(
        category="materials",
        requirement="A reflective diary is required.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    calls = 0
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "materials:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {"key": "materials.reflective_diary", "evidence_type": "material_status", "label": "Reflective diary"}
                        ],
                        "constraint": {
                            "kind": "material_boolean",
                            "options": [{"key": "materials.reflective_diary", "kind": "material_boolean"}],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:diary",
                        "prompt": "你是否已经准备好 reflective diary？",
                        "expected_evidence_keys": ["materials.reflective_diary"],
                        "control_type": "boolean",
                        "fields": [
                            {"field_id": "ready", "label": "准备状态", "evidence_key": "materials.reflective_diary", "value_path": "status"}
                        ],
                        "allow_unknown": True,
                        "allow_other": True,
                    }
                ],
            }
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
    assert plan.planning_llm_requests == 1
    assert plan.questions[0].control_type == "boolean"

    invalid_question = application.GapPlannerQuestion(
        question_id="q:invalid",
        prompt="Invalid schema",
        expected_evidence_keys=["materials.reflective_diary"],
        control_type="number",
        fields=[
            {"field_id": "invented", "label": "Invented threshold", "evidence_key": "invented.hard_requirement", "value_path": "score"}
        ],
    )
    normalized = application.normalize_question_schema(
        invalid_question,
        ["materials.reflective_diary"],
        {plan.requirements[0].evidence_needs[0].key: plan.requirements[0].evidence_needs[0]},
        {},
    )
    assert normalized.control_type == "number"
    assert normalized.schema_status == "invalid"
    assert normalized.schema_error_code == "invalid_evidence_key"
    assert normalized.allowed_evidence_keys == ["materials.reflective_diary"]

    for availability in ("known", "known_negative", "unknown"):
        existing = application.UserEvidence(
            evidence_type="material_status",
            key="materials.reflective_diary",
            value={"status": True} if availability == "known" else None,
            raw_answer=availability,
            availability=availability,
            updated_at="2026-08-30T00:00:00Z",
        )
        application.call_deepseek = fake_deepseek
        try:
            reused_plan = await application.build_gap_plan(
                application.GapPlanRequest(
                    target_program=TARGET,
                    requirements_review=review,
                    user_evidence=[existing],
                )
            )
        finally:
            application.call_deepseek = original
        assert reused_plan.questions == []


async def check_planner_categorical_academic_path() -> None:
    requirement = application.RequirementItem(
        category="academic",
        requirement="A recognized degree classification or a numeric grade is accepted.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "academic:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "degree_classification",
                                "evidence_type": "academic_score",
                                "label": "学位等级",
                            },
                            {
                                "key": "gpa",
                                "evidence_type": "academic_score",
                                "label": "GPA",
                            },
                        ],
                        "constraint": {
                            "kind": "score",
                            "relation": "any",
                            "options": [
                                {"key": "degree_classification", "kind": "none"},
                                {"key": "gpa", "kind": "score", "minimum": 3.5},
                            ],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:academic",
                        "prompt": "请选择符合你的学位等级。",
                        "expected_evidence_keys": ["degree_classification"],
                        "control_type": "single_select",
                        "options": [
                            {
                                "value": "fixture-level",
                                "label": "Fixture Level",
                                "evidence_key": "degree_classification",
                                "evidence_value": {"description": "Fixture Level"},
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
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
    needs = {need.key: need for need in plan.requirements[0].evidence_needs}
    assert needs["degree_classification"].required_fields == ["description"]
    assert needs["gpa"].required_fields == ["score", "scale"]
    assert plan.questions[0].control_type == "single_select"
    assert plan.questions[0].schema_status == "valid"


async def check_questions_do_not_cross_requirement_boundaries() -> None:
    requirements = [
        application.RequirementItem(
            category="academic",
            requirement="The applicant must provide their prior field of study.",
            importance="required",
            source_level="program",
            source_type="official_retrieval",
            verification_status="official_verified",
            source_url="https://example.edu/programme",
            temporal_applicability="undated",
        ),
        application.RequirementItem(
            category="language",
            requirement="One accepted language test is required.",
            importance="required",
            source_level="program",
            source_type="official_retrieval",
            verification_status="official_verified",
            source_url="https://example.edu/programme",
            temporal_applicability="undated",
        ),
        application.RequirementItem(
            category="materials",
            requirement="A specified quantity of supporting material is required.",
            importance="required",
            source_level="program",
            source_type="official_retrieval",
            verification_status="official_verified",
            source_url="https://example.edu/programme",
            temporal_applicability="undated",
        ),
        application.RequirementItem(
            category="experience",
            requirement="Relevant experience information is requested.",
            importance="required",
            source_level="program",
            source_type="official_retrieval",
            verification_status="official_verified",
            source_url="https://example.edu/programme",
            temporal_applicability="undated",
        ),
        application.RequirementItem(
            category="academic",
            requirement="A recognized classification or numeric grade is accepted.",
            importance="required",
            source_level="program",
            source_type="official_retrieval",
            verification_status="official_verified",
            source_url="https://example.edu/programme",
            temporal_applicability="undated",
        ),
    ]
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=requirements),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "academic:0",
                        "matchable": True,
                        "match_strategy": "semantic",
                        "evidence_needs": [
                            {
                                "key": "education.major",
                                "evidence_type": "education_major",
                                "label": "本科专业",
                            }
                        ],
                    },
                    {
                        "requirement_id": "academic:1",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "degree_classification",
                                "evidence_type": "academic_score",
                                "label": "学位等级",
                            },
                            {
                                "key": "gpa",
                                "evidence_type": "academic_score",
                                "label": "GPA",
                            },
                        ],
                        "constraint": {
                            "kind": "score",
                            "relation": "any",
                            "options": [
                                {"key": "degree_classification", "kind": "none"},
                                {"key": "gpa", "kind": "score"},
                            ],
                        },
                    },
                    {
                        "requirement_id": "language:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "ielts",
                                "evidence_type": "language_score",
                                "label": "IELTS",
                            },
                            {
                                "key": "toefl",
                                "evidence_type": "language_score",
                                "label": "TOEFL",
                            },
                        ],
                        "constraint": {
                            "kind": "score",
                            "relation": "any",
                            "options": [
                                {"key": "ielts", "kind": "score"},
                                {"key": "toefl", "kind": "score"},
                            ],
                        },
                    },
                    {
                        "requirement_id": "materials:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "materials.fixture_quantity",
                                "evidence_type": "material_quantity",
                                "label": "材料数量",
                            }
                        ],
                        "constraint": {
                            "kind": "material_quantity",
                            "options": [
                                {
                                    "key": "materials.fixture_quantity",
                                    "kind": "material_quantity",
                                    "required_quantity": 2,
                                }
                            ],
                        },
                    },
                    {
                        "requirement_id": "experience:0",
                        "matchable": True,
                        "match_strategy": "semantic",
                        "evidence_needs": [
                            {
                                "key": "experience",
                                "evidence_type": "experience",
                                "label": "相关经历",
                            }
                        ],
                    },
                ],
                "questions": [
                    {
                        "question_id": "q:mixed-academic-category",
                        "prompt": "请提供本科专业和成绩信息。",
                        "expected_evidence_keys": [
                            "education.major",
                            "degree_classification",
                        ],
                        "control_type": "single_select",
                        "options": [
                            {
                                "value": "fixture-major",
                                "label": "Fixture Major",
                                "evidence_key": "education.major",
                                "evidence_value": {"description": "Fixture Major"},
                            },
                            {
                                "value": "fixture-level",
                                "label": "Fixture Level",
                                "evidence_key": "degree_classification",
                                "evidence_value": {"description": "Fixture Level"},
                            },
                        ],
                    },
                    {
                        "question_id": "q:mixed-numeric-and-unbound",
                        "prompt": "请补充语言、材料和经历信息。",
                        "expected_evidence_keys": [
                            "ielts",
                            "materials.fixture_quantity",
                            "experience",
                        ],
                        "control_type": "number_group",
                        "fields": [
                            {
                                "field_id": "ielts-score",
                                "label": "IELTS",
                                "evidence_key": "ielts",
                                "value_path": "score",
                            },
                            {
                                "field_id": "fixture-quantity",
                                "label": "数量",
                                "evidence_key": "materials.fixture_quantity",
                                "value_path": "quantity",
                            },
                        ],
                    },
                ],
            },
            ensure_ascii=False,
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

    questions_by_requirement = {}
    for question in plan.questions:
        questions_by_requirement.setdefault(question.requirement_id, []).append(question)
    assert set(questions_by_requirement) == {
        "academic:0",
        "academic:1",
        "language:0",
        "materials:0",
        "experience:0",
    }
    question_by_requirement = {
        requirement_id: questions[0]
        for requirement_id, questions in questions_by_requirement.items()
        if requirement_id != "academic:1"
    }
    assert set(question_by_requirement["academic:0"].allowed_evidence_keys) == {"education.major"}
    academic_policy_questions = questions_by_requirement["academic:1"]
    assert {
        key
        for question in academic_policy_questions
        for key in question.allowed_evidence_keys
    } == {
        "degree_classification",
        "gpa",
    }
    assert question_by_requirement["academic:0"].group_relation == "all"
    assert all(question.group_relation == "any" for question in academic_policy_questions)
    assert question_by_requirement["academic:0"].control_type == "single_select"
    assert {question.control_type for question in academic_policy_questions} == {
        "single_select", "number_group"
    }
    assert len(question_by_requirement["academic:0"].options) == 1
    assert len(next(question for question in academic_policy_questions if question.control_type == "single_select").options) == 5
    assert question_by_requirement["language:0"].control_type == "single_select"
    assert question_by_requirement["language:0"].fields == []
    assert {option.evidence_key for option in question_by_requirement["language:0"].options} == {
        "ielts", "toefl"
    }
    assert question_by_requirement["language:0"].group_relation == "any"
    assert question_by_requirement["materials:0"].control_type == "number_group"
    assert [field.field_id for field in question_by_requirement["materials:0"].fields] == ["fixture-quantity"]
    assert question_by_requirement["experience:0"].control_type == "experience_form"
    assert question_by_requirement["academic:0"].prompt == "你的本科专业是什么？"
    for question in plan.questions:
        assert "requirement" not in question.prompt.casefold()
        assert question.requirement_id not in question.prompt
        assert all(key not in question.prompt for key in question.allowed_evidence_keys)
    assert question_by_requirement["experience:0"].schema_status == "valid"
    assert question_by_requirement["experience:0"].question_id.startswith("policy:")
    assert plan.requirements[0].evidence_needs[0].evidence_group == "academic:0"
    assert {
        need.evidence_group for need in plan.requirements[1].evidence_needs
    } == {"academic:1:alternatives"}
    assert all(
        not (
            "education.major" in question.allowed_evidence_keys
            and "degree_classification" in question.allowed_evidence_keys
        )
        for question in plan.questions
    )


async def check_structured_only_repair_contract() -> None:
    evidence_need = need(
        "education.major",
        "education_major",
        required_fields=["description"],
        group="academic:0",
    )
    requirement = application.GapPlannedRequirement(
        requirement_id="academic:0",
        matchable=True,
        user_matchable=True,
        match_strategy="semantic",
        evidence_needs=[evidence_need],
        category="academic",
        requirement="A prior field of study is required.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    valid = application.GapPlannerQuestion(
        question_id="q:major:valid",
        requirement_id="academic:0",
        prompt="请选择你的本科专业。",
        expected_evidence_keys=["education.major"],
        allowed_evidence_keys=["education.major"],
        evidence_group="academic:0",
        control_type="single_select",
        options=[
            {
                "value": "fixture-major",
                "label": "Fixture Major",
                "evidence_key": "education.major",
                "evidence_value": {"description": "Fixture Major"},
            }
        ],
    )
    original = application.call_deepseek

    async def unexpected_call(*args, **kwargs):
        raise AssertionError("valid schema must not invoke repair")

    application.call_deepseek = unexpected_call
    try:
        unchanged, calls = await application.repair_gap_questions_once(
            [valid],
            {"academic:0": requirement},
            {},
        )
    finally:
        application.call_deepseek = original
    assert calls == 0
    assert unchanged[0].control_type == "single_select"

    invalid = application.missing_structured_question(
        requirement,
        [evidence_need],
        prompt="请选择你的本科专业。",
    ).model_copy(update={"question_id": "q:major:repair"})
    assert invalid.schema_status == "invalid"
    assert invalid.control_type != "text_fallback"
    assert invalid.generation_diagnostics.initial_failure_stage == "initial_schema_missing"
    assert invalid.generation_diagnostics.initial_schema is None
    repair_calls = 0

    async def valid_repair(*args, **kwargs):
        nonlocal repair_calls
        repair_calls += 1
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "q:major:repair",
                        "requirement_id": "academic:0",
                        "prompt": "请选择你的本科专业。",
                        "expected_evidence_keys": ["education.major"],
                        "control_type": "single_select",
                        "options": [
                            {
                                "value": "fixture-major",
                                "label": "Fixture Major",
                                "evidence_key": "education.major",
                                "evidence_value": {"description": "Fixture Major"},
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )

    application.call_deepseek = valid_repair
    try:
        repaired, calls = await application.repair_gap_questions_once(
            [invalid],
            {"academic:0": requirement},
            {},
        )
    finally:
        application.call_deepseek = original
    assert calls == 1
    assert repair_calls == 1
    assert repaired[0].schema_status == "valid"
    assert repaired[0].control_type == "single_select"
    assert repaired[0].repair_attempts == 1
    assert repaired[0].generation_diagnostics.initial_failure_stage == "initial_schema_missing"
    assert repaired[0].generation_diagnostics.repair_schema["control_type"] == "single_select"
    submitted = submit(repaired[0], [evidence_need], selected=["fixture-major"])
    assert submitted.parser_calls == 0
    assert submitted.evidence[0].key == "education.major"
    assert submitted.evidence[0].availability == "known"
    assert submitted.missing_slots == []

    invalid_repair_calls = 0

    async def still_invalid_repair(*args, **kwargs):
        nonlocal invalid_repair_calls
        invalid_repair_calls += 1
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "q:major:repair",
                        "requirement_id": "academic:0",
                        "prompt": "请输入数值。",
                        "expected_evidence_keys": ["education.major"],
                        "control_type": "number",
                        "fields": [
                            {
                                "field_id": "invalid-score",
                                "label": "Score",
                                "evidence_key": "education.major",
                                "value_path": "score",
                            }
                        ],
                    }
                ]
            }
        )

    application.call_deepseek = still_invalid_repair
    try:
        failed, calls = await application.repair_gap_questions_once(
            [invalid],
            {"academic:0": requirement},
            {},
        )
    finally:
        application.call_deepseek = original
    assert calls == 1
    assert invalid_repair_calls == 1
    assert failed[0].schema_status == "generation_error"
    assert failed[0].prompt == "这个问题暂时无法生成，请重新尝试。"
    assert failed[0].options == []
    assert failed[0].fields == []
    assert failed[0].allow_other is False
    assert failed[0].generation_diagnostics.repair_failure_stage == "repair_schema_invalid"
    assert failed[0].generation_diagnostics.repair_validator_error == "invalid_value_path"
    assert failed[0].generation_diagnostics.final_failure_stage == "repair_schema_invalid"

    async def failed_repair_request(*args, **kwargs):
        raise application.HTTPException(status_code=502, detail="fixture repair failure")

    application.call_deepseek = failed_repair_request
    try:
        generation_failed, calls = await application.repair_gap_questions_once(
            [invalid],
            {"academic:0": requirement},
            {},
        )
    finally:
        application.call_deepseek = original
    assert calls == 1
    assert generation_failed[0].schema_status == "generation_error"
    assert generation_failed[0].generation_diagnostics.repair_failure_stage == "repair_generation_failed"
    assert generation_failed[0].generation_diagnostics.final_failure_stage == "repair_generation_failed"


async def check_existing_any_branch_skips_sibling_question() -> None:
    requirement = application.RequirementItem(
        category="language",
        requirement="Accepted test A or accepted test B.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    calls = 0
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "language:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {"key": "test.a", "evidence_type": "language_score", "label": "Test A"},
                            {"key": "test.b", "evidence_type": "language_score", "label": "Test B"},
                        ],
                        "constraint": {
                            "kind": "score",
                            "relation": "any",
                            "options": [
                                {"key": "test.a", "kind": "score", "minimum": 7},
                                {"key": "test.b", "kind": "score", "minimum": 100},
                            ],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:test-b",
                        "prompt": "Provide Test B.",
                        "expected_evidence_keys": ["test.b"],
                        "control_type": "number",
                        "fields": [
                            {"field_id": "b", "label": "Test B", "evidence_key": "test.b", "value_path": "score"}
                        ],
                    }
                ],
            }
        )

    application.call_deepseek = fake_deepseek
    try:
        fresh_plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
            )
        )
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
                user_evidence=[
                    application.UserEvidence(
                        evidence_type="language_score",
                        key="test.a",
                        value={"score": 8},
                        raw_answer="Test A 8",
                        availability="known",
                        updated_at="2026-08-30T00:00:00Z",
                    )
                ],
            )
        )
    finally:
        application.call_deepseek = original
    assert calls == 2
    assert set(fresh_plan.questions[0].expected_evidence_keys) == {"test.a", "test.b"}
    assert set(fresh_plan.questions[0].allowed_evidence_keys) == {"test.a", "test.b"}
    assert fresh_plan.questions[0].evidence_group == "language:0:alternatives"
    assert fresh_plan.questions[0].group_relation == "any"
    assert plan.questions == []


async def check_complete_language_branch_skips_alternative() -> None:
    requirement = application.RequirementItem(
        category="language",
        requirement="An applicant may satisfy the language requirement with Test A or Test B.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    calls = 0
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "language:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {"key": "ielts", "evidence_type": "language_score", "label": "Test A"},
                            {"key": "toefl", "evidence_type": "language_score", "label": "Test B"},
                        ],
                        "constraint": {
                            "kind": "score",
                            "relation": "any",
                            "options": [
                                {
                                    "key": "ielts",
                                    "kind": "score",
                                    "minimum": 7,
                                    "component_minimum": 6.5,
                                },
                                {"key": "toefl", "kind": "score", "minimum": 100},
                            ],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:toefl",
                        "requirement_id": "language:0",
                        "prompt": "Provide Test B scores.",
                        "expected_evidence_keys": ["toefl"],
                        "control_type": "number_group",
                        "fields": [
                            {
                                "field_id": path,
                                "label": path,
                                "evidence_key": "toefl",
                                "value_path": path,
                            }
                            for path in ("score", "listening", "reading", "writing", "speaking")
                        ],
                    }
                ],
            }
        )

    complete_branch = application.UserEvidence(
        evidence_type="language_score",
        key="ielts",
        value={
            "score": 7.5,
            "subscores": {
                "listening": 7.5,
                "reading": 7.5,
                "writing": 7.5,
                "speaking": 7.5,
            },
        },
        raw_answer="Test A complete",
        availability="known",
        updated_at="2026-08-30T00:00:00Z",
    )
    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
                user_evidence=[complete_branch],
            )
        )
    finally:
        application.call_deepseek = original
    assert calls == 1
    assert plan.planning_llm_requests == 1
    assert plan.questions == []


async def check_missing_material_question_repairs_directly() -> None:
    requirement = application.RequirementItem(
        category="materials",
        requirement="A current curriculum vitae is required.",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    calls = 0
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps(
                {
                    "requirements": [
                        {
                            "requirement_id": "materials:0",
                            "matchable": True,
                            "match_strategy": "deterministic",
                            "evidence_needs": [
                                {
                                    "key": "materials.cv",
                                    "evidence_type": "material_status",
                                    "label": "CV",
                                }
                            ],
                            "constraint": {
                                "kind": "material_boolean",
                                "options": [
                                    {
                                        "key": "materials.cv",
                                        "kind": "material_boolean",
                                    }
                                ],
                            },
                        }
                    ],
                    "questions": [
                        {
                            "question_id": "q:llm-cv-duplicate",
                            "requirement_id": "materials:0",
                            "prompt": "Describe your CV status.",
                            "expected_evidence_keys": ["materials.cv"],
                            "control_type": "single_select",
                            "options": [
                                {
                                    "value": "ready",
                                    "label": "Ready",
                                    "evidence_key": "materials.cv",
                                    "evidence_value": {"status": True},
                                }
                            ],
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "q:materials:0",
                        "requirement_id": "materials:0",
                        "prompt": "你目前是否已有该申请材料？",
                        "expected_evidence_keys": ["materials.cv"],
                        "control_type": "boolean",
                        "fields": [
                            {
                                "field_id": "cv-status",
                                "label": "材料状态",
                                "evidence_key": "materials.cv",
                                "value_path": "status",
                            }
                        ],
                    }
                ]
            }
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
    assert plan.planning_llm_requests == 1
    assert len(plan.questions) == 1
    question = plan.questions[0]
    assert question.question_id.startswith("policy:")
    assert question.control_type == "boolean_group"
    assert question.schema_status == "valid"
    assert all(item.question_id != "q:llm-cv-duplicate" for item in plan.questions)
    result = submit(
        question,
        plan.requirements[0].evidence_needs,
        values={question.fields[0].field_id: True},
    )
    assert result.parser_calls == 0
    assert result.evidence[0].key.startswith("material_item.")
    assert result.evidence[0].value["material_type"] == "cv"
    assert result.evidence[0].availability == "known"


async def check_conditional_applicability_gating() -> None:
    requirement_text = (
        "Select either the Interaction Design track or the Machine Learning track. "
        "If selecting the Interaction Design track, Human-Computer Interaction is required."
    )
    requirement = application.RequirementItem(
        category="course",
        requirement=requirement_text,
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        temporal_applicability="undated",
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(requirements=[requirement]),
    )
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "course:0",
                        "matchable": True,
                        "match_strategy": "deterministic",
                        "evidence_needs": [
                            {
                                "key": "generic.selected_track",
                                "evidence_type": "generic",
                                "value_kind": "categorical",
                                "label": "Selected track",
                            },
                            {
                                "key": "courses.hci",
                                "evidence_type": "courses",
                                "value_kind": "boolean",
                                "label": "Human-Computer Interaction",
                            },
                        ],
                        "constraint": {"kind": "none", "relation": "all", "options": []},
                        "course_requirements": [
                            {
                                "evidence_key": "courses.hci",
                                "course_name": "Human-Computer Interaction",
                            }
                        ],
                        "other_items": [
                            {
                                "source_evidence_key": "generic.selected_track",
                                "label": "Selected track",
                                "value_kind": "single_select",
                                "options": ["Interaction Design", "Machine Learning"],
                            }
                        ],
                        "conditional": {
                            "is_conditional": True,
                            "condition_text": "If selecting the Interaction Design track",
                            "controlling_evidence_keys": ["generic.selected_track"],
                            "predicate_relation": "all",
                            "predicates": [
                                {
                                    "evidence_key": "generic.selected_track",
                                    "operator": "equals",
                                    "expected_values": ["Interaction Design"],
                                }
                            ],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:legacy-hci",
                        "requirement_id": "course:0",
                        "prompt": "Confirm the selected track and HCI course.",
                        "expected_evidence_keys": ["generic.selected_track", "courses.hci"],
                        "control_type": "boolean_group",
                        "fields": [
                            {
                                "field_id": "hci",
                                "label": "HCI",
                                "evidence_key": "courses.hci",
                                "value_path": "completed",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    application.call_deepseek = fake_deepseek
    try:
        pending_plan = await application.build_gap_plan(
            application.GapPlanRequest(target_program=TARGET, requirements_review=review)
        )
        track_item_id = application.other_policy_item_id("course:0", "Selected track")
        track_key = application.other_policy_evidence_key(track_item_id)

        assert pending_plan.requirements[0].conditional_state == "pending"
        assert len(pending_plan.questions) == 1
        assert pending_plan.questions[0].control_type == "single_select"
        assert pending_plan.questions[0].allowed_evidence_keys == [track_key]
        assert all(question.question_id != "q:legacy-hci" for question in pending_plan.questions)

        def track_evidence(value: str) -> application.UserEvidence:
            return application.UserEvidence(
                evidence_type="generic",
                key=track_key,
                value={
                    "requirement_id": "course:0",
                    "item_id": track_item_id,
                    "label": "Selected track",
                    "value_kind": "single_select",
                    "value": value,
                    "options": ["Interaction Design", "Machine Learning"],
                },
                raw_answer=value,
                availability="known",
                updated_at="2026-08-31T00:00:00Z",
            )

        active_plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
                user_evidence=[track_evidence("Interaction Design")],
            )
        )
        assert active_plan.requirements[0].conditional_state == "active"
        assert len(active_plan.questions) == 1
        assert active_plan.questions[0].question_id.startswith("policy:course:")
        assert active_plan.questions[0].control_type == "boolean_group"
        assert all(
            key.startswith("course_requirement.")
            for key in active_plan.questions[0].allowed_evidence_keys
        )

        active_requirement = active_plan.requirements[0]
        for wording in (
            "If selecting Interaction Design track",
            "Applicants choosing the Interaction Design pathway",
            "This requirement applies only to the Interaction-Design specialization",
        ):
            wording_variant = active_requirement.model_copy(
                update={
                    "conditional": active_requirement.conditional.model_copy(
                        update={"condition_text": wording}
                    )
                }
            )
            assert application.resolve_conditional_state(
                wording_variant,
                {track_key: track_evidence("Interaction Design")},
            ) == "active"

        legacy_without_predicate = active_requirement.model_copy(
            update={
                "conditional": active_requirement.conditional.model_copy(
                    update={"predicates": []}
                )
            }
        )
        assert application.resolve_conditional_state(
            legacy_without_predicate,
            {track_key: track_evidence("Interaction Design")},
        ) == "pending"

        unsupported_predicate = application.GapConditionalMetadata.model_validate(
            {
                "is_conditional": True,
                "condition_text": "If selecting Interaction Design",
                "controlling_evidence_keys": [track_key],
                "predicates": [
                    {
                        "evidence_key": track_key,
                        "operator": "contains",
                        "expected_values": ["Interaction Design"],
                    }
                ],
            }
        )
        assert unsupported_predicate.predicates == []
        assert application.resolve_conditional_state(
            active_requirement.model_copy(update={"conditional": unsupported_predicate}),
            {track_key: track_evidence("Interaction Design")},
        ) == "pending"

        unknown_track = track_evidence("Interaction Design").model_copy(
            update={"availability": "unknown"}
        )
        assert application.resolve_conditional_state(
            active_requirement,
            {track_key: unknown_track},
        ) == "pending"

        second_key = "generic.second_controller"

        def controller_evidence(key: str, value: str) -> application.UserEvidence:
            return application.UserEvidence(
                evidence_type="generic",
                key=key,
                value={"value": value},
                raw_answer=value,
                availability="known",
                updated_at="2026-08-31T00:00:00Z",
            )

        predicates = [
            application.GapConditionalPredicate(
                evidence_key=track_key,
                operator="equals",
                expected_values=["Interaction Design"],
            ),
            application.GapConditionalPredicate(
                evidence_key=second_key,
                operator="in",
                expected_values=["Domestic", "International"],
            ),
        ]
        multi_base = active_requirement.model_copy(
            update={
                "conditional": application.GapConditionalMetadata(
                    is_conditional=True,
                    condition_text="Structured two-controller fixture",
                    controlling_evidence_keys=[track_key, second_key],
                    predicates=predicates,
                )
            }
        )
        all_evidence = {
            track_key: track_evidence("Interaction Design"),
            second_key: controller_evidence(second_key, "Domestic"),
        }
        assert application.resolve_conditional_state(multi_base, all_evidence) == "active"
        assert application.resolve_conditional_state(
            multi_base,
            {**all_evidence, second_key: controller_evidence(second_key, "Other")},
        ) == "inactive"
        assert application.resolve_conditional_state(
            multi_base,
            {track_key: track_evidence("Machine Learning")},
        ) == "pending"

        any_requirement = multi_base.model_copy(
            update={
                "conditional": multi_base.conditional.model_copy(
                    update={"predicate_relation": "any"}
                )
            }
        )
        assert application.resolve_conditional_state(
            any_requirement,
            {track_key: track_evidence("Interaction Design")},
        ) == "active"
        assert application.resolve_conditional_state(
            any_requirement,
            {
                track_key: track_evidence("Machine Learning"),
                second_key: controller_evidence(second_key, "Other"),
            },
        ) == "inactive"
        assert application.resolve_conditional_state(
            any_requirement,
            {track_key: track_evidence("Machine Learning")},
        ) == "pending"

        inactive_plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
                user_evidence=[track_evidence("Machine Learning")],
            )
        )
        assert inactive_plan.requirements[0].conditional_state == "inactive"
        assert inactive_plan.questions == []

        empty_controller = pending_plan.requirements[0].model_copy(
            update={
                "conditional": application.GapConditionalMetadata(
                    is_conditional=True,
                    condition_text="If selecting an applicable track",
                    controlling_evidence_keys=[],
                ),
                "conditional_state": "pending",
            }
        )
        assert application.conditional_question_policy_view([empty_controller]) == []

        pending_gap = await application.analyze_gap(
            application.GapAnalysisRequest(
                target_program=TARGET,
                plan=pending_plan,
            )
        )
        assert len(pending_gap.results) == 1
        assert pending_gap.results[0].reason_code == "conditional_pending"
        assert pending_gap.results[0].status == "unknown"
        selected = application.select_planning_gaps(pending_gap.results)
        assert selected[0]["selected_action_kind"] == "confirm_information"

        inactive_gap = await application.analyze_gap(
            application.GapAnalysisRequest(
                target_program=TARGET,
                plan=inactive_plan,
                user_evidence=[track_evidence("Machine Learning")],
            )
        )
        assert inactive_gap.results == []
        assert application.select_planning_gaps(inactive_gap.results) == []
    finally:
        application.call_deepseek = original


async def check_conditional_controller_typed_boundary() -> None:
    requirement_text = (
        "For the Accelerated Graduate Program pathway, applicants must be current "
        "Carnegie Mellon senior undergraduates and must have identified a Robotics "
        "Institute faculty advisor."
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(
            requirements=[
                application.RequirementItem(
                    category="academic",
                    requirement=requirement_text,
                    importance="required",
                    source_level="program",
                    source_type="official_retrieval",
                    verification_status="official_verified",
                    source_url="https://example.edu/accelerated",
                    temporal_applicability="undated",
                )
            ]
        ),
    )
    controller_key = "generic.accelerated_pathway_selection"
    output = {
        "requirements": [
            {
                "requirement_id": "academic:0",
                "matchable": True,
                "match_strategy": "hybrid",
                "evidence_needs": [
                    {
                        "key": controller_key,
                        "evidence_type": "generic",
                        "value_kind": "boolean",
                        "label": "你通过 Accelerated Graduate Program pathway 申请",
                    },
                    {
                        "key": "education.university",
                        "evidence_type": "education_university",
                        "value_kind": "text",
                        "label": "本科院校",
                    },
                    {
                        "key": "generic.cmu_senior_status",
                        "evidence_type": "generic",
                        "value_kind": "boolean",
                        "label": "CMU senior status",
                    },
                    {
                        "key": "generic.ri_faculty_advisor",
                        "evidence_type": "generic",
                        "value_kind": "boolean",
                        "label": "RI faculty advisor",
                    },
                ],
                "constraint": {"kind": "none", "relation": "all", "options": []},
                "other_items": [
                    {
                        "source_evidence_key": controller_key,
                        "label": "你通过 Accelerated Graduate Program pathway 申请",
                        "value_kind": "boolean",
                        "options": [],
                    }
                ],
                "conditional": {
                    "is_conditional": True,
                    "condition_text": "For the Accelerated Graduate Program pathway",
                    "controlling_evidence_keys": [controller_key],
                    "predicate_relation": "all",
                    "predicates": [
                        {
                            "evidence_key": controller_key,
                            "operator": "equals",
                            "expected_values": ["true"],
                        }
                    ],
                },
            }
        ],
        "questions": [
            {
                "question_id": "q:legacy-accelerated-controller",
                "requirement_id": "academic:0",
                "prompt": "Legacy controller must not be used.",
                "expected_evidence_keys": [controller_key],
                "control_type": "boolean",
                "fields": [
                    {
                        "field_id": "legacy-controller-a",
                        "label": "Legacy A",
                        "evidence_key": controller_key,
                        "value_path": "status",
                    },
                    {
                        "field_id": "legacy-controller-b",
                        "label": "Legacy B",
                        "evidence_key": controller_key,
                        "value_path": "description",
                    },
                ],
            }
        ],
    }
    calls = 0
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(output, ensure_ascii=False)

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
    assert plan.planning_llm_requests == 1
    assert len(plan.questions) == 1
    question = plan.questions[0]
    assert question.question_id.startswith(
        "policy:academic:0:conditional-controller:"
    )
    assert question.control_type == "boolean"
    assert question.schema_status == "valid"
    assert question.repair_attempts == 0
    assert len(question.fields) == 1
    assert question.conditional_controller_bindings[0].expected_values == ["true"]
    assert all(
        item.question_id != "q:legacy-accelerated-controller"
        for item in plan.questions
    )

    planned = plan.requirements[0]
    controller_need = next(
        need for need in planned.evidence_needs if need.key in question.allowed_evidence_keys
    )
    controller_field = question.fields[0].field_id

    true_result = submit(question, [controller_need], values={controller_field: True})
    true_evidence = true_result.evidence[0]
    assert true_evidence.availability == "known"
    assert true_evidence.value["matches_condition"] is True
    assert true_evidence.value["value"] == "true"
    assert application.resolve_conditional_state(
        planned, {true_evidence.key: true_evidence}
    ) == "active"

    false_result = submit(question, [controller_need], values={controller_field: False})
    false_evidence = false_result.evidence[0]
    assert false_evidence.availability == "known_negative"
    assert false_evidence.value["matches_condition"] is False
    assert application.resolve_conditional_state(
        planned, {false_evidence.key: false_evidence}
    ) == "inactive"

    unknown_result = submit(question, [controller_need], terminal="unknown")
    unknown_evidence = unknown_result.evidence[0]
    assert unknown_evidence.availability == "unknown"
    assert application.resolve_conditional_state(
        planned, {unknown_evidence.key: unknown_evidence}
    ) == "pending"

    controller_keys = set(planned.conditional.controlling_evidence_keys)
    assert controller_keys == {controller_need.key}
    assert "education.university" not in controller_keys
    assert "generic.cmu_senior_status" not in controller_keys
    assert "generic.ri_faculty_advisor" not in controller_keys

    no_descriptor_output = json.loads(json.dumps(output))
    no_descriptor_output["requirements"][0]["other_items"] = []
    no_descriptor_calls = 0

    async def fake_no_descriptor(*args, **kwargs):
        nonlocal no_descriptor_calls
        no_descriptor_calls += 1
        return json.dumps(no_descriptor_output, ensure_ascii=False)

    application.call_deepseek = fake_no_descriptor
    try:
        no_descriptor_plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review,
            )
        )
    finally:
        application.call_deepseek = original
    assert no_descriptor_calls == 1
    assert no_descriptor_plan.requirements[0].conditional_state == "pending"
    assert no_descriptor_plan.questions == []
    assert no_descriptor_plan.planning_llm_requests == 1


async def check_cmu_required_course_inventory() -> None:
    requirement_text = (
        "Applicants must have, or be able to rapidly acquire, basic understanding "
        "at introductory undergraduate level in: Mathematics (calculus, linear "
        "algebra, numerical analysis, probability and statistics), Computer Science "
        "(programming, data structures, algorithms), and Physics and Engineering "
        "(mechanics, dynamics, electricity and magnetism, optics)."
    )
    review = application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(
            requirements=[
                application.RequirementItem(
                    category="course",
                    requirement=requirement_text,
                    importance="required",
                    source_level="program",
                    source_type="official_retrieval",
                    verification_status="official_verified",
                    source_url="https://example.edu/msr",
                    temporal_applicability="undated",
                )
            ]
        ),
    )
    groups = {
        "Mathematics": [
            "calculus",
            "linear algebra",
            "numerical analysis",
            "probability and statistics",
        ],
        "Computer Science": ["programming", "data structures", "algorithms"],
        "Physics and Engineering": [
            "mechanics",
            "dynamics",
            "electricity and magnetism",
            "optics",
        ],
    }
    source_key_by_group = {
        "Mathematics": "courses.math",
        "Computer Science": "courses.cs",
        "Physics and Engineering": "courses.physics_engineering",
    }
    course_requirements = [
        {
            "evidence_key": source_key_by_group[group],
            "course_name": course_name,
            "group_label": group,
        }
        for group, names in groups.items()
        for course_name in names
    ]
    output = {
        "requirements": [
            {
                "requirement_id": "course:0",
                "matchable": True,
                "match_strategy": "deterministic",
                "evidence_needs": [
                    {
                        "key": source_key,
                        "evidence_type": "courses",
                        "value_kind": "text",
                        "label": group,
                    }
                    for group, source_key in source_key_by_group.items()
                ],
                "constraint": {"kind": "none", "relation": "all", "options": []},
                "course_requirements": course_requirements,
            }
        ],
        "questions": [
            {
                "question_id": "q:legacy-course-domains",
                "requirement_id": "course:0",
                "prompt": "至少选择一项课程领域。",
                "expected_evidence_keys": list(source_key_by_group.values()),
                "group_relation": "any",
                "control_type": "multi_select",
                "options": [
                    {
                        "value": source_key,
                        "label": group,
                        "evidence_key": source_key,
                        "evidence_value": {"description": group},
                    }
                    for group, source_key in source_key_by_group.items()
                ],
                "validation": {"required": True, "min_selections": 1},
            }
        ],
    }
    calls = 0
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(output, ensure_ascii=False)

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
    assert plan.planning_llm_requests == 1
    planned = plan.requirements[0]
    assert len(planned.course_requirements) == 11
    assert [item.course_name for item in planned.course_requirements] == [
        course_name
        for names in groups.values()
        for course_name in names
    ]
    assert [item.group_label for item in planned.course_requirements] == [
        group for group, names in groups.items() for _ in names
    ]
    assert all(
        need.key.startswith("course_requirement.")
        for need in planned.evidence_needs
    )
    assert all(
        need.group_relation == "all" and need.required_fields == ["completed"]
        for need in planned.evidence_needs
    )
    assert len(plan.questions) == 1
    checklist = plan.questions[0]
    assert checklist.control_type == "boolean_group"
    assert "至少选择一项" not in checklist.prompt
    assert len(checklist.fields) == 11
    assert all(" — " in field.label for field in checklist.fields)
    assert all(
        question.question_id != "q:legacy-course-domains"
        for question in plan.questions
    )
    assert all(
        question.control_type not in {"multi_select", "text_fallback"}
        for question in plan.questions
    )

    first_field, second_field = checklist.fields[:2]
    partial = submit(
        checklist,
        planned.evidence_needs,
        values={first_field.field_id: True, second_field.field_id: False},
    )
    assert partial.parser_calls == 0
    assert len(partial.evidence) == 2
    assert [item.value["completed"] for item in partial.evidence] == [True, False]
    assert all(item.availability == "known" for item in partial.evidence)
    assert len(partial.missing_slots) == 9
    assert all(
        not slot.startswith(f"{first_field.evidence_key}.")
        and not slot.startswith(f"{second_field.evidence_key}.")
        for slot in partial.missing_slots
    )
    reusable = {item.key: item for item in partial.evidence}
    follow_up, _ = application.build_backend_course_questions([planned], reusable)
    follow_up_checklist = next(
        question for question in follow_up if question.control_type == "boolean_group"
    )
    assert len(follow_up_checklist.fields) == 9
    assert first_field.evidence_key not in follow_up_checklist.expected_evidence_keys
    assert second_field.evidence_key not in follow_up_checklist.expected_evidence_keys


async def main() -> None:
    check_dynamic_single_select()
    check_categorical_academic_schema_and_fallback_wording()
    check_real_academic_any_structured_convergence()
    check_number_and_number_group()
    check_score_group_terminal_actions()
    check_deterministic_language_score_forms()
    check_language_proof_selector_handoff()
    check_backend_academic_question_policy()
    check_backend_language_question_policy()
    check_backend_course_question_policy()
    check_backend_gre_question_policy()
    check_backend_experience_question_policy()
    check_backend_materials_question_policy()
    check_backend_other_question_policy()
    await check_backend_academic_policy_overrides_llm_question()
    await check_backend_language_policy_overrides_llm_question()
    await check_backend_course_policy_overrides_llm_question()
    await check_backend_gre_policy_overrides_llm_question()
    await check_backend_experience_policy_overrides_llm_question()
    await check_backend_other_policy_overrides_llm_question()
    await check_conditional_applicability_gating()
    await check_conditional_controller_typed_boundary()
    await check_cmu_required_course_inventory()
    check_dynamic_multi_select()
    check_any_and_all_groups()
    check_schema_satisfiability_and_any_convergence()
    check_terminal_and_text_fallback()
    await check_planner_schema_and_safety()
    await check_planner_categorical_academic_path()
    await check_questions_do_not_cross_requirement_boundaries()
    await check_structured_only_repair_contract()
    await check_existing_any_branch_skips_sibling_question()
    await check_complete_language_branch_skips_alternative()
    await check_missing_material_question_repairs_directly()
    print("structured adaptive interview regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
