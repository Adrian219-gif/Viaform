# MVP Baseline Eval Report

## Run metadata

- Dataset: `docs/evals/mvp_eval_dataset.md`
- Evaluation date: `2026-08-28` (Asia/Shanghai)
- Planning reference date: `2026-08-28`
- Intended entry cycle for Core cases: `Fall 2027`
- Cases: 15
- Product code / Prompt / Dataset changes during eval: none
- Dynamic-fact policy: cases marked `requires_manual_review=true` remain `MANUAL REVIEW` unless a separate technical failure prevents the workflow. `official_verified` is treated only as the current internal provenance enum, not as independent backend verification.
- Supplemental capture: the first evaluator discarded Requirements/Timeline payloads when Planning raised. Requirements + Timeline were therefore re-fetched only for CORE-001/002/005 for report preservation. These 6 additional Web Search API requests and 188.981 s are reported separately and are excluded from baseline latency averages.

## Manual Review Rubric

本 rubric 在 Baseline 原始结果之后固定，用于后续人工审核；本报告已有 verdict、指标、case 记录和历史观察不做自动或追溯重判。

Manual Review 不是要求模型逐字、逐项复刻官网全部内容，也不是 exhaustive factual audit。评价重点是错误或遗漏是否会实际影响用户的申请决策、资格判断、Gap 结果或 Planning，而不是追求与官网内容 100% 完整一致。

人工审核主要检查：

- 是否存在错误的硬性申请要求。
- 是否漏掉会影响申请资格或材料准备的重要 Requirement。
- Timeline 是否存在会影响行动计划的错误。
- 发现的错误是否会实际改变本 case 的 Gap 或 Planning 结果。

### Issue severity

#### Critical

- Deadline 或 application cycle 错误。
- 把 required requirement 判断为不需要。
- 严重错误的硬性资格门槛。
- 会直接导致用户错过申请或错误判断申请资格的问题。

#### Major

- 漏掉 required material 或其他 important requirement。
- 会导致 Gap 或 Planning 明显遗漏重要任务的问题。
- 重要 Requirement 存在 factual error，但不一定直接导致用户错过 Deadline。

#### Minor

- 不影响本 case 核心申请判断的边缘事实错误。
- 非核心行政信息过时。
- 用户当前未使用的 alternative requirement 存在轻微错误。
- 措辞或低影响 completeness 问题。

### Case verdict

- 存在任一 Critical issue：`FAIL`。
- 存在会实质影响本 case Gap 或 Planning 的 Major issue：`FAIL`。
- 只有 Minor issue：`PASS with issues`。
- 未发现实质问题：`PASS`。
- 动态事实尚未完成人工核对：`MANUAL REVIEW`。

### Manual review issue record

每个人工审核 issue 建议记录：

- `severity`
- `module`
- `observed_issue`
- `official_source`
- `impact_on_user_gap_planning`
- `verdict_rationale`

## Executive summary

| Metric | Result |
| --- | ---: |
| PASS | 8 |
| FAIL | 3 |
| MANUAL REVIEW | 4 |
| Strict total Case Pass Rate | 53.3% (8/15) |
| Non-failing completion incl. Manual Review | 80.0% (12/15) |
| Core completion | 40.0% (2/5 reached a validated Action Plan) |
| Behavioral / Edge strict pass rate | 88.9% (8/9; 1 Manual Review) |
| Regression strict pass rate | 83.3% (5/6 regression-tagged PASS; 1 Manual Review) |
| Interview convergence | 100% (5/5 Core reached Gap; all local interview cases passed) |
| Gap deterministic / structural checks | 100% of evaluated checks; no Gap-stage failure |
| Timeline date-fabrication violations | 0 |
| Planning hard-constraint violations | 3/6 Planning cases (50%); 3/5 live Core (60%) |
| Average latency, all case identities | 29.053 s |
| Average latency, live/manual case identities | 62.254 s |
| Baseline physical DeepSeek API requests | 26 (11 Web Search + 15 non-Web LLM; REQ-REG-001 reused CORE-001) |
| Supplemental capture requests | 6 Web Search API requests |

### Blockers

- Confirmed blocker cases: 3 (`CORE-001`, `CORE-002`, `CORE-005`), all at Planning validation.
- Additional Manual Review blocker: `REQ-REG-001` supplemental RCA snapshot returned zero Requirements; automated recall precondition was not met, but dynamic factual adjudication remains manual as required.
- Reported blocker count: 4 case-level blockers (3 confirmed FAIL + 1 Manual Review blocker).

## Per-case results

### EDGE-001 — PASS

- Actual result: `KTH CS` 与“宁波诺丁汉大学 计算机专业”均解析出 university + major；两个 slot 为 known，无 follow-up。
- Failure module: none
- Failure reason: none
- Latency: 0.001554 s
- DeepSeek requests: 0 live requests

### EDGE-002 — PASS

- Actual result: IELTS 7.5 满足 `group_relation=any`；group satisfied，未追问 TOEFL。
- Failure module: none
- Failure reason: none
- Latency: 0.002272 s
- DeepSeek requests: 0 live requests

### EDGE-003 — PASS

- Actual result: CV、PS、transcript、degree certificate=known；recommendations=known_negative；无 missing slot。
- Failure module: none
- Failure reason: none
- Latency: 0.000442 s
- DeepSeek requests: 0 live requests

### EDGE-004 — PASS

- Actual result: “没有”与“暂时没有”两个变体均进入 known_negative；无重复 follow-up。
- Failure module: none
- Failure reason: none
- Latency: 0.000109 s
- DeepSeek requests: 0 live requests

### EDGE-005 — PASS

- Actual result: “不知道 / 不记得 / 不清楚”进入 unknown；无 missing slot 或重复 follow-up。
- Failure module: none
- Failure reason: none
- Latency: 0.000150 s
- DeepSeek requests: 0 live requests

### EDGE-006 — PASS

- Actual result: 首次仅返回 `ielts.listening` missing；补充 Listening 7.5 后所有 IELTS slots known。
- Failure module: none
- Failure reason: none
- Latency: 0.000246 s
- DeepSeek requests: 0 live requests

### EDGE-007 — PASS

- Actual result: conditional Gap 仅生成 `confirm_information`；met Gap 无 Action；required/optional track 约束通过。使用本地 stub，无 live 请求。
- Failure module: none
- Failure reason: none
- Latency: 0.005851 s
- DeepSeek requests: 0 live requests

### EDGE-008 — PASS

- Actual result: `material_boolean → material_status`；未知 evidence_type → generic 并记录 warning；整份 Gap Plan 可用。使用本地 stub，无 live 请求。
- Failure module: none
- Failure reason: none
- Latency: 0.006093 s
- DeepSeek requests: 0 live requests

### CORE-001 — FAIL

- Actual result: Requirements, Timeline, Interview and Gap completed; Action Plan was rejected by the Planning Validator.
- Failure module: End-to-End MVP Workflow
- Failure reason: HTTPException: 502: Action kind violates code selector for Gap: materials:0
- Baseline latency: 70.556 s
- Baseline DeepSeek requests: 5（Web Search API 2；非 Web LLM 3）
- Supplemental snapshot capture: 72.965 s；2 additional Web Search API requests（Requirements 59.567 s；Timeline 13.399 s）
- Capture note: this supplemental snapshot may differ from the stochastic snapshot used by the original failed workflow; it is preserved for manual inspection only.
- Completed phase latency before failure: `{"requirements_seconds": 40.35, "timeline_seconds": 9.623, "interview_gap_plan_seconds": 10.227, "gap_analysis_seconds": 1.784}`

#### Actual Requirements snapshot

_本次快照返回 0 条 Requirements，未产生 source URL。_

#### Actual Timeline snapshot

```json
{
  "admission_cycle": "Fall 2027",
  "application_open_date": null,
  "application_open_source_url": null,
  "application_deadlines": [],
  "rolling_admission": null,
  "rolling_admission_source_url": null,
  "status": "not_found"
}
```

### CORE-002 — FAIL

- Actual result: Requirements, Timeline, Interview and Gap completed; Action Plan was rejected by the Planning Validator.
- Failure module: End-to-End MVP Workflow
- Failure reason: HTTPException: 502: Action kind violates code selector for Gap: language:1
- Baseline latency: 86.456 s
- Baseline DeepSeek requests: 5（Web Search API 2；非 Web LLM 3）
- Supplemental snapshot capture: 72.541 s；2 additional Web Search API requests（Requirements 58.977 s；Timeline 13.564 s）
- Capture note: this supplemental snapshot may differ from the stochastic snapshot used by the original failed workflow; it is preserved for manual inspection only.
- Completed phase latency before failure: `{"requirements_seconds": 49.652, "timeline_seconds": 11.103, "interview_gap_plan_seconds": 10.048, "gap_analysis_seconds": 2.248}`

#### Actual Requirements snapshot

_本次快照返回 0 条 Requirements，未产生 source URL。_

#### Actual Timeline snapshot

```json
{
  "admission_cycle": "Fall 2027",
  "application_open_date": null,
  "application_open_source_url": null,
  "application_deadlines": [],
  "rolling_admission": null,
  "rolling_admission_source_url": null,
  "status": "not_found"
}
```

### CORE-003 — MANUAL REVIEW

- Actual result: Full workflow completed; dynamic facts pending human review.
- Failure module: none
- Failure reason: none
- Baseline latency: 103.393 s
- Baseline DeepSeek requests: 5（Web Search API 2；非 Web LLM 3）
- Interview：11 questions / 12 turns；unresolved=[]
- Gap：11 results；status distribution={'unknown': 5, 'met': 1, 'not_met': 5}
- Planning：14 actions；timeline_status=complete；deadline=2026-12-01；ready_by=2026-11-10

| action_id | action_kind | time_period | target_date | source_gap_id | track |
| --- | --- | --- | --- | --- | --- |
| confirm_bachelor_degree | confirm_information | Immediate (by 2026-09-15) | 2026-09-15 | academic:0 | main |
| confirm_gpa_equivalent | confirm_information | Immediate (by 2026-09-15) | 2026-09-15 | academic:1 | main |
| confirm_english_test_scores | confirm_information | Immediate (by 2026-09-15) | 2026-09-15 | language:0 | main |
| confirm_gre_not_required | confirm_information | Immediate (by 2026-09-15) | 2026-09-15 | standardized_test:0 | main |
| confirm_research_experience_importance | confirm_information | Immediate (by 2026-09-15) | 2026-09-15 | experience:0 | main |
| draft_statement_of_purpose | resolve_gap | 2026-09-16 to 2026-09-30 | 2026-09-30 | materials:0 | main |
| draft_personal_history_statement | resolve_gap | 2026-09-16 to 2026-09-30 | 2026-09-30 | materials:1 | main |
| refine_cv | resolve_gap | 2026-09-16 to 2026-09-30 | 2026-09-30 | materials:2 | main |
| identify_recommenders | resolve_gap | 2026-09-16 to 2026-10-15 | 2026-10-15 | materials:3 | main |
| review_essays_1 | resolve_gap | 2026-10-01 to 2026-10-20 | 2026-10-20 | materials:0 | main |
| finalize_essays | resolve_gap | 2026-10-21 to 2026-11-05 | 2026-11-05 | materials:0 | main |
| request_recommendation_letters | resolve_gap | 2026-10-16 to 2026-11-10 | 2026-11-10 | materials:3 | main |
| prepare_application_submission | resolve_gap | 2026-11-01 to 2026-11-10 | 2026-11-10 | other:0 | main |
| submit_application | resolve_gap | 2026-11-11 to 2026-11-30 | 2026-11-30 | other:0 | main |

#### Actual Requirements snapshot

| category | requirement | provenance | source level | source URL |
| --- | --- | --- | --- | --- |
| academic | A bachelor's degree or recognized equivalent from an accredited institution is required. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| academic | A satisfactory scholastic average, usually a minimum GPA of 3.0 (B) on a 4.0 scale, is required. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| academic | Applicants must have enough undergraduate training to do graduate work in the chosen field. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| language | Applicants from countries where English is not the official language must demonstrate English proficiency: TOEFL iBT of at least 90 (or 570 paper-based) or IELTS Band score of at least 7.0. | official_verified | university | https://grad.berkeley.edu/admissions/requirements/ |
| standardized_test | The GRE is not required for EECS M.S./Ph.D. admission in recent admissions cycles. | model_memory_unverified | unknown | — |
| experience | The M.S. program emphasizes research preparation and experience (a research-oriented degree); research experience is valued but is not a formal admission requirement. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| materials | A Statement of Purpose is required, addressing why you are applying, what you hope to accomplish, and your goals after the degree. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| materials | A Personal History Statement is required, addressing past experiences that led you into the field and how your personal history will help you succeed. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| materials | A full resume/CV listing experience and education is required. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| materials | Letters of recommendation are required (typically three), submitted online through the application system. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| other | Applicants must submit the online UC Berkeley graduate application, with program-specific materials uploaded and recommender links sent in advance. | official_verified | program | https://berkeleyguidearchive.github.io/2024-25/graduate/degree-programs/electrical-engineering-computer-sciences/ |
| other | The application deadline for fall admission is December 1 (December 1, 2026 for Fall 2027 entry). | official_verified | university | https://grad.berkeley.edu/admissions/our-programs/ |

#### Actual Timeline snapshot

```json
{
  "admission_cycle": "Fall 2027",
  "application_open_date": "September 2026",
  "application_open_source_url": "https://eecs.berkeley.edu/academics/graduate/research-programs/admissions/",
  "application_deadlines": [
    {
      "label": "Application deadline",
      "type": "final",
      "date": "2026-12-01",
      "source_url": "https://grad.berkeley.edu/admissions/our-programs/?degrees=masters-professional#11"
    }
  ],
  "rolling_admission": false,
  "rolling_admission_source_url": "https://eecs.berkeley.edu/academics/graduate/faq-3/",
  "status": "complete"
}
```

### CORE-004 — MANUAL REVIEW

- Actual result: Full workflow completed; dynamic facts pending human review.
- Failure module: none
- Failure reason: none
- Baseline latency: 58.048 s
- Baseline DeepSeek requests: 5（Web Search API 2；非 Web LLM 3）
- Interview：8 questions / 9 turns；unresolved=[]
- Gap：8 results；status distribution={'unknown': 2, 'partial': 5, 'not_met': 1}
- Planning：8 actions；timeline_status=not_found；deadline=None；ready_by=None

| action_id | action_kind | time_period | target_date | source_gap_id | track |
| --- | --- | --- | --- | --- | --- |
| confirm_degree_equivalence | confirm_information | Before application | — | academic:0 | main |
| obtain_academic_transcript | complete_gap | Before application | — | academic:1 | main |
| verify_ielts_validity | complete_gap | Before application | — | language:0 | main |
| check_toefl_alternative | complete_gap | Before application | — | language:1 | main |
| develop_experience_plan | resolve_gap | Before application | — | experience:0 | main |
| write_personal_statement | complete_gap | Before application | — | materials:0 | main |
| obtain_two_referees | complete_gap | Before application | — | materials:1 | main |
| confirm_transcript_and_certificate_requirement | confirm_information | Before application | — | materials:2 | main |

#### Actual Requirements snapshot

| category | requirement | provenance | source level | source URL |
| --- | --- | --- | --- | --- |
| academic | Minimum entry standard is a First class Honours in Electrical/Electronic Engineering or a related subject with a substantial Electrical/Electronic Engineering component. | official_verified | program | https://www.imperial.ac.uk/study/courses/postgraduate-taught/applied-machine-learning/ |
| academic | The First class Honours requirement is commonly specified as a minimum of 75% overall. | model_memory_unverified | unknown | — |
| language | English proficiency is required, commonly stated as IELTS 7.0 overall with a minimum of 6.5 in all elements for this programme. | model_memory_unverified | unknown | — |
| language | English proficiency may also be evidenced by TOEFL 100 overall with a minimum of 22 in all elements. | model_memory_unverified | unknown | — |
| experience | When an applicant does not meet the entry requirements, but has at least three years of relevant work experience, exceptionally the Postgraduate Admissions Tutor may make a special case for admission. | official_verified | program | https://www.imperial.ac.uk/study/courses/postgraduate-taught/applied-machine-learning/ |
| materials | A personal statement is part of the application, typically aimed at one or two pages of A4 (roughly 500-1,000 words), explaining interest, relevant experience, and reasons for choosing Imperial. | model_memory_unverified | unknown | — |
| materials | Applicants typically provide two referees, at least one of whom must be an academic reference; the second may be academic or professional. | model_memory_unverified | unknown | — |
| materials | Official academic transcripts and degree certificate(s) demonstrating the first-class degree are required as part of the application. | model_memory_unverified | unknown | — |
| other | A staged admissions process with several application rounds applies; applicants are advised to apply as early as possible as places may not be available in later rounds. | official_verified | program | https://www.imperial.ac.uk/study/courses/postgraduate-taught/applied-machine-learning/ |
| other | A Master's application fee of £90 applies per application (excluding Imperial Business School courses) before submitting the application. | official_verified | program | https://www.imperial.ac.uk/study/courses/postgraduate-taught/applied-machine-learning/ |

#### Actual Timeline snapshot

```json
{
  "admission_cycle": "Fall 2027",
  "application_open_date": null,
  "application_open_source_url": null,
  "application_deadlines": [],
  "rolling_admission": null,
  "rolling_admission_source_url": null,
  "status": "not_found"
}
```

### CORE-005 — FAIL

- Actual result: Requirements, Timeline, Interview and Gap completed; Action Plan was rejected by the Planning Validator.
- Failure module: End-to-End MVP Workflow
- Failure reason: HTTPException: 502: Action kind violates code selector for Gap: materials:2
- Baseline latency: 72.769 s
- Baseline DeepSeek requests: 5（Web Search API 2；非 Web LLM 3）
- Supplemental snapshot capture: 43.475 s；2 additional Web Search API requests（Requirements 24.418 s；Timeline 19.057 s）
- Capture note: this supplemental snapshot may differ from the stochastic snapshot used by the original failed workflow; it is preserved for manual inspection only.
- Completed phase latency before failure: `{"requirements_seconds": 30.886, "timeline_seconds": 15.974, "interview_gap_plan_seconds": 12.462, "gap_analysis_seconds": 2.046}`

#### Actual Requirements snapshot

| category | requirement | provenance | source level | source URL |
| --- | --- | --- | --- | --- |
| academic | A bachelor's degree from an internationally recognised university equivalent to a Swedish bachelor's degree (180 ECTS credits) is required. Students in the final year of their bachelor's studies can apply and meet the requirement upon completion. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| course | Mathematics: four different subjects totalling 28.5 ECTS credits, which must include a course in Calculus in one variable, a course in Linear Algebra, a course in Probability Theory and Statistics, and a course in Discrete Mathematics. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| course | Computer technology / Computer science and engineering / Computer science / Information technology: three different subjects totalling 22.5 ECTS credits, which must include a course in Object Oriented Programming, a course in Algorithms and Data Structures, and an in-depth course in Algorithmic Complexity. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| course | Track-specific special eligibility: Multivariable analysis is a special eligibility requirement for compulsory courses in the Data analysis and Cognitive systems tracks; Human-computer interaction is a special entry requirement for compulsory courses in the Interaction Design track. Additional prerequisites may exist for some conditionally elective or recommended courses. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| language | English proficiency equivalent to the Swedish upper secondary course English 6 / English Level 2 is required. This can be met with an English test, for example an overall IELTS score of 6.5 or a TOEFL score of 90 (iBT), or through completed upper secondary or university studies depending on your country of previous studies. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| materials | Official degree certificates of completed degrees must be submitted; documentation requirements vary by country. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| materials | An official transcript of courses and grades completed in your degree must be submitted (students from Swedish universities using Ladok do not need to submit degree certificates or transcripts). | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| materials | Proof of English proficiency must be submitted; what proof is needed depends on whether you meet the requirement through a test or previous studies. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| materials | A copy of your passport with personal data and photograph, or other identification document, must be submitted. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| materials | A CV in English is required, clearly and concisely outlining education, relevant research or work experience, extracurricular activities, qualifications and achievements; no standard template is required. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| materials | A letter of motivation in English, less than 500 words, is required, explaining why you chose this programme at KTH, what you hope to gain, and how your interests and skills will help you succeed; include an autobiography of academic and professional pursuits. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |
| materials | Two letters of recommendation are required describing why you are the right choice, preferably one from an academic environment and one from a professional setting; letters must include referees' full contact details and an English translation if in another language. | official_verified | program | https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975 |

#### Actual Timeline snapshot

```json
{
  "admission_cycle": "Fall 2027",
  "application_open_date": "2026-10-16",
  "application_open_source_url": "https://www.kth.se/en/studies/master/computer-science/msc-computer-science-1.419974",
  "application_deadlines": [
    {
      "label": "Last day to apply",
      "type": "final",
      "date": "2027-01-15",
      "source_url": "https://www.kth.se/en/studies/master/computer-science/msc-computer-science-1.419974"
    }
  ],
  "rolling_admission": null,
  "rolling_admission_source_url": null,
  "status": "complete"
}
```

### EDGE-009 — MANUAL REVIEW

- Actual result: `{"university": "University of California, Berkeley", "program": "EECS - Computer Science MS", "official_program_url": "https://grad.berkeley.edu/program/eecs-computer-science-ms/", "official_domain": "grad.berkeley.edu", "confirmation_status": "confirmed", "intended_entry_year": 2027, "intended_entry_term": "fall"}`
- Failure module: none
- Failure reason: none; programme identity and official URL require human review.
- Latency: 4.207 s
- DeepSeek requests: 1（Web Search API 1；非 Web LLM 0）

### REQ-REG-001 — MANUAL REVIEW

- Actual result: supplemental RCA Requirements snapshot returned 0 items and no source URLs. The automated section-recall precondition is not satisfied; because this case mandates Manual Review, no claim is made here about current website truth.
- Failure module: Requirements Retrieval (manual-review blocker)
- Failure reason: zero Requirements were returned in the preserved supplemental snapshot; the original CORE-001 snapshot was not retained after its later Planning exception.
- Latency: 59.567 s (supplemental Requirements capture)
- DeepSeek requests: 1 Web Search API request for the preserved snapshot; 0 additional requests for logical reuse in the case table.
- Actual Requirements: empty list `[]`
- Actual source URLs: none
- Provenance note: no `official_verified` item was returned. If present in future runs, that enum still would not represent an independent backend verifier.

## Metric details

### Interview convergence

- All five Core workflows finished Gap planning, applied the fixed fixture, and reached Gap Analysis before any failure.
- EDGE-001/002/003/004/005/006 all passed their terminal-state or missing-slot assertions.
- No repeated-question or unresolved-slot failure was observed in the baseline run.

### Gap deterministic checks

- No Core failed in Gap Planning, evidence parsing, deterministic matching, or semantic matching.
- OR alternatives, known_negative, unknown, partial IELTS subscores, compound materials, and evidence_type compatibility all passed their dedicated cases.

### Timeline date-fabrication checks

- CORE-004 returned `not_found` with no dates; its validated Planning output used phase labels and null target dates.
- Supplemental CORE-001 and CORE-002 snapshots also returned `not_found` with no dates.
- CORE-003 and supplemental CORE-005 returned explicit dates with source URLs; factual/current-cycle correctness remains Manual Review.
- Automated fabrication violations: 0.

### Planning hard constraints

- EDGE-007 passed the conditional-confirmation constraint.
- CORE-003 and CORE-004 produced validated Action Plans.
- CORE-001, CORE-002 and CORE-005 were rejected because the model-generated `action_kind` did not match the code-owned selector for a source Gap.

## Failure slices

| Module | Failure class | Cases | Count | Observation |
| --- | --- | --- | ---: | --- |
| Planning | Action Selector contract violation | CORE-001, CORE-002, CORE-005 | 3 | Model Action `action_kind` differed from the code-selected kind; validator rejected the whole plan. |
| Requirements Retrieval | Empty / unstable section recall | CORE-001, CORE-002, REQ-REG-001 | 3 observations | Supplemental RCA and Oxford captures returned zero Requirements despite the original workflows reaching Planning; indicates stochastic recall stability risk. |
| Target identity / provenance | Source freshness and exact-programme review | CORE-003, EDGE-009 | 2 Manual Review observations | Berkeley Core used an archived 2024-25 guide plus general graduate pages; identity edge returned a current-looking URL that requires human confirmation. |
| Adaptive Interview | None | — | 0 | All local behavior cases passed; all Core interviews reached Gap. |
| Gap | None | — | 0 | No deterministic or schema failure. |
| Timeline | Date fabrication | — | 0 | No automated violation detected. |

## Regression status

- PASS: EDGE-001, EDGE-002, EDGE-004, EDGE-006, EDGE-008.
- FAIL: none confirmed.
- MANUAL REVIEW / blocker: REQ-REG-001 (preserved snapshot returned zero Requirements).

## Top three priorities

1. **Planning Action Selector compliance** — 3/5 live Core plans were rejected by the same hard validator class. This is the highest direct completion blocker.
2. **Requirements recall stability for known programme URLs** — RCA and Oxford supplemental captures returned empty Requirements, while their original runs progressed to Planning. Stabilize section-level recall before relying on one-shot snapshots.
3. **Exact programme identity and current-source quality for Berkeley** — CORE-003 relied heavily on an archived 2024-25 guide and general graduate pages; identity/source freshness needs stronger manual or product-level resolution.

## Manual review queue

- CORE-003: verify M.S. EECS identity, 12 Requirements, archived/current source applicability, and Fall 2027 Timeline.
- CORE-004: verify 10 Requirements (6 AI references), exact-programme applicability, and that Fall 2027 Timeline is genuinely unpublished.
- EDGE-009: verify `EECS - Computer Science MS` and `https://grad.berkeley.edu/program/eecs-computer-science-ms/` refer to the intended programme.
- REQ-REG-001: manually inspect the current RCA Painting MA page and adjudicate the zero-item preserved snapshot against the live page.
