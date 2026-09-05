# KTH output-contract and stage-rubric single run

## Scope and implementation inspection

Previous request already used native Responses text.format json_schema with
name=requirements_extraction and current production model_json_schema(). The
response echoed that configuration, but the final text contained a preface.
This was not prompt-only JSON. Provider internals do not establish whether the
format was ignored, downgraded, or not enforced during native-tool generation.
Do not attribute failure conclusively to a missing strict flag.

Official reference: https://api-docs.deepseek.com/api/create-response/
Documents text.format json_schema and system-level instructions, but does not
document a text.format strict guarantee. No undocumented strict flag was used.

Production schema stages: pre_admission, conditional_admission, in_program,
informational, unclear. It has temporal_applicability, source_cycle,
temporal_note and applicability_stage, but no structured applicant condition
field. Stage has a default and is not originally required. Additional fields
are not forbidden in the original Pydantic-generated schema.

This independent request keeps every field/type/enum, closes object schemas with
additionalProperties=false and requires explicit existing fields. It adds only
system output-contract, generic temporal stage rubric and evidence-fidelity
instructions. No production schema expansion/edit. Conditional applicability
must remain in requirement/requirement_zh prose. Generic final-year example
comes from the user rubric; no KTH baseline answers entered the prompt.

Assertions confirm unchanged Global request, selected URL, original input prompt,
model, reasoning, tools, tool_choice and max_output_tokens. Only instructions
and wire output contract differ. One Global request and one DeepSeek request;
no retries, repair, local direct fetch, Custom, production workflow or cache.

## Measurements

| Metric | Previous | This run |
|---|---:|---:|
| Global seconds | 1.676 | 0.533 |
| DeepSeek seconds | 41.597 | 36.493 |
| Wall-clock seconds | 43.440 | 37.192 |
| DeepSeek client requests | 1 | 1 |
| Native tools | 2 | 1 |
| search / open_page / find_in_page | 0 / 2 / 0 | 0 / 1 / 0 |
| Input tokens | 10431 | 5139 |
| Output tokens | 5587 | 5666 |
| Reasoning within output | 1792 | 2211 |
| Total tokens | 16018 | 10805 |
| Direct structured output | FAIL | FAIL |
| Visible requirement records (manual audit) | 14 | 15 |
| Admission core topic coverage | 14/14 | 14/14 |
| Clear stage errors in visible rows | >=1 | 0 |
| model_memory_unverified rows | 0 | 0 |
| Official source URL rate | 100% | 100% |

Global exact URL rank 1; Top 5 identical to previous. Single completed native
open of the supplied exact entry URL. No broad search or supporting-page open.
Cached input tokens=1920. No latency tuning; single-run timing is descriptive.

## Output contract: FAILED

The raw final response begins "I'll extract the requirements..." and wraps JSON
in a markdown code fence. Full json.loads rejects line 1 column 1. It therefore
does not directly pass the existing Requirements schema, let alone the closed
wire contract. The raw response is preserved unchanged. No regex/substripping,
repair output, or second model request. The 15 records and quality measurements
below are manual content auditing, not a machine-consumable success claim.
No unexpected schema fields were apparent in the displayed records, but this
does not rescue the failed full-response contract.

## Quality

All visible records cite the exact KTH entry page and are official_retrieval /
official_verified. Thirteen admissions rows use pre_admission, and selection
and acceptance statistics use informational. Track eligibility is excluded.
Final-year applicability is separately expressed in text, still pre_admission,
consistent with this user's rubric. All 14 admission topics are represented.

No model-memory rows or explicit claims that an official number is wrong are
present. However, full-output unsupported judgment count is at least 1: the
preface asserts the page does not link additional kth.se requirement pages,
whereas the official page does contain KTH requirement/instruction links.
This is outside the requirement rows but still violates the all-output factual
judgment rule. It is not treated as permission to perform another search.

New regressions compared with the preceding guided run:
- TOEFL number is omitted, not faithfully preserved.
- Ladok document exemption is omitted, broadening the apparent duty.
- Referee postal/not-email submission detail is omitted.
- Per-programme motivation-letter instruction is omitted.
- Motivation limit is mistranslated from fewer than 500 words to no more than
  500 Chinese characters; both unit and boundary are wrong.
- Acceptance statistics appear as an extra informational row, not an admission
  requirement. Stage is correct, extraction scope is less focused.

Improvements: track stage error removed; final-year 150-credit condition and
motivation autobiography restored; source_cycle null used for undated rules.
Previous-cycle 2026 statistics are not labelled confirmed for Fall 2027.
No obvious old-version content signals, but provider raw body timestamps are
unavailable. Independent official-page review is evaluation-only, excluded from
experiment context/request metrics:
https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975

## Success criteria

1. Direct schema success: FAIL.
2. No preface/fence: FAIL.
3. Core coverage >=13/14: content-level PASS (14/14), not direct delivery.
4. Clear stage error zero: content-level PASS.
5. Unsupported inference zero: FAIL for full output (>=1 preface assertion);
   no official-value correction claims in requirement rows.
6. model_memory_unverified zero: PASS.
7. Official-source URL rate 100%: PASS, not a blanket correctness score.
8. Tool calls <=3: PASS (1).

Overall FAIL. Primary blocker is output contract; additional failures concern
extraction fidelity/detail retention. Retrieval worked and the stage rubric
resolved the observed classification error in this one sample. Native schema
parameter plus stronger system instructions did not yield enforceable output
in this run; do not claim a guaranteed repair. Stopped after one run. No
production changes, deployment, commit, push or follow-up experiments.
