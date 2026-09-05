# Global URL discovery -> guided DeepSeek low: Oxford

One Global request, fixed query and Top 5. Exact admissions URL ranked first,
0.676 s. Only its URL (not cached snippets or baseline answers) supplied to
deepseek-v4-flash low with native web_search auto. Prompt explicitly prohibited
broad rediscovery, allowed only necessary linked official supporting pages and
required early stopping. Current Requirements schema used. No local direct fetch,
Custom, client retry, fallback or production workflow.

## Measurements

DeepSeek request count 1; HTTP 200 / completed, 62.203 s. Full wall-clock 63.036 s.
Input tokens 51370, output 4739, reasoning 3252 within output, total 56109,
cached input 45824. Native calls 20: open_page 15, search 3, find_in_page 2.
Six completed calls (3 search, 2 departmental opens, 1 find); fourteen failed.

First call opened the supplied exact URL including tracking parameter and failed.
Subsequent calls tried its canonical variant repeatedly, other paths, programme
PDF and departmental pages. Three searches rediscovered requirements broadly.
One attempted open was web.archive.org, outside the allowed official domain,
and failed. This is a provider-side instruction-adherence failure; these actions
were not a client-implemented fallback or retry workflow.

No successful central admissions-page open is recorded. The exact underlying
HTTP status for provider tool failure is not exposed, so do not claim provider
returned 403 specifically. It did not solve the previously observed local 403
access problem in the outcome sense: current admissions body was not obtained.

Final assistant message is prose describing central-domain access failure and
intent to explore departmental pages, not Requirements JSON. schema_valid false;
zero usable requirement records, not a valid empty-array response. Completed
API status is not task completion. No output repair or second model call.

## Quality and comparison

Delivered completeness zero. Fact correctness, provenance rate, programme/stage/
cycle correctness and current-page freshness are N/A. Successful departmental
access alone does not establish current admissions evidence; raw page snapshots
were not retained by the collector. No quality-preservation claim is possible.

Compared with KTH autonomous-low: 20 vs 6 calls (3.33x), 63.036 vs 63.727 s
(about 1.1% faster, not material), 56109 vs 30290 total tokens. This is cross-case
and different-schema comparison, not matched Oxford controlled benchmarking.
Exact URL provision did not constrain the provider's autonomous search behavior.

Conclusion: failed combination for this sample; discovery works but page access
and adherence remain blockers. Stopped, no mitigation, no additional tests,
no production edits/deploy/commit/push.
