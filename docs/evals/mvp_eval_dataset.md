# MVP Eval Dataset

## Dataset contract

- 版本：MVP V1
- 范围：Requirements → Adaptive Interview → Gap → Timeline → Planning
- Case 类型：`core`、`behavioral_edge`、`regression`
- `tags` 可表达一个 case 的交叉属性；历史真实 Bug 在不重复创建 case 的前提下增加 `regression` tag。
- 动态事实原则：院校官网 Requirements 与 Timeline 不在本文件中固化为永久 gold answer。需要核对动态官网事实的 case 标记 `requires_live_web_search: true` 和 `requires_manual_review: true`，执行时按下方统一 Manual Review Rubric 评估实际产品影响与用户风险。
- 本文件只定义测试输入、预期行为和通过标准，不包含本轮执行结果。

## Manual Review Rubric

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

## Fixed User Fixture

### UF-CORE-001 — Core workflow applicant

- `fixture_id`: `UF-CORE-001`
- `planning_reference_date`: `2026-08-28`
- `intended_entry_cycle`: `Fall 2027`
- `initial_profile`: 本科院校 KTH Royal Institute of Technology；本科专业 Computer Science。其余 evidence 在 Adaptive Interview 中按下列脚本回答。
- `user_answer_script`: 执行器按当前 question 的 expected evidence keys 选择对应固定回答；同一 evidence key 始终复用首次答案，不因学校改变而改变。

| expected evidence keys / topic | 固定用户回答 | 预期 evidence 终态 |
| --- | --- | --- |
| `education.university` + `education.major` | `KTH CS` | 两项均 `known`；若 initial Profile 已注入则跳过提问 |
| `gpa` / `average_score` | `我的本科平均分是 85/100，没有单独的 GPA。` | `average_score=85/100` 为 `known`；`gpa` 为 `known_negative` |
| `courses` | `学过 Algorithms、Data Structures、Discrete Mathematics、Linear Algebra、Calculus、Probability、Operating Systems、Computer Networks 和 Machine Learning。` | `courses` 为 `known`，保留课程列表 |
| `ielts` / `toefl` | `IELTS 总分 7.0，听力 7.0，阅读 7.5，写作 6.5，口语 6.5；没有 TOEFL。` | IELTS 总分及四项为 `known`；TOEFL 为 `known_negative` |
| `gre` / `gmat` | `GRE 和 GMAT 都没有。` | 两项均 `known_negative` |
| `experience` | `有一段 3 个月的软件工程实习，以及一个机器学习课程项目；没有正式科研经历。` | 实习与项目为 `known`；科研经历为 `known_negative`（若分 slot） |
| `materials.cv` | `CV 已准备。` | `known` |
| `materials.personal_statement` / `materials.statement_of_purpose` | `个人陈述还没有。` | `known_negative` |
| `materials.transcript` | `成绩单已有。` | `known` |
| `materials.degree_certificate` | `学位证已有。` | `known` |
| `materials.recommendations` | `推荐信暂时没有。` | `known_negative` |
| `materials.portfolio` | `作品集暂时没有。` | `known_negative` |
| `materials.video` | `申请视频暂时没有。` | `known_negative` |
| 未列出的事实或 conditional applicability | `不清楚。` | 当前 slot 为 `unknown`，不得重复追问 |

- `comparison_rule`: Core case 的 Gap/Planning 比较以相同 live Requirements snapshot、相同 Timeline snapshot、上述 fixture 和固定 `planning_reference_date` 为前提；官网 snapshot 变化时不得把跨时间结果差异直接判为产品回归。

## Core Cases

### CORE-001 — RCA Painting MA

- `case_id`: `CORE-001`
- `module`: `End-to-End MVP Workflow`
- `case_type`: `core`
- `user_fixture`: `UF-CORE-001`
- `user_answer_script`: 使用 `UF-CORE-001.user_answer_script`，不得临时补充或改写用户背景。
- `input / scenario`: 用户选择 Royal College of Art 的 Painting MA，确认一个未来入学周期，依次进入 Requirements、Adaptive Interview、Gap、Timeline 与 Planning。
- `expected_behavior`: 优先从当前官方项目页获取 programme-level Requirements；访谈只补齐当前要求需要的用户证据；Gap 保留 Requirement 与 evidence 关联；Timeline 只使用所选申请周期的官方信息；Planning 根据 Gap 与 Timeline 生成统一阶段计划。
- `pass_criteria`: 全链路结构化输出均通过 schema；Requirements 的事实、数量、阈值、材料要求与来源层级经人工对照当时官网确认；访谈最终收敛；每个可匹配 Requirement 均有合理 Gap 结果；Timeline 不借用其他周期日期；Planning 不遗漏 required Gap，且无精确 Deadline 时不伪造日期。
- `requires_live_web_search`: `true`
- `requires_manual_review`: `true`

### CORE-002 — Oxford MSc Advanced Computer Science

- `case_id`: `CORE-002`
- `module`: `End-to-End MVP Workflow`
- `case_type`: `core`
- `user_fixture`: `UF-CORE-001`
- `user_answer_script`: 使用 `UF-CORE-001.user_answer_script`，不得临时补充或改写用户背景。
- `input / scenario`: 用户选择 University of Oxford 的 MSc Advanced Computer Science，确认目标入学周期后运行完整申请规划流程。
- `expected_behavior`: Requirements 与 Timeline 以该项目和所选周期的当前官方页面为准；Adaptive Interview 复用已有 Profile，只追问缺失 evidence；Gap 与 Planning 使用同一组 Requirement 关联。
- `pass_criteria`: 项目身份准确；动态官网事实由人工确认而非使用静态 gold；Requirements、Gap、Timeline、Planning 输出均满足 schema；Timeline 不混入其他 programme 或其他年份日期；主计划只由 required/hard Gaps 驱动，可选项不阻塞主计划。
- `requires_live_web_search`: `true`
- `requires_manual_review`: `true`

### CORE-003 — UC Berkeley M.S. in Electrical Engineering and Computer Sciences

- `case_id`: `CORE-003`
- `module`: `End-to-End MVP Workflow`
- `case_type`: `core`
- `user_fixture`: `UF-CORE-001`
- `user_answer_script`: 使用 `UF-CORE-001.user_answer_script`，不得临时补充或改写用户背景。
- `input / scenario`: 目标项目固定为 University of California, Berkeley 的 `Master of Science in Electrical Engineering and Computer Sciences (M.S. EECS)`；执行时由人工确认该项目当前官方名称和 exact programme URL，再选择目标申请周期。
- `expected_behavior`: Requirements 和 Timeline 只绑定已确认的 M.S. EECS 项目；不得混入 Berkeley 其他 CS/EECS 学位路径；后续访谈、Gap 与 Planning 均沿用同一 target programme identity。
- `pass_criteria`: 人工确认项目身份与官方 URL 正确；不得合并其他项目的 Requirements；动态要求经官网复核；访谈能够收敛；Timeline 仅对应所选周期；Planning 的每条 Action 保留正确 `source_gap_id`。
- `requires_live_web_search`: `true`
- `requires_manual_review`: `true`

### CORE-004 — Imperial Applied Machine Learning MSc

- `case_id`: `CORE-004`
- `module`: `End-to-End MVP Workflow`
- `case_type`: `core`
- `user_fixture`: `UF-CORE-001`
- `user_answer_script`: 使用 `UF-CORE-001.user_answer_script`，不得临时补充或改写用户背景。
- `input / scenario`: 用户选择 Imperial College London 的 Applied Machine Learning MSc，并为未来入学周期生成完整申请计划。
- `expected_behavior`: 从 exact programme 及适用的官方院系/学校页面整理 Requirements；只询问完成 Gap 判断所需的证据；Timeline 严格绑定用户选择的申请周期；Planning 按 Deadline 可用性决定使用精确日期或阶段。
- `pass_criteria`: Requirements 与来源层级通过人工复核；不得将相关但不同项目的要求混入；Adaptive Interview 无重复问题；Gap 状态与证据一致；Timeline 未公布时返回 `not_found`；对应 Planning 不包含伪造日期。
- `requires_live_web_search`: `true`
- `requires_manual_review`: `true`

### CORE-005 — KTH MSc Computer Science

- `case_id`: `CORE-005`
- `module`: `End-to-End MVP Workflow`
- `case_type`: `core`
- `user_fixture`: `UF-CORE-001`
- `user_answer_script`: 使用 `UF-CORE-001.user_answer_script`，不得临时补充或改写用户背景。
- `input / scenario`: 用户选择 KTH Royal Institute of Technology 的 MSc Computer Science，Profile 可包含简写形式的院校与专业信息，并确认目标申请周期。
- `expected_behavior`: 识别准确项目和官方来源；已有 Profile evidence 可复用；缺失证据才进入 Adaptive Interview；Timeline 与 Planning 使用用户确认的周期。
- `pass_criteria`: 官网动态事实经人工复核；`education.university` 与 `education.major` 等可复用 evidence 不被重复询问；所有 required Requirement 均进入 Gap 判断；Timeline 不使用其他周期日期；Planning 在无明确 Deadline 时仅生成阶段计划。
- `requires_live_web_search`: `true`
- `requires_manual_review`: `true`

## Behavioral / Edge Cases

### EDGE-001 — 学校与专业多字段纯值回答

- `case_id`: `EDGE-001`
- `module`: `Adaptive Interview`
- `case_type`: `behavioral_edge`
- `tags`: `[behavioral_edge, regression, multi_field_parsing]`
- `input / scenario`: 当前 question 的 expected evidence keys 为 `education.university`、`education.major`；用户回答 `KTH CS`（等价变体可使用“宁波诺丁汉大学 计算机专业”），回答中不要求显式出现字段 alias。
- `expected_behavior`: 直接按当前 expected keys 解析两个字段。
- `pass_criteria`: university 与 major 均为 `known`；两个 description slot 均非 `missing`；不生成重复 follow-up。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-002 — IELTS OR TOEFL alternative evidence

- `case_id`: `EDGE-002`
- `module`: `Adaptive Interview`
- `case_type`: `behavioral_edge`
- `tags`: `[behavioral_edge, regression, alternative_evidence, repeat_follow_up]`
- `input / scenario`: Requirement 为 `IELTS >= 7.0 OR TOEFL >= 100`，两个 evidence need 属于同一 `group_relation=any` group；用户提供 IELTS 7.5，未提供 TOEFL。
- `expected_behavior`: IELTS evidence 足以满足 alternative group 后，不再追问 TOEFL。
- `pass_criteria`: IELTS 为 `known` 且满足最低分；evidence group 被标记 satisfied；TOEFL 不出现在 `missing_slots` 或 follow-up；流程可继续进入 Gap。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-003 — Compound materials：“除了推荐信都有”

- `case_id`: `EDGE-003`
- `module`: `Adaptive Interview`
- `case_type`: `behavioral_edge`
- `input / scenario`: expected evidence keys 包含 CV、Personal Statement、transcript、degree certificate、recommendations；用户回答“除了推荐信都有”。
- `expected_behavior`: 将 compound answer 拆分为每个材料的独立终态，而不是整体判为 unknown。
- `pass_criteria`: CV、PS、transcript、degree certificate 为 `known`；recommendations 为 `known_negative`；无 `missing_slots`，不重复追问。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-004 — “没有 / 暂时没有”进入 known_negative

- `case_id`: `EDGE-004`
- `module`: `Adaptive Interview`
- `case_type`: `behavioral_edge`
- `tags`: `[behavioral_edge, regression, negative_answer, repeat_follow_up]`
- `input / scenario`: 当前 follow-up 明确询问一个 missing evidence slot；分别使用“没有”和“暂时没有”作为固定输入变体。
- `expected_behavior`: 将当前 slot 记录为明确否定终态，而不是继续保持 missing。
- `pass_criteria`: availability 为 `known_negative`；对应 slot state 为 `known_negative`；无 follow-up；同一 slot 不再被询问。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-005 — “不记得”进入 unknown

- `case_id`: `EDGE-005`
- `module`: `Adaptive Interview`
- `case_type`: `behavioral_edge`
- `input / scenario`: 当前 question 正在询问一个或多个尚未回答的 evidence slots；用户明确回答“不记得”。
- `expected_behavior`: 将适用的当前 slots 记录为 `unknown` 终态。
- `pass_criteria`: availability/slot state 为 `unknown`；不得保留为 `missing`；不得对相同 slots 无限重复追问；流程可以继续收敛到 Gap。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-006 — IELTS 缺一个 subscore

- `case_id`: `EDGE-006`
- `module`: `Adaptive Interview`
- `case_type`: `behavioral_edge`
- `tags`: `[behavioral_edge, regression, partial_evidence, subscore_follow_up]`
- `input / scenario`: IELTS evidence 需要 overall、listening、reading、writing、speaking；用户已经提供 overall 7.5、reading 8、writing 7、speaking 7，但未提供 listening。
- `expected_behavior`: 保留已提供的 IELTS 字段，只针对 listening 生成 follow-up。
- `pass_criteria`: `missing_slots` 仅包含 `ielts.listening`；overall、reading、writing、speaking 均保持 `known`；follow-up 只询问听力；补充 listening 后所有 slots 进入终态。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-007 — Conditional requirement 未确认适用性

- `case_id`: `EDGE-007`
- `module`: `Planning`
- `case_type`: `behavioral_edge`
- `input / scenario`: 一个 conditional required Requirement 的适用条件尚未确认，对应 Gap 为 `unknown`，且直接补救会产生较高成本。
- `expected_behavior`: Action Selector 只生成低成本的 `confirm_information` 任务；在确认适用性前不生成补考、重修、制作材料等高成本补救任务。
- `pass_criteria`: 对应 `source_gap_id` 至少有一个确认任务；其 `action_kind=confirm_information`；不存在同一 conditional Gap 的高成本 remediation Action；其他 required Gaps 的计划不受阻塞。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-008 — Gap Plan evidence_type schema compatibility

- `case_id`: `EDGE-008`
- `module`: `Gap Evidence Planning`
- `case_type`: `behavioral_edge`
- `tags`: `[behavioral_edge, regression, schema_compatibility, evidence_type]`
- `input / scenario`: Gap Planner structured output 中一个 evidence need 返回历史同义值 `material_boolean`；另一个输入变体返回任意未知 `evidence_type`。
- `expected_behavior`: 兼容层将 `material_boolean` 归一化为现有枚举 `material_status`；任何其他未知值安全降级为 `generic` 并记录 warning；不得新增 evidence type。
- `pass_criteria`: 两个输入变体均不导致整份 Gap Plan schema validation 失败；归一化结果分别为 `material_status` 与 `generic`；其余 Gap Plan 内容保持可用，Gap Matching 算法不发生变化。
- `requires_live_web_search`: `false`
- `requires_manual_review`: `false`

### EDGE-009 — Berkeley 模糊项目身份

- `case_id`: `EDGE-009`
- `module`: `Target Program Confirmation`
- `case_type`: `behavioral_edge`
- `tags`: `[behavioral_edge, programme_identity, ambiguous_input]`
- `input / scenario`: 用户只输入 `Berkeley CS MS / EECS`，未提供可唯一确定学位路径的 exact programme URL。
- `expected_behavior`: 将输入视为待确认的项目身份，不得静默合并或混用 Berkeley 不同 CS/EECS 项目；通过当前 Target Program Confirmation 流程给出一个明确 programme identity 与官方 URL，供用户确认后再进入 CORE-003。
- `pass_criteria`: 输出只对应一个明确项目；programme name 与 official URL 语义一致；不把多个项目 Requirements 合并；若无法可靠唯一识别则不得假装已确认。项目身份与官网 URL 需要人工核对。
- `requires_live_web_search`: `true`
- `requires_manual_review`: `true`

## Regression Cases

### REQ-REG-001 — RCA Painting MA section-level recall

- `case_id`: `REQ-REG-001`
- `module`: `Requirements Retrieval`
- `case_type`: `regression`
- `input / scenario`: 已知 RCA Painting MA 的 `official_program_url`。历史失败表现为模型只召回 Overview 或学校通用申请页，漏掉同一项目页内的 Requirements section。
- `expected_behavior`: 第一次搜索锚定 exact programme URL 与 program name，优先提取项目页的 programme-level Requirements；第二次搜索仅补材料、语言等仍缺失要求。
- `pass_criteria`: 能从当前官方来源召回学历、Portfolio、约 300 词 Personal Statement、最长 2 分钟 Video、English requirement；项目页事实保持 `source_level=program`、`source_type=official_retrieval`、`verification_status=official_verified`，并保留 exact programme page URL。上述动态事实执行时须由人工再次对照官网确认。
- `provenance_note`: `official_verified` 是当前产品内部 provenance enum，表示模型将该项归因于官方来源；它不代表 backend 独立 verifier 已抓取并验证了官网事实，因此本 case 仍要求 Manual Review。
- `requires_live_web_search`: `true`
- `requires_manual_review`: `true`
- `source_regression_record`: `docs/evals/regression_cases.md#REQ-REG-001`

## Dataset summary

| case_type | count | live Web Search | Manual Review |
| --- | ---: | ---: | ---: |
| Core | 5 | 5 | 5 |
| Behavioral / Edge | 9 | 1 | 1 |
| Regression | 1 | 1 | 1 |
| **Total** | **15** | **7** | **7** |

- `regression_tagged_cases`: 6（`EDGE-001`、`EDGE-002`、`EDGE-004`、`EDGE-006`、`EDGE-008`、`REQ-REG-001`）。其中前 5 个同时保留 `behavioral_edge` 身份，没有创建重复 case。
