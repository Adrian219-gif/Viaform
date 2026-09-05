# Oxford Advanced Computer Science: Doubao Custom + non-thinking extraction

One search and one extraction, no retry or fallback. Same KTH non-thinking model,
schema, output budget, reasoning none, tools [], tool_choice none, and prompt
template; only target and domain replaced. Payload comparison assertion passed.
Search Count 5, Sites ox.ac.uk, NeedContent false, NeedUrl true, text content,
QueryRewrite false. User's quality checklist was not included in model input.

## Measurements

- Search: 0.836 s, HTTP 200, 5 results, 5/5 official domains, 5/5 full-text fields,
  5/5 RankScore values. Evidence text fields 40699 characters; serialized evidence
  42460 characters / 42525 UTF-8 bytes; raw response 44859 bytes.
- Extraction: 1.476 s, HTTP 200 / completed; input 9508, output 7, total 9515
  tokens; reasoning 0, cache hit 0; 0 Requirements. Direct schema success.
- End-to-end: 2.382 s. This is fast failure/abstention, not successful extraction.

## Retrieval relevance and freshness

First result is the exact programme's departmental introduction:
https://www.cs.ox.ac.uk/admissions/graduate/cs-advanced-msc.html
It supplies only 1454 body characters: a broad audience description and 2025-26
specialisation/course-completion information, referring readers elsewhere for
entry requirements. The text's 'here' link target is not preserved in returned
plain text. The central graduate admissions requirements page was not a result.

Other four results: undergraduate UCAS application, undergraduate Computer Science,
undergraduate applicant guide, and MSc Digital Scholarship. Official-domain rate
100% does not mean programme-relevant evidence: only 1/5 is the target programme,
and even that is not the detailed admission-requirements evidence needed.

Evidence is insufficient for a reliable programme requirement set. Posthoc official
inspection after extraction (not supplied to model, not used as fallback) found
the departmental URL now redirects to the central graduate admissions page, which
differs substantially from Doubao's short 2025-26 departmental text. This strongly
indicates a stale/indexed version; exact indexing age is unknown. The central page
itself labels requirements 2026-27 and separately updated costs 2027-28, so even
current page content must not be silently promoted to target Fall 2027.
https://www.ox.ac.uk/admissions/graduate/courses/msc-advanced-computer-science

## Quality checklist (posthoc only)

All requested topics have zero delivered coverage: academic degree, subject
background, mathematical ability, programming/projects, GRE/GMAT, English,
referees, transcript, CV, statement of purpose and other application materials.
There is no usable result on which to score factual precision, output official-
source rate, stage classification or cycle correctness: these are N/A, not 100%.
The empty array avoids copying unrelated undergraduate/course-completion rules,
but schema validity is not task success. The prompt explicitly permits an empty
array when evidence is insufficient; this behavior is consistent with that rule.
No definitive claim about the model's internal cause is made.

## Interpretation

KTH non-thinking extraction was 12.376 s / 10415 tokens / 13 records. Oxford's
1.476 s / 9515 tokens / 0 records is not a quality-preserving improvement. The
failure illustrates poor one-query recall and source-version risk despite fast
Custom search. Suitable only for a diagnostic comparative evaluation that counts
empty outputs, relevance and freshness failures; not a production candidate yet.
No automatic mitigation, second query, Oxford retry, production edit, deployment,
commit or push. Stopped after this one Oxford run.
