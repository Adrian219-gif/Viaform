"""Core Planning V1 selector, deadline, and validator regressions."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from time import perf_counter

from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


TARGET = application.TargetProgram(
    university="Example University",
    program="Example MSc",
    official_program_url="https://example.edu/program",
    official_domain="example.edu",
    intended_entry_year=2027,
)


def gap(
    requirement_id: str,
    status: str,
    importance: str,
    requirement: str,
) -> application.GapResult:
    return application.GapResult(
        requirement_id=requirement_id,
        category="materials",
        requirement=requirement,
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
        importance=importance,
        status=status,
        user_evidence="test evidence",
        gap="test gap",
        reason="test reason",
    )


def analysis() -> application.GapAnalysisResponse:
    return application.GapAnalysisResponse(
        target_program=TARGET,
        results=[
            gap("materials:met", "met", "required", "Transcript is required."),
            gap("language:partial", "partial", "required", "IELTS 7.0 is required."),
            gap("experience:optional", "not_met", "recommended", "Relevant experience is recommended."),
            gap("materials:conditional", "unknown", "required", "A portfolio may be required if requested."),
            gap("academic:unknown", "unknown", "unknown", "Degree equivalency must be confirmed."),
        ],
    )


def precise_timeline() -> application.ApplicationTimeline:
    return application.ApplicationTimeline(
        admission_cycle="Fall 2027",
        application_open_date="2026-09-01",
        application_deadlines=[
            application.ApplicationDeadline(
                label="Final deadline",
                type="final",
                date="2027-01-15",
                source_url="https://example.edu/deadline",
            )
        ],
        rolling_admission=False,
        status="complete",
    )


async def check_main_plan() -> None:
    output = {
        "actions": [
            {
                "action_id": "language-prepare",
                "action": "开始语言准备并制定首考目标",
                "action_kind": "complete_gap",
                "time_period": "2026-09",
                "target_date": "2026-09-30",
                "source_gap_id": "language:partial",
                "reason": "补齐语言成绩差距。",
                "status": "pending",
                "depends_on": [],
                "parallel_group": "foundation",
            },
            {
                "action_id": "optional-experience",
                "action": "整理可选的相关经历证明",
                "action_kind": "resolve_gap",
                "time_period": "2026-10",
                "target_date": "2026-10-31",
                "source_gap_id": "experience:optional",
                "reason": "作为可选提升项。",
                "status": "pending",
                "depends_on": [],
                "parallel_group": "enhancement",
            },
            {
                "action_id": "confirm-portfolio",
                "action": "向项目方确认是否适用作品集要求",
                "action_kind": "confirm_information",
                "time_period": "2026-09",
                "target_date": "2026-09-15",
                "source_gap_id": "materials:conditional",
                "reason": "条件要求适用性尚未确认。",
                "status": "pending",
                "depends_on": [],
                "parallel_group": "foundation",
            },
            {
                "action_id": "confirm-degree",
                "action": "确认学位等同性信息",
                "action_kind": "confirm_information",
                "time_period": "2026-09",
                "target_date": "2026-09-20",
                "source_gap_id": "academic:unknown",
                "reason": "当前信息不足。",
                "status": "pending",
                "depends_on": [],
                "parallel_group": "foundation",
            },
        ]
    }
    prompts = []
    original = application.call_deepseek

    async def fake_call(*args, **kwargs):
        prompts.append(kwargs["messages"][1]["content"])
        return json.dumps(output, ensure_ascii=False)

    application.call_deepseek = fake_call
    try:
        plan = await application.build_action_plan(
            application.ActionPlanRequest(
                target_program=TARGET,
                gap_analysis=analysis(),
                application_timeline=precise_timeline(),
            ),
            current_date=date(2026, 8, 26),
        )
    finally:
        application.call_deepseek = original

    assert plan.application_deadline == "2027-01-15"
    assert plan.ready_by_date == "2026-12-25"
    assert all(action.source_gap_id != "materials:met" for action in plan.actions)
    by_gap = {action.source_gap_id: action for action in plan.actions}
    assert by_gap["language:partial"].priority == "high"
    assert by_gap["experience:optional"].plan_track == "optional"
    assert by_gap["experience:optional"].priority == "optional"
    assert by_gap["materials:conditional"].action_kind == "confirm_information"
    assert "application-level milestones, not daily checklists" in prompts[0]
    assert "Do not output, choose, or change action_kind" in prompts[0]


async def check_core_selector_contract_replays() -> None:
    schema = application.DeepSeekActionPlanContent.model_json_schema()
    action_properties = schema["$defs"]["DeepSeekPlanningActionDraft"]["properties"]
    assert "action_kind" not in action_properties

    cases = [
        ("CORE-001", "materials:0", "not_met", "resolve_gap", "complete_gap"),
        ("CORE-002", "language:1", "partial", "complete_gap", "resolve_gap"),
        ("CORE-005", "materials:2", "unknown", "confirm_information", "resolve_gap"),
    ]
    original = application.call_deepseek
    try:
        for case_id, gap_id, gap_status, expected_kind, model_kind in cases:
            output = {
                "actions": [
                    {
                        "action_id": f"{case_id.lower()}-action",
                        "action": "完成对应申请里程碑",
                        "action_kind": model_kind,
                        "time_period": "阶段 1 · 核心准备",
                        "target_date": None,
                        "source_gap_id": gap_id,
                        "reason": "处理当前申请差距。",
                    }
                ]
            }

            async def fake_call(*args, **kwargs):
                return json.dumps(output, ensure_ascii=False)

            application.call_deepseek = fake_call
            started = perf_counter()
            plan = await application.build_action_plan(
                application.ActionPlanRequest(
                    target_program=TARGET,
                    gap_analysis=application.GapAnalysisResponse(
                        target_program=TARGET,
                        results=[gap(gap_id, gap_status, "required", "Required application evidence.")],
                    ),
                    application_timeline=application.ApplicationTimeline(
                        admission_cycle="Fall 2027",
                        application_deadlines=[],
                        status="not_found",
                    ),
                ),
                current_date=date(2026, 8, 26),
            )
            elapsed_ms = (perf_counter() - started) * 1000
            assert plan.actions[0].action_kind == expected_kind
            print(
                f"{case_id}: PASS selector={expected_kind} "
                f"model_attempt={model_kind} latency_ms={elapsed_ms:.2f}"
            )
    finally:
        application.call_deepseek = original


async def check_not_found_timeline_uses_phases() -> None:
    one_gap = application.GapAnalysisResponse(
        target_program=TARGET,
        results=[gap("language:0", "not_met", "required", "IELTS is required.")],
    )
    output = {
        "actions": [
            {
                "action_id": "language-stage",
                "action": "准备并参加语言考试",
                "action_kind": "resolve_gap",
                "time_period": "阶段 1 · 核心准备",
                "target_date": None,
                "source_gap_id": "language:0",
                "reason": "解决语言差距。",
            }
        ]
    }
    original = application.call_deepseek

    async def fake_call(*args, **kwargs):
        return json.dumps(output, ensure_ascii=False)

    application.call_deepseek = fake_call
    try:
        plan = await application.build_action_plan(
            application.ActionPlanRequest(
                target_program=TARGET,
                gap_analysis=one_gap,
                application_timeline=application.ApplicationTimeline(
                    admission_cycle="Fall 2027",
                    application_deadlines=[],
                    status="not_found",
                ),
            ),
            current_date=date(2026, 8, 26),
        )
    finally:
        application.call_deepseek = original
    assert plan.application_deadline is None
    assert plan.ready_by_date is None
    assert plan.actions[0].target_date is None


def check_validator_rejects_invalid_plans() -> None:
    gaps = analysis().results
    selected = application.select_planning_gaps(gaps)
    selector_mismatch = application.DeepSeekActionPlanOutput(
        actions=[
            application.PlanningActionDraft(
                action_id="wrong-kind",
                action="完成语言成绩",
                action_kind="resolve_gap",
                time_period="2026-09",
                target_date="2026-09-30",
                source_gap_id="language:partial",
                reason="模拟越过代码 Selector 的输入。",
            )
        ]
    )
    try:
        application.validate_action_plan(
            selector_mismatch,
            gaps,
            selected,
            date(2027, 1, 15),
        )
        raise AssertionError("direct selector mismatch should still fail validation")
    except HTTPException as error:
        assert "Action kind violates code selector" in error.detail

    missing_required = application.DeepSeekActionPlanOutput(actions=[])
    try:
        application.validate_action_plan(
            missing_required,
            gaps,
            selected,
            date(2027, 1, 15),
        )
        raise AssertionError("required Gap omission should fail")
    except HTTPException as error:
        assert "omitted required Gaps" in error.detail

    invented_date = application.DeepSeekActionPlanOutput(
        actions=[
            application.PlanningActionDraft(
                action_id="late",
                action="完成语言成绩",
                action_kind="complete_gap",
                time_period="2027-01",
                target_date="2027-01-16",
                source_gap_id="language:partial",
                reason="补齐差距。",
            ),
            application.PlanningActionDraft(
                action_id="conditional",
                action="确认作品集",
                action_kind="confirm_information",
                time_period="2026-09",
                target_date="2026-09-01",
                source_gap_id="materials:conditional",
                reason="确认适用性。",
            ),
        ]
    )
    try:
        application.validate_action_plan(
            invented_date,
            gaps,
            selected,
            date(2027, 1, 15),
        )
        raise AssertionError("post-deadline action should fail")
    except HTTPException as error:
        assert "exceeds Application Deadline" in error.detail


async def main() -> None:
    await check_core_selector_contract_replays()
    await check_main_plan()
    await check_not_found_timeline_uses_phases()
    check_validator_rejects_invalid_plans()
    print("planning v1 regressions: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
