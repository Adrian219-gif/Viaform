"""Live ownership regressions for same-institution affiliated domains."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import (  # noqa: E402
    TargetProgramConfirmationRequest,
    WebSearchEvidence,
    confirm_target_program,
    get_verified_affiliated_domains,
    resolve_official_domain,
    verify_affiliated_official_domain,
    verify_target_program_url,
)


NEGATIVE_CASES = [
    (
        "KTH Royal Institute of Technology",
        "https://stuex.nju.edu.cn/",
        "Third-party exchange page that may mention the complete institution name",
    ),
    (
        "University of Oxford",
        "https://www.oxfordma.us/",
        "Municipal site with a high-ambiguity place name",
    ),
    (
        "Sapienza University of Rome",
        "https://backcheckgroup.com/product/sapienza-university-of-rome/",
        "Third-party page whose path and content identify the target university",
    ),
    (
        "University of Oxford",
        "https://www.mastersportal.com/universities/384/university-of-oxford.html",
        "Excluded third-party platform with the complete university name",
    ),
]

OFFICIAL_DOMAIN_CASES = [
    "KTH Royal Institute of Technology",
    "University of Oxford",
    "University of Amsterdam",
    "Technische Universität Wien",
    "Sapienza University of Rome",
    "Royal College of Art",
    "Imperial College London",
]


async def main() -> None:
    negative_results = []
    for institution, candidate_url, description in NEGATIVE_CASES:
        primary = await resolve_official_domain(institution)
        if primary is None:
            negative_results.append(
                {
                    "institution": institution,
                    "candidate_url": candidate_url,
                    "description": description,
                    "error": "primary official domain unavailable",
                }
            )
            continue
        result = await verify_affiliated_official_domain(
            institution,
            primary.official_domain,
            primary.official_url,
            candidate_url,
            [
                WebSearchEvidence(
                    title=f"{institution} official information",
                    url=candidate_url,
                    snippet=f"This page explicitly mentions {institution}.",
                )
            ],
        )
        negative_results.append(
            {
                "institution": institution,
                "primary_domain": primary.official_domain,
                "candidate_url": candidate_url,
                "description": description,
                "accepted": result is not None,
            }
        )

    official_results = []
    for institution in OFFICIAL_DOMAIN_CASES:
        result = await resolve_official_domain(institution)
        official_results.append(
            {
                "institution": institution,
                "official_domain": result.official_domain if result else None,
                "verification_version": result.verification_version if result else None,
            }
        )

    tu_affiliates = get_verified_affiliated_domains(
        "Technische Universität Wien",
        "tuwien.at",
    )
    programme_checks = []
    for program, url, allowed_domain in [
        (
            "Logic and Artificial Intelligence",
            "https://informatics.tuwien.ac.at/master/logic-and-artificial-intelligence/",
            "tuwien.ac.at",
        ),
        (
            "Computer Science",
            "https://www.tuwien.at/en/studies/studies/master-programmes/computer-science",
            "tuwien.at",
        ),
    ]:
        confirmed, status = await verify_target_program_url(
            "Technische Universität Wien",
            program,
            url,
            allowed_domain,
        )
        programme_checks.append(
            {
                "input_program": program,
                "url": url,
                "status": status,
                "confirmed_program": confirmed.program if confirmed else None,
            }
        )

    selected_target = await confirm_target_program(
        TargetProgramConfirmationRequest(
            university="Technische Universität Wien",
            program="Logic and Artificial Intelligence",
            official_program_url=(
                "https://informatics.tuwien.ac.at/master/"
                "logic-and-artificial-intelligence/"
            ),
        )
    )
    print(
        json.dumps(
            {
                "negative_cases": negative_results,
                "official_domain_v3": official_results,
                "tu_wien_affiliated_cache": [item.model_dump() for item in tu_affiliates],
                "tu_wien_programme_checks": programme_checks,
                "tu_wien_target_confirmation": selected_target.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
