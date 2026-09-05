# KTH: Global URL discovery + guided DeepSeek low

One Global request, one Responses request. No Custom, local direct fetch, cached
Doubao body in model context, production workflow, client retry or fallback.
Raw request, response, tool events and every requirement citation are preserved
in `global_guided_kth.json`. Only standalone experiment files were added.

## Measurements

| Metric | This run | Prior autonomous stopping-low |
|---|---:|---:|
| Global seconds | 1.676 | N/A |
| DeepSeek seconds | 41.597 | 63.727 |
| Full wall-clock seconds | 43.440 | 63.727 |
| DeepSeek client requests | 1 | 1 |
| Native tool calls | 2 | 6 |
| search / open_page / find_in_page | 0 / 2 / 0 | 1 / 5 / 0 |
| Input tokens | 10431 | 23238 |
| Output tokens | 5587 | 7052 |
| Reasoning tokens (within output) | 1792 | 3477 |
| Total tokens | 16018 | 30290 |
| Direct schema validation | FAIL | FAIL |
| Offline-auditable requirement rows | 14 | 13 |
| Admission topic coverage | 14/14 | 13/14 |

Wall-clock improves 31.8%, total tokens 47.1%, calls 66.7%. Cached input tokens
6656. Provider-internal model request count is unknown. This is a single sample,
and the earlier experiment used a different schema/prompt, so it is not a strict
single-variable causal comparison.

## Global

Exact unchanged query: `KTH MSc Computer Science entry requirements`.
Body: Query, SearchType=web, DocCount=5. No client query rewriting. Global's
provider-internal query processing is not exposed or independently controlled.

Top 5 in returned order:
1. https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975
2. https://www.kth.se/student/kurser/program/TCSCM-20262.pdf
3. https://www.mastersportal.com/studies/46948/computer-science.html
4. https://www.kth.se/en/2.985/admissions/entry-requirements-for-master-s-studies-1.6915
5. https://www.uni-cube.cn/majors/kth-royal-institute-of-technology-computer-science-master

Rank 1 was selected. Only this URL, not snippets or bodies, entered the prompt.
Both native calls were successful opens of this same exact URL (with distinct
provider ws_call_id fragments). No supporting pages, broad searches, external
domains or failed calls were recorded. Reopening the same page means stopping
and non-redundancy instructions were not followed perfectly; necessity of the
second open cannot be established from telemetry.

## Output and per-record provenance

Direct response starts with English commentary before JSON. The original full
output fails model_validate_json. For evaluation only, the one JSON object was
decoded from the response and validates as the current RequirementsExtraction
schema. No repaired result replaced the raw output; no extra model request.

All 14 rows have this identical source URL:
https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975

All have source_type=official_retrieval, verification_status=official_verified,
source_level=program, temporal_applicability=undated and source_cycle="undated".
The last value is a literal string instead of the preferable null for no cycle.
No model_memory or model_memory_unverified rows were generated. Official URL
rate is 14/14, not proof every interpretation is accurate.

| Row | Topic | Returned stage |
|---|---|---|
| 1 | Degree plus final-year eligibility | pre_admission |
| 2 | 180 ECTS degree and mathematics prerequisites | pre_admission |
| 3 | Computing prerequisites | pre_admission |
| 4 | Track-specific course eligibility | pre_admission: WRONG; in-program |
| 5 | English | pre_admission |
| 6 | Degree certificates | pre_admission |
| 7 | Transcript, including Ladok exemption | pre_admission |
| 8 | English proof | pre_admission |
| 9 | Identification | pre_admission |
| 10 | CV | pre_admission |
| 11 | Motivation letter | pre_admission |
| 12 | Recommendation letters | pre_admission |
| 13 | Summary sheet | pre_admission |
| 14 | Selection criteria | informational |

## Post-run quality audit

Baseline answers were not included in model prompt. Existing fixture contains
15 topics, including an in-program track topic; admission-only denominator is
14. All 14 admission topics are present at topic level (final-year eligibility
is merged with degree). This does not mean all constraints are complete or
correct. The 8 document topics and selection are present. Track is an extra
out-of-scope row incorrectly labelled pre_admission; final-year eligibility is
not separately represented as conditional_admission.

Details preserved: mathematics/computing credit quantities and named subjects,
current CV instructions, motivation language/word limit and per-programme
letters, referee contact/translation/postal-not-email instructions, Ladok
exemption and summary-sheet submission route. Details omitted include motivation
autobiography and what the applicant hopes to gain, reference reuse across
programmes, and Swedish final-year 150-credit condition. No precise aggregate
detail-completeness score is claimed without a fixed detail rubric.

Independent official-page inspection was performed only for evaluation and was
never provided to the experiment model; it is outside experiment timing and
request counts. Reference: the same official KTH URL, page changed May 19 2026.
Output matches contemporary English Level 2, TOEFL 4.5 and CV wording, rather
than the earlier stale Custom evidence. No obvious stale-version signal is
seen, but provider raw page body and retrieval/index timestamp are not exposed.
Freshness of every source fragment therefore cannot be guaranteed.

The output adds an unsupported interpretation that the printed TOEFL value is
anomalous; it preserves the value but adds this judgment in commentary/Chinese.
The page does not certify all requirements for Fall 2027. The model correctly
does not promote them to target_cycle_confirmed. An undated admission cycle is
not equivalent to the page having no last-modified date.

## Decision

Promising URL-guided retrieval efficiency: fewer calls and lower latency/tokens,
with preserved topic recall and some improved actionable details. Worth another
comparative evaluation, not production substitution: direct structured output
still fails, track stage regresses, some details remain missing, and repeatability
is untested. Stopped after this KTH run; no output repair, optimization, Oxford
test, production edit, deployment, commit or push.
