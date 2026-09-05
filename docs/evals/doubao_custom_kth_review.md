# Doubao Custom + evidence-only DeepSeek: KTH

2026-09-04. One search request and one extraction request; no retries, fallback,
direct-fetch retrieval, other provider retrieval, cache, or Oxford run.

Official Custom documentation verified before execution:
https://www.volcengine.com/docs/87772/2272953?lang=zh
POST https://open.feedcoopapi.com/search_api/web_search, Bearer API key, JSON.
Body: Query (<=100 characters), SearchType web, Count 5, Filter.Sites kth.se,
Filter.NeedUrl true, Filter.NeedContent false, ContentFormats text,
QueryControl.QueryRewrite false. NeedContent is a filter, not a body-fetch toggle;
false preserves results even when body is absent. No time filter was imposed.
Response fields used: Result.WebResults Title/Url/Summary/Content/Snippet,
RankScore/SortId/PublishTime/ContentFormats; metadata and TimeCost retained.
RankScore is relevance, not proof of a distinct reranker operation.

## Search

- HTTP 200; one request; client latency 0.802 s; server TimeCost 620 ms.
- Five results, all kth.se, all with full text and RankScore.
- Exact Computer Science entry page ranked first (RankScore 0.829156).
- Other results: general master's requirements, how-to-apply, Chinese application
  guide, and a different programme's old 2010 syllabus. Official does not imply
  programme-relevant. The extractor did not cite the unrelated programme.
- Evidence text fields 30978 characters; evidence JSON 32712 characters /
  35344 UTF-8 bytes. Search response 37546 bytes.

## Extraction

deepseek-v4-flash Responses API, reasoning high, max_output_tokens 20000,
tools empty and tool_choice none. Current RequirementsExtraction/RequirementItem
schema loaded via isolated AST definitions, not app import; schema and hash saved.
No baseline supplied to model. Compared with previous experiments this schema
includes requirement_zh and production stage/source fields, so this is not a
single-variable performance comparison.

- One request; HTTP 200 / completed; 150.592 s.
- Tokens input 7925 / output 19093 / total 27018; reasoning tokens 15917 within
  output, cached input 0. High reasoning usage accompanies the long extraction
  latency; this alone does not establish its complete cause.
- Thirteen records; unchanged production schema validation succeeds directly.
- Zero web_search_call items; no JSON repair or second extraction.

## Quality

All thirteen output URLs are the exact official programme entry page (100%
official-source rate). One record still contains in-program track prerequisites,
but is explicitly labelled in_program; remaining twelve are pre_admission.
Final-year conditional eligibility is merged into the bachelor record rather
than separately stage-labelled. Thus scope/stage quality is not perfect.

Fixture topic recall 14/15: selection omitted even though present in evidence.
Excluding in-program topic: 13/14 admission-topic recall. All eight document
topics and both subject-credit thresholds appear; math and CS are merged.
This is topic recall, not complete exact-detail correctness.

All items correctly retain undated / source_cycle null and explicitly say 2027
is not confirmed. Target-cycle evidence is insufficient, not a confirmed 2027
requirement set. Source-version risk remains: retrieved programme body says
TOEFL 90, 3 February, 2025 acceptance rate, and older CV wording. Current official
page observed in posthoc audit says TOEFL 4.5, 1 February, 2026 acceptance rate,
and revised CV wording. The extracted TOEFL 90 is grounded in retrieved evidence,
not demonstrated hallucination, but cannot be treated as verified current rules.
Exact age of search snapshot is unknown. Output also lacks the current summary
sheet instruction not to upload it to University Admissions, absent in that
retrieved body. Evidence freshness limits current correctness despite official URLs.

Posthoc official source (not supplied to extraction, not a retrieval fallback):
https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975

## Comparison

| Variant | Total seconds | Search calls | DeepSeek total tokens |
|---|---:|---:|---:|
| Native free | 173.579 | 14 tool calls | 179894 |
| Native stopping | 95.605 | 8 tool calls | 58925 |
| Native soft four | 98.878 | 9 tool calls | 78454 |
| Doubao + extraction | 151.456 | 1 external request | 27018 |

Versus free: time -12.7%, tokens -85.0%. Versus stopping: time +58.4%,
tokens -54.1%. Versus soft four: time +53.2%, tokens -65.6%.
Current workflow historical Requirements phase 30.886 s is much shorter, but
historical/noncontrolled. Prior native runs do not isolate retrieval-only timing,
so 0.802 s search is excellent absolute performance, not a measured same-stage
speedup ratio. No stability claim can be based on one sample.

Conclusion: fast search and low model input, successful schema, broadly retained
topic coverage; no end-to-end advantage over stopping variants, with serious
freshness caveat. A later Oxford experiment may help assess provider coverage,
but no production replacement recommendation. Prefer resolving freshness and
understanding extraction latency before expanding. No further requests made.

Only new experiment script and reports were created. Keys read from environment/
backend .env, never logged; .env and production files unchanged. No deploy,
commit or push.
