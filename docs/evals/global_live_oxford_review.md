# Oxford Global -> live fetch -> none: blocked at fetch

One successful Global search using the exact fixed query, Top 5. Search latency
0.769 s, HTTP 200, exact official admissions URL at rank 1:
https://www.ox.ac.uk/admissions/graduate/courses/msc-advanced-computer-science?trk=public_post_comment-text

Live GET used the discovered URL without substituting cached search content.
HTTPS Oxford domain validation before each redirect; no redirects occurred.
Fetch latency 4.468 s, HTTP 403 Forbidden; final URL equals discovered URL.
No successful page body, entry/supporting sections or freshness assessment.
Reason for server refusal is not determined (403 alone does not prove WAF cause).
No tracking-parameter removal, alternate user agent, retry or fallback attempted.

Full measured run wall-clock 5.295 s. DeepSeek requests 0, tokens 0, extraction
latency N/A, requirement count N/A (not a model-produced empty array). Structured
output, completeness, correctness, source/stage/cycle quality cannot be scored.
This is an unsuccessful pipeline, not a successful low-latency extraction.

Before the live run, missing bs4 caused import-time failure without network calls;
the experiment was changed to use standard-library HTMLParser. No dependency
installation or production code edit. Thus there was still only one live search
and one live GET in the actual experiment.

Discovery has now succeeded twice consecutively including the previous Global vs
Custom experiment, both rank 1; this is encouraging, not statistical stability.
Direct fetch freshness benefit and none extraction quality remain untested due
to 403. Resolve/understand permitted live-access constraints before claiming this
combination ready for expanded comparative evaluation. No Oxford autonomous-low
matched baseline exists here; 63.727 s was KTH and cannot validate this failed run.

Stopped, no DeepSeek invocation, production edits, deployment, commit or push.
