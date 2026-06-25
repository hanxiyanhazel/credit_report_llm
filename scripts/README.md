# 解析脚本说明（当前可用）

更新时间：2026-05-13

## 目录定位

仓库根目录下的 `scripts/` 当前保留的是主流程脚本，目标是：

1. 解析 XML 为标准层 JSON
2. 解析 PDF 为可对照 JSON
3. 用 PDF 为 XML 码值字段补 `label`

## 当前脚本

### 个人报告主流程

- `parse_individual_report.py`
  - 输入：`individual.xml`
  - 输出：`individual.standard.json`
  - 作用：生成个人报告标准层（主数据）

- `parse_individual_pdf_report.py`
  - 输入：`report_indv.pdf`
  - 输出：`individual.pdf.standard.json`
  - 作用：提取 PDF 文本层关键字段（用于对照和补义）

- `enrich_individual_code_labels_from_pdf.py`
  - 输入：XML 标准层 + PDF 标准层 + 原始 PDF
  - 输出：`individual.standard.enriched_labels.json`
  - 作用：给 XML 里 `code` 但 `label=null` 的字段补业务语义

- `extract_official_code_tables.py`
  - 输入：`data_recource/码表/` 下官方规范 PDF
  - 输出：
    - `mapping/official_code_tables.extracted.json`
    - `mapping/official_code_tables.by_field.individual_v1.json`
  - 作用：抽取“代码 -> 中文名称”官方码表，并整理为当前个人报告字段可直接消费的映射

### 企业报告（仍可用）

- `parse_corporate_report.py`
  - 输入：`corporate.xml`
  - 输出：`corporate.standard.json`

## 推荐执行顺序（个人）

### 1) XML 标准层

```bash
python3 scripts/parse_individual_report.py \
  data_recource/individual.xml \
  -o output/individual.standard.json
```

### 2) PDF 标准层风格抽取

```bash
python3 scripts/parse_individual_pdf_report.py \
  data_recource/report_indv.pdf \
  -o output/individual.pdf.standard.json
```

### 3) PDF 补码值语义

```bash
python3 scripts/enrich_individual_code_labels_from_pdf.py \
  --xml output/individual.standard.json \
  --pdf output/individual.pdf.standard.json \
  --pdf-file data_recource/report_indv.pdf \
  -o output/individual.standard.enriched_labels.json
```

### 4) 官方码表抽取（推荐）

```bash
python3 scripts/extract_official_code_tables.py
```

## 关键说明

1. 当前策略是“双路融合”，不是“PDF 替代 XML”。
2. 无码表场景下，`enrich` 脚本会把 `code -> label` 尽量从 PDF 推断补齐。
3. 当前不覆盖扫描件 OCR 场景；仅保证文本层 PDF。

## 归档说明

原目录中不再使用的 PoC/对照脚本和输出已经从主线清理，不再作为当前仓库结构的一部分。
