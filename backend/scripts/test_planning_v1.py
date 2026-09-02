"""Deterministic Planning regressions; no live or mocked LLM response is used."""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402

TARGET = application.TargetProgram(
    university="Example University", program="Example MSc",
    official_program_url="https://example.edu/program", official_domain="example.edu",
    intended_entry_year=2027,
)


def gap(requirement_id: str, status: str, importance: str, requirement: str, *,
        category: str = "materials", user_evidence: str = "未提供") -> application.GapResult:
    return application.GapResult(
        requirement_id=requirement_id, category=category, requirement=requirement,
        requirement_verification_status="official_verified", temporal_applicability="undated",
        importance=importance, status=status, user_evidence=user_evidence,
        gap="test gap", reason="test reason",
    )


def timeline(deadline: str | None = None) -> application.ApplicationTimeline:
    deadlines = [] if deadline is None else [application.ApplicationDeadline(
        label="Final deadline", type="final", date=deadline,
        source_url="https://example.edu/deadline",
    )]
    return application.ApplicationTimeline(
        admission_cycle="Fall 2027", application_deadlines=deadlines,
        status="complete" if deadline else "not_found",
    )


async def plan_for(gaps, deadline: str | None = None, today=date(2026, 8, 26)):
    return await application.build_action_plan(
        application.ActionPlanRequest(
            target_program=TARGET,
            gap_analysis=application.GapAnalysisResponse(target_program=TARGET, results=gaps),
            application_timeline=timeline(deadline),
        ),
        current_date=today,
    )


async def main() -> None:
    # 1: met -> no Planning item.
    plan = await plan_for([gap("met", "met", "required", "Transcript is required.")])
    assert not plan.actions and not plan.needs_confirmation and not plan.eligibility_risks

    # 2: unknown -> confirmation only, undated.
    plan = await plan_for([gap(
        "ielts-unknown", "unknown", "required", "IELTS subscores are required.", category="language"
    )], "2027-01-15")
    assert not plan.actions and plan.needs_confirmation[0].target_date is None

    # 3-4: no-score and retake buffers.
    no_score = gap("ielts-none", "not_met", "required", "IELTS 7.0 is required.",
                   category="language", user_evidence="没有有效成绩")
    retake = gap("ielts-retake", "partial", "required", "IELTS 7.0 is required.",
                 category="language", user_evidence="IELTS 6.5")
    assert application.select_planning_gaps([no_score])[0]["buffer_weeks"] == 20
    assert application.select_planning_gaps([retake])[0]["buffer_weeks"] == 8

    # 5-7: recommendation, PS and Transcript buffers.
    recommendations = gap("rec", "not_met", "required", "Three letters of recommendation are required.")
    ps = gap("ps", "not_met", "required", "A Personal Statement is required.")
    transcript = gap("transcript", "not_met", "required", "An official transcript is required.")
    selected = {item["requirement_id"]: item for item in application.select_planning_gaps(
        [recommendations, ps, transcript]
    )}
    assert selected["rec"]["buffer_weeks"] == 10
    assert selected["ps"]["buffer_weeks"] == 4
    assert selected["transcript"]["buffer_weeks"] == 2

    # 8-11: immutable hard qualifications -> eligibility risks.
    risks = [
        gap("major", "not_met", "required", "A Computer Science academic background is required.", category="academic"),
        gap("gpa", "not_met", "required", "A final GPA of 3.5 is required.", category="academic", user_evidence="GPA 3.2"),
        gap("course", "not_met", "required", "Linear Algebra is a required prerequisite course.", category="course"),
        gap("experience", "not_met", "required", "At least 3 years of work experience is required.", category="experience"),
    ]
    plan = await plan_for(risks)
    assert not plan.actions
    assert {item.source_gap_id for item in plan.eligibility_risks} == {"major", "gpa", "course", "experience"}

    # 12: no Deadline -> priority-only, long preparation first.
    plan = await plan_for([transcript, recommendations, ps])
    assert [item.source_gap_id for item in plan.actions] == ["rec", "ps", "transcript"]
    assert [item.priority_order for item in plan.actions] == [1, 2, 3]
    assert all(item.target_date is None and item.timing_status == "priority_only" for item in plan.actions)

    # 13: reliable Deadline -> deadline minus buffer, ascending target dates.
    plan = await plan_for([transcript, recommendations, retake], "2027-01-15")
    assert [item.source_gap_id for item in plan.actions] == ["rec", "ielts-retake", "transcript"]
    by_id = {item.source_gap_id: item for item in plan.actions}
    assert by_id["rec"].target_date == "2026-11-06"
    assert by_id["ielts-retake"].target_date == "2026-11-20"
    assert by_id["transcript"].target_date == "2027-01-01"

    # 14: a past computed target becomes urgent and undated.
    plan = await plan_for([no_score, transcript], "2026-09-15")
    assert plan.actions[0].source_gap_id == "ielts-none"
    assert plan.actions[0].timing_status == "urgent" and plan.actions[0].target_date is None

    # 15: non-required partial/not_met is outside the MVP plan.
    optional = gap("optional", "not_met", "preferred", "A writing sample is preferred.")
    plan = await plan_for([optional])
    assert not plan.actions and not plan.eligibility_risks and not plan.needs_confirmation

    # 16: unmapped required Gap -> confirmation, never free inference.
    unmapped = gap("other", "not_met", "required", "A bespoke semantic criterion must be met.", category="other")
    plan = await plan_for([unmapped])
    assert not plan.actions and plan.needs_confirmation[0].source_gap_id == "other"

    # 17: one Action per source Gap and deterministic order.
    gaps = [ps, transcript, recommendations, retake]
    first = await plan_for(gaps)
    second = await plan_for(list(reversed(gaps)))
    first_ids = [item.source_gap_id for item in first.actions]
    assert first_ids == [item.source_gap_id for item in second.actions]
    assert len(first_ids) == len(set(first_ids))

    # 18: production Planning makes zero DeepSeek calls.
    original = application.call_deepseek
    async def forbidden_call(*args, **kwargs):
        raise AssertionError("Planning must not call DeepSeek")
    application.call_deepseek = forbidden_call
    try:
        plan = await plan_for([recommendations, unmapped])
    finally:
        application.call_deepseek = original
    assert plan.planning_llm_requests == 0

    print("deterministic planning regressions: 18 cases passed")


if __name__ == "__main__":
    asyncio.run(main())
