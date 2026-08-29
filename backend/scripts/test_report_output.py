"""Regression for UTF-8 acceptance report output on a simulated Windows GBK stdout."""

from __future__ import annotations

import io
import json

from report_output import print_json_report


def main() -> None:
    raw = io.BytesIO()
    gbk_stdout = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
    report = {
        "case": "Oxford MSc Advanced Computer Science",
        "requirement": "Application fee: £75",
        "temporal_applicability": "previous_cycle",
    }

    print_json_report(report, stream=gbk_stdout)
    gbk_stdout.flush()
    encoded = raw.getvalue()

    assert encoded.decode("utf-8")
    assert json.loads(encoded.decode("utf-8")) == report
    assert gbk_stdout.encoding.casefold() == "utf-8"
    print("UTF-8 report output regression: PASS")


if __name__ == "__main__":
    main()

