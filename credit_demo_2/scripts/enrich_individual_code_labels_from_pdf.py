#!/usr/bin/env python3
"""Enrich XML standard JSON coded fields using official code tables + PDF fallback."""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader

OFFICIAL_CANONICAL_OVERRIDES: dict[str, dict[str, str]] = {
    # Query reason codes: remove corporate-meaning pollution.
    "PA01BD02": {"02": "贷款审批", "03": "信用卡审批", "08": "担保资格审查"},
    "PC05AQ01": {"02": "贷款审批", "03": "信用卡审批", "08": "担保资格审查"},
    "PH010Q03": {"02": "贷款审批", "03": "信用卡审批", "08": "担保资格审查"},
    # PD01 status-like coded fields are high-risk for PDF row misalignment.
    "PD01BD01": {
        "1": "正常",
        "2": "逾期",
        "3": "结清",
        "4": "呆账",
        "5": "核销",
        "6": "未激活",
    },
    "PD01BD04": {
        "N": "正常还款",
        "*": "本月无还款历史",
        "1": "逾期1-30天",
        "2": "逾期31-60天",
        "3": "逾期61-90天",
        "4": "逾期91-120天",
        "5": "逾期121-150天",
        "6": "逾期151-180天",
        "7": "逾期180天以上",
        "D": "担保人代还",
        "Z": "以资抵债",
        "C": "结清",
        "G": "结束",
    },
    # Monthly snapshot status / five-classification in PD01C.
    "PD01CD01": {
        "1": "正常",
        "2": "逾期",
        "3": "结清",
        "4": "呆账",
        "5": "核销",
        "6": "未激活",
    },
    "PD01CD02": {
        "1": "正常",
        "2": "关注",
        "3": "次级",
        "4": "可疑",
        "5": "损失",
        "9": "未分类",
    },
    # 24-month and 5-year monthly repayment status code set.
    "PD01DD01": {
        "N": "正常还款",
        "*": "本月无还款历史",
        "1": "逾期1-30天",
        "2": "逾期31-60天",
        "3": "逾期61-90天",
        "4": "逾期91-120天",
        "5": "逾期121-150天",
        "6": "逾期151-180天",
        "7": "逾期180天以上",
        "D": "担保人代还",
        "Z": "以资抵债",
        "C": "结清",
        "G": "结束",
        "#": "还款状态未知",
        "/": "未开立账户",
    },
    "PD01ED01": {
        "N": "正常还款",
        "*": "本月无还款历史",
        "1": "逾期1-30天",
        "2": "逾期31-60天",
        "3": "逾期61-90天",
        "4": "逾期91-120天",
        "5": "逾期121-150天",
        "6": "逾期151-180天",
        "7": "逾期180天以上",
        "D": "担保人代还",
        "Z": "以资抵债",
        "C": "结清",
        "G": "结束",
        "#": "还款状态未知",
        "/": "未开立账户",
    },
    "PD01ZD01": {
        "1": "异议处理期标注",
        "2": "异议信息更正受限声明",
    },
}


def norm(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def read_pdf_text(pdf_path: Path) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf_path)).pages)


def extract_pdf_path(pdf_obj: dict[str, Any], fallback_pdf_path: Path | None) -> Path | None:
    if fallback_pdf_path and fallback_pdf_path.exists():
        return fallback_pdf_path
    source_files = pdf_obj.get("source_files", [])
    if source_files and isinstance(source_files[0], str):
        p = Path(source_files[0])
        return p if p.exists() else None
    return None


def clean_lines(block: str) -> list[str]:
    lines: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        if "ccps-ccs-web" in line:
            continue
        lines.append(line)
    return lines


def add_vote(mapping: dict[str, dict[str, Counter]], field_code: str, code: Any, label: Any) -> None:
    c = norm(code)
    l = norm(label)
    if not c or not l:
        return
    mapping[field_code][c][l] += 1


def choose_majority(mapping: dict[str, dict[str, Counter]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for field_code, bucket in mapping.items():
        out[field_code] = {}
        for code, counter in bucket.items():
            out[field_code][code] = counter.most_common(1)[0][0]
    return out


def clean_label_text(label: str) -> str:
    text = norm(label)
    if not text:
        return ""
    # Remove explanatory parentheses to reduce near-duplicate noise.
    text = re.sub(r"[（(].*?[）)]", "", text).strip()
    text = text.replace("大陆", "内地")
    return text


def pick_official_label(candidates: list[str]) -> str:
    cleaned = [clean_label_text(x) for x in candidates if norm(x)]
    cleaned = [x for x in cleaned if x]
    if not cleaned:
        return ""
    uniq = list(dict.fromkeys(cleaned))
    if len(uniq) == 1:
        return uniq[0]
    # Truly conflicting semantics: keep unresolved and rely on field-level canonical override.
    return ""


def load_official_code_map(mapping_path: Path) -> dict[str, dict[str, str]]:
    if not mapping_path.exists():
        return {}
    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    fields_obj = payload.get("fields", {})
    if not isinstance(fields_obj, dict):
        return {}

    code_map: dict[str, dict[str, str]] = {}
    for field_code, info in fields_obj.items():
        if not isinstance(info, dict):
            continue
        code_labels = info.get("code_labels", {})
        if not isinstance(code_labels, dict):
            continue
        out_labels: dict[str, str] = {}
        for code, labels in code_labels.items():
            if not isinstance(labels, list):
                continue
            picked = pick_official_label([str(x) for x in labels])
            if picked:
                out_labels[str(code)] = picked
        if out_labels:
            code_map[str(field_code)] = out_labels
    for field_code, overrides in OFFICIAL_CANONICAL_OVERRIDES.items():
        bucket = code_map.setdefault(field_code, {})
        bucket.update(overrides)
    return code_map


def init_code_mapping_with_pdf_surface(xml_obj: dict[str, Any], pdf_obj: dict[str, Any]) -> dict[str, dict[str, Counter]]:
    """Use already parsed surface fields (PA01/PB01/PB02/PC05) to seed code->label votes."""
    votes: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    xml_tables = xml_obj.get("tables", {})
    pdf_tables = pdf_obj.get("tables", {})

    for table_code, table in xml_tables.items():
        pdf_table = pdf_tables.get(table_code, {})
        pdf_fields = pdf_table.get("fields", {})

        # top-level fields
        for field_code, x_field in table.get("fields", {}).items():
            if not isinstance(x_field, dict):
                continue
            if "code" not in x_field:
                continue
            p_field = pdf_fields.get(field_code, {})
            add_vote(votes, field_code, x_field.get("code"), p_field.get("value"))

            # nested value list (e.g., PA01CH)
            if isinstance(x_field.get("value"), list):
                for item in x_field["value"]:
                    if not isinstance(item, dict):
                        continue
                    for n_code, n_field in item.get("fields", {}).items():
                        if not isinstance(n_field, dict) or "code" not in n_field:
                            continue
                        p_nested = pdf_fields.get(n_code, {})
                        add_vote(votes, n_code, n_field.get("code"), p_nested.get("value"))

        # records
        for rec in table.get("records", []):
            for field_code, x_field in rec.get("fields", {}).items():
                if not isinstance(x_field, dict) or "code" not in x_field:
                    continue
                p_field = pdf_fields.get(field_code, {})
                add_vote(votes, field_code, x_field.get("code"), p_field.get("value"))

    return votes


def infer_pb03_pb04_from_page1(xml_obj: dict[str, Any], pdf_text: str, votes: dict[str, dict[str, Counter]]) -> None:
    """Infer PB03/PB04 coded labels by row-order alignment on page-1 tables."""
    page1 = pdf_text[: pdf_text.find("ccps-ccs-web.t2.bocsys.cn/#/viewIdvReport 1/217") + 80]

    # PB03: 居住信息（居住状况列）
    pb03_rows = []
    m = re.search(r"\(三\) 居住信息(.*?)\(四\) 职业信息", page1, flags=re.S)
    if m:
        seg = m.group(1)
        for line in seg.splitlines():
            line = line.strip()
            row = re.match(r"^\d+\s+.+?\s+\S+\s+(自置|租房|按揭|与父母同住|单位宿舍)\s+\d{4}-\d{2}-\d{2}$", line)
            if row:
                pb03_rows.append(row.group(1))
    pb03_records = xml_obj.get("tables", {}).get("PB03", {}).get("records", [])
    for i, rec in enumerate(pb03_records):
        if i >= len(pb03_rows):
            break
        code = rec.get("fields", {}).get("PB030D01", {}).get("code")
        add_vote(votes, "PB030D01", code, pb03_rows[i])

    # PB04: 职业信息，两段表格
    pb04_records = xml_obj.get("tables", {}).get("PB04", {}).get("records", [])
    unit_nature_rows: list[str] = []
    role_rows: list[tuple[str, str, str]] = []
    m1 = re.search(r"编号 工作单位 单位性质 单位地址 单位电话(.*?)编号 职业 行业 职务 职称", page1, flags=re.S)
    if m1:
        seg = m1.group(1)
        for line in seg.splitlines():
            line = line.strip()
            row = re.match(r"^\d+\s+.+?\s+(其他|机关、事业单位|外资企业|国有企业|民营企业|私营企业)\s+.+$", line)
            if row:
                unit_nature_rows.append(row.group(1))
    m2 = re.search(r"编号 职业 行业 职务 职称 进入本单位年份 信息更新日期(.*)$", page1, flags=re.S)
    if m2:
        seg = m2.group(1)
        for line in seg.splitlines():
            line = line.strip()
            row = re.match(r"^\d+\s+(.+?)\s+(.+?)\s+(一般员工|中级领导|高层领导)\s+(无|初级|中级|高级)\s+.+$", line)
            if row:
                role_rows.append((row.group(1), row.group(2), row.group(3), row.group(4)))
    for i, rec in enumerate(pb04_records):
        fields = rec.get("fields", {})
        if i < len(unit_nature_rows):
            add_vote(votes, "PB040D02", fields.get("PB040D02", {}).get("code"), unit_nature_rows[i])
        if i < len(role_rows):
            prof, industry, duty, title = role_rows[i]
            add_vote(votes, "PB040D04", fields.get("PB040D04", {}).get("code"), prof)
            add_vote(votes, "PB040D03", fields.get("PB040D03", {}).get("code"), industry)
            add_vote(votes, "PB040D05", fields.get("PB040D05", {}).get("code"), duty)
            add_vote(votes, "PB040D06", fields.get("PB040D06", {}).get("code"), title)


def infer_ph01_from_query_rows(xml_obj: dict[str, Any], pdf_text: str, votes: dict[str, dict[str, Counter]]) -> None:
    start = pdf_text.find("八 查询记录")
    end = pdf_text.find("报告说明")
    if start == -1 or end == -1 or end <= start:
        return
    seg = pdf_text[start:end]
    rows = []
    for line in seg.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(.+?)“([A-Z0-9]+)”\s+(.+)$", line)
        if m:
            rows.append(
                {
                    "idx": int(m.group(1)),
                    "date": m.group(2).strip(),
                    "org_type": m.group(3).strip(),
                    "org_code": m.group(4).strip(),
                    "reason": m.group(5).strip(),
                }
            )
    xml_recs = xml_obj.get("tables", {}).get("PH01", {}).get("records", [])
    # Use (date, org_code) match first; fallback to positional zip.
    row_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        row_by_key[(norm(row.get("date")), norm(row.get("org_code")))] = row

    matched = 0
    for i, rec in enumerate(xml_recs):
        x_fields = rec.get("fields", {})
        date_val = norm(x_fields.get("PH010R01", {}).get("value"))
        org_code_val = norm(x_fields.get("PH010Q02", {}).get("value"))
        row = row_by_key.get((date_val, org_code_val))
        if row is None and i < len(rows):
            row = rows[i]
        if row is None:
            continue
        matched += 1
        add_vote(votes, "PH010D01", x_fields.get("PH010D01", {}).get("code"), row.get("org_type"))
        add_vote(votes, "PH010Q03", x_fields.get("PH010Q03", {}).get("code"), row.get("reason"))


def infer_pos_from_sections(xml_obj: dict[str, Any], pdf_text: str, votes: dict[str, dict[str, Counter]]) -> None:
    # PDF section titles provide the semantic type of declaration blocks.
    sec6_start = pdf_text.find("六 异议标注")
    sec7_start = pdf_text.find("七 特殊标注")
    sec8_start = pdf_text.find("八 查询记录")
    if sec6_start == -1 or sec7_start == -1:
        return
    sec6 = pdf_text[sec6_start:sec7_start]
    sec7 = pdf_text[sec7_start:sec8_start if sec8_start != -1 else len(pdf_text)]

    cnt6 = len(re.findall(r"^\d+\s+.+?\s+\d{4}-\d{2}-\d{2}$", sec6, flags=re.M))
    cnt7 = len(re.findall(r"^\d+\s+.+?\s+\d{4}-\d{2}-\d{2}$", sec7, flags=re.M))
    pos_recs = xml_obj.get("tables", {}).get("POS", {}).get("records", [])

    # Empirically this dataset is ordered by section: first 异议标注 then 特殊标注.
    for i, rec in enumerate(pos_recs):
        code = rec.get("fields", {}).get("PG010D03", {}).get("code")
        if i < cnt6:
            add_vote(votes, "PG010D03", code, "异议标注")
        elif i < cnt6 + cnt7:
            add_vote(votes, "PG010D03", code, "特殊标注")
    # Safety fallback for code-level mapping.
    add_vote(votes, "PG010D03", "1", "异议标注")
    add_vote(votes, "PG010D03", "2", "特殊标注")


def _split_business_line(row: str) -> tuple[str, str, str, str, str]:
    """Return (biz, guarantee, frequency, repayment_method, issuance_form)."""
    guarantee_tokens = [
        "组合（不含保证）",
        "组合(不含保证)",
        "组合（含保证）",
        "组合(含保证)",
        "信用/免担保",
        "抵押",
        "保证",
        "质押",
        "无",
    ]
    biz = guar = freq = method = issuance = ""
    g_token = ""
    g_pos = -1
    for token in guarantee_tokens:
        pos = row.find(token)
        if pos != -1 and (g_pos == -1 or pos < g_pos):
            g_pos = pos
            g_token = token
    if g_pos == -1:
        return biz, guar, freq, method, issuance

    biz = row[:g_pos].strip()
    guar = g_token
    right = row[g_pos + len(g_token) :].strip()
    parts = right.split()
    if parts:
        issuance = parts[-1]  # XML field PD01AD08
    if len(parts) >= 2:
        # Usually: [期数, 频率, 还款方式, 贷款发放形式]
        freq = parts[1] if len(parts) >= 3 else ""
    if len(parts) >= 3:
        method = " ".join(parts[2:-1]) if len(parts) > 3 else parts[2]
    return biz, guar, freq, method, issuance


def infer_pd01_from_credit_detail(xml_obj: dict[str, Any], pdf_text: str, votes: dict[str, dict[str, Counter]]) -> None:
    start = pdf_text.find("（一）被追偿信息")
    end = pdf_text.find("四 非信贷交易信息明细")
    if start == -1 or end == -1 or end <= start:
        return
    seg = pdf_text[start:end]

    headers = [
        "（一）被追偿信息",
        "（二）非循环贷账户",
        "（三）循环额度下分账户",
        "（四）循环贷账户",
        "（五）贷记卡账户",
        "（六）准贷记卡账户",
        "（七）其他",
        "（八）相关还款责任信息",
    ]

    # XML PD01 records are grouped by AD01 code.
    pd01_recs = xml_obj.get("tables", {}).get("PD01", {}).get("records", [])
    by_ad01: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(pd01_recs):
        ad01 = rec.get("fields", {}).get("PD01AD01", {}).get("code")
        by_ad01[norm(ad01)].append(i)

    sec_to_xml_indices: dict[str, list[int]] = {
        "（一）被追偿信息": by_ad01.get("C1", []),
        "（二）非循环贷账户": by_ad01.get("D1", [])[:74],
        "（三）循环额度下分账户": by_ad01.get("R4", []),
        "（四）循环贷账户": by_ad01.get("R1", []),
        "（五）贷记卡账户": by_ad01.get("R2", []),
        "（六）准贷记卡账户": by_ad01.get("R3", []),
        "（七）其他": by_ad01.get("D1", [])[74:],
    }

    # AD01 semantic mapping from section names.
    fixed_ad01 = {
        "C1": "被追偿信息",
        "D1": "非循环贷账户/其他",
        "R1": "循环贷账户",
        "R2": "贷记卡账户",
        "R3": "准贷记卡账户",
        "R4": "循环额度下分账户",
    }
    for code, label in fixed_ad01.items():
        add_vote(votes, "PD01AD01", code, label)

    for i, h in enumerate(headers[:-1]):
        if h not in sec_to_xml_indices:
            continue
        s = seg.find(h)
        e = seg.find(headers[i + 1])
        if s == -1:
            continue
        if e == -1:
            e = len(seg)
        block = seg[s:e]
        accounts = re.findall(r"(账户\d+[^\n]*\n.*?)(?=\n账户\d+[^\n]*\n|\Z)", block, flags=re.S)
        xml_indices = sec_to_xml_indices[h]
        pair_count = min(len(accounts), len(xml_indices))

        for j in range(pair_count):
            x_fields = pd01_recs[xml_indices[j]].get("fields", {})
            lines = clean_lines(accounts[j])

            # org/date/amount line
            org_line = ""
            for ln in lines:
                if "“" in ln and re.search(r"\d{4}-\d{2}-\d{2}", ln):
                    org_line = ln
                    break
            org_type = ""
            if org_line:
                m = re.search(r'([^\s“”"]+)\s*“[A-Z0-9]+”', org_line)
                if m:
                    org_type = m.group(1)
            add_vote(votes, "PD01AD02", x_fields.get("PD01AD02", {}).get("code"), org_type)

            # business row parsing
            biz = guar = freq = method = issuance = ""
            if h == "（一）被追偿信息":
                m = re.search(r"“[A-Z0-9]+”\s+(.+?)\s+\d{4}-\d{2}-\d{2}\s+[0-9,]+\s+(.+)$", org_line)
                if m:
                    biz = m.group(1).strip()
                    add_vote(votes, "PD01AD10", x_fields.get("PD01AD10", {}).get("code"), m.group(2).strip())
            elif h in {"（二）非循环贷账户", "（三）循环额度下分账户", "（四）循环贷账户", "（七）其他"}:
                row = ""
                for k, ln in enumerate(lines):
                    if "业务种类" in ln and "担保方式" in ln and k + 1 < len(lines):
                        row = lines[k + 1]
                        break
                biz, guar, freq, method, issuance = _split_business_line(row)
            elif h == "（五）贷记卡账户":
                row = ""
                m = re.search(r"(人民币元|美元|日元)\s+(.+)$", org_line)
                if m:
                    row = m.group(2).strip()
                # row style: 贷记卡 组合（不含保证） / 大额专项分期卡 组合（不含保证）
                tokens = row.split()
                if tokens:
                    biz = tokens[0]
                    guar = tokens[1] if len(tokens) > 1 else ""
            elif h == "（六）准贷记卡账户":
                # section itself is business semantic
                biz = "准贷记卡"
                m = re.search(r"(人民币元|美元|日元)\s+(.+)$", org_line)
                if m:
                    guar = m.group(2).strip()

            add_vote(votes, "PD01AD03", x_fields.get("PD01AD03", {}).get("code"), biz)
            add_vote(votes, "PD01AD07", x_fields.get("PD01AD07", {}).get("code"), guar)
            add_vote(votes, "PD01AD06", x_fields.get("PD01AD06", {}).get("code"), freq)
            add_vote(votes, "PD01AD05", x_fields.get("PD01AD05", {}).get("code"), method)
            add_vote(votes, "PD01AD08", x_fields.get("PD01AD08", {}).get("code"), issuance)

            # account status / five-classification
            status = five = ""
            for k, ln in enumerate(lines):
                if ln.startswith("账户状态") and k + 1 < len(lines):
                    cand = lines[k + 1]
                    if cand == "还款日期" and k + 2 < len(lines):
                        cand = lines[k + 2]
                    tokens = cand.split()
                    if tokens:
                        status = tokens[0]
                    if len(tokens) >= 2 and not re.fullmatch(r"[0-9,.\-]+", tokens[1]) and tokens[1] != "--":
                        five = tokens[1]
                    break
            add_vote(votes, "PD01BD01", x_fields.get("PD01BD01", {}).get("code"), status)
            add_vote(votes, "PD01BD03", x_fields.get("PD01BD03", {}).get("code"), five)

            # repayment status symbol mapping
            bd04_code = norm(x_fields.get("PD01BD04", {}).get("code"))
            if bd04_code:
                status_label = bd04_code
                for ln in lines:
                    m = re.search(r"([0-9N\*])\s*-\s*([^\s]+)", ln)
                    if m and m.group(1) == bd04_code:
                        status_label = m.group(2)
                        break
                add_vote(votes, "PD01BD04", bd04_code, status_label)

    # normalize a few noisy observations to stable business terms
    fallback_overrides = {
        "PA01CD01": {
            "20": "军人身份证件",
        },
        "PB040D01": {
            "91": "在职",
        },
        "PB040D02": {
            "20": "国有企业",
        },
        "PD01AD03": {
            "81": "贷记卡",
            "82": "大额专项分期卡",
            "71": "贷记卡",
            "92": "融资租赁业务",
        },
        "PD01AD02": {
            "23": "小额贷款公司",
            "51": "汽车金融公司",
            "99": "其他机构",
        },
        "PD01BD04": {
            "N": "正常还款",
            "*": "*",
            "1": "1",
            "2": "2",
            "7": "7",
        },
    }
    for field_code, code_map in fallback_overrides.items():
        for code, label in code_map.items():
            if code not in votes[field_code] or not votes[field_code][code]:
                add_vote(votes, field_code, code, label)


def build_pdf_code_label_mapping(
    xml_obj: dict[str, Any],
    pdf_obj: dict[str, Any],
    pdf_text: str,
) -> dict[str, dict[str, str]]:
    votes = init_code_mapping_with_pdf_surface(xml_obj, pdf_obj)
    infer_pb03_pb04_from_page1(xml_obj, pdf_text, votes)
    infer_ph01_from_query_rows(xml_obj, pdf_text, votes)
    infer_pos_from_sections(xml_obj, pdf_text, votes)
    infer_pd01_from_credit_detail(xml_obj, pdf_text, votes)
    code_map = choose_majority(votes)
    # Force-fix high-confidence business overrides where voting can be biased by noisy rows.
    forced_overrides = {
        "PD01AD02": {
            "23": "小额贷款公司",
            "51": "汽车金融公司",
            "99": "其他机构",
        },
        "PD01AD03": {
            "82": "大额专项分期卡",
        },
        "PD01BD01": {
            "6": "未激活",
        },
        "PD01BD04": {
            "N": "正常还款",
        },
        "PG010D03": {
            "2": "特殊标注",
        },
    }
    for field_code, mapping in forced_overrides.items():
        bucket = code_map.setdefault(field_code, {})
        for code, label in mapping.items():
            bucket[code] = label
    return code_map


def enrich_field_with_label_source(
    field_obj: dict[str, Any],
    *,
    label: str,
    label_source: str,
    interpretation_status: str,
    inference_method: str,
) -> dict[str, Any]:
    updated = copy.deepcopy(field_obj)
    updated["label"] = label
    updated["label_source"] = label_source
    updated["interpretation_status"] = interpretation_status
    meta = updated.setdefault("value_meta", {})
    extra = meta.setdefault("extra_fields", {})
    extra["label_inference_method"] = inference_method
    return updated


def enrich_xml_labels(
    xml_obj: dict[str, Any],
    official_code_map: dict[str, dict[str, str]],
    pdf_code_map: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], dict[str, int]]:
    enriched = copy.deepcopy(xml_obj)
    stats = {
        "coded_fields_total": 0,
        "coded_fields_already_labeled": 0,
        "coded_fields_empty_code": 0,
        "coded_fields_unresolved": 0,
        "coded_fields_resolved_from_official": 0,
        "coded_fields_resolved_from_pdf": 0,
        "coded_fields_still_unresolved": 0,
    }

    def process_field(field_code: str, field_obj: dict[str, Any]) -> dict[str, Any]:
        if "code" not in field_obj:
            return field_obj

        stats["coded_fields_total"] += 1
        if field_obj.get("label") not in (None, ""):
            stats["coded_fields_already_labeled"] += 1
            return field_obj

        code = norm(field_obj.get("code"))
        if not code:
            stats["coded_fields_empty_code"] += 1
            return field_obj

        stats["coded_fields_unresolved"] += 1
        official_bucket = official_code_map.get(field_code, {})
        candidate_official = official_code_map.get(field_code, {}).get(code, "")
        if candidate_official:
            stats["coded_fields_resolved_from_official"] += 1
            return enrich_field_with_label_source(
                field_obj,
                label=candidate_official,
                label_source="official_codebook",
                interpretation_status="resolved_from_codebook",
                inference_method="official_code_tables_by_field",
            )

        # For fields already covered by official codebook, do not fall back to PDF to avoid
        # row-alignment pollution (e.g., PD01BD04 mislabeled as "11"/"60天").
        if not official_bucket:
            candidate_pdf = pdf_code_map.get(field_code, {}).get(code, "")
            if candidate_pdf:
                stats["coded_fields_resolved_from_pdf"] += 1
                return enrich_field_with_label_source(
                    field_obj,
                    label=candidate_pdf,
                    label_source="pdf_text_inferred",
                    interpretation_status="resolved_from_pdf",
                    inference_method="code_to_label_mapping_from_pdf",
                )

        stats["coded_fields_still_unresolved"] += 1
        return field_obj

    for table in enriched.get("tables", {}).values():
        fields = table.get("fields", {})
        for field_code in list(fields.keys()):
            if isinstance(fields[field_code], dict):
                fields[field_code] = process_field(field_code, fields[field_code])

        for rec in table.get("records", []):
            rec_fields = rec.get("fields", {})
            for field_code in list(rec_fields.keys()):
                if isinstance(rec_fields[field_code], dict):
                    rec_fields[field_code] = process_field(field_code, rec_fields[field_code])
            for field_code, field_obj in rec_fields.items():
                if not isinstance(field_obj, dict):
                    continue
                if "value" in field_obj and isinstance(field_obj["value"], list):
                    for item in field_obj["value"]:
                        if not isinstance(item, dict):
                            continue
                        nested_fields = item.get("fields", {})
                        for n_code in list(nested_fields.keys()):
                            n_obj = nested_fields[n_code]
                            if isinstance(n_obj, dict):
                                nested_fields[n_code] = process_field(n_code, n_obj)

        for field_code, field_obj in fields.items():
            if not isinstance(field_obj, dict):
                continue
            if "value" in field_obj and isinstance(field_obj["value"], list):
                for item in field_obj["value"]:
                    if not isinstance(item, dict):
                        continue
                    nested_fields = item.get("fields", {})
                    for n_code in list(nested_fields.keys()):
                        n_obj = nested_fields[n_code]
                        if isinstance(n_obj, dict):
                            nested_fields[n_code] = process_field(n_code, n_obj)

    enriched.setdefault("raw_sections", {}).setdefault("source_summary", {})
    enriched["raw_sections"]["source_summary"]["code_label_enrichment"] = {
        "source": "official_codebook_plus_pdf_fallback",
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "stats": stats,
        "official_mapped_field_count": len(official_code_map),
        "pdf_mapped_field_count": len(pdf_code_map),
    }
    return enriched, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xml",
        type=Path,
        default=Path("output/individual.standard.json"),
        help="Path to XML-derived standard JSON.",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=Path("output/individual.pdf.standard.json"),
        help="Path to PDF-derived standard-like JSON.",
    )
    parser.add_argument(
        "--pdf-file",
        type=Path,
        default=None,
        help="Optional raw PDF file path. If omitted, inferred from --pdf source_files.",
    )
    parser.add_argument(
        "--codebook-map",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "mapping" / "official_code_tables.by_field.individual_v1.json",
        help="Official per-field code->label mapping JSON.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output/individual.standard.enriched_labels.json"),
        help="Output path for enriched JSON.",
    )
    args = parser.parse_args()

    xml_obj = json.loads(args.xml.read_text(encoding="utf-8"))
    pdf_obj = json.loads(args.pdf.read_text(encoding="utf-8"))
    pdf_path = extract_pdf_path(pdf_obj, args.pdf_file)
    if not pdf_path:
        raise FileNotFoundError("Cannot locate raw PDF file for label inference.")
    pdf_text = read_pdf_text(pdf_path)

    official_code_map = load_official_code_map(args.codebook_map)
    pdf_code_map = build_pdf_code_label_mapping(xml_obj, pdf_obj, pdf_text)
    enriched, stats = enrich_xml_labels(xml_obj, official_code_map, pdf_code_map)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "stats": stats,
                "official_mapped_fields": sorted(official_code_map.keys()),
                "pdf_mapped_fields": sorted(pdf_code_map.keys()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
