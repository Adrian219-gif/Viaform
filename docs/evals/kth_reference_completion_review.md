# Fast Official Retrieval + AI Reference Completion: display-only KTH

One Doubao Custom search, three DeepSeek v4-flash non-thinking calls (extraction,
gate, reference). No model tools, additional retrieval, direct fetch, retries,
baseline answer injection, production integration, deployment, commit or push.

## Performance

- Search 0.252 s, 5 official results, exact entry page first.
- Extraction 16.164 s, 18 rows, direct schema success, 11281 tokens
  (input 7847 / output 3434, reasoning 0).
- Fast Path internal elapsed 16.468 s; parent subprocess-inclusive elapsed saved
  in raw report. Evidence remains same old-version material as earlier runs.
- Quality Gate 6.054 s, 14 gaps, schema success.
- Reference completion 15.029 s, 14 references, no abstentions, schema success.
- Full measured wall-clock 37.906 s (includes local processing and subprocess,
  excludes pre-launch approval). Total model calls 3; search API requests 1.
- Total tokens input 23200 / output 6314 / total 29514.
- 40.5% below autonomous-low 63.727 s, but 2.3x this run's Fast Path; not a
  controlled same-schema comparison against autonomous-low.

## A: factual extraction

Official-evidence label means grounded in supplied university-source content,
NOT guaranteed current or correct applicability. All 18 rows cite the exact
programme page. Fixture topic recall 15/15 (admission-only 14/14), before any AI
completion. This run already contains motivation content and postal/not-email
recommendation details missing from an earlier non-thinking sample. Thus that
improvement predates B/C and cannot be attributed to AI completion.

Quality defects remain: three in-program course-condition rows are incorrectly
labelled pre_admission. Degree/final-year stage classification remains coarse.
Old evidence repeats TOEFL 90 and 3 February; the prior official-page audits
showed newer wording. Provenance does not certify source freshness or stage.

## B: gate contract violation

Gate correctly returns a schema-shaped list, but not a compliant gaps-only gate:
its reasons introduce specific deadline dates, SEK 900, and four-programme limits.
Those values leak from existing evidence into the subsequent reference prompt.
It also expands into tuition, visa/residency, acceptance statistics, contact
information and in-program details rather than staying within admission-detail
gaps. Duplicate track/syllabus gaps further inflate the list.

No repair or rerun was performed. The run is a negative result for gate adherence;
some references cannot be attributed purely to model memory because the gate
supplied factual answers. No baseline was supplied in either prompt.

## C: reference audit

All 14 additions have ai_reference/confidence/uncertainty, no source URL, and are
kept in a separate array. Official rows are copied unchanged. All additions
self-classify as general_advice, even where they contain KTH-specific assertions.
No formal Gap or Planning consumer receives them.

Coarse reference-level posthoc buckets (not fact-level precision):
- 4/14 partially overlap existing fixture facts: track prerequisites/syllabus
  (indices 9,10), selection criteria (12), Ladok exemption (13). These repeat
  already present facts rather than restore missing core requirements.
- 2/14 contain facts supported by other original evidence but outside the core
  fixture: fee (2) and programme ranking limit (6). Gate already disclosed those
  facts; neither is a clean test of memory-based recovery. Other clauses in these
  paragraphs remain unverified; particularly eligibility is not guaranteed offer.
- 1/14 contains a clear conflict/unsupported interpretation: acceptance statistics
  (11) described as not typically published with requirements/external, while
  supplied official page itself publishes the figure. Added 10-15% range is not
  established by that single-year evidence and is not a 2027 verified figure.
- 7/14 remaining entries are generic/uncertain or not verifiable against the
  available baseline (0,1,3,4,5,7,8). They are not counted as correct factual fills.

All 14 express uncertainty, but none abstains entirely. Some broad advice (such
as international-student permits, translation rules, offer response) needs
citizenship/country/round conditions and cannot be promoted to programme rules.
No reliable overall factual accuracy percentage can be derived from this mixture
of advice, repetitions and claims without a much broader fact audit.

Core completeness A -> merged remains 15/15 (admission-only 14/14). Verified
incremental core/detail recovery against the existing fixture: 0. Two peripheral
topics partly supported by evidence are added, but no demonstrated recovery of
missing recommendation/motivation detail (already present in A). At least one
conflict with original official evidence remains in raw AI output. No official
row was overwritten; precedence is preserved in data layout but conflict-free
AI output was NOT achieved.

## Recommendation

No demonstrated meaningful detail-completeness gain over this run's Fast Path.
Do not claim the reference factual accuracy is sufficient for unqualified display.
May support a provenance hierarchy conceptually, but official_verified >
ai_reference > unknown is an ordering of evidential support, not automatic
truth or freshness. Keep uncertain advice visibly separate; do not allow it to
repair or override verified requirements. In this experiment both gate scope and
conflict control fail. No corrective changes were implemented; stopped after KTH.
