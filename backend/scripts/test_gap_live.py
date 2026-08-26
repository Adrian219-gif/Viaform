"""Live no-search regression for Gap planning and batched semantic matching."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import (  # noqa: E402
    Education,
    GapAnalysisRequest,
    GapEvidenceNeed,
    GapEvidenceParseRequest,
    GapPlanRequest,
    GapPlannerQuestion,
    RequirementCategoryReview,
    RequirementItem,
    TargetProgram,
    TargetProgramRequirementsReview,
    UserProfile,
    analyze_gap,
    build_gap_plan,
    parse_gap_evidence,
)


def requirement(
    category: str,
    text: str,
    importance: str = "required",
    status: str = "official_verified",
) -> RequirementItem:
    return RequirementItem(
        category=category,
        requirement=text,
        importance=importance,
        source_level="program" if status == "official_verified" else "unknown",
        source_type="official_retrieval" if status == "official_verified" else "model_memory",
        verification_status=status,
        source_url="https://example.edu/programme" if status == "official_verified" else None,
    )


def review(target: TargetProgram, items: list[RequirementItem]) -> TargetProgramRequirementsReview:
    categories = []
    for category in {item.category for item in items}:
        category_items = [item for item in items if item.category == category]
        coverage = (
            "official_verified"
            if any(item.verification_status == "official_verified" for item in category_items)
            else "model_memory_unverified"
        )
        categories.append(
            RequirementCategoryReview(
                category=category,
                coverage=coverage,
                requirements=category_items,
            )
        )
    return TargetProgramRequirementsReview(
        target_program=target,
        checked_at="2026-08-24T00:00:00Z",
        categories=categories,
    )


async def semantic_case() -> dict:
    target = TargetProgram(
        university="Example University",
        program="Computer Science MSc",
        official_program_url="https://example.edu/programme",
        official_domain="example.edu",
    )
    current_profile = UserProfile(
        education=Education(
            university="Example Undergraduate University",
            major="Software Engineering",
            courses=["Matrix Algebra：vectors, matrices, eigenvalues and linear systems"],
        )
    )
    requirements = review(
        target,
        [
            requirement("academic", "A bachelor's degree in Computer Science or a closely related discipline is required."),
            requirement("course", "Prior university-level coursework covering Linear Algebra is required."),
            requirement("other", "Application processing takes approximately six weeks."),
            requirement("standardized_test", "GRE may historically be expected.", status="model_memory_unverified"),
        ],
    )
    plan = await build_gap_plan(
        GapPlanRequest(
            target_program=target,
            requirements_review=requirements,
            user_profile=current_profile,
        )
    )
    analysis = await analyze_gap(
        GapAnalysisRequest(
            target_program=target,
            plan=plan,
            user_profile=current_profile,
        )
    )
    return {
        "case": "semantic_major_course",
        "planning_calls": plan.planning_llm_requests,
        "semantic_calls": analysis.semantic_llm_requests,
        "questions": [item.model_dump() for item in plan.questions],
        "plan": [item.model_dump() for item in plan.requirements],
        "results": [item.model_dump() for item in analysis.results],
        "informational": [item.requirement for item in analysis.informational_requirements],
    }


async def requirement_driven_case(
    case_name: str,
    target: TargetProgram,
    requirements: list[RequirementItem],
    answer: str,
) -> dict:
    requirements_review = review(target, requirements)
    plan = await build_gap_plan(
        GapPlanRequest(
            target_program=target,
            requirements_review=requirements_review,
            user_profile=UserProfile(),
        )
    )
    collected = []
    needs_by_key = {
        need.key: need
        for item in plan.requirements
        for need in item.evidence_needs
    }
    for question in plan.questions:
        needs = [needs_by_key[key] for key in question.evidence_keys if key in needs_by_key]
        parsed = parse_gap_evidence(
            GapEvidenceParseRequest(
                question=GapPlannerQuestion.model_validate(question),
                evidence_needs=[GapEvidenceNeed.model_validate(item) for item in needs],
                answer=answer,
            )
        )
        collected.extend(parsed.evidence)
    analysis = await analyze_gap(
        GapAnalysisRequest(
            target_program=target,
            plan=plan,
            user_profile=UserProfile(),
            user_evidence=collected,
        )
    )
    return {
        "case": case_name,
        "planning_calls": plan.planning_llm_requests,
        "semantic_calls": analysis.semantic_llm_requests,
        "questions": [item.model_dump() for item in plan.questions],
        "evidence": [item.model_dump() for item in collected],
        "results": [item.model_dump() for item in analysis.results],
    }


async def main() -> None:
    requested_case = " ".join(sys.argv[1:]).strip().casefold()
    oxford = TargetProgram(
        university="University of Oxford",
        program="Master of Fine Art (MFA)",
        official_program_url="https://www.rsa.ox.ac.uk/study/mfa/applying-to-study-for-an-mfa",
        official_domain="ox.ac.uk",
    )
    tu_wien = TargetProgram(
        university="Technische Universität Wien",
        program="Logic and Artificial Intelligence",
        official_program_url="https://informatics.tuwien.ac.at/master/logic-and-artificial-intelligence/",
        official_domain="tuwien.ac.at",
    )
    reports = []
    if not requested_case or "semantic" in requested_case:
        reports.append(await semantic_case())
    if not requested_case or "oxford" in requested_case:
        reports.append(await requirement_driven_case(
            "oxford_mfa",
            oxford,
            [
                requirement(
                    "materials",
                    "Applicants must provide a portfolio link, a statement of purpose and referee supporting statements; incomplete applications are not assessed.",
                )
            ],
            "作品集和个人陈述已准备，目前有 1 位推荐人。",
        ))
    if not requested_case or "wien" in requested_case or "tu" == requested_case:
        reports.append(await requirement_driven_case(
            "tu_wien_language",
            tu_wien,
            [
                requirement(
                    "language",
                    "English proficiency at CEFR level B2 is required for this English-taught programme.",
                ),
                requirement(
                    "standardized_test",
                    "GRE may not usually be required.",
                    status="model_memory_unverified",
                ),
            ],
            "我有 IELTS 7.0，但不记得小分。",
        ))
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
