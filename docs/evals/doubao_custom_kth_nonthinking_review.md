# Same-evidence KTH extraction: thinking off

One DeepSeek request, zero Doubao/search requests. Original saved input (including
evidence), schema, model, output budget and all other payload fields are identical.
Only reasoning changed from {effort: high} to {effort: none}. Official reference:
https://api-docs.deepseek.com/api/create-response/ documents none as disabling
thinking. Input and baseline hashes are in the result JSON; baseline unchanged.

| Metric | Thinking ON | Thinking OFF |
|---|---:|---:|
| Extraction seconds | 150.592 | 12.376 |
| Input tokens | 7925 | 7847 |
| Output tokens | 19093 | 2568 |
| Total tokens | 27018 | 10415 |
| Reasoning tokens (within output) | 15917 | 0 |
| Cached input tokens | 0 | 0 |
| Requirement records | 13 | 13 |
| Direct schema validation | pass | pass |
| Official URL rate | 100% | 100% |
| Fixture topic recall | 14/15 | 14/15 |
| Admission-only topic recall | 13/14 | 13/14 |

Latency -91.8% (about 12.2x faster); output tokens -86.6%; total tokens -61.5%.
The 78-token input accounting difference occurs despite verified identical input
and schema. Do not infer changed evidence; provider internal accounting cause is
not established. No cache hit was reported in either run.

## Quality comparison

Core academic thresholds and eight document topics remain. Both omit selection.
But unchanged topic recall masks meaningful detail loss: OFF omits the referee's
direct-submission postal/not-email instructions, reuse across programmes, and
much of motivation-letter content/autobiography instruction. Prior-learning
recognition (outside the 15-topic fixture) is also lost. OFF translates the
motivation letter word limit as Chinese '字' rather than words.

Most importantly, the in-program track prerequisite is now labelled required /
pre_admission, whereas ON labelled it unknown importance / in_program. This is
a substantive stage-classification regression even though both included a record
that the extraction prompt asked to exclude. Final-year eligibility is still
pre_admission rather than a separate conditional_admission stage.

All output citations remain the exact official Computer Science requirements URL.
All 13 records retain source_cycle null and temporal_applicability undated; OFF
drops the explicit note warning that Fall 2027 is unconfirmed. OFF also repeats
3 February from the old supplied evidence where ON generalized it to the KTH
deadline. Both retain old TOEFL 90 from the same evidence. This is evidence
freshness risk, not demonstrated hallucination introduced by non-thinking.
Current-2027 correctness remains unverified; official URL rate is not accuracy.
No new webpage retrieval or search was performed in this experiment.

## Interpretation

If adding the previous 0.802-second search measurement, the illustrative pipeline
sum is 13.178 s (not a newly measured end-to-end run). The measured result here is
extraction only. This materially improves latency and token usage, but correctness
and detailed completeness regressed. One sample cannot establish stability.

Worth a later isolated Oxford test to assess generalization, with explicit detail,
stage and freshness evaluation; not ready to replace production. No Oxford test
or mitigation was performed. Only new experiment script/report artifacts; no
production edits, .env changes, deploy, commit or push.
