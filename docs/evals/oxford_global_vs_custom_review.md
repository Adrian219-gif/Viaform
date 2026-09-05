# Oxford pure retrieval: Global vs Custom

Fixed query: University of Oxford MSc Advanced Computer Science entry requirements
One request per endpoint, in Global then Custom order. Top 5 requested through
DocCount/Count respectively. No domain filter on either side because Global's
documented API lacks Custom's Sites allowlist; no site operator added to query.
No DeepSeek, Oxford direct fetch, second query, fallback or retry.
Official Global documentation: https://www.volcengine.com/docs/87772/2548026?lang=zh

| Metric | Global | Custom |
|---|---:|---:|
| Latency | 0.807 s | 0.375 s |
| Actual results | 5 | 5 |
| Exact admissions page | 1, rank 1 | 0 |
| Other relevant official | 0 | 1 departmental introduction |
| Irrelevant official | 0 | 1 undergraduate CS |
| Nonofficial | 4 | 3 |

## URLs in API order (one-based display ranking)

Global:
1. https://www.ox.ac.uk/admissions/graduate/courses/msc-advanced-computer-science?trk=public_post_comment-text
2. https://liuxue.xdf.cn/blog/likun3/blog/5129972.shtml
3. https://collegedunia.com/uk/university/865-university-of-oxford-oxford/master-of-science-msc-advanced-computer-science-170427
4. https://ulec.com.cn/posts/uk-oxford-cs/
5. https://www.htiedu-uk.com/news-3748.html

Custom:
1. https://www.cs.ox.ac.uk/admissions/graduate/cs-advanced-msc.html
2. https://www.ox.ac.uk/admissions/Undergraduate/courses/course-listing/computer-science
3. https://m.hksg.org/major_5976
4. https://liuxue.xdf.cn/blog/blog_8049034.shtml
5. https://m.sohu.com/a/808365988_121124324

Exact-page matching ignores the trk parameter. Global API Rank=0 means first
result. Departmental introduction is target-programme-related but not counted
as the exact admissions-page hit, consistent with previous failures.

## Evidence and freshness

Global returns Snippet arrays, not a Content full-body field. Its first result
contains the actual 2026-27 entry-requirements section, degree/background,
mathematical/programming criteria, GRE/GMAT and part of English score table.
These agree with the official content inspected in prior turns. It does not
contain the entire application-material section, and the summary ends partway
through the English table. DocumentInfo.ContentCharCount 32034 is metadata, not
32034 characters actually returned as body. PublishTime empty; no indexing or
cache timestamp. Thus currently compatible excerpts, not proof of a fully fresh
snapshot or complete 2027 evidence. No new direct-fetch verification was done.

Custom returns full Content fields, but target hit remains the 1454-character
old departmental introduction featuring 2025-26 specialisations, rather than
the current redirect destination's admissions body established in prior audits.
This is a clear persistence of the earlier stale-version symptom; actual cache
age unknown. Other Custom results include explicitly 2025-cycle third-party
content. Global's third parties also cannot be assumed current or accurate.

## Interpretation

Global's additional 432 ms bought the exact admissions-page hit in this sample,
an important improvement over Custom. Worth further retrieval/evidence-coverage
evaluation, but not proof of stable recall from one sample. Comparing freshness
is limited by distinct sources and excerpt-vs-body formats: Global provided more
current/useful target admission evidence, not a controlled same-page full-text
freshness benchmark. No complete Requirements extraction claim is made.

Nonofficial results must not be accepted as university evidence. Both calls
succeeded HTTP 200. No production edits, deploy, commit or push; stopped.
