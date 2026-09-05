# KTH bounded Custom search (max 3) + low extraction

Only one search was necessary for topical completeness. No additional search,
provider fallback, direct fetch, retry, Oxford, production edit or deployment.

## Round log

Round 1 query: KTH Master's Programme in Computer Science entry requirements application documents

- Latency 0.413 s; HTTP 200; 5 results; all 5 official kth.se, with full text.
- Exact programme entry page ranked first, containing bachelor/final-year,
  mathematics/CS prerequisites, English, all eight document sections and selection.
- Evidence sufficient for main requirement-topic extraction; stop immediately.
- Freshness is NOT confirmed: returned text still contains TOEFL 90, 3 February,
  2025 acceptance figures and older CV wording, matching previously observed
  stale content. This was recorded, not silently accepted as current-cycle truth.
- Rounds 2 and 3 not executed: no missing major topical section justified them.
  This run cannot measure whether supplemental searches improve recall stability.

Retrieved evidence: 5 documents; 30978 text-field characters; serialized evidence
32712 characters / 35344 UTF-8 bytes. One exact-page hit in this one case, not a
population recall estimate. Other documents include general policies and an
unrelated old programme syllabus; output did not cite that unrelated page.

## Extraction and timing

One deepseek-v4-flash Responses request, reasoning low, tools [], tool_choice none.
Same prior Doubao extraction prompt template and current Requirements schema;
baseline answers never enter prompt. Evidence de-duplicated by URL, no truncation
or rewriting. No repair request.

- Extraction latency 88.963 s; HTTP 200 / completed; web_search_call 0.
- Input 7847, output 12858, reasoning 9771 (within output), total 20705 tokens.
- Cached input 7808 tokens. Cache usage is provider-managed, not Viaform cache.
- Direct schema validation passes; 14 records; no failure or empty result.
- Retrieval total 0.413 s; API-stage total 89.376 s.

This was a staged experiment with human/agent evidence inspection between calls.
89.376 s excludes approval/inspection idle time and is NOT a continuous measured
wall-clock end-to-end request. No reliable full-session wall-clock was recorded.
It is already slower than autonomous-low's 63.727 s even excluding inspection.

## Quality

Fixture topic coverage 14/15; selection omitted despite evidence. Excluding
in-program topic gives 13/14 admission topics, equal to autonomous-low. All eight
material topics and subject-credit thresholds retained. Material details such as
motivation autobiography, per-programme letters, recommendation translation,
postal/not-email submission and Ladok exemptions are more complete than prior
non-thinking and some autonomous-low requirement fields.

All output sources are exact programme page URLs: official-source rate 100%.
One track-course condition remains in Requirements as required / unclear stage.
Better than prior non-thinking's false pre_admission, but not as good as
autonomous-low excluding that item from admission requirements. Final-year
conditional eligibility is still combined into pre_admission bachelor record.

All 14 records source_cycle null / undated, with explicit notes that Fall 2027 is
not confirmed. This is appropriately cautious, not successful 2027 verification.
TOEFL 90 and 3 February are supported by returned text, but conflict with current
page facts already verified in previous audits (TOEFL 4.5 and 1 February). Thus
extraction grounding is not the same as current correctness. Missing current
summary-sheet upload restriction reflects stale evidence. No new live source
audit was performed or fed back to the model in this run.

## Comparison

| Metric | Autonomous stopping + low | Custom <=3 + low |
|---|---:|---:|
| Measured time / active API sum | 63.727 s | 89.376 s |
| Search | 6 native tool calls | 1 Custom request |
| Total model tokens | 30290 | 20705 |
| Reasoning tokens | 3477 | 9771 |
| Direct structured output | failed | passed |
| Admission topic coverage | 13/14 | 13/14 |

Active API time +40.2%; total tokens -31.6%. Different schema/prompt between native
and Custom pipelines (including bilingual requirement fields) prevents a strict
single-variable inference. Single samples do not establish stability.

Conclusion: good retrieval latency and direct JSON, richer material detail than
none, but no overall speed or correctness superiority. Freshness remains a major
problem. A later same-policy Oxford test is useful specifically to exercise the
currently untested second/third search decision; not a production recommendation.
Stopped after KTH, with no mitigation changes or further requests.
