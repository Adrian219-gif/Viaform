"""Schema and compatibility checks for optional Requirement Chinese translations."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import RequirementItem, RequirementsExtraction  # noqa: E402


def numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def official_item(
    category: str,
    requirement: str,
    requirement_zh: Optional[str],
    importance: str,
) -> RequirementItem:
    return RequirementItem(
        category=category,
        requirement=requirement,
        requirement_zh=requirement_zh,
        importance=importance,
        source_level="program",
        source_type="official_retrieval",
        verification_status="official_verified",
        source_url="https://example.edu/programme",
    )


def main() -> None:
    language = official_item(
        "language",
        "IELTS overall 7.0 with at least 6.5 in each component.",
        "IELTS 总分 7.0，且各单项不低于 6.5。",
        "required",
    )
    assert numbers(language.requirement) == numbers(language.requirement_zh or "")
    assert "各单项" in (language.requirement_zh or "")

    academic = official_item(
        "academic",
        "A bachelor's degree in Computer Science or a closely related discipline is required.",
        "必须具有计算机科学或密切相关专业的本科学位。",
        "required",
    )
    assert "或" in (academic.requirement_zh or "")
    assert "必须" in (academic.requirement_zh or "")

    materials = official_item(
        "materials",
        "A portfolio is required; a CV is recommended.",
        "必须提交作品集；建议提交 CV。",
        "required",
    )
    assert "必须" in (materials.requirement_zh or "")
    assert "建议" in (materials.requirement_zh or "")

    legacy = RequirementItem.model_validate(
        {
            "category": "course",
            "requirement": "Prior coursework is required.",
            "importance": "required",
            "source_level": "program",
            "source_type": "official_retrieval",
            "verification_status": "official_verified",
            "source_url": "https://example.edu/programme",
        }
    )
    assert legacy.requirement_zh is None

    extraction = RequirementsExtraction(
        requirements=[language, academic, materials, legacy]
    )
    round_trip = RequirementsExtraction.model_validate_json(
        extraction.model_dump_json()
    )
    assert round_trip.requirements[-1].requirement_zh is None
    print("requirement translation schema regressions: all checks passed")


if __name__ == "__main__":
    main()
