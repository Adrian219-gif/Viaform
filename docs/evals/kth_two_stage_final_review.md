# Final KTH two-stage experiment

One execution only. One Global URL request, one DeepSeek low native-web reader,
one DeepSeek none tools-off extractor. No retries, repair, fallback, local direct
fetch, Custom, production workflow, deployment, commit or push.

## Metrics

Global: 0.670 seconds, exact official entry URL rank 1. Top 5 and selected URL
in kth_two_stage_final.json. Query and discovery rule unchanged.
Reader: 18.358 seconds; one completed open_page, zero search/find_in_page.
Input 2980, output 1847, reasoning 211 (inside output), total 4827 tokens.
Evidence 7973 characters / 8003 UTF-8 bytes. Only the supplied exact KTH entry
URL was opened, no repeated opens or supporting pages. Its provider fragment
ws_call_id does not change the page identity.
Extractor: 19.896 seconds; no tools, reasoning none. Input 2570, output 3760,
reasoning 0, total 6330 tokens. Whole raw response passes json.loads and the
existing Pydantic model, plus the closed-field contract. No prose, code fence,
unexpected fields or repair. 13 requirement records.
Full wall-clock 39.096 seconds, summed tokens 11157, native calls 1, client model
requests 2. Evidence input to Call 2 is exactly Call 1 output, without Global
snippets, reference answers or external factual evidence added.

## Content audit

Admission topic coverage 14/14; number of records differs because academic and
final-year eligibility are merged, mathematics/computing are merged, and four
general documents are merged. All 13 source URLs are the exact kth.se entry
page, all official_retrieval / official_verified, zero model_memory_unverified.
Official-source URL rate is 100%, not proof of all semantic labels.

Evidence reading preserves the key known regression details: language numbers,
credits and named prerequisites, final-year credit/date condition, Ladok waiver,
CV, full motivation-letter guidance, reference submission/reuse/translation,
summary-sheet route, track context and selection. Sufficient evidence in this
sample; one success cannot establish repeated reliability or raw-page freshness.

Extraction preserves TOEFL 4.5, motivation strictly fewer than 500 words and
Chinese 少于500个单词, per-programme motivation letters, autobiography, referee
postal/not-email route and identifying details, final-year 150-credit condition,
Ladok exception, and track in_program. No clear pre-admission/in-program timing
error remains. Final-year eligibility is expressed within the degree row rather
than assigned a new stage. No invented condition field. Undated requirements
are not promoted to confirmed Fall 2027; 2026 statistics are previous_cycle.

Minor compression: country-specific degree-document wording and separate English
proof test/studies distinction are not repeated in the general-materials row,
although country/test distinctions exist elsewhere. Topic-level completeness
does not guarantee granular downstream usability of combined rows.

## Remaining failure

Row 10 correctly says the applicant CAN apply for recognition of prior learning,
but assigns importance=required. The reader evidence only grants an optional
route. This is at least one unsupported obligation judgment in structured
metadata, an extraction/semantic-classification error, even though its placement
before enrolment is not a clear temporal-stage error. Do not conflate required
importance with proof of a timing-stage error.

Row 1 temporal_note additionally says the explicit 1 February deadline is
"not date-specific". If intended as "not entry-year-specific", it is poorly
expressed; the actual requirement text does preserve the date. Treat as a
wording defect, not evidence for a second exact factual-error count.

Selection is required/pre_admission; the evidence explicitly says admission
requires passing selection, so this is not counted as a clear unsupported
requirement. Track remains in_program; acceptance/advice are informational.

## Success criteria verdict

1 PASS direct schema; 2 PASS no prose; 3 PASS no fence; 4 PASS core 14/14;
5 no clear timing-stage error observed; 6 PASS no model_memory_unverified;
7 FAIL unsupported factual/obligation inference at least 1 (required RPL);
8 PASS official URL rate 100%; 9 key listed numerical/submission details retained,
but optional-to-required semantic mutation prevents an unqualified fidelity pass;
10 PASS reader native calls 1 <=3.

Overall: FAIL under the all-criteria rule. Output contract and observed track
stage issue are resolved in this single run, but extraction/semantic
classification still fails. Not a URL discovery or reader-access failure.

Reference for post-run comparison (not supplied as new evidence to Call 2):
https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975
The existing 14-topic admission baseline excludes the in-program track topic.
No follow-up experiment or mitigation performed.
