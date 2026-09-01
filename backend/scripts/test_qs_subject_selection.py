"""Offline regressions for canonical QS Subject selection without LLM mapping."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


def subject_request(subject_name: str) -> application.ExploreTargetRequest:
    return application.ExploreTargetRequest(
        mode="explore",
        countries=[],
        target_major="Computer Science",
        ranking=application.RankingScope(type="QS", basis="subject", min=1, max=100),
        ranking_subject_id=application.qs_subject_id(subject_name),
        ranking_subject=subject_name,
    )


async def main() -> None:
    llm = AsyncMock(side_effect=AssertionError("QS subject selection must not call DeepSeek"))
    with patch.object(application, "call_deepseek", llm):
        taxonomy = await application.list_qs_subjects()
        assert taxonomy["subjects"]
        assert len(taxonomy["subjects"]) == taxonomy["subject_count"]
        assert len({item["subject_id"] for item in taxonomy["subjects"]}) == len(
            taxonomy["subjects"]
        )

        computer_science = "Computer Science & Information Systems"
        cs_result = await application._filter_candidate_universities(
            subject_request(computer_science)
        )
        assert cs_result.universities
        assert all(item.ranking_subject == computer_science for item in cs_result.universities)
        assert all(
            item.subject_ranking and item.subject_ranking.subject == computer_science
            for item in cs_result.universities
        )

        art_design = "Art & Design"
        art_result = await application._filter_candidate_universities(
            subject_request(art_design)
        )
        assert art_result.universities
        assert all(item.ranking_subject == art_design for item in art_result.universities)
        assert all(item.ranking_subject != computer_science for item in art_result.universities)

        uncertain = await application._filter_candidate_universities(
            application.ExploreTargetRequest(
                mode="explore",
                countries=[],
                target_major="Not sure yet",
                ranking=application.RankingScope(type="QS", basis="overall", min=1, max=5),
                ranking_subject_id=None,
                ranking_subject=None,
            )
        )
        assert uncertain.universities
        assert all(item.ranking_basis == "overall" for item in uncertain.universities)
        assert all(item.ranking_subject is None for item in uncertain.universities)

    assert llm.await_count == 0
    assert "/rankings/qs/map-subject" not in application.app.openapi()["paths"]
    print("QS subject selection regressions: all checks passed; DeepSeek calls=0")


if __name__ == "__main__":
    asyncio.run(main())
