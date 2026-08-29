# MVP Manual Review Adjudication Results

## Adjudication scope

- Adjudication date: `2026-08-28`
- Rubric: `docs/evals/mvp_eval_dataset.md` 中的统一 Manual Review Rubric。
- Evidence policy: 本文件只整理已经完成的人工官网核对结论；未重新访问官网，未调用 DeepSeek 或 Web Search。
- History policy: `original_verdict` 保留 Baseline Eval 的历史判定；`adjudicated_verdict` 是独立的人工审核结论，不回写或替换 Baseline 历史 verdict。

## Summary

| Case ID | Original verdict | Adjudicated verdict |
| --- | --- | --- |
| `REQ-REG-001` | `MANUAL REVIEW` | `FAIL` |
| `CORE-002` | `FAIL` | `FAIL` |
| `CORE-003` | `MANUAL REVIEW` | `FAIL` |
| `CORE-004` | `MANUAL REVIEW` | `PASS with issues` |
| `CORE-005` | `FAIL` | `FAIL` |
| `EDGE-009` | `MANUAL REVIEW` | `PASS` |

## Case adjudications

### REQ-REG-001 — RCA Painting MA

- `original_verdict`: `MANUAL REVIEW`
- `adjudicated_verdict`: `FAIL`

| Severity | Module | Observed issue | Impact on user / Gap / Planning |
| --- | --- | --- | --- |
| Critical / Major | Requirements Retrieval | 当前官网存在明确的 programme-level Requirements，但 preserved snapshot 返回 0 条；属于 section-level recall failure。 | 用户无法获得可靠的项目要求，Gap 与 Planning 缺少必要输入，无法可靠生成。 |

`final_rationale`: Requirements Retrieval 完全漏掉官网已有的 programme-level Requirements，对后续 Gap 和 Planning 构成直接阻塞，因此人工裁定为 `FAIL`。

### CORE-002 — Oxford MSc Advanced Computer Science

- `original_verdict`: `FAIL`
- `adjudicated_verdict`: `FAIL`

| Severity | Module | Observed issue | Impact on user / Gap / Planning |
| --- | --- | --- | --- |
| Major | Requirements Retrieval | 当前官网存在明确 Requirements，但 supplemental snapshot 返回 0 条；属于 Requirements Retrieval recall failure。 | 重要申请要求无法进入 Adaptive Interview、Gap 和 Planning，可能造成关键资格或材料任务遗漏。 |
| Minor | Requirements Retrieval / Application Cycle | 当前官网展示的是 2026-27 entry requirements；2027-28 尚未正式开放，不能将上一周期要求无条件视为 Fall 2027 的已确认事实。 | 形成 temporal uncertainty；在当前 case 中应保持未确认，而不是把上一周期事实直接绑定到目标周期。 |

`final_rationale`: supplemental snapshot 对官网明确 Requirements 的召回失败属于会实质影响 Gap 与 Planning 的 Major issue，因此维持 `FAIL`。周期差异作为额外 Minor temporal note 记录。

### CORE-003 — Berkeley M.S. EECS

- `original_verdict`: `MANUAL REVIEW`
- `adjudicated_verdict`: `FAIL`

| Severity | Module | Observed issue | Impact on user / Gap / Planning |
| --- | --- | --- | --- |
| Major | Requirements Retrieval | 核心 programme identity 与 Deadline 基本正确，但漏掉 required transcript / application material。 | Gap 不会识别该必需材料缺口，Planning 会遗漏成绩单准备与提交任务。 |
| Minor | Requirements Retrieval / Provenance | 部分来源使用 archived / older guide，存在 freshness 风险。 | 可能带来低影响的时效性偏差；本身不是本 case 判为 FAIL 的主要原因。 |

`final_rationale`: required transcript 属于重要申请材料，遗漏会实质改变 Gap 和 Planning，因此人工裁定为 `FAIL`；programme identity 与 Deadline 基本正确不足以抵消该 Major omission。

### CORE-004 — Imperial Applied Machine Learning MSc

- `original_verdict`: `MANUAL REVIEW`
- `adjudicated_verdict`: `PASS with issues`

| Severity | Module | Observed issue | Impact on user / Gap / Planning |
| --- | --- | --- | --- |
| Minor | Requirements Retrieval / Application Cycle | 部分 requirement 或 administrative facts 来自前一申请周期。 | 存在时效性风险，但未改变本 case 的核心申请资格判断或关键准备任务。 |
| Minor | Requirements Retrieval / Administrative Facts | Application fee 等信息对当前 Fall 2027 尚未正式确认。 | 属于非核心或当前未确认的行政信息，不构成实质 Gap / Planning 错误。 |

Positive findings:

- 核心学历要求基本正确。
- Fall 2027 Timeline 返回 `not_found`，没有伪造 Deadline。
- 已发现问题不构成当前 case 的实质 Gap 或 Planning 错误。

`final_rationale`: 只有低影响的时效性和行政信息问题，没有会实质改变申请资格、Gap 或 Planning 的 Major/Critical issue，因此人工裁定为 `PASS with issues`。

### CORE-005 — KTH MSc Computer Science

- `original_verdict`: `FAIL`
- `adjudicated_verdict`: `FAIL`

| Severity | Module | Observed issue | Impact on user / Gap / Planning |
| --- | --- | --- | --- |
| Major | Requirements Retrieval | 漏掉 programme Summary Sheet 这一重要 required material。 | Gap 无法识别 Summary Sheet 材料缺口，Planning 不会提醒用户准备，造成重要申请任务遗漏。 |
| Minor | Requirements Retrieval | TOEFL alternative score 信息过时。 | 对当前 fixture 中已使用的语言路径不构成核心影响，但存在 alternative requirement 的时效性问题。 |

Positive finding:

- Timeline open date 和 Deadline 与当前官网一致。

`final_rationale`: 虽然 Timeline 正确，但 required Summary Sheet 的遗漏会实质改变 Gap 与 Planning，因此人工裁定为 `FAIL`。TOEFL alternative 的过时信息作为 Minor issue 单独记录。

### EDGE-009 — Berkeley programme identity

- `original_verdict`: `MANUAL REVIEW`
- `adjudicated_verdict`: `PASS`
- `issues`: none
- `severity`: none
- `module`: Target Programme Identity
- `observed_issue`: 未发现实质问题；当前官方确实存在 `EECS - Computer Science MS` programme identity，official programme URL 与目标 programme 对应。
- `impact_on_user / Gap / Planning`: 目标项目身份与 URL 绑定正确，不会导致后续 Requirements、Gap 或 Planning 关联到错误项目。

`final_rationale`: programme identity 和 official programme URL 均经人工确认与目标项目对应，未发现实质风险，因此人工裁定为 `PASS`。
