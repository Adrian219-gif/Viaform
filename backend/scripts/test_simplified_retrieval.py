"""Regression checks for the model-owned retrieval data flow."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


def university() -> application.CandidateUniversity:
    return application.CandidateUniversity(
        university="Example University",
        country="英国",
        ranking=12,
        rank_display="12",
        rank_min=12,
        ranking_edition=2027,
        ranking_source_url="",
    )


async def run() -> None:
    original = application.call_deepseek_web_search
    calls: list[type[application.BaseModel]] = []
    prompts: list[str] = []

    async def fake_search(prompt, output_model, **kwargs):
        calls.append(output_model)
        prompts.append(prompt)
        if output_model is application.SchoolOfficialUrlOutput:
            return application.SchoolOfficialUrlOutput(
                schools=[
                    application.SchoolOfficialUrl(
                        index=0,
                        school_official_url="https://model-selected.example.edu/",
                    )
                ]
            )
        if output_model is application.ProgramDiscoveryWebSearchOutput:
            return application.ProgramDiscoveryWebSearchOutput(
                programs=[
                    application.WebSearchProgramCandidate(
                        program="MSc Example Studies",
                        official_program_url="https://programs.example.edu/msc-example",
                        degree_type="MSc",
                        relevance_reason="Matches the intended field.",
                    )
                ]
            )
        if output_model is application.TargetProgramLookupOutput:
            return application.TargetProgramLookupOutput(
                program="MSc Identified Programme",
                official_program_url="https://elsewhere.example/programme",
            )
        if output_model is application.RequirementsExtraction:
            return application.RequirementsExtraction(
                requirements=[
                    application.RequirementItem(
                        category="language",
                        requirement="IELTS 7.0 overall is required.",
                        requirement_zh="IELTS 总分须达到 7.0。",
                        importance="required",
                        source_level="program",
                        source_type="official_retrieval",
                        verification_status="official_verified",
                        source_url="https://reference.example/requirements",
                    ),
                    application.RequirementItem(
                        category="materials",
                        requirement="A portfolio may be required.",
                        requirement_zh="可能需要提交作品集。",
                        importance="unknown",
                        source_level="unknown",
                        source_type="model_memory",
                        verification_status="model_memory_unverified",
                        source_url="https://public-reference.example/portfolio",
                    ),
                ]
            )
        raise AssertionError(output_model)

    application.call_deepseek_web_search = fake_search
    try:
        school = university()
        enriched = await application.enrich_school_official_urls([school])
        assert enriched[0].school_official_url == "https://model-selected.example.edu/"

        request = application.UniversityProgramRequest(
            target=application.ExploreTargetRequest(
                mode="explore",
                target_major="Example Studies",
                ranking=application.RankingScope(type="QS", min=1, max=20),
            ),
            university=enriched[0],
        )
        programmes = await application.discover_candidate_programs(request)
        assert programmes.candidates[0].official_program_url == (
            "https://programs.example.edu/msc-example"
        )

        selected = await application.confirm_target_program(
            application.TargetProgramConfirmationRequest(
                university="Example University",
                program="MSc Example Studies",
                official_program_url="https://programs.example.edu/msc-example",
            )
        )
        assert selected.program == "MSc Example Studies"
        assert calls.count(application.TargetProgramLookupOutput) == 0

        identified = await application.confirm_target_program(
            application.TargetProgramConfirmationRequest(
                university="Example University",
                official_program_url="https://elsewhere.example/programme",
            )
        )
        assert identified.program == "MSc Identified Programme"

        review = await application.retrieve_target_program_requirements(selected)
        language = next(item for item in review.categories if item.category == "language")
        assert language.coverage == "official_verified"
        assert language.requirements[0].source_url == (
            "https://reference.example/requirements"
        )
        materials = next(item for item in review.categories if item.category == "materials")
        assert materials.coverage == "model_memory_unverified"
        assert materials.requirements[0].source_url == (
            "https://public-reference.example/portfolio"
        )
        assert materials.requirements[0].requirement_zh
        assert len(review.categories) == 7
        requirements_prompt = next(
            prompt for prompt in prompts if "Requirements snapshot" in prompt
        )
        assert "403/WAF" in requirements_prompt
        assert "do not automatically omit" in requirements_prompt
        assert "existing knowledge" in requirements_prompt
        assert "Only omit a category" in requirements_prompt

        ai_only = application.requirements_review_from_extraction(
            selected,
            application.RequirementsExtraction(
                requirements=[
                    application.RequirementItem(
                        category="language",
                        requirement="IELTS 7.0 may be expected.",
                        requirement_zh="可能要求 IELTS 7.0。",
                        importance="unknown",
                        source_level="unknown",
                        source_type="model_memory",
                        verification_status="model_memory_unverified",
                        source_url=None,
                    )
                ]
            ),
        )
        ai_language = next(
            item for item in ai_only.categories if item.category == "language"
        )
        assert ai_language.coverage == "model_memory_unverified"

        empty = application.requirements_review_from_extraction(
            selected,
            application.RequirementsExtraction(),
        )
        assert all(category.coverage == "not_found" for category in empty.categories)
    finally:
        application.call_deepseek_web_search = original


if __name__ == "__main__":
    asyncio.run(run())
    print("simplified retrieval checks passed")
