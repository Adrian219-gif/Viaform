from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import main as application


def run() -> None:
    target = application.TargetProgram(
        university="Example University",
        program="MSc Example",
        official_program_url="https://example.edu/program",
        official_domain="example.edu",
        confirmation_status="confirmed",
        intended_entry_year=2027,
        intended_entry_term="fall",
    )
    need = application.GapEvidenceNeed(
        key="materials.cv",
        evidence_type="material_status",
        value_kind="boolean",
        label="CV",
    )
    requirement = application.GapPlannedRequirement(
        requirement_id="materials:0",
        matchable=True,
        match_strategy="deterministic",
        evidence_needs=[need],
        constraint=application.GapDeterministicConstraint(
            kind="material_boolean",
            options=[application.GapConstraintOption(key="materials.cv")],
        ),
        category="materials",
        requirement="A CV is required.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    legacy_question = application.GapPlannerQuestion(
        question_id="legacy:cv",
        requirement_id="materials:0",
        prompt="Do you have a CV?",
        expected_evidence_keys=["materials.cv"],
        allowed_evidence_keys=["materials.cv"],
        control_type="boolean",
        fields=[application.GapQuestionField(
            field_id="cv",
            label="CV",
            evidence_key="materials.cv",
            value_path="status",
        )],
    )
    plan = application.GapPlan(
        target_program=target,
        requirements=[requirement],
        questions=[legacy_question],
    )
    result = asyncio.run(application.analyze_gap(application.GapAnalysisRequest(
        target_program=target,
        plan=plan,
        user_evidence=[],
    )))
    assert len(result.results) == 1
    assert result.results[0].status == "unknown"
    assert result.results[0].reason_code == "user_evidence_missing"
    print("PASS current Gap accepts a plan with unanswered legacy questions")


if __name__ == "__main__":
    run()
