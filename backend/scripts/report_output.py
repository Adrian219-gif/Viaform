"""UTF-8 JSON report output shared by local regression and acceptance runners."""

from __future__ import annotations

import json
import sys
from typing import Any, Optional, TextIO


def configure_utf8_stdout(stream: Optional[TextIO] = None) -> TextIO:
    """Use UTF-8 explicitly on Windows Python 3.8 instead of the active code page."""
    output = stream or sys.stdout
    reconfigure = getattr(output, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="strict")
    return output


def print_json_report(payload: Any, *, stream: Optional[TextIO] = None) -> None:
    output = configure_utf8_stdout(stream)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=output)

