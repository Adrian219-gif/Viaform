# KTH soft max-four experiment

2026-09-04. One live KTH request; no retries, Oxford, deployment or production edits.
Payload assertion passed against stopping-criterion run: only the exact requested
soft-budget sentence was appended. No max_tool_calls parameter or client workflow
was introduced. Model, reasoning, tools, auto choice, schema and output budget
remain unchanged. Baselines were not supplied to the model.

| Metric | Free | Stopping | Stopping + soft four |
|---|---:|---:|---:|
| Seconds | 173.579 | 95.605 | 98.878 |
| web_search_call | 14 | 8 | 9 |
| Client requests | 1 | 1 | 1 |
| Input tokens | 158445 | 46706 | 66237 |
| Output tokens | 21449 | 12219 | 12217 |
| Total tokens | 179894 | 58925 | 78454 |
| Requirement records | 16 recovered | 15 recovered | 13 direct |
| Official URL rate | 100% | 100% | 100% |
| Fixture topic coverage | 14/15 | 14/15 | 15/15 |
| Admission-only fixture coverage | 13/14 | 13/14 | 14/14 |

## Budget and performance

The model did NOT obey the four-call budget: nine completed tool calls, comprising
three search operations and six open_page operations. All are web_search_call
items and count toward the same metric used in previous runs. Counting only the
three search operations would incorrectly suggest compliance. The exact entry
requirements page was opened twice; searches continued into generic English and
fee pages. Internal model invocation counts are undisclosed.

Relative to stopping-only: latency +3.4%, input tokens +41.8%, output approximately
unchanged, total tokens +33.1%. This run provides no evidence of an additional
latency/token benefit. Because the budget was not obeyed, it does not establish
quality or latency under an actual four-call cap. Single stochastic samples
cannot establish a causal effect of the prompt change.

HTTP 200 / completed. Response id ac620ef1-fd86-4fb1-92c8-db7565ac62e7.
Cached input tokens 55936; reasoning tokens 7681 (included in output tokens).

## Output and quality

The final assistant message is valid JSON and passes the unchanged Pydantic JSON
schema without stripping fences or repair. Intermediate messages are preserved
separately. Structured output succeeded for this run; no structured-output fix
was made, and one success does not establish reliability.

All 13 records cite official kth.se URLs and are self-labelled confirmed.
Twelve cite programme-specific pages; one is explicitly programme-linked general
application-fee policy. A track/course prerequisite still describes in-program
eligibility rather than admission. Thus source identity is correct, but the set
is not exclusively programme admission requirements. Timeline and fee items are
additional records, not evidence of higher academic/document recall.

All 15 fixture topics appear semantically, including the selection process missing
from both previous runs. Excluding the in-program track topic gives 14/14 admission
topics. Four general document requirements are now combined into one record;
degree/final-year conditions are also combined. Consequently 13 records does not
mean lower completeness. Topic recall is not exact-detail recall: the motivation
letter's autobiographical-content instruction is less explicit than last time.
There is no evidence of a major completeness loss, but no all-correct verdict.

Cycle handling: one timeline item is target_cycle_confirmed for August 2027;
12 other records retain undated applicability. Top-level confirmed describes the
advertised intake, not a verified 2027-specific version of all requirements.

Known residual factual/representation issues from the previous official-page audit
remain: the summary-sheet uncertainty says its link appears only when applications
open despite an existing official link; full English-test thresholds remain
uncertain inside a record labelled confirmed. Official-domain rate is not a
correctness score. No new official-page retrieval was fed into the experiment.

Conclusion: soft budget not obeyed, no further speed/token improvement, no major
topic recall loss. Cannot evaluate the true four-call tradeoff with this run.
Stopped after this one request; no strategy changes or further experiments.
