# Regression Cases

## REQ-REG-001

- 模块：Requirements Retrieval
- Failure Class：Section-level Recall Failure
- Case：RCA Painting MA
- 原问题：已知官方项目页，但模型只召回 Overview / 通用申请页，漏掉项目页 Requirements section。
- 预期：优先从 `official_program_url` 对应项目页提取 programme-level requirements。
- 修复：第一次搜索锚定 exact programme URL + program name；第二次仅补缺失要求。
- Pass Criteria：能召回学历、Portfolio、约 300 词 PS、最长 2 分钟 Video、English requirement，并保持 programme-level official source。
- 状态：Fixed
