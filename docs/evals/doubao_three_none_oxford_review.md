# Oxford Advanced CS: bounded three Custom searches + none

Three actual Custom requests, all restricted by Filter.Sites ox.ac.uk, Count 5,
NeedUrl true, NeedContent false, text, no query rewrite. No other retrieval
provider, direct fetch or request retry. One extraction with unchanged production
Requirements schema, same generic prompt template, target Oxford Fall 2027,
deepseek-v4-flash reasoning none, tools [], tool_choice none. Baseline facts not
included in prompt. Identity URL in final search is not a baseline answer.

## Per-round log

1. Query: University of Oxford MSc Advanced Computer Science entry requirements application documents
   0.279 s; 5 results, all official. Only exact-programme departmental overview,
   not admissions body; remaining undergraduate or other programme. Insufficient
   academic/language/materials evidence; continue. Old 2025-26 overview persists.
2. Query: Oxford MSc Advanced Computer Science graduate admissions requirements English supporting documents
   0.844 s; 5 results, all official. Departmental graduate directory, undergraduate
   pages and general deadlines; no exact MSc admissions body. Still insufficient;
   continue. General/old-cycle content cannot establish target programme rules.
3. Query: site:ox.ac.uk/admissions/graduate/courses/msc-advanced-computer-science entry requirements
   0.749 s; 3 results, all official. Old departmental overview, undergraduate CS,
   DPhil CS; none is requested exact admissions body. Insufficient; stop at cap.
   The site/path operator did not force exact-page recall; server domain filter
   was respected, but path relevance was not.

A planned round-2 query exceeded the documented 100-character limit and was
blocked locally before any request. Its AssertionError remains in the raw report
as historical local error. Shortening it produced actual request 2; no HTTP retry
occurred. All three actual searches returned HTTP 200. This is not an API failure.

## Results

Retrieval total 1.872 s. Exact admissions-page hit: 0 across all three rounds;
the target departmental overview was found, but it lacked detailed requirements.
URL-deduplicated official evidence was provided once; irrelevant official material
was not re-labelled as the target programme. Freshness concern remains the same
old departmental snapshot identified in previous posthoc audits; no new live
website fetching was used in this experiment.

Extraction 0.778 s; HTTP 200 / completed; input 14947 / output 5 / total 14952
tokens, reasoning 0, cached input 9472. Requirements 0; direct schema success;
web_search_calls 0. Output is an empty requirements array.

Active API-stage total 2.650 s. This is NOT a continuous wall-clock end-to-end
measurement: staged approvals and evidence inspection are excluded; full-session
wall-clock was not instrumented. Fast empty output must not be sold as successful
latency improvement against autonomous-low's 63.727 s KTH sample. No matched
Oxford autonomous-low baseline is available in this experiment history.

## Posthoc quality

Delivered coverage is zero for every requested category: degree, subject
background, mathematical ability, programming/projects, GRE/GMAT, English,
referees, transcript, CV, statement of purpose and other application materials.
No returned facts exist, so output precision, official-source rate, programme-
level, stage and admission-cycle correctness are N/A (not 100%). Retrieved URL
official-source rate is 13/13 result occurrences, a different metric.

Abstention avoids incorrectly importing undergraduate/DPhil rules, but does not
meet the requirements retrieval objective. Main blocker is exact-page recall;
stale/irrelevant evidence is an additional persistent problem. Three changed
queries did not solve the previous one-query failure. Cannot establish adequate
none-extraction quality without relevant evidence or meaningful speed superiority.

Stopped after Oxford; no fourth search, repair, production modification,
deployment, commit or push. Only experiment code and reports changed.
