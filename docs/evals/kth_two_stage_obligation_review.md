# Final obligation-rubric validation: KTH

Exactly one full run, no retries, repairs, output rewriting, tuning or production
changes. Only Call 2 generic obligation rubric was appended. Global request,
Call 1 complete request, Call 2 model/reasoning/tools/output schema/stage rubric
and token budget were verified unchanged. Fresh Call 1 output was passed
verbatim to Call 2. Full rerun necessarily regenerated evidence (8842 vs 7973
characters); this is not a controlled identical-evidence replay and causal
attribution to the rubric alone is limited.

## Measurements

Global 0.783 s, exact URL rank 1, same Top 5 as before (raw artifact retains all).
Call 1 18.499 s, 8842 characters / 8866 bytes, one successful exact-URL open.
search/open_page/find_in_page = 0/1/0, unchanged count from previous run.
Call 1 tokens input/output/reasoning/total = 2982/2281/431/5263.
Call 2 22.745 s, no tools, reasoning none; tokens = 3044/4267/0/7311.
Reasoning is included in output. Wall-clock 42.194 s, total tokens 12574.
One Global and two DeepSeek client requests.

## Output contract failure

The raw Call 2 response starts with a markdown json fence and ends with a fence.
No explanatory prose outside it, but full json.loads fails at line 1 column 1.
Direct schema validation therefore FAILS. No fence stripping, regex, repaired
JSON, second LLM call or forced importance downgrade was used. The 16 visible
records were manually audited as text, not returned as valid structured data.

## Classification and fidelity audit

Prior learning recognition now retains permission wording and has
importance=unknown, applicability_stage=informational. The previous required
error is absent. Current importance enum has no optional value; unknown is the
conservative existing value, not an added schema field.

Manual obligation errors=0; required-vs-permission conflicts=0; unsupported
obligation inferences=0 in the visible requirement propositions/metadata.
Mixed rows with may/can are not automatic conflicts: final-year and English
rows also contain mandatory conditions, and references are mandatory while
reuse is optional. A naive token guard would not distinguish these propositions.
No deterministic semantic guard was added: direct JSON failure blocks reliable
row inspection without stripping, and evidence has no structured per-row span
alignment. Manual checks only; no output mutation.

Core admission coverage 14/14 at topic level; some general documents remain
merged. Track stage is in_program, not pre_admission. Final-year is now
conditional_admission with explicit applicant-specific conditions, compatible
with the unchanged current rubric; not counted as a clear stage error merely
because previous run used pre_admission. No clear timing-stage error observed.
Track category changed from course to academic: less precise taxonomy, though
the course-specific conditions and in_program stage remain explicit.

All 16 visible records cite the same exact kth.se entry URL and have
official_retrieval/official_verified provenance. model_memory_unverified=0.
Official URL rate=100%; no new unsupported factual proposition identified in
the English requirements. These content measures do not rescue direct failure.

Key details retained: TOEFL value, mathematics/computing thresholds, final-year
150 credits/date, Ladok exception, motivation autobiography/content and strictly
fewer than 500 words (Chinese 单词), per-programme letters, reference reuse,
translation/contact details and postal/not-email submission, summary-sheet route.
Minor compression of CV examples/country-document detail persists. New Chinese
semantic imprecision: merit rating translated as 绩点评定, not admission merit
evaluation; programme/course distinction is also blurred in places. No blanket
claim of perfect correctness or no semantic regressions.

## Verdict

Observed obligation fix: YES for this run, without forced downgrade.
New clear importance/stage regression: none identified; minor category/translation
imprecision remains. Direct structured output: FAIL (code fence).
All Success Criteria: FAIL, primarily output contract. The native format schema
and no-tool non-thinking configuration did not guarantee stable plain JSON.
No follow-up experiment or fix performed. Only standalone script/results/report
were added; no production edits, deploy, commit or push.
