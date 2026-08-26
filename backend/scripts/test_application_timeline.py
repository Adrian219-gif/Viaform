"""Deterministic checks for the minimal Application Timeline contract."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


REQUEST = application.ApplicationTimelineRequest(
    university="Example University",
    program_name="MSc Example Studies",
    official_program_url="https://example.edu/programme",
    intended_entry_year=2027,
    intended_entry_term="fall",
)


def deadline(label: str, kind: str, date: str) -> application.ApplicationDeadline:
    return application.ApplicationDeadline(
        label=label,
        type=kind,
        date=date,
        source_url="https://example.edu/official-deadlines",
    )


async def run() -> None:
    original = application.call_deepseek_web_search
    prompts: list[str] = []
    results = [
        application.ApplicationTimeline(
            admission_cycle="Fall 2027",
            application_open_date="2026-09-15",
            application_open_source_url="https://example.edu/official-deadlines",
            application_deadlines=[
                deadline("Round 1", "round", "2026-12-01"),
                deadline("Round 2", "round", "2027-02-01"),
                deadline("Final", "final", "2027-04-01"),
            ],
            rolling_admission=False,
            rolling_admission_source_url="https://example.edu/official-deadlines",
            status="partial",
        ),
        application.ApplicationTimeline(
            admission_cycle="Fall 2027",
            application_deadlines=[deadline("Final", "final", "2027-04-01")],
            rolling_admission=None,
            status="complete",
        ),
        application.ApplicationTimeline(
            admission_cycle="Fall 2027",
            application_open_date="September 2026",
            application_open_source_url="https://example.edu/official-deadlines",
            application_deadlines=[deadline("Final", "final", "2027-04-01")],
            rolling_admission=None,
            status="complete",
        ),
        application.ApplicationTimeline(
            admission_cycle="Fall 2027",
            application_open_date=None,
            application_deadlines=[],
            rolling_admission=None,
            status="partial",
        ),
    ]

    async def fake_search(prompt, output_model, **kwargs):
        assert output_model is application.ApplicationTimeline
        assert kwargs["schema_name"] == "application_timeline"
        assert kwargs["max_search_uses"] == 4
        prompts.append(prompt)
        return results.pop(0)

    application.call_deepseek_web_search = fake_search
    try:
        complete = await application.retrieve_application_timeline(REQUEST)
        assert complete.status == "complete"
        assert [item.label for item in complete.application_deadlines] == [
            "Round 1",
            "Round 2",
            "Final",
        ]
        assert complete.rolling_admission is False

        deadline_only = await application.retrieve_application_timeline(REQUEST)
        assert deadline_only.status == "partial"
        assert deadline_only.application_open_date is None

        month_only = await application.retrieve_application_timeline(REQUEST)
        assert month_only.application_open_date == "September 2026"
        assert month_only.application_open_date != "2026-09-01"

        missing = await application.retrieve_application_timeline(REQUEST)
        assert missing.status == "not_found"
        assert not missing.application_deadlines

        assert len(prompts) == 4
        prompt = prompts[0]
        assert "Use only current official university information" in prompt
        assert "Do not use model memory" in prompt
        assert "Do not collapse multiple rounds" in prompt
        assert "scholarship" in prompt and "decision release" in prompt
        assert "do not invent a day" in prompt
    finally:
        application.call_deepseek_web_search = original


if __name__ == "__main__":
    asyncio.run(run())
    print("application timeline checks passed")
