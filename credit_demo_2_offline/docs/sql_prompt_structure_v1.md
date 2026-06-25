# SQL 版两阶段 Prompt 结构（V1）

当前 `credit_demo_2` 采用两种 **两次大模型调用** 的最小闭环：

1. `SQL Planner`
2. `Answer Generator`

以及：

1. `Question Router`
2. `Extraction Answer`

目标是避免把规划信息、全量 schema、业务规则、最终回答要求一次性塞进同一个 prompt，同时给“展示层直接提取”保留独立链路。

## 1. SQL Planner

### system prompt 角色

- 只负责“怎么查”
- 输出单条 SQLite 只读 SQL
- 不负责最终回答用户

### user prompt 结构

1. `用户问题`
2. `最近对话`
3. `previous_context`
4. `report_context`
5. `可用表`
6. `可用视图`
7. `本题查询规则`

### 典型输入原则

- 只给当前问题相关的表和视图，不给全量 schema
- 只给当前问题相关的查询规则，不给全量业务知识
- 明确报告日期锚点与单报告隔离约束
- 单报告模式下，`report_context` 只暴露最小子集，例如 `report_date / single_report_only / report_filter_mode`
- 单报告模式下，不向 planner 暴露 `selected_report_id / internal_report_id`

## 2. Answer Generator

### system prompt 角色

- 只负责“怎么说”
- 基于已执行成功的 SQL 结果生成中文答案
- 不负责重新规划 SQL 或重新计算

### user prompt 结构

1. `用户问题`
2. `已执行 SQL`
3. `查询结果`
4. `结果字段释义`
5. `本题统计口径`
6. `限制与提醒`

### 典型输入原则

- 不再传全量 schema
- 不再传 planner 阶段的大段规则
- 只传本题结果相关字段和本题口径说明

## 3. 当前实现里的程序步骤

### Planner 阶段前

程序先做：

- 相关表/视图筛选
- 本题查询规则筛选

输出为：

- `available_tables`
- `available_views`
- `planner_rules`

### Answer 阶段前

程序先做：

- 查询结果字段中文释义整理
- 本题口径事实整理（时间窗口口径、业务对象口径、指标计算口径、排除范围）
- 基于口径事实生成简短口径摘要
- 限制项整理

输出为：

- `field_labels`
- `scope_facts`
- `scope_note`
- `limitation_note`

说明：

- `scope_facts` 是结构化口径事实，作为 Answer Generator 的主要口径输入
- `scope_note` 是程序整理出的简短摘要，供模型参考，但不是最终文案模板

## 4. 设计原则

1. Planner 和 Answer 的 prompt 必须职责分离。
2. 每次调用只注入当前阶段真正需要的信息。
3. 全量 schema / 全量业务知识只用于程序侧筛选，不直接整包喂给模型。
4. 展示层提取问题不直接走 SQL；优先由 `Question Router` 判断，再对 PDF 目标模块做小范围抽取。

## 5. 直接提取链路（新增）

### 适用问题

- 请提取基本信息
- 请按以下格式提取身份信息
- 请提取信息概要
- 请提取查询记录概要

### Question Router

输入：

1. `用户问题`
2. `最近对话`

输出：

- `mode = extract | sql | explain`
- `target_modules`

### Extraction Answer

输入：

1. `用户问题`
2. `可用报告模块文本`

当前模块范围（第一版）：

- `report_header`
- `identity_info`
- `residence_info`
- `occupation_info`
- `basic_info_bundle`
- `overview_summary`
- `query_summary`

设计原则：

- 先结构化字段候选，再模块定位与小范围抽取
- 不对全 PDF 做自由 RAG
- 优先使用 `standard.enriched_labels.json` 中的结构化字段值
- 只能基于结构化字段候选和模块文本提取，不补写、不推断
