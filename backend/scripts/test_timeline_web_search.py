"""One live Application Timeline smoke test using DeepSeek Web Search."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import (  # noqa: E402
    ApplicationTimelineRequest,
    retrieve_application_timeline,
)


async def main() -> None:
    request = ApplicationTimelineRequest(
        university="Imperial College London",
        program_name="Applied Machine Learning MSc",
        official_program_url=(
            "https://www.imperial.ac.uk/study/courses/postgraduate-taught/"
            "applied-machine-learning/"
        ),
        intended_entry_year=2027,
        intended_entry_term="fall",
    )
    started_at = time.perf_counter()
    timeline = await retrieve_application_timeline(request)
    print(
        json.dumps(
            {
                "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                "timeline": timeline.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
