"""Live regression checks for Candidate Program Discovery Web Search fast path."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import (  # noqa: E402
    CandidateUniversity,
    ExploreTargetRequest,
    RankingScope,
    UniversityProgramRequest,
    discover_candidate_programs,
)


CASES = [
    ("Imperial College London", "United Kingdom", "Machine Learning"),
    ("University of Oxford", "United Kingdom", "Fine Art / Art"),
    ("Technische Universität Wien", "Austria", "Computer Science / Artificial Intelligence"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    results = []
    for university, country, target_major in CASES:
        request = UniversityProgramRequest(
            target=ExploreTargetRequest(
                mode="explore",
                countries=[country],
                target_major=target_major,
                ranking=RankingScope(type="QS", basis="overall", min=1, max=500),
            ),
            university=CandidateUniversity(
                university=university,
                country=country,
                ranking=1,
                rank_display="1",
                rank_min=1,
                ranking_system="QS",
                ranking_basis="overall",
                ranking_edition=2027,
                ranking_source_url="local-regression-test",
            ),
        )
        try:
            result = await discover_candidate_programs(request)
            results.append(
                {
                    "university": university,
                    "target_major": target_major,
                    "programs": [item.model_dump() for item in result.candidates],
                }
            )
        except Exception as error:  # keep cases independent for diagnostics
            results.append(
                {
                    "university": university,
                    "target_major": target_major,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
