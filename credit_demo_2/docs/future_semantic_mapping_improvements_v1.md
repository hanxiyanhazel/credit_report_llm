# 未来改进方向：征信语义映射层（V1）

本文档用于记录 `credit_demo_2` 的下一阶段改进方向：在现有 SQL demo 基础上，引入一层可复用的 `semantic mapping / semantic resolver`，减少“每出现一个新问法就补一条 if/else 或 SQL 模板”的维护方式。

当前先不落代码，后续需要做这一层时，以本文档为准。

## 1. 现状

当前系统已经能处理一部分：

- 单指标问题
- 少量存在性判断
- 少量多时间窗口 + 多指标复合汇总题
- 部分直接提取问题

但当前 SQL 能力仍偏：

- `问题关键词 -> 本地 planner / LLM planner -> SQL`

因此会出现：

- `新增贷款` 已支持，但 `结清贷款` 还要额外补一条业务对象
- `逾期`、`B/D/G`、`查询`、`担保` 等问题随着问法扩展，会继续增加本地模板

根本原因不是 SQL 不能写，而是缺少：

> 业务语义 -> 标准 query_plan -> 受控 SQL

这一层。

## 2. 目标链路

后续理想链路：

用户问题  
→ LLM / planner 识别问题意图  
→ 生成标准 query_plan  
→ semantic resolver 根据字段词典和业务规则补全字段映射  
→ SQL generator 生成只读 SQL  
→ SQL validator 校验字段、表、聚合逻辑  
→ answer generator 输出结果 + 业务口径 + 时间窗口口径

说明：

- 不让大模型直接自由写 SQL
- 不把所有问题都写成固定 SQL 模板
- 重点增强 query planning 和 semantic resolving，而不是继续堆积问法模板

## 3. 优先支持的业务域

后续优先支持：

1. 逾期情况
2. 授信情况（贷款 / 信用卡）
3. 新增贷款
4. 结清贷款
5. 查询情况
6. 五级分类
7. 担保情况
8. 异议情况

## 4. 建议新增的 semantic_map 层

建议新增：

- `semantic/semantic_map.py`
或
- `semantic/semantic_map.yaml`

作用：

- 维护业务对象、事件、指标、字段、默认口径、排除项、失败提示
- 不维护“问题 -> SQL”
- 只维护“语义 -> 字段和规则”

### 4.1 entities

建议优先抽象这些 entity：

- `loan_account`
- `repayment_history`
- `credit_card_account`
- `query_record`
- `guarantee_record`
- `dispute_record`

### 4.2 events

建议优先抽象这些 event：

- `opened`
- `settled`
- `overdue`
- `special_status_bdg`
- `query_happened`
- `guarantee`
- `dispute_in_progress`

### 4.3 metrics

建议优先抽象这些 metric：

- `count`
- `amount_sum`
- `balance_sum`
- `overdue_amount_sum`
- `exists`
- `max_consecutive_overdue_terms`

## 5. query_plan 的目标形态

后续 query_plan 不应只保留 `sql`，还应尽量保留：

- `question_type`
- `entity`
- `event`
- `time_windows`
- `time_window_policy`
- `metrics`
- `date_field`
- `amount_field`
- `filters`
- `exclusions`

示例：

```json
{
  "question_type": "multi_window_event_summary",
  "entity": "loan_account",
  "event": "settled",
  "time_windows": ["1m", "3m", "6m"],
  "time_window_policy": "以报告日期为锚点精准倒推，多个窗口为嵌套窗口",
  "metrics": [
    {
      "name": "settled_loan_count",
      "aggregation": "count",
      "unit": "account"
    },
    {
      "name": "settled_loan_amount_sum",
      "aggregation": "sum",
      "field": "original_amount",
      "definition": "按结清贷款账户的原始借款金额汇总"
    }
  ],
  "date_field": "close_date",
  "filters": {
    "account_scope": ["非循环贷账户", "循环额度下分账户", "循环贷账户"],
    "status_condition": "account_status = '结清'"
  },
  "exclusions": ["贷记卡账户", "准贷记卡账户", "被追偿信息", "相关还款责任"]
}
```

## 6. 失败方式要可解释

后续不应只返回：

- `sql_plan_not_generated`

应尽量返回更可解释的失败原因，例如：

- 缺少 `close_date` 字段，无法按结清日期统计近1/3/6个月结清贷款。
- 缺少月度还款表现表，无法计算连续逾期期数。
- 缺少信用卡月度用卡金额字段，无法从明细计算近6个月平均用卡金额。
- 缺少机构类型字段，只能按查询机构名称关键词粗略判断。

## 7. 与当前处理方式的差距

当前：

- 已有本地 planner + LLM planner
- 已有部分业务口径台账
- 已有字段语义台账
- 已有 SQL validator 雏形

缺口：

- 缺少正式的 semantic_map
- 缺少标准化 `entity / event / metric` 层
- 缺少 resolver 把“用户问法”稳定映射成“可执行 query_plan”
- 缺少更细的 explainable failure 层

## 8. 推荐改造顺序

建议按以下顺序逐步改造，不要一次重写：

1. 新增 `semantic_map`
2. 先让 planner 输出标准 query_plan（不直接以 SQL 为唯一中间产物）
3. 增加 semantic resolver，根据 entity/event/metric 补全字段
4. SQL generator 从 query_plan 生成受控 SQL
5. SQL validator 做字段、聚合、事件逻辑校验
6. Answer generator 继续基于 `query_result + scope_facts` 输出

## 9. 当前阶段的策略

在 semantic mapping 正式落地之前，当前阶段继续沿用：

- `metric_definition_catalog.md`：业务口径主档
- `schema_metadata.json`：字段语义说明
- `sql_runtime.py`：运行时防呆
- `agent_loop.py`：按题动态注入 planner 规则

也就是说：

> 当前阶段先沿用“轻模板 + 规则注入 + 口径说明”的方式，未来再演进到 semantic mapping/resolver。
