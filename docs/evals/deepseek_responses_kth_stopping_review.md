# KTH stopping-criterion single-variable experiment

2026-09-04. Exactly one live request, KTH only. No Oxford run.
Request comparison assertion passed: every payload field matches the previous
KTH request, with only the user's Chinese stopping principle appended to input.
Model deepseek-v4-flash, reasoning high, max_output_tokens 20000, Responses API,
native web_search, tool_choice auto, JSON schema unchanged. No production imports,
retrieval, fallback or cache. Baseline used only in posthoc evaluation.

| Metric | Previous KTH | Stopping criterion |
|---|---:|---:|
| Seconds | 173.579 | 95.605 |
| web_search_call | 14 | 8 |
| DeepSeek client requests reaching API | 1 | 1 |
| Input tokens | 158445 | 46706 |
| Output tokens | 21449 | 12219 |
| Total tokens | 179894 | 58925 |
| Cached input tokens | 141056 | 37120 |
| Reasoning tokens within output | 15757 | 7410 |
| Recovered requirement records | 16 | 15 |
| Direct structured-output validation | failed on aggregated text | failed on final message |
| Official URL domain rate | 100% | 100% |
| Fixture topic coverage | 14/15 | 14/15 |
| Admission-only fixture topic coverage | 13/14 | 13/14 |

Latency decreased 44.9%, tool calls 42.9%, total tokens 67.2%. These are single
observations, not a statistically established causal effect.

The initial sandbox connection was blocked with WinError 10013 before an API
response (0.148 s). That local failed attempt is recorded separately in
deepseek_responses_kth_stopping.json. The authorized live run made one request,
without retries, and returned HTTP 200 / completed. Internal model call counts
remain undisclosed. Actual tool usage: one search operation, four open_page,
three find_in_page; all eight completed. One programme URL was opened twice and
the entry page was searched for TOEFL, IELTS and 2027. Some verification remains,
but no long search expansion like the previous 14-call run was observed.

## Quality and cycle audit

Exactly one schema-valid JSON object can be recovered from the final message,
but the final message itself contains prose and Markdown fences. Therefore
structured output did NOT succeed directly. Unlike the previous capture,
message boundaries are preserved this time. No repair request was made.

All 15 recovered records have official kth.se URLs, self-label confirmed and
explicit_programme. They retain the bachelor/final-year conditions, subject-credit
thresholds, English requirement, and all eight document topics. As before, the
selection process is missing. The English threshold is now combined into the
language record, the fee-only record is absent, and prior-learning recognition
is added. Record count alone is not a completeness measure.

All records are sourced from the exact programme or its entry page, but one
track/course prerequisite explicitly applies after admission, not to programme
admission itself. Thus not all records are clean admission-level requirements.
There is also a timeline record and an exemption pathway, rather than only
eligibility/document requirements. No important fixture topic was lost relative
to the previous run; this does not establish full correctness.

Fourteen records retain undated source applicability and one timeline record is
labelled target-cycle-confirmed. The top-level confirmed cycle describes the
2027 intake, not verification of every rule for 2027. Main-page dates match the
previous audit. The exact entry page currently has no explicit cycle label.

Residual quality issues: the summary-sheet uncertainty incorrectly says its link
is not yet published, although the official page exposes it. English-test details
are described as partly unconfirmed while the combined record is confirmed;
uncertainty is not consistently represented with status unknown. No full
correctness score is claimed. Official-source rate is not correctness rate.

Posthoc source review:
https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975

Conclusion: promising reduction in search/latency/tokens without observed topic
recall loss in this single run. Still not a production-ready replacement due to
output-contract failure and residual scope/uncertainty issues. Stopped after KTH;
no further strategy change, production edit, deployment, commit or push.
