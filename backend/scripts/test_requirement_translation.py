"""Schema and compatibility checks for optional Requirement Chinese translations."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Optional


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pydantic import ValidationError  # noqa: E402

from app.main import RequirementItem, RequirementsExtraction  # noqa: E402


class WarningCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


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
        temporal_applicability="undated",
    )


def check_importance_enum_compatibility() -> None:
    capture = WarningCapture()
    logger = logging.getLogger("app.main")
    logger.addHandler(capture)
    try:
        alias = official_item(
            "materials",
            "A programme-specific form is required when the stated condition applies.",
            None,
            "conditional_required",  # type: ignore[arg-type]
        )
    finally:
        logger.removeHandler(capture)
    assert alias.importance == "required"
    assert any(
        "requirements_importance_alias" in message
        and "conditional_required" in message
        for message in capture.messages
    )

    for importance in ("required", "recommended", "preferred", "unknown"):
        assert official_item("materials", "Example requirement.", None, importance).importance == importance

    try:
        official_item(
            "materials",
            "Example requirement.",
            None,
            "mandatory",  # type: ignore[arg-type]
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("unknown importance values must not pass validation")


def main() -> None:
    check_importance_enum_compatibility()

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
            "temporal_applicability": "undated",
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
