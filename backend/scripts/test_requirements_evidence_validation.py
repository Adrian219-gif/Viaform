"""Deterministic negative checks for Phase B Requirements evidence validation."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import (  # noqa: E402
    classify_requirement_lifecycle,
    domain_is_allowed,
    normalized_hostname,
    readable_requirements_page_text,
    requirement_evidence_supports,
    requirements_http_response_is_usable,
)


def main() -> None:
    assert requirement_evidence_supports(
        "IELTS overall 7.0 with a minimum 6.5 in each component",
        "English language evidence. IELTS overall 7.0 with at least 6.5 in each component.",
    )
    assert not requirement_evidence_supports(
        "IELTS overall 7.0 with a minimum 6.5 in each component",
        "IELTS is accepted. The programme has 7.0 modules and tuition is split into 6.5 units.",
    )
    assert not requirement_evidence_supports(
        "GRE is not required",
        "The admissions page describes academic transcripts and references but does not mention GRE.",
    )

    mixed_policy = (
        "Minimum score for admission consideration: IELTS Academic 7.0.\n"
        "Applicants with IELTS 8.0 are exempt from the English Placement Test."
    )
    assert classify_requirement_lifecycle(
        "Minimum score for admission consideration: IELTS Academic 7.0.",
        "https://example.edu/admissions/english-policy",
        "English proficiency policy",
        mixed_policy,
    ) == "application_stage"
    assert classify_requirement_lifecycle(
        "IELTS 8.0 exempts admitted students from the English Placement Test.",
        "https://example.edu/admissions/english-policy",
        "English proficiency policy",
        mixed_policy,
    ) == "post_admission"
    assert classify_requirement_lifecycle(
        "Students must complete 45 units to graduate.",
        "https://example.edu/program/degree-requirements",
        "Degree requirements",
        "Students must complete 45 units to graduate with the master's degree.",
    ) == "degree_completion"
    assert classify_requirement_lifecycle(
        "A score report is described on this page.",
        "https://example.edu/information",
        "Information",
        "A score report is described on this page.",
    ) == "unclear"
    assert classify_requirement_lifecycle(
        "Applicants must submit an IELTS score with the application.",
        "https://example.edu/admitted-students/combined-policy",
        "Combined English policy",
        mixed_policy + "\nApplicants must submit an IELTS score with the application.",
    ) == "application_stage"

    allowed_domains = {"ox.ac.uk"}
    assert domain_is_allowed("www.ox.ac.uk", allowed_domains)
    assert not domain_is_allowed(
        normalized_hostname("https://www.example-study-platform.com/oxford"),
        allowed_domains,
    )
    assert not domain_is_allowed(
        normalized_hostname("https://www.cam.ac.uk/redirect-target"),
        allowed_domains,
    )
    allowed_response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        text="<html><h1>Oxford programme</h1></html>",
        request=httpx.Request("GET", "https://www.ox.ac.uk/programme"),
    )
    third_party_response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        text="<html><h1>Oxford programme requirements</h1></html>",
        request=httpx.Request("GET", "https://www.example-study-platform.com/oxford"),
    )
    redirected_outside_response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        text="<html><h1>Programme requirements</h1></html>",
        request=httpx.Request("GET", "https://www.cam.ac.uk/redirect-target"),
    )
    assert requirements_http_response_is_usable(allowed_response, allowed_domains)
    assert not requirements_http_response_is_usable(
        third_party_response,
        allowed_domains,
    )
    assert not requirements_http_response_is_usable(
        redirected_outside_response,
        allowed_domains,
    )

    cleaned = readable_requirements_page_text(
        "<html><header>Navigation</header><main><h1>Entry requirements</h1>"
        "<p>An upper second-class degree is required.</p><ul><li>Portfolio</li>"
        "</ul></main><footer>Footer links</footer></html>"
    )
    assert "Navigation" not in cleaned
    assert "Footer links" not in cleaned
    assert "Entry requirements" in cleaned
    assert "upper second-class degree" in cleaned
    assert "Portfolio" in cleaned
    print("requirements evidence validation: all deterministic checks passed")


if __name__ == "__main__":
    main()
