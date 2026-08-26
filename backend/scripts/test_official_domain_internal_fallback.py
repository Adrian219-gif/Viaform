"""Deterministic regressions for same-root official-domain evidence fallback."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main as application  # noqa: E402


def search_result(evidence: list[application.WebSearchEvidence]):
    return application.OfficialDomainWebSearchResult(
        web_search_used=True,
        web_search_requests=1,
        evidence=evidence,
        structured_output=application.OfficialDomainWebSearchOutput(
            canonical_name="Example University",
            local_name="Example University",
            aliases=["Example U"],
            candidate_domain="example.edu",
            candidate_official_url="https://www.example.edu/",
        ),
    )


async def run_case(
    name: str,
    evidence: list[application.WebSearchEvidence],
    verifier,
    expected_domain: str | None,
    expected_urls: list[str],
    failure_reasons: dict[str, str] | None = None,
) -> None:
    originals = {
        "cached": application.get_cached_official_domain,
        "stale": application.get_any_cached_official_domain,
        "search": application.deepseek_official_domain_web_search,
        "verify": application.verify_official_domain_candidate,
        "cache": application.cache_official_domain,
        "bocha": application.bocha_search,
    }
    calls: list[str] = []
    cached: list[application.VerifiedOfficialDomain] = []

    async def wrapped_verifier(university, candidate_url, *args, **kwargs):
        calls.append(candidate_url)
        result = await verifier(candidate_url)
        if not result and kwargs.get("failure_reason") is not None:
            kwargs["failure_reason"]["reason"] = (failure_reasons or {}).get(
                candidate_url,
                "identity_mismatch",
            )
        return result

    try:
        application.get_cached_official_domain = lambda university: None
        application.get_any_cached_official_domain = lambda university: None

        async def fake_search(institution_name, country_region=""):
            return search_result(evidence)

        async def fake_bocha(query, count=10):
            return []

        application.deepseek_official_domain_web_search = fake_search
        application.verify_official_domain_candidate = wrapped_verifier
        application.cache_official_domain = cached.append
        application.bocha_search = fake_bocha

        result = await application.resolve_official_domain("Example University")
        actual_domain = result.official_domain if result else None
        assert actual_domain == expected_domain, (name, actual_domain)
        assert calls == expected_urls, (name, calls)
        assert bool(cached) == bool(expected_domain), (name, cached)
        print(f"PASS {name}")
    finally:
        application.get_cached_official_domain = originals["cached"]
        application.get_any_cached_official_domain = originals["stale"]
        application.deepseek_official_domain_web_search = originals["search"]
        application.verify_official_domain_candidate = originals["verify"]
        application.cache_official_domain = originals["cache"]
        application.bocha_search = originals["bocha"]


async def main() -> None:
    internal = application.WebSearchEvidence(
        title="Example University Graduate Division",
        url="https://grad.example.edu/admissions/",
        snippet="Official graduate division of Example University.",
    )
    ambiguous = application.WebSearchEvidence(
        title="Admissions information",
        url="https://catalog.example.edu/programs/",
        snippet="Programme listings.",
    )
    third_party = application.WebSearchEvidence(
        title="Example University profile",
        url="https://rankings.example.com/example-university",
        snippet="A third-party page mentioning Example University.",
    )
    root = application.WebSearchEvidence(
        title="Example University",
        url="https://www.example.edu/",
        snippet="Official website of Example University.",
    )

    async def root_success(url):
        return ("example.edu", url) if url == root.url else None

    await run_case(
        "root_200_original_flow",
        [root, internal],
        root_success,
        "example.edu",
        [root.url],
    )

    async def internal_success(url):
        return ("example.edu", url) if url == internal.url else None

    await run_case(
        "root_403_internal_identity_success",
        [root, internal],
        internal_success,
        "example.edu",
        [root.url, internal.url],
        {root.url: "unavailable"},
    )

    original_timeout = application.OFFICIAL_DOMAIN_INTERNAL_VERIFY_TIMEOUT_SECONDS
    application.OFFICIAL_DOMAIN_INTERNAL_VERIFY_TIMEOUT_SECONDS = 0.01
    try:
        async def root_timeout(url):
            if url == root.url:
                await asyncio.sleep(0.05)
                return None
            return ("example.edu", url) if url == internal.url else None

        await run_case(
            "root_timeout_internal_identity_success",
            [root, internal],
            root_timeout,
            "example.edu",
            [root.url, internal.url],
        )
    finally:
        application.OFFICIAL_DOMAIN_INTERNAL_VERIFY_TIMEOUT_SECONDS = original_timeout

    async def reject_all(url):
        return None

    await run_case(
        "ambiguous_internal_identity_rejected",
        [root, ambiguous],
        reject_all,
        None,
        [root.url, ambiguous.url],
        {root.url: "unavailable", ambiguous.url: "identity_mismatch"},
    )

    await run_case(
        "third_party_mention_never_attempted",
        [root, third_party],
        reject_all,
        None,
        [root.url],
        {root.url: "unavailable"},
    )

    await run_case(
        "root_identity_mismatch_does_not_try_internal",
        [root, internal],
        reject_all,
        None,
        [root.url],
        {root.url: "identity_mismatch"},
    )


if __name__ == "__main__":
    asyncio.run(main())
