"""Live Phase B regression checks for Target Program Requirements retrieval."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import TargetProgram, retrieve_target_program_requirements  # noqa: E402


CASES = [
    TargetProgram(
        university="Imperial College London",
        program="Applied Machine Learning MSc",
        official_program_url=(
            "https://www.imperial.ac.uk/study/courses/postgraduate-taught/"
            "applied-machine-learning/"
        ),
        official_domain="imperial.ac.uk",
    ),
    TargetProgram(
        university="University of Oxford",
        program="Master of Fine Art (MFA)",
        official_program_url=(
            "https://www.ox.ac.uk/admissions/graduate/courses/mfa-fine-art"
        ),
        official_domain="ox.ac.uk",
    ),
    TargetProgram(
        university="Technische Universität Wien",
        program="Logic and Artificial Intelligence",
        official_program_url=(
            "https://informatics.tuwien.ac.at/master/"
            "logic-and-artificial-intelligence/"
        ),
        official_domain="tuwien.ac.at",
    ),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    reports = []
    requested_case = " ".join(sys.argv[1:]).strip().casefold()
    selected_cases = [
        target
        for target in CASES
        if not requested_case
        or requested_case in f"{target.university} {target.program}".casefold()
    ]
    for target in selected_cases:
        started_at = time.perf_counter()
        try:
            review = await retrieve_target_program_requirements(target)
            items = [
                item.model_dump()
                for category in review.categories
                for item in category.requirements
            ]
            reports.append(
                {
                    "university": target.university,
                    "program": target.program,
                    "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                    "coverage": {
                        category.category: category.coverage
                        for category in review.categories
                    },
                    "official_evidence_urls": sorted(
                        {
                            item["source_url"]
                            for item in items
                            if item["verification_status"] == "official_verified"
                            and item["source_url"]
                        }
                    ),
                    "requirements": items,
                }
            )
        except Exception as error:  # keep live cases independent for diagnostics
            reports.append(
                {
                    "university": target.university,
                    "program": target.program,
                    "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
