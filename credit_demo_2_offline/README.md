# credit_demo_2（SQL Query Demo）

这是一个与 `credit_report_demo` 隔离的第二版实验目录。  
目标不是继续扩展 `metric_name` 路由，而是验证两条新链路：

1. `用户问题 -> 大模型生成 SQL -> 在核心表/语义视图执行 -> 大模型解释结果`
2. `用户问题 -> 大模型判断为提取型 -> PDF 模块定位 -> 大模型小范围抽取 -> 模板化输出`

## 设计目标

1. 与旧版 demo 互不干扰。
2. 复用既有解析产物：
   - `individual.standard.enriched_labels.json`
   - `individual.core_tables.json`
3. 不再以固定 `metric_name` 作为主取数路径。
4. 使用 SQLite 内存库承载核心表，并额外构造少量语义视图：
   - `v_report_context`
   - `v_outstanding_summary`
   - `v_query_summary_pc05`
5. 在前端右侧继续保留：
   - `query_plan`
   - `query_result`
   - `prompt_trace`

## 运行

```bash
cd credit_demo_2
pip install -r requirements.txt
BACKEND_PORT=8011 bash run.sh
```
或者（一下仅限个人电脑，不涉及内网系统路线）
```
cd /Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2
BACKEND_HOST=127.0.0.1 BACKEND_PORT=8000 bash run.sh
```
默认地址：

- [http://127.0.0.1:8011](http://127.0.0.1:8011)

## 模型配置

SQL 版主链路依赖模型生成 SQL。建议在启动前设置：

```bash
export QWEN_API_BASE="https://dashscope.aliyuncs.com/compatible-mode/v1"
export QWEN_API_KEY="你的 key"
export QWEN_MODEL="qwen3.5-plus"
```

如果模型未配置，系统只会走极少量本地 SQL fallback，用于演示基础链路。

## 当前实现

### 1. 数据层

- 将 `individual.core_tables.json` 中的核心表加载到内存 SQLite
- `individual.core_tables.json` 现已升级为 `core_tables.v3`：高风险码值字段默认输出中文语义值，并保留 `_code` 备份字段，避免把裸码值误当成可直接统计的数字
- 建库时统一将核心表中的 `report_id` 映射为当前外层选中的报告 ID，避免内层/外层 `report_id` 混淆
- 提供 `v_report_context`，把 `selected_report_id / internal_report_id / report_time / report_date` 暴露为统一上下文
- 按列值自动推断 SQLite 类型
- 额外构造语义视图，减少模型直接面对 `PC02/PC05` 码值表的负担

### 2. SQL 规划层

- 主路径：LLM 读取问题、最近对话、上一轮上下文、schema 描述，输出单条只读 SQL
- 本地 fallback：仅覆盖少数高频问题
- 当前已补一类轻量复合汇总题：`多时间窗口 + 多指标 + 同一业务对象`
  - 例如：`近1个月、近3个月、近6个月新增贷款笔数和金额是多少？`
  - 例如：`近6个月、近12个月、近24个月逾期次数和金额是多少？`
  - 当前在本地 planner 中固化为 CASE 聚合 SQL，避免完全依赖 LLM 临场生成

### 3. 直接提取层

- 对“基本信息 / 信息概要 / 查询记录概要 / 按模板提取字段”这类展示层问题，优先走 `direct_extract`
- 对字段型提取，优先使用 `individual.standard.enriched_labels.json` 中的结构化字段值；PDF 模块文本用于校验、补充和兜底
- 当前先从 PDF 前 4 页中切出这些模块：
  - `report_header`
  - `identity_info`
  - `residence_info`
  - `occupation_info`
  - `basic_info_bundle`
  - `overview_summary`
  - `query_summary`
- 大模型先做轻路由，再在模块内小范围抽取，不直接对全 PDF 做自由 RAG

### 4. 答案生成层

- 主路径：LLM 基于 SQL 结果生成面向业务人员的中文答案
- fallback：当模型不可用或失败时，用本地模板输出结果摘要

### 5. 会话上下文

进程内保留 `session_id -> previous_context`，便于处理：

- “这些账户”
- “那近15个月呢”
- “分别多少钱”

这只是第一版，后续还可以升级为更稳定的结果集引用机制。

## 关键文件

- [app.py](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/app.py)
- [agent_loop.py](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/agent_loop.py)
- [qwen_client.py](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/qwen_client.py)
- [sql_runtime.py](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/sql_runtime.py)
- [report_store.py](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/report_store.py)
- [parse_pipeline.py](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/parse_pipeline.py)
- [business_review_questions_v1.md](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/docs/business_review_questions_v1.md)
- [sql_prompt_structure_v1.md](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/docs/sql_prompt_structure_v1.md)
- [current_usability_v1.md](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/docs/current_usability_v1.md)
- [rule_maintenance_playbook_v1.md](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/docs/rule_maintenance_playbook_v1.md)

## 当前边界

这版的重点是验证“SQL 查询主链路”是否比 `metric_name` 路由更灵活，因此还存在几个刻意保留的边界：

1. 还没有做 SQL AST 级安全校验，只做了只读 SQL 白名单拦截。
2. 还没有把所有业务口径沉淀成视图；目前只补了最关键的概要视图。
3. 连续追问的“这些账户”仍主要依赖模型结合 `previous_context` 理解。
4. 还没有做数据库持久化，SQLite 每次请求从核心表重建。

## 已落地的运行时约束

1. 当前 SQLite 会话只包含当前选中报告的数据。
2. 所有核心表中的 `report_id` 在建库时统一映射为当前外层选中的 `report_id`，避免未来上传报告时再次混淆。
3. 所有近 X 个月/年的时间窗口，统一应以 `v_report_context.report_date` 为锚点，而不是 `now/current_date`。
4. 在当前单报告模式下，planner prompt 只暴露最小报告上下文：`report_date + single_report_only`；默认不暴露 `selected_report_id / internal_report_id` 给大模型。
5. 执行器会对 SQL 做只读校验，并把常见的 `report_id = ...` 与 `date('now', ...)` 写法归一到当前报告上下文。
6. 在当前单报告模式下，执行器会直接拦截 `selected_report_id / internal_report_id` 引用，以及通过 `report_id` 与 `v_report_context` 做 join 的 SQL，避免模型写出与运行时映射冲突的查询。
7. 对还款状态、五级分类、查询原因、证件类型等高风险码值字段，core tables 默认提供“中文主字段 + `_code` 备份字段”；planner 和 SQL 应优先使用中文主字段理解语义，需要做码值筛选时再使用 `_code` 字段。

## Prompt 结构（当前）

当前采用两种两阶段 prompt：

1. `SQL Planner -> Answer Generator`
   - SQL Planner 输入：问题、最近对话、previous_context、report_context、相关表/视图、当前问题的查询规则
   - Answer Generator 输入：问题、已执行 SQL、查询结果、结果字段释义、本题统计口径、限制与提醒

2. `Question Router -> Extraction Answer`
   - Question Router 输入：问题、最近对话
   - Extraction Answer 输入：问题、目标模块文本、用户模板/字段要求

详细设计见：
- [sql_prompt_structure_v1.md](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/docs/sql_prompt_structure_v1.md)

当前 SQL 答案层的口径说明采用：

- 程序提供 `scope_facts`（时间窗口口径、业务对象口径、指标计算口径、排除范围）
- 大模型根据 `query_result + scope_facts` 自然组织业务可读答案
- 本地 fallback 仅作为模型不可用时的最小保底，不作为主表达形态

## 规则维护方法（新增）

后续如果需要新增“本题规则提示 / 字段语义限制 / 执行前防呆”，请优先参考：

- [rule_maintenance_playbook_v1.md](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/docs/rule_maintenance_playbook_v1.md)

核心分层固定为：

1. **怎么算** -> `docs/metric_definition_catalog.md`
2. **字段是什么** -> `semantic/schema_metadata.json`
3. **错 SQL 要不要拦** -> `sql_runtime.py`
4. **当前题要不要提醒模型** -> `agent_loop.py`

如果这版跑通、体验好，下一步再做：

- query spec 中间层
- 更细的 SQL 校验器
- 更多语义视图
- 更稳定的结果集引用

未来如果要从“轻模板/本地 planner”升级到“业务语义 -> 标准 query_plan -> 受控 SQL”的方式，请参考：

- [future_semantic_mapping_improvements_v1.md](/Users/hanxiyan/Desktop/Skill_Exploration/claude-code-main/credit_report/credit_demo_2/docs/future_semantic_mapping_improvements_v1.md)
