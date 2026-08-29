"""Static regressions for Requirement temporal applicability and the Gap gate."""

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
    university="Temporal Regression University",
    program="Temporal Regression MSc",
    official_program_url="https://example.edu/programme",
    official_domain="example.edu",
    intended_entry_year=2027,
    intended_entry_term="fall",
)


def requirement_item(
    temporal_applicability: application.RequirementTemporalApplicability,
) -> application.RequirementItem:
    return application.RequirementItem(
        category="materials",
        requirement="An official transcript is required.",
        requirement_zh="必须提交正式成绩单。",
        importance="required",
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
        source_cycle="2026-27" if temporal_applicability == "previous_cycle" else None,
        temporal_applicability=temporal_applicability,
        temporal_note=(
            "The page explicitly covers 2026-27 entry."
            if temporal_applicability == "previous_cycle"
            else None
        ),
    )


def review_for(
    temporal_applicability: application.RequirementTemporalApplicability,
) -> application.TargetProgramRequirementsReview:
    return application.requirements_review_from_extraction(
        TARGET,
        application.RequirementsExtraction(
            requirements=[requirement_item(temporal_applicability)]
        ),
    )


def negative_transcript_evidence() -> application.UserEvidence:
    return application.UserEvidence(
        evidence_type="material_status",
        key="materials.transcript",
        value={"status": False},
        raw_answer="暂时没有成绩单",
        availability="known_negative",
        updated_at="2026-08-29T00:00:00Z",
    )


async def run_gap_case(
    temporal_applicability: application.RequirementTemporalApplicability,
) -> tuple[application.GapPlan, application.GapAnalysisResponse]:
    original = application.call_deepseek

    async def fake_deepseek(*args, **kwargs):
        return json.dumps(
            {
                "requirements": [
                    {
                        "requirement_id": "materials:0",
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
                            "relation": "all",
                            "options": [
                                {
                                    "key": "materials.transcript",
                                    "kind": "material_boolean",
                                }
                            ],
                        },
                    }
                ],
                "questions": [
                    {
                        "question_id": "q:materials:0",
                        "question": "成绩单准备好了吗？",
                        "evidence_keys": ["materials.transcript"],
                    }
                ],
            },
            ensure_ascii=False,
        )

    evidence = negative_transcript_evidence()
    application.call_deepseek = fake_deepseek
    try:
        plan = await application.build_gap_plan(
            application.GapPlanRequest(
                target_program=TARGET,
                requirements_review=review_for(temporal_applicability),
                user_evidence=[evidence],
            )
        )
    finally:
        application.call_deepseek = original

    analysis = await application.analyze_gap(
        application.GapAnalysisRequest(
            target_program=TARGET,
            plan=plan,
            user_evidence=[evidence],
        )
    )
    return plan, analysis


async def main() -> None:
    for status in ("target_cycle_confirmed", "undated", "previous_cycle"):
        item = requirement_item(status)
        assert item.verification_status == "official_verified"
        assert item.temporal_applicability == status
    previous = requirement_item("previous_cycle")
    assert previous.source_cycle == "2026-27"
    assert previous.verification_status != "model_memory_unverified"

    for active_status in ("target_cycle_confirmed", "undated"):
        plan, analysis = await run_gap_case(active_status)
        assert plan.requirements[0].matchable
        assert analysis.results[0].status == "not_met"
        assert analysis.results[0].temporal_applicability == active_status

    for blocked_status in ("previous_cycle", "not_yet_published", "unknown"):
        plan, analysis = await run_gap_case(blocked_status)
        assert not plan.requirements[0].matchable
        assert not plan.questions
        result = analysis.results[0]
        assert result.status == "unknown"
        assert result.temporal_applicability == blocked_status
        assert result.requirement_verification_status == "official_verified"
        assert "硬性匹配" in result.user_evidence
        selected = application.select_planning_gaps([result])
        assert selected[0]["selected_action_kind"] == "confirm_information"
        assert selected[0]["selected_action_kind"] != "resolve_gap"

    print("temporal applicability regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
