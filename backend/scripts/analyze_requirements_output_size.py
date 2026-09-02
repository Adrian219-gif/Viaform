"""Measure cached Requirements payload sizes without calling an API."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict


BACKEND_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DB = BACKEND_DIR / "data" / "runtime" / "programme_cache.sqlite"

CASES = {
    "Oxford": ("msc by research in biology", 2),
    "KTH": ("master's programme in computer science", 1),
}


def compact_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def measure(label: str, payload: Dict[str, Any], search_uses: int) -> Dict[str, Any]:
    requirements = [
        item
        for category in payload.get("categories", [])
        for item in category.get("requirements", [])
    ]
    model_projection = {
        "requirements": requirements,
        "search_audit": {
            "search_attempts_completed": search_uses,
            "programme_page_checked": True,
            "sections_checked": [],
            "programme_page_has_no_extractable_requirements": False,
            "empty_result_reason": None,
        },
    }
    compact = json.dumps(
        model_projection,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    english_chars = sum(len(item.get("requirement") or "") for item in requirements)
    chinese_chars = sum(len(item.get("requirement_zh") or "") for item in requirements)
    source_chars = sum(
        len(item.get("source_url") or "")
        + len(item.get("source_cycle") or "")
        + len(item.get("temporal_note") or "")
        for item in requirements
    )
    named_content_chars = english_chars + chinese_chars + source_chars
    return {
        "case": label,
        "checked_at": payload.get("checked_at"),
        "requirement_count": len(requirements),
        "cached_review_compact_json_chars": compact_chars(payload),
        "model_output_projection_compact_json_chars": len(compact),
        "model_output_projection_utf8_bytes": len(compact.encode("utf-8")),
        "approx_tokens_chars_div_4": round(len(compact) / 4),
        "approx_tokens_utf8_bytes_div_4": round(len(compact.encode("utf-8")) / 4),
        "requirement_english_chars": english_chars,
        "requirement_zh_chars": chinese_chars,
        "source_cycle_note_chars": source_chars,
        "json_keys_enums_structure_chars": len(compact) - named_content_chars,
    }


def main() -> None:
    connection = sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True)
    reports = []
    for label, (programme_marker, search_uses) in CASES.items():
        row = connection.execute(
            "SELECT payload_json FROM programme_cache "
            "WHERE cache_kind = 'requirements' "
            "AND lower(payload_json) LIKE ? ORDER BY checked_at DESC LIMIT 1",
            (f"%{programme_marker}%",),
        ).fetchone()
        if row is None:
            raise AssertionError(f"missing cached Requirements snapshot for {label}")
        reports.append(measure(label, json.loads(row[0]), search_uses))
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
