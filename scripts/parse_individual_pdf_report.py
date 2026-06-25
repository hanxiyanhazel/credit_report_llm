#!/usr/bin/env python3
"""Parse individual credit-report PDF into a standard-like JSON structure."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader


SCHEMA_VERSION = "0.2.0-pdf-poc"
TABLE_LABEL_SOURCE = "pdf_layout_headers"

TABLE_NAMES = {
    "PA01": "报告头信息单元",
    "PB01": "身份信息单元",
    "PB02": "配偶信息单元",
    "PC05": "查询记录概要信息单元",
}

FIELD_LABELS = {
    "PA01AI01": "报告编号",
    "PA01AR01": "报告时间",
    "PA01BQ01": "被查询者姓名",
    "PA01BD01": "被查询者证件类型",
    "PA01BI01": "被查询者证件号码",
    "PA01BD02": "查询原因",
    "PB01AD01": "性别",
    "PB01AR01": "出生日期",
    "PB01AD02": "学历",
    "PB01AD03": "学位",
    "PB01AD04": "就业状况",
    "PB01AD05": "国籍",
    "PB01AQ01": "电子邮箱",
    "PB01AQ02": "通讯地址",
    "PB01AQ03": "户籍地址",
    "PB020D01": "婚姻状况",
    "PA01CD01": "证件类型",
    "PA01CI01": "证件号码",
    "PC05AR01": "上一次查询日期",
    "PC05AD01": "上一次查询机构类型",
    "PC05AI01": "上一次查询机构代码",
    "PC05AQ01": "上一次查询原因",
    "PC05BS01": "最近一个月内的查询机构数（贷款审批）",
    "PC05BS02": "最近一个月内的查询机构数（信用卡审批）",
    "PC05BS03": "最近一个月内的查询次数（贷款审批）",
    "PC05BS04": "最近一个月内的查询次数（信用卡审批）",
    "PC05BS05": "最近一个月内的查询次数（本人查询）",
    "PC05BS06": "最近2年内的查询次数（贷后管理）",
    "PC05BS07": "最近2年内的查询次数（担保资格审查）",
    "PC05BS08": "最近2年内的查询次数（特约商户实名审查）",
}


def normalize(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def to_number(value: str | None) -> int | None:
    value = normalize(value)
    if value is None:
        return None
    value = value.replace(",", "")
    try:
        return int(value)
    except ValueError:
        return None


def make_trace(source_file: Path, section: str, fields: list[str]) -> dict[str, Any]:
    return {
        "source_file": str(source_file),
        "source_section": section,
        "source_table": "PDF_TEXT_LAYER",
        "source_fields": fields,
        "source_id": None,
    }


def plain_field(
    source_file: Path,
    source_section: str,
    field_code: str,
    value: str | int | None,
) -> dict[str, Any]:
    return {
        "field_code": field_code,
        "field_name": FIELD_LABELS.get(field_code, field_code),
        "value": value,
        "value_meta": {
            "value_source": "pdf_text_regex",
            "trace": make_trace(source_file, source_section, [field_code]),
            "extra_fields": {},
        },
    }


def read_pdf_text(pdf_path: Path) -> tuple[str, str]:
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    raw = "\n".join(pages)
    compact = re.sub(r"\s+", "", raw)
    return raw, compact


def cap(pattern: str, text: str, flags: int = 0) -> str | None:
    m = re.search(pattern, text, flags=flags)
    if not m:
        return None
    return normalize(m.group(1))


def extract_fields(pdf_path: Path) -> dict[str, dict[str, Any]]:
    raw, _ = read_pdf_text(pdf_path)

    pa01: dict[str, Any] = {}
    pb01: dict[str, Any] = {}
    pb02: dict[str, Any] = {}
    pc05: dict[str, Any] = {}

    # PA01: report header fields.
    report_no = cap(r"报告编号[:：]?\s*([0-9]{18,})", raw)
    report_time = cap(
        r"报告时间[:：]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})",
        raw,
    )
    head_row = re.search(
        r"\n([^\s]+)\s+(身份证|护照|军人身份证件)\s+([0-9\*]{10,})\s+([^\n]+)",
        raw,
    )
    if report_no is not None:
        pa01["PA01AI01"] = plain_field(pdf_path, "PAGE1/HEADER", "PA01AI01", report_no)
    if report_time is not None:
        pa01["PA01AR01"] = plain_field(pdf_path, "PAGE1/HEADER", "PA01AR01", report_time)
    if head_row:
        name = normalize(head_row.group(1).lstrip("*"))
        cert_type = normalize(head_row.group(2))
        cert_no = normalize(head_row.group(3))
        query_reason_text = normalize(head_row.group(4))
        if name:
            pa01["PA01BQ01"] = plain_field(pdf_path, "PAGE1/HEADER", "PA01BQ01", name)
        if cert_type:
            pa01["PA01BD01"] = plain_field(pdf_path, "PAGE1/HEADER", "PA01BD01", cert_type)
        if cert_no:
            pa01["PA01BI01"] = plain_field(pdf_path, "PAGE1/HEADER", "PA01BI01", cert_no)
        if query_reason_text:
            # PDF直接展示中文查询原因，和XML码值不同。
            pa01["PA01BD02"] = plain_field(pdf_path, "PAGE1/HEADER", "PA01BD02", query_reason_text)
    other_cert = re.search(
        r"其他证件信息\s*证件类型\s+证件号码\s*\n([^\s]+)\s+([0-9A-Za-z\*]+)",
        raw,
        flags=re.DOTALL,
    )
    if other_cert:
        pa01["PA01CD01"] = plain_field(pdf_path, "PAGE1/PA01CH", "PA01CD01", normalize(other_cert.group(1)))
        pa01["PA01CI01"] = plain_field(pdf_path, "PAGE1/PA01CH", "PA01CI01", normalize(other_cert.group(2)))

    # PB01: identity basic fields.
    identity_row = re.search(
        (
            r"性别\s+出生日期\s+婚姻状况\s+学历\s+学位\s+就业状况\s+国籍\s+电子邮箱\s*"
            r"\n([^\n]+)"
        ),
        raw,
    )
    if identity_row:
        tokens = re.split(r"\s+", identity_row.group(1).strip())
        if len(tokens) >= 8:
            pb01["PB01AD01"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AD01", tokens[0])
            pb01["PB01AR01"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AR01", tokens[1])
            pb02["PB020D01"] = plain_field(pdf_path, "PAGE1/PB02A", "PB020D01", tokens[2])
            pb01["PB01AD02"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AD02", tokens[3])
            pb01["PB01AD03"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AD03", tokens[4])
            pb01["PB01AD04"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AD04", tokens[5])
            pb01["PB01AD05"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AD05", tokens[6])
            pb01["PB01AQ01"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AQ01", tokens[-1])

    addr_row = re.search(r"通讯地址\s+户籍地址\s*\n([^\n]+)", raw)
    if addr_row:
        text = addr_row.group(1).strip()
        parts = re.split(r"\s{2,}", text)
        if len(parts) >= 2:
            pb01["PB01AQ02"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AQ02", normalize(parts[0]))
            pb01["PB01AQ03"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AQ03", normalize(parts[1]))
        else:
            # 回退：单空格分隔（地址中一般不含空格，样本可用）
            bits = text.split(" ")
            if len(bits) >= 2:
                pb01["PB01AQ02"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AQ02", normalize(bits[0]))
                pb01["PB01AQ03"] = plain_field(pdf_path, "PAGE1/PB01A", "PB01AQ03", normalize(bits[1]))

    # PC05: query summary fields from section "（七）查询记录概要".
    query_row = re.search(
        (
            r"上一次查询记录\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*"
            r"([^\s]+)\s+“([A-Z0-9]+)”\s+([^\s]+)\s*"
            r"最近1个月内的查询机构数.*?特约商户实名\s*审查\s*"
            r"([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)"
        ),
        raw,
        flags=re.DOTALL,
    )
    if query_row:
        pc05["PC05AR01"] = plain_field(pdf_path, "PAGE3/PC05", "PC05AR01", normalize(query_row.group(1)))
        pc05["PC05AD01"] = plain_field(pdf_path, "PAGE3/PC05", "PC05AD01", normalize(query_row.group(2)))
        pc05["PC05AI01"] = plain_field(pdf_path, "PAGE3/PC05", "PC05AI01", normalize(query_row.group(3)))
        pc05["PC05AQ01"] = plain_field(pdf_path, "PAGE3/PC05", "PC05AQ01", normalize(query_row.group(4)))
        pc05["PC05BS01"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS01", to_number(query_row.group(5)))
        pc05["PC05BS02"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS02", to_number(query_row.group(6)))
        pc05["PC05BS03"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS03", to_number(query_row.group(7)))
        pc05["PC05BS04"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS04", to_number(query_row.group(8)))
        pc05["PC05BS05"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS05", to_number(query_row.group(9)))
        pc05["PC05BS06"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS06", to_number(query_row.group(10)))
        pc05["PC05BS07"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS07", to_number(query_row.group(11)))
        pc05["PC05BS08"] = plain_field(pdf_path, "PAGE3/PC05", "PC05BS08", to_number(query_row.group(12)))

    return {"PA01": pa01, "PB01": pb01, "PB02": pb02, "PC05": pc05}


def build_output(pdf_path: Path) -> dict[str, Any]:
    extracted = extract_fields(pdf_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "individual",
        "source_files": [str(pdf_path)],
        "tables": {
            table_code: {
                "table_code": table_code,
                "table_name": TABLE_NAMES[table_code],
                "source_table_name": TABLE_NAMES[table_code],
                "source_table_name_source": TABLE_LABEL_SOURCE,
                "fields": extracted.get(table_code, {}),
                "records": [],
            }
            for table_code in ("PA01", "PB01", "PB02", "PC05")
        },
        "raw_sections": {
            "source_summary": {
                "value_source": "pdf_text_regex",
                "summary": "PDF文本层规则抽取（PoC），用于和XML标准层做可比字段重合度评估。",
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse individual report PDF to standard-like JSON.")
    parser.add_argument("pdf", type=Path, help="Path to individual report PDF.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output/individual.pdf.standard.json"),
        help="Output JSON path.",
    )
    args = parser.parse_args()

    payload = build_output(args.pdf)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
