"""Deterministic regressions for Requirements AI Reference fallback semantics."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


TARGET = application.TargetProgram(
    university="Example University",
    program="Example MSc",
    official_program_url="https://example.edu/programme",
    official_domain="example.edu",
)
SITE = application.VerifiedOfficialDomain(
    university=TARGET.university,
    official_domain="example.edu",
    official_url="https://example.edu/",
    evidence_type="result_url",
    evidence_source_url="https://example.edu/",
)


def requirement(
    category: str,
    text: str,
    status: str,
    source_url: str | None = None,
) -> application.RequirementItem:
    official = status == "official_verified"
    return application.RequirementItem(
        category=category,
        requirement=text,
        requirement_zh=f"中文：{text}",
        importance="required",
        source_level="program" if official else "unknown",
        source_type="official_retrieval" if official else "model_memory",
        verification_status=status,
        source_url=source_url,
    )


async def check_fallback_verification() -> None:
    original_fetch = application.fetch_requirement_evidence_pages
    official_url = "https://example.edu/apply/test-scores"
    post_url = "https://example.edu/admitted-students/placement"

    async def fake_fetch(
        source_urls: list[str],
        source_levels: dict[str, str],
        allowed_domains: set[str],
        attempted: set[tuple[str, str]],
    ) -> tuple[dict[str, application.RequirementEvidenceItem], int, int, float]:
        fetched = {
            official_url: application.RequirementEvidenceItem(
                url=official_url,
                resolved_url=official_url,
                title="Application test score requirements",
                content="Applicants must submit IELTS 7.0 with the application.",
                source_level="university",
                evidence_type="web_search",
            ),
            post_url: application.RequirementEvidenceItem(
                url=post_url,
                resolved_url=post_url,
                title="English Placement Test for admitted students",
                content="Admitted students with IELTS below 8.0 take the English Placement Test.",
                source_level="university",
                evidence_type="web_search",
            ),
        }
        return ({url: fetched[url] for url in source_urls}, len(source_urls), 0, 0.01)

    result = application.RequirementsWebSearchResult(
        web_search_used=True,
        evidence=[
            application.WebSearchEvidence(title="Application test scores", url=official_url),
            application.WebSearchEvidence(title="Placement", url=post_url),
        ],
        structured_output=application.RequirementsExtraction(
            requirements=[
                requirement(
                    "language",
                    "Applicants must submit IELTS 7.0 with the application.",
                    "official_verified",
                    official_url,
                ),
                requirement(
                    "language",
                    "IELTS 8.0 exempts admitted students from the English Placement Test.",
                    "official_verified",
                    post_url,
                ),
                requirement(
                    "standardized_test",
                    "GRE may be required.",
                    "model_memory_unverified",
                ),
            ]
        ),
    )
    try:
        application.fetch_requirement_evidence_pages = fake_fetch
        official, references, _, _ = await application.verify_reference_fallback_result(
            result,
            TARGET,
            {"example.edu"},
        )
    finally:
        application.fetch_requirement_evidence_pages = original_fetch

    assert len(official) == 1 and "7.0" in official[0].requirement
    assert len(references) == 2
    assert all(item.verification_status == "model_memory_unverified" for item in references)
    assert all(item.source_url is None for item in references)


async def check_trigger_and_failure_safety() -> None:
    originals = {
        "resolve": application.resolve_official_domain,
        "affiliated": application.get_verified_affiliated_domains,
        "direct": application.fetch_program_requirements_page,
        "first": application.deepseek_requirements_web_search,
        "fallback": application.run_reference_fallback,
    }

    async def resolve(_: str) -> application.VerifiedOfficialDomain:
        return SITE

    async def no_direct(*args: object) -> None:
        return None

    async def first_official(*args: object) -> application.RequirementsWebSearchResult:
        url = "https://example.edu/admissions"
        return application.RequirementsWebSearchResult(
            web_search_used=True,
            evidence=[
                application.WebSearchEvidence(
                    title="Graduate admissions",
                    url=url,
                    snippet="Applicants must hold a recognized bachelor's degree.",
                )
            ],
            structured_output=application.RequirementsExtraction(
                requirements=[
                    requirement(
                        "academic",
                        "Applicants must hold a recognized bachelor's degree.",
                        "official_verified",
                        url,
                    )
                ]
            ),
        )

    async def fallback_error(*args: object) -> object:
        raise application.HTTPException(status_code=502, detail="fallback failed")

    try:
        application.resolve_official_domain = resolve
        application.get_verified_affiliated_domains = lambda *_: []
        application.fetch_program_requirements_page = no_direct
        application.deepseek_requirements_web_search = first_official
        application.run_reference_fallback = fallback_error
        review = await application.retrieve_target_program_requirements(TARGET)
        academic = next(item for item in review.categories if item.category == "academic")
        assert academic.coverage == "official_verified"

        async def first_post_admission(*args: object) -> application.RequirementsWebSearchResult:
            url = "https://example.edu/admitted-students/placement"
            return application.RequirementsWebSearchResult(
                web_search_used=True,
                evidence=[
                    application.WebSearchEvidence(
                        title="English Placement Test for admitted students",
                        url=url,
                        snippet=(
                            "Admitted students with IELTS below 8.0 take the English "
                            "Placement Test."
                        ),
                    )
                ],
                structured_output=application.RequirementsExtraction(
                    requirements=[
                        requirement(
                            "language",
                            "IELTS 8.0 exempts admitted students from the English Placement Test.",
                            "official_verified",
                            url,
                        )
                    ]
                ),
            )

        ai_language = requirement(
            "language",
            "IELTS 7.0 may be required for application.",
            "model_memory_unverified",
        )

        async def fallback_reference(
            target: application.TargetProgram,
            domains: set[str],
            official: list[application.RequirementItem],
            missing: list[str],
        ) -> tuple[
            application.RequirementsWebSearchResult,
            list[application.RequirementItem],
            list[application.RequirementItem],
            int,
            int,
        ]:
            assert "language" in missing
            return application.RequirementsWebSearchResult(), [], [ai_language], 0, 0

        application.deepseek_requirements_web_search = first_post_admission
        application.run_reference_fallback = fallback_reference
        review = await application.retrieve_target_program_requirements(TARGET)
        language = next(item for item in review.categories if item.category == "language")
        assert language.coverage == "model_memory_unverified"
        assert len(language.requirements) == 1
    finally:
        application.resolve_official_domain = originals["resolve"]
        application.get_verified_affiliated_domains = originals["affiliated"]
        application.fetch_program_requirements_page = originals["direct"]
        application.deepseek_requirements_web_search = originals["first"]
        application.run_reference_fallback = originals["fallback"]


def check_topic_merge() -> None:
    official_ielts = requirement(
        "language",
        "IELTS overall 7.0 is required.",
        "official_verified",
        "https://example.edu/apply/language",
    )
    reference_ielts = requirement(
        "language",
        "IELTS 7.5 may be required.",
        "model_memory_unverified",
    )
    official_transcript = requirement(
        "materials",
        "Transcript required.",
        "official_verified",
        "https://example.edu/apply/materials",
    )
    reference_letters = requirement(
        "materials",
        "Two recommendation letters may be required.",
        "model_memory_unverified",
    )
    official, references = application.merge_requirements_by_provenance(
        [official_ielts, official_transcript],
        [reference_ielts, reference_letters],
    )
    assert len(official) == 2
    assert len(references) == 1
    assert "recommendation" in references[0].requirement.casefold()

    official_references = requirement(
        "materials",
        "Two academic references are required.",
        "official_verified",
        "https://example.edu/apply/materials",
    )
    _, duplicate_references = application.merge_requirements_by_provenance(
        [official_references],
        [reference_letters],
    )
    assert not duplicate_references


async def main() -> None:
    check_topic_merge()
    await check_fallback_verification()
    await check_trigger_and_failure_safety()
    empty = application.RequirementsWebSearchResult(
        structured_output=application.RequirementsExtraction(requirements=[])
    )
    official, references, _, _ = await application.verify_reference_fallback_result(
        empty,
        TARGET,
        {"example.edu"},
    )
    assert not official and not references
    print("requirements fallback regressions: all deterministic checks passed")


if __name__ == "__main__":
    asyncio.run(main())
