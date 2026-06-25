# 字段映射与补义策略（V3）

更新时间：2026-05-13

## 文档用途

这份文档只描述当前可执行方案：

1. XML -> 标准层映射
2. PDF -> 码值语义补齐
3. 两路融合后的问答可用字段

## 核心策略

1. 标准层以 XML 为主，不改 `code`。
2. 对 `code` 且 `label=null` 的字段，使用 PDF 推断补齐 `label`。
3. 补齐后保留来源标记：
   - `label_source = pdf_text_inferred`
   - `interpretation_status = resolved_from_pdf`

## 当前重点覆盖表

本轮重点补义对象（你当前最需要）：

- `PD01`：账户类型、机构类型、业务种类、还款方式、还款频率、担保方式、账户状态、五级分类、还款状态码等
- `PB04`：单位性质、行业、职业、职务、职称
- `PH01`：查询机构类型、查询原因
- `POS`：异议标注/特殊标注分类

## 标准路径写法

- 单值：`tables.<TABLE>.fields.<FIELD>`
- 多值：`tables.<TABLE>.records[].fields.<FIELD>`

示例：

- `tables.PD01.records[].fields.PD01AD03`
- `tables.PH01.records[].fields.PH010Q03`
- `tables.POS.records[].fields.PG010D03`

## 当前补义状态

基于 `individual.standard.enriched_labels.json` 最新结果：

- 有码值但原无 label 的字段已补齐（`coded_fields_still_unresolved = 0`）
- 空码值字段不参与补义（由源数据决定）

## 关于“全量”口径

当前“全量”是指：**现阶段标准 JSON 中问答会用到的码值语义字段**已覆盖，不代表“全 XML 所有字段/所有逻辑表”已全部建模。

## 边界提醒

1. 扫描件 PDF（无文本层）暂不在本策略内。
2. 少数字段可能出现格式噪声，必要时保留 `code` 作为回退展示。
3. 后续若新增问答字段，按同一流程补映射即可。
