# Independent Responses API experiment

Date: 2026-09-04. Model: deepseek-v4-flash, reasoning high. Target: Fall 2027 / 2027-28.
One client request per programme, sequential, no retries. Native web_search,
tool_choice auto, text.format json_schema. No Viaform retrieval, fallback, cache,
or production imports. Baselines loaded after both responses, never into prompts.

## Measured results

| Metric | KTH Computer Science | Oxford Advanced Computer Science |
|---|---:|---:|
| Wall-clock seconds | 173.579 | 86.761 |
| HTTP / response status | 200 / completed | 200 / completed |
| Client DeepSeek requests | 1 | 1 |
| Internal model invocations | undisclosed | undisclosed |
| web_search_call items | 14 | 25 |
| Completed / failed tool calls | 14 / 0 | 8 / 17 |
| Search / open_page / find_in_page | 5 / 9 / 0 | 5 / 19 / 1 |
| Input tokens | 158445 | 87523 |
| Cached input tokens | 141056 | 79488 |
| Output tokens | 21449 | 8033 |
| Reasoning tokens (within output) | 15757 | 6346 |
| Total tokens | 179894 | 95556 |
| Direct JSON validation | failed | failed: empty output_text |
| Posthoc recoverable requirement records | 16 | 0 |

Tool counts include page operations, not just search-engine queries. Usage is
provider-reported cumulative usage; do not infer internal model rounds from it.
The output-token budget is not evidence of a global cumulative usage ceiling.

## Output-contract limitation

The first-run collector concatenated assistant output_text segments and did not
preserve message boundaries or other message content types. KTH contains prose
and fenced JSON; exactly one schema-valid object is recoverable offline. This
does NOT count as direct structured-output success, and cannot isolate a provider
final-message contract failure from collector behavior. Oxford has no captured
output_text; HTTP success is not task success. Its failed tool calls are evidence
of search difficulties, not proof of the reason for the absent answer.

The experiment-only collector was subsequently changed to preserve message texts
and content types and validate the last message. No further paid requests were
made with that revision. Original measurements are preserved in the raw report.

## KTH posthoc quality review

All 16 recovered records cite kth.se URLs (100% official-domain rate); 15 are
self-labelled confirmed and one English-test record unknown. Official-domain
validation alone is not factual validation.

Semantic coverage of the fixture is 14/15 topics (93.3%): selection process is
missing. Excluding the fixture's in-program track prerequisite, admission-topic
coverage is 13/14 (92.9%). This is topic coverage, not exact-field recall: the
English threshold appears in an unknown record, so confirmed-only completeness
is lower. Bachelor and final-year conditions are combined; extra fee and timeline
records do not increase baseline recall.

The core academic thresholds and application-document requirements agree with
the official programme entry page. Problems prevent an all-correct verdict:

- One record is explicitly an in-program track prerequisite, not a general
  admission requirement, despite the instruction to exclude completion rules.
- One record is a linked university-wide fee rule, not programme-specific.
- The output says the summary-sheet link is unavailable until applications open;
  the current entry page already exposes a link. Link availability is not proven
  by the output's uncertainty explanation.
- The 2027 intake timeline is supported by the programme landing page. Fourteen
  records correctly retain undated evidence; only two are target-cycle-labelled.
  Top-level cycle_status confirmed must not imply all requirements are verified
  specifically for 2027.

Sources reviewed after inference:
- https://www.kth.se/en/studies/master/computer-science
- https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975

## Oxford posthoc quality review

Zero usable requirement records. Completeness as delivered is zero; correctness,
official-source rate, programme applicability and cycle correctness are N/A.
Do not substitute Oxford Biology's fixture for Advanced Computer Science.
The official Advanced CS page currently mixes updated 2027-28 fees with remaining
2026-27 information, which any future usable answer must distinguish.

Source: https://www.ox.ac.uk/admissions/graduate/courses/msc-advanced-computer-science

## Historical comparison and conclusion

Repository mvp_eval_report CORE-005 records KTH Requirements phase 30.886 s
(supplemental capture 24.418 s); this experiment is 5.62x the phase latency.
CORE-002 records Oxford Advanced CS Requirements phase 49.652 s (supplemental
capture 58.977 s with zero requirements); this experiment is 1.75x the phase
latency, also without a usable answer. These are historical single samples,
not a same-time controlled benchmark. Historical full-workflow latency and five
DeepSeek requests include Timeline/Gap/Planning and cannot be compared directly
to this experiment's Requirements-only request count. Baseline actual search-tool
counts and internal model rounds are not available.

Current Viaform already invokes native DeepSeek web search via the Anthropic-
compatible messages endpoint, then applies its own orchestration/normalization/
fallbacks. This tests Responses protocol + schema + autonomous search, not the
first introduction of native search. No latency advantage or replacement-quality
reliability was demonstrated. Keep production unchanged; only further isolated
tests of final-message extraction/schema behavior and empty-output handling are
warranted before a repeated controlled comparison.

Artifacts: experiment_responses_requirements.py, raw JSON, audited JSON, this review.
No production edits, deployment, commit, or push were performed for this experiment.
