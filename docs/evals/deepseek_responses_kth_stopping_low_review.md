# KTH stopping criterion: low vs high reasoning

One live request. Saved high stopping payload replayed verbatim except
reasoning.effort high -> low. Prompt/schema/tools/auto/output budget unchanged;
no soft four-call budget. Baseline file hash and equality assertions retained.
No Doubao, custom retrieval, cache, client retry or fallback. Search remains
provider-autonomous; repeated opens are provider actions, not client retries.

| Metric | High | Low |
|---|---:|---:|
| Seconds | 95.605 | 63.727 |
| Tool calls | 8 | 6 |
| Client requests | 1 | 1 |
| Input tokens | 46706 | 23238 |
| Output tokens | 12219 | 7052 |
| Reasoning tokens within output | 7410 | 3477 |
| Total tokens | 58925 | 30290 |
| Cached input tokens | 37120 | 15872 |
| Recovered requirements | 15 | 13 |
| Direct schema validation | failed | failed |
| Official URL rate | 100% | 100% |
| Admission-only topic recall | 13/14 | 13/14 |

Latency -33.3%, reasoning -53.1%, total tokens -48.6%, calls -25%.
Low has one search and five open_page operations: four completed, two failed.
High had one search, four open_page, three find_in_page, all completed. Client
HTTP 200 and provider completed status do not imply all tool operations succeed.
Internal model invocation count is undisclosed. One stochastic sample does not
establish repeatability or sole causation by reasoning effort.

## Quality

Final message contains prose and fenced JSON. Exactly one valid schema object
was recovered offline for evaluation only; no repair request. All thirteen rows
have official sources and are self-labelled confirmed. Four general document
rows are correctly tagged programme_linked_general because explicitly listed on
the exact programme entry page. No unrelated university policy is introduced.

Baseline 15-topic comparison: 13/15 as requirement rows vs high 14/15. This is NOT
a new admission recall loss: low correctly moves in-program track prerequisites
out of requirements into unknowns. Both omit selection. Excluding the in-program
fixture topic, both cover 13/14 admission topics, including all eight documents.
Prior-learning recognition from high (outside the fixture) is absent in low.

Detailed completeness weakens: motivation-letter autobiography/content guidance
is absent; some per-programme-letter, postal/not-email referee and Ladok degree
certificate exemption details remain only in evidence_excerpt rather than the
requirement field. High included more of these in actionable requirement text.
Thus topic recall is preserved, but field-level downstream fidelity is lower.

Stage distinction improves for track prerequisites, not regresses. This original
experimental schema has no explicit applicability_stage field, so no structured
stage accuracy score is claimed. A timeline record remains, as in high.

Cycle: twelve undated items, one target-cycle timeline; top-level confirmed
refers to 2027 intake and cannot certify all rules for 2027. Most source facts
match the current-page facts inspected in the earlier audits (1 February,
English Level 2, TOEFL 4.5 quote, current CV wording and summary-sheet instruction).
No obvious old-version signals like Doubao's 3 February/TOEFL 90 are present.
However raw provider search page bodies/indexing timestamps are not retained;
freshness cannot be guaranteed for all evidence.

Residual unsupported interpretations: low calls the TOEFL 4.5 text a rendering
error without supporting evidence; it also says the summary-sheet link is not
available before opening, while the earlier official-page audit found a link.
The page being undated by admission cycle is not the same as lacking a revision
date; low conflates these in one uncertainty note. Core thresholds are not
obviously corrupted, but correctness is not perfect.

Conclusion: promising speed/token reduction with unchanged admission-topic recall,
improved track scoping, but less detailed actionable text and continuing direct
JSON failure. Worth a separate Oxford low-reasoning experiment, not production
replacement. Stopped after KTH; no mitigation or additional test implemented.
Only independent experiment script/report artifacts added; no production edits,
deployment, commit or push.
