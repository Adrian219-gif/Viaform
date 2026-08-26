"""Minimal DeepSeek server-side Web Search capability test.

This script is intentionally independent from the FastAPI application. It calls
DeepSeek's Anthropic-compatible Messages endpoint and treats output as web-search
facts only when the response contains server-side Web Search result blocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parent.parent
DEEPSEEK_ANTHROPIC_MESSAGES_URL = "https://api.deepseek.com/anthropic/v1/messages"
MODEL = "deepseek-v4-flash"
INSTITUTIONS = [
    "KTH Royal Institute of Technology",
    "University of Oxford",
    "University of Amsterdam",
    "Technische Universität Wien",
    "Sapienza University of Rome",
    "Royal College of Art",
]


def parse_json_text(text: str) -> Optional[Dict[str, Any]]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def search_evidence(content: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    evidence: List[Dict[str, str]] = []
    seen_urls = set()
    for block in content:
        if block.get("type") != "web_search_tool_result":
            continue
        results = block.get("content")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict) or result.get("type") != "web_search_result":
                continue
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            evidence.append(
                {
                    "title": str(result.get("title") or "").strip(),
                    "url": url,
                }
            )
    return evidence


async def search_institution(
    client: httpx.AsyncClient,
    api_key: str,
    institution: str,
) -> Dict[str, Any]:
    prompt = f"""
You must use the provided real-time Web Search tool before answering.
Find the official website identity for this institution: {institution}

Return only one JSON object with exactly these fields:
{{
  "official_name": "",
  "aliases": [],
  "official_domain": "",
  "official_url": "",
  "evidence_source_urls": [],
  "fact_basis": "web_search",
  "model_knowledge_notes": ""
}}

Rules:
- Populate factual fields only from pages found by Web Search in this request.
- Prefer the institution's own website as evidence.
- Do not use model memory to fill missing facts.
- If Web Search cannot verify a field, leave it empty.
- aliases must contain at most 3 names.
- evidence_source_urls must contain only URLs actually returned by Web Search.
- model_knowledge_notes must remain empty unless you explicitly identify a claim
  that came from model knowledge; such claims must not be copied into factual fields.
""".strip()
    response = await client.post(
        DEEPSEEK_ANTHROPIC_MESSAGES_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 1800,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 3,
                }
            ],
        },
    )
    if response.is_error:
        error_text = response.text[:2000].replace(api_key, "[REDACTED]")
        return {
            "institution_query": institution,
            "http_status": response.status_code,
            "error": error_text,
            "web_search_used": False,
        }

    payload = response.json()
    content = payload.get("content") if isinstance(payload, dict) else None
    blocks = content if isinstance(content, list) else []
    evidence = search_evidence(blocks)
    text = "\n".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    model_output = parse_json_text(text)
    web_search_used = bool(evidence) or any(
        isinstance(block, dict)
        and block.get("type") == "server_tool_use"
        and block.get("name") == "web_search"
        for block in blocks
    )
    return {
        "institution_query": institution,
        "http_status": response.status_code,
        "web_search_used": web_search_used,
        "web_search_evidence": evidence,
        "facts_from_web_search": model_output if web_search_used else None,
        "unverified_model_output": model_output if not web_search_used else None,
        "raw_text_if_not_json": text if model_output is None else "",
        "usage": payload.get("usage", {}),
    }


async def main() -> None:
    load_dotenv(BACKEND_DIR / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not configured in backend/.env")

    async with httpx.AsyncClient(trust_env=False, timeout=180.0) as client:
        results = []
        for institution in INSTITUTIONS:
            results.append(await search_institution(client, api_key, institution))
    print(json.dumps({"model": MODEL, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
