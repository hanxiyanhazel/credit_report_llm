# Schema 说明（当前）

更新时间：2026-05-13

## 分层原则

当前按三层理解：

1. `XML 原始层`
2. `标准层 JSON`（个人/企业分开）
3. `问答解释层`（后续统一）

结论不变：**标准层分开，问答层再统一**。

## 当前 Schema 文件

- `individual_standard_report.schema.json`
  - 个人征信标准层 schema
- `corporate_standard_report.schema.json`
  - 企业征信标准层 schema
- `unified_credit_report.schema.json`
  - 早期原型 schema，保留为历史参考，不作为主目标

## 标准层字段对象约定

对于码值字段，标准层允许以下状态：

1. `code` 有值，`label` 有值
2. `code` 有值，`label` 暂时为空
3. 后处理补齐 `label`

当前项目的补齐来源分两类：

- `xml_dictionary`（来自已有字典/规则）
- `pdf_text_inferred`（从 PDF 文本推断）

## 当前与脚本的一致性

当前脚本链路已经是：

1. XML 解析到标准层
2. PDF 抽取到标准层风格结果
3. 再把 PDF 语义补回 XML 标准层

也就是 schema 与实现已对齐，不再是“schema 先行、脚本未迁移”状态。

## 边界

1. 当前不覆盖 OCR 扫描件。
2. 当前“全量”是面向现阶段业务需要字段，不等于全 XML 字段镜像。
3. 对于语义噪声字段，可保留 `code` 并标记低置信 `label`。
