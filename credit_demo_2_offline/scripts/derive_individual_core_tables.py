#!/usr/bin/env python3
"""Derive core normalized tables from individual.standard.enriched_labels.json."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def field_value(field_obj: dict[str, Any] | None) -> Any:
    if not isinstance(field_obj, dict):
        return None
    return field_obj.get("value")


def field_label_or_code(field_obj: dict[str, Any] | None) -> str | None:
    if not isinstance(field_obj, dict):
        return None
    for key in ("label", "value", "code"):
        v = field_obj.get(key)
        if v not in (None, ""):
            return str(v)
    return None


def field_code(field_obj: dict[str, Any] | None) -> str | None:
    if not isinstance(field_obj, dict):
        return None
    v = field_obj.get("code")
    if v in (None, ""):
        return None
    return str(v)


def get_field(fields: dict[str, Any], code: str) -> dict[str, Any]:
    return as_dict(fields.get(code))


def labeled_value_and_code(field_obj: dict[str, Any] | None) -> tuple[str | None, str | None]:
    return field_label_or_code(field_obj), field_code(field_obj)


def maybe_int(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except Exception:
        return None


def overdue_code_to_months(code_or_label: Any) -> int | None:
    s = str(code_or_label or "").strip().upper()
    if not s:
        return None
    digit_match = None
    if s.isdigit():
        digit_match = int(s)
    else:
        # 支持"逾期31-60天"这类文本取首个数字
        import re

        m = re.search(r"\b([1-7])\b", s)
        if m:
            digit_match = int(m.group(1))
    if digit_match is None:
        return None
    if 1 <= digit_match <= 7:
        return digit_match
    return None


def sum_fields_numeric(fields: dict[str, Any], codes: list[str]) -> float:
    total = 0.0
    for code in codes:
        v = field_value(get_field(fields, code))
        if v in (None, ""):
            continue
        try:
            total += float(str(v).replace(",", "").strip())
        except Exception:
            continue
    return total


def _norm_text(v: Any) -> str:
    return str(v or "").strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def _is_outstanding_account(status: Any, close_date: Any) -> bool:
    status_text = _norm_text(status)
    close_text = _norm_text(close_date)
    if "结清" in status_text:
        return False
    if close_text:
        return False
    return True


def _is_loan_category(category: Any) -> bool:
    return _norm_text(category) in {"非循环贷账户", "循环额度下分账户", "循环贷账户"}


def _derive_loan_classification(
    *,
    account_category: Any,
    business_type: Any,
    guarantee_method: Any,
    institution_name: Any,
    institution_type: Any,
) -> str | None:
    if not _is_loan_category(account_category):
        return None

    biz = _norm_text(business_type)
    guarantee = _norm_text(guarantee_method)
    inst_name = _norm_text(institution_name)
    inst_type = _norm_text(institution_type)
    text = f"{biz}|{guarantee}|{inst_name}|{inst_type}"

    # Institution-level categories have priority.
    if _contains_any(text, ["小额贷款", "小贷"]):
        return "小额贷款"
    if _contains_any(text, ["消费金融"]):
        return "消费金融公司贷款"
    if _contains_any(text, ["信托"]):
        return "信托公司贷款"

    # Housing / commercial housing.
    if _contains_any(text, ["住房", "公积金贷款", "按揭"]):
        return "住房贷款"
    if _contains_any(text, ["商用房", "商住两用"]):
        return "商用房/商住两用贷款"

    # Operation loans.
    if _contains_any(text, ["经营"]):
        if _contains_any(text, ["抵押", "质押"]):
            return "抵押经营贷款"
        return "无抵押经营贷款"

    # Consumer loans.
    if _contains_any(text, ["消费"]):
        if _contains_any(text, ["抵押", "质押"]):
            return "抵押消费贷款"
        return "无抵质押消费贷款"

    return "其他贷款"


def normalize_report_id(report_id: str | None) -> str:
    if report_id:
        return report_id
    return f"generated_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def mask_id_no(id_no: str | None) -> str | None:
    if not id_no:
        return None
    if "*" in id_no:
        return id_no
    if len(id_no) <= 10:
        return id_no
    return f"{id_no[:6]}****{id_no[-4:]}"


def guess_source_paths(source_files: list[Any]) -> tuple[str | None, str | None]:
    xml_path = None
    pdf_path = None
    for item in source_files:
        if isinstance(item, dict):
            role = str(item.get("role") or "")
            path = str(item.get("path") or "")
            if role == "xml" and path:
                xml_path = path
            if role == "pdf" and path:
                pdf_path = path
        elif isinstance(item, str):
            if item.lower().endswith(".xml"):
                xml_path = item
            if item.lower().endswith(".pdf"):
                pdf_path = item
    return xml_path, pdf_path


def derive_report_basic(report_id: str, tables: dict[str, Any], source_files: list[Any]) -> list[dict[str, Any]]:
    pa01 = as_dict(as_dict(tables.get("PA01")).get("fields"))
    xml_path, pdf_path = guess_source_paths(source_files)
    subject_id_type, subject_id_type_code = labeled_value_and_code(get_field(pa01, "PA01BD01"))
    query_reason, query_reason_code = labeled_value_and_code(get_field(pa01, "PA01BD02"))
    row = {
        "report_id": report_id,
        "report_time": field_value(get_field(pa01, "PA01AR01")),
        "report_type": "individual",
        "subject_name": field_value(get_field(pa01, "PA01BQ01")),
        "subject_id_type": subject_id_type,
        "subject_id_type_code": subject_id_type_code,
        "subject_id_no_masked": mask_id_no(field_value(get_field(pa01, "PA01BI01"))),
        "query_reason": query_reason,
        "query_reason_code": query_reason_code,
        "source_xml_file": xml_path,
        "source_pdf_file": pdf_path,
    }
    return [row]


def derive_credit_summary(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pc02_fields = as_dict(as_dict(tables.get("PC02")).get("fields"))
    amount_units = {
        "PC02BJ01",
        "PC02CJ01",
        "PC02EJ01",
        "PC02EJ02",
        "PC02EJ03",
        "PC02FJ01",
        "PC02FJ02",
        "PC02FJ03",
        "PC02GJ01",
        "PC02GJ02",
        "PC02GJ03",
        "PC02HJ01",
        "PC02HJ02",
        "PC02HJ03",
        "PC02HJ04",
        "PC02HJ05",
        "PC02IJ01",
        "PC02IJ02",
        "PC02IJ03",
        "PC02IJ04",
        "PC02IJ05",
        "PC02KJ01",
        "PC02KJ02",
        "PC02DJ01",
    }

    # PC02: 信贷交易授信及负债信息概要（报告说明第7条：未结清/未销户口径）
    # Top-level scalar fields
    for field_code, field_obj_any in pc02_fields.items():
        field_obj = as_dict(field_obj_any)
        metric_value = field_value(field_obj)
        if metric_value in (None, ""):
            continue
        if isinstance(metric_value, (list, dict)):
            continue
        unit = ""
        if field_code in amount_units:
            unit = "元"
        elif "S" in field_code:
            unit = "个"
        rows.append(
            {
                "report_id": report_id,
                "metric_key": field_code,
                "metric_name_cn": field_obj.get("field_name"),
                "metric_value": metric_value,
                "unit": unit,
                "business_domain": "credit_liability_summary",
                "data_scope": "current_summary_unsettled_or_uncancelled",
                "source_json_path": f"tables.PC02.fields.{field_code}",
                "pdf_page": None,
            }
        )

    # PC02 nested details, currently only K section is required for liability aggregation.
    pc02kh = as_list(as_dict(pc02_fields.get("PC02KH")).get("value"))
    for idx, rec_any in enumerate(pc02kh):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        for field_code, field_obj_any in fields.items():
            field_obj = as_dict(field_obj_any)
            metric_value = field_value(field_obj)
            if metric_value in (None, ""):
                continue
            if isinstance(metric_value, (list, dict)):
                continue
            unit = "元" if field_code in amount_units else ("个" if "S" in field_code else "")
            rows.append(
                {
                    "report_id": report_id,
                    "metric_key": field_code,
                    "metric_name_cn": field_obj.get("field_name"),
                    "metric_value": metric_value,
                    "unit": unit,
                    "business_domain": "credit_liability_summary",
                    "data_scope": "current_summary_unsettled_or_uncancelled",
                    "source_json_path": f"tables.PC02.fields.PC02KH.value[{idx}].fields.{field_code}",
                    "pdf_page": None,
                }
            )

    pc05_fields = as_dict(as_dict(tables.get("PC05")).get("fields"))
    for field_code, field_obj_any in pc05_fields.items():
        field_obj = as_dict(field_obj_any)
        metric_value = field_value(field_obj)
        if metric_value in (None, ""):
            continue
        rows.append(
            {
                "report_id": report_id,
                "metric_key": field_code,
                "metric_name_cn": field_obj.get("field_name"),
                "metric_value": metric_value,
                "unit": "次" if field_code.startswith("PC05BS") else "",
                "business_domain": "query_summary",
                "data_scope": "current_summary",
                "source_json_path": f"tables.PC05.fields.{field_code}",
                "pdf_page": None,
            }
        )

    pos_summary = as_dict(as_dict(tables.get("POS")).get("summary_fields"))
    for field_code, field_obj_any in pos_summary.items():
        field_obj = as_dict(field_obj_any)
        metric_value = field_value(field_obj)
        if metric_value in (None, ""):
            continue
        rows.append(
            {
                "report_id": report_id,
                "metric_key": field_code,
                "metric_name_cn": field_obj.get("field_name"),
                "metric_value": metric_value,
                "unit": "条" if field_code == "PG010S01" else "",
                "business_domain": "objection_summary",
                "data_scope": "current_summary",
                "source_json_path": f"tables.POS.summary_fields.{field_code}",
                "pdf_page": None,
            }
        )
    return rows


def derive_credit_account(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pd01_records = as_list(as_dict(tables.get("PD01")).get("records"))
    for idx, rec_any in enumerate(pd01_records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        account_id = field_value(get_field(fields, "PD01AI01")) or f"pd01_{idx + 1}"
        overdue_code = (get_field(fields, "PD01BD04") or {}).get("code")
        account_status, account_status_code = labeled_value_and_code(get_field(fields, "PD01BD01"))
        if not account_status:
            account_status, account_status_code = labeled_value_and_code(get_field(fields, "PD01CD01"))
        account_category, account_category_code = labeled_value_and_code(get_field(fields, "PD01AD01"))
        business_type, business_type_code = labeled_value_and_code(get_field(fields, "PD01AD03"))
        institution_type, institution_type_code = labeled_value_and_code(get_field(fields, "PD01AD02"))
        currency, currency_code = labeled_value_and_code(get_field(fields, "PD01AD04"))
        five_classification, five_classification_code = labeled_value_and_code(get_field(fields, "PD01CD02"))
        if not five_classification:
            five_classification, five_classification_code = labeled_value_and_code(get_field(fields, "PD01BD03"))
        guarantee_method, guarantee_method_code = labeled_value_and_code(get_field(fields, "PD01AD05"))
        overdue_total = field_value(get_field(fields, "PD01CJ06"))
        if overdue_total in (None, ""):
            overdue_total = field_value(get_field(fields, "PD01BJ02"))
        overdue_principal = sum_fields_numeric(fields, ["PD01CJ07", "PD01CJ08", "PD01CJ09", "PD01CJ10"])
        if overdue_principal == 0:
            raw_bj3 = field_value(get_field(fields, "PD01BJ03"))
            if raw_bj3 not in (None, ""):
                try:
                    overdue_principal = float(str(raw_bj3).replace(",", "").strip())
                except Exception:
                    overdue_principal = 0
        rows.append(
            {
                "report_id": report_id,
                "account_id": str(account_id),
                "account_status": account_status,
                "account_status_code": account_status_code,
                "account_category": account_category,
                "account_category_code": account_category_code,
                "business_type": business_type,
                "business_type_code": business_type_code,
                "institution_name": field_value(get_field(fields, "PD01AI02")),
                "institution_type": institution_type,
                "institution_type_code": institution_type_code,
                "currency": currency,
                "currency_code": currency_code,
                "open_date": field_value(get_field(fields, "PD01AR01")),
                "due_date": field_value(get_field(fields, "PD01AR02")),
                "close_date": field_value(get_field(fields, "PD01BR01")),
                "original_amount": field_value(get_field(fields, "PD01AJ01")),
                "credit_limit": field_value(get_field(fields, "PD01AJ02")),
                "balance": field_value(get_field(fields, "PD01BJ01")),
                "five_classification": five_classification,
                "five_classification_code": five_classification_code,
                "overdue_total": overdue_total,
                "overdue_principal": overdue_principal if overdue_principal != 0 else None,
                "overdue_months": maybe_int(field_value(get_field(fields, "PD01CS02")))
                or overdue_code_to_months(overdue_code),
                "latest_repay_date": field_value(get_field(fields, "PD01BR03")),
                "guarantee_method": guarantee_method,
                "guarantee_method_code": guarantee_method_code,
                "is_outstanding_account": _is_outstanding_account(
                    account_status,
                    field_value(get_field(fields, "PD01BR01")),
                ),
                "is_loan_account": _is_loan_category(account_category),
                "loan_classification": _derive_loan_classification(
                    account_category=account_category,
                    business_type=business_type,
                    guarantee_method=guarantee_method,
                    institution_name=field_value(get_field(fields, "PD01AI02")),
                    institution_type=institution_type,
                ),
                "source_json_path": f"tables.PD01.records[{idx}].fields",
                "pdf_page": None,
                "evidence_text": None,
            }
        )
    return rows


def derive_identity_info(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    pb01 = as_dict(as_dict(tables.get("PB01")).get("fields"))
    gender, gender_code = labeled_value_and_code(get_field(pb01, "PB01AD01"))
    education, education_code = labeled_value_and_code(get_field(pb01, "PB01AD02"))
    degree, degree_code = labeled_value_and_code(get_field(pb01, "PB01AD03"))
    employment_status, employment_status_code = labeled_value_and_code(get_field(pb01, "PB01AD04"))
    nationality, nationality_code = labeled_value_and_code(get_field(pb01, "PB01AD05"))
    row = {
        "report_id": report_id,
        "gender": gender,
        "gender_code": gender_code,
        "birth_date": field_value(get_field(pb01, "PB01AR01")),
        "education": education,
        "education_code": education_code,
        "degree": degree,
        "degree_code": degree_code,
        "employment_status": employment_status,
        "employment_status_code": employment_status_code,
        "nationality": nationality,
        "nationality_code": nationality_code,
        "email": field_value(get_field(pb01, "PB01AQ01")),
        "communication_address": field_value(get_field(pb01, "PB01AQ02")),
        "hukou_address": field_value(get_field(pb01, "PB01AQ03")),
        "source_json_path": "tables.PB01.fields",
    }
    return [row]


def derive_residence_info(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = as_list(as_dict(tables.get("PB03")).get("records"))
    for idx, rec_any in enumerate(records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        residence_status, residence_status_code = labeled_value_and_code(get_field(fields, "PB030D01"))
        rows.append(
            {
                "report_id": report_id,
                "residence_id": f"pb03_{idx + 1}",
                "residence_status": residence_status,
                "residence_status_code": residence_status_code,
                "residence_address": field_value(get_field(fields, "PB030Q01")),
                "residence_phone": field_value(get_field(fields, "PB030Q02")),
                "update_date": field_value(get_field(fields, "PB030R01")),
                "source_json_path": f"tables.PB03.records[{idx}].fields",
            }
        )
    return rows


def derive_occupation_info(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = as_list(as_dict(tables.get("PB04")).get("records"))
    for idx, rec_any in enumerate(records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        company_nature, company_nature_code = labeled_value_and_code(get_field(fields, "PB040D02"))
        industry, industry_code = labeled_value_and_code(get_field(fields, "PB040D03"))
        occupation, occupation_code = labeled_value_and_code(get_field(fields, "PB040D04"))
        position, position_code = labeled_value_and_code(get_field(fields, "PB040D05"))
        title, title_code = labeled_value_and_code(get_field(fields, "PB040D06"))
        rows.append(
            {
                "report_id": report_id,
                "occupation_id": f"pb04_{idx + 1}",
                "company_name": field_value(get_field(fields, "PB040Q01")),
                "company_nature": company_nature,
                "company_nature_code": company_nature_code,
                "industry": industry,
                "industry_code": industry_code,
                "company_address": field_value(get_field(fields, "PB040Q02")),
                "company_phone": field_value(get_field(fields, "PB040Q03")),
                "occupation": occupation,
                "occupation_code": occupation_code,
                "position": position,
                "position_code": position_code,
                "title": title,
                "title_code": title_code,
                "entry_year": field_value(get_field(fields, "PB040R01")),
                "update_date": field_value(get_field(fields, "PB040R02")),
                "source_json_path": f"tables.PB04.records[{idx}].fields",
            }
        )
    return rows


def derive_special_transaction(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pd01_records = as_list(as_dict(tables.get("PD01")).get("records"))
    card_categories = {"贷记卡账户", "准贷记卡账户"}
    for idx, rec_any in enumerate(pd01_records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        account_id = field_value(get_field(fields, "PD01AI01")) or f"pd01_{idx + 1}"
        account_category, account_category_code = labeled_value_and_code(get_field(fields, "PD01AD01"))
        business_type, business_type_code = labeled_value_and_code(get_field(fields, "PD01AD03"))
        institution_name = field_value(get_field(fields, "PD01AI02"))
        z_list = as_list(field_value(get_field(fields, "PD01ZH")))
        for z_idx, z_any in enumerate(z_list):
            z_fields = as_dict(as_dict(z_any).get("fields"))
            type_label, type_code = labeled_value_and_code(get_field(z_fields, "PD01ZD01"))
            desc = field_value(get_field(z_fields, "PD01ZQ01"))
            trade_date = field_value(get_field(z_fields, "PD01ZR01"))
            text = _norm_text(type_label) + "|" + _norm_text(desc)
            is_card_related = _norm_text(account_category) in card_categories
            has_personalized_installment = _contains_any(text, ["个性化分期", "专项分期", "大额专项分期"])
            has_extension = _contains_any(text, ["展期"])
            is_negative_event = _contains_any(text, ["个性化分期", "展期", "代偿", "呆账", "异议处理期"])
            rows.append(
                {
                    "report_id": report_id,
                    "special_id": f"pd01_{idx + 1}_z_{z_idx + 1}",
                    "account_id": str(account_id),
                    "account_category": account_category,
                    "account_category_code": account_category_code,
                    "business_type": business_type,
                    "business_type_code": business_type_code,
                    "institution_name": institution_name,
                    "special_type": type_label,
                    "special_type_code": type_code,
                    "special_description": desc,
                    "special_date": trade_date,
                    "is_card_related": is_card_related,
                    "has_personalized_installment": has_personalized_installment,
                    "has_extension": has_extension,
                    "is_negative_event": is_negative_event,
                    "source_json_path": f"tables.PD01.records[{idx}].fields.PD01ZH.value[{z_idx}]",
                }
            )
    return rows


def derive_account_history(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pd01_records = as_list(as_dict(tables.get("PD01")).get("records"))
    for idx, rec_any in enumerate(pd01_records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        account_id = field_value(get_field(fields, "PD01AI01")) or f"pd01_{idx + 1}"
        # Prefer monthly sequence from PD01D + overdue amount from PD01E.
        monthly_status_rows = as_list(field_value(get_field(fields, "PD01DH")))
        monthly_overdue_rows = as_list(field_value(get_field(fields, "PD01EH")))
        overdue_by_month: dict[str, Any] = {}
        for item in monthly_overdue_rows:
            item_fields = as_dict(as_dict(item).get("fields"))
            month = field_value(get_field(item_fields, "PD01ER03"))
            overdue_amt = field_value(get_field(item_fields, "PD01EJ01"))
            if month not in (None, ""):
                overdue_by_month[str(month)] = overdue_amt

        if monthly_status_rows:
            for m_idx, item in enumerate(monthly_status_rows):
                item_fields = as_dict(as_dict(item).get("fields"))
                month = field_value(get_field(item_fields, "PD01DR03"))
                repay_type, status_code = labeled_value_and_code(get_field(item_fields, "PD01DD01"))
                if month in (None, ""):
                    continue
                rows.append(
                    {
                        "report_id": report_id,
                        "account_id": str(account_id),
                        "period_date": month,
                        "balance": None,
                        "balance_change_date": None,
                        "five_classification": None,
                        "five_classification_date": None,
                        "overdue_total": overdue_by_month.get(str(month)),
                        "overdue_principal": None,
                        "overdue_months": overdue_code_to_months(status_code),
                        "scheduled_repay_date": None,
                        "scheduled_repay_amount": None,
                        "actual_repay_date": None,
                        "actual_repay_amount": None,
                        "repay_type": repay_type,
                        "repay_type_code": status_code,
                        "source_json_path": f"tables.PD01.records[{idx}].fields.PD01DH.value[{m_idx}]",
                        "pdf_page": None,
                    }
                )
            continue

        # Fallback: latest monthly profile (PD01C) or account snapshot (PD01B).
        period_date = (
            field_value(get_field(fields, "PD01CR04"))
            or field_value(get_field(fields, "PD01CR01"))
            or field_value(get_field(fields, "PD01BR03"))
            or field_value(get_field(fields, "PD01BR02"))
            or field_value(get_field(fields, "PD01AR01"))
        )
        if period_date in (None, ""):
            continue
        overdue_total = field_value(get_field(fields, "PD01CJ06"))
        if overdue_total in (None, ""):
            overdue_total = field_value(get_field(fields, "PD01BJ02"))
        overdue_principal = sum_fields_numeric(fields, ["PD01CJ07", "PD01CJ08", "PD01CJ09", "PD01CJ10"])
        if overdue_principal == 0:
            raw_bj3 = field_value(get_field(fields, "PD01BJ03"))
            if raw_bj3 not in (None, ""):
                try:
                    overdue_principal = float(str(raw_bj3).replace(",", "").strip())
                except Exception:
                    overdue_principal = 0
        repay_type, status_code = labeled_value_and_code(get_field(fields, "PD01BD04"))
        five_classification, five_classification_code = labeled_value_and_code(get_field(fields, "PD01CD02"))
        if not five_classification:
            five_classification, five_classification_code = labeled_value_and_code(get_field(fields, "PD01BD03"))
        rows.append(
            {
                "report_id": report_id,
                "account_id": str(account_id),
                "period_date": period_date,
                "balance": field_value(get_field(fields, "PD01CJ01")) or field_value(get_field(fields, "PD01BJ01")),
                "balance_change_date": field_value(get_field(fields, "PD01BR02")),
                "five_classification": five_classification,
                "five_classification_code": five_classification_code,
                "five_classification_date": None,
                "overdue_total": overdue_total,
                "overdue_principal": overdue_principal if overdue_principal != 0 else None,
                "overdue_months": maybe_int(field_value(get_field(fields, "PD01CS02")))
                or overdue_code_to_months(status_code),
                "scheduled_repay_date": field_value(get_field(fields, "PD01CR02")) or field_value(get_field(fields, "PD01BR02")),
                "scheduled_repay_amount": field_value(get_field(fields, "PD01CJ04")),
                "actual_repay_date": field_value(get_field(fields, "PD01CR03")) or field_value(get_field(fields, "PD01BR03")),
                "actual_repay_amount": field_value(get_field(fields, "PD01CJ05")),
                "repay_type": repay_type,
                "repay_type_code": status_code,
                "source_json_path": f"tables.PD01.records[{idx}].fields",
                "pdf_page": None,
            }
        )
    return rows


def derive_query_record(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = as_list(as_dict(tables.get("PH01")).get("records"))
    for idx, rec_any in enumerate(records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        query_reason, query_reason_code = labeled_value_and_code(get_field(fields, "PH010Q03"))
        query_type, query_type_code = labeled_value_and_code(get_field(fields, "PH010D01"))
        rows.append(
            {
                "report_id": report_id,
                "query_date": field_value(get_field(fields, "PH010R01")),
                "query_institution": field_value(get_field(fields, "PH010Q02")),
                "query_reason": query_reason,
                "query_reason_code": query_reason_code,
                "query_type": query_type,
                "query_type_code": query_type_code,
                "source_json_path": f"tables.PH01.records[{idx}].fields",
                "pdf_page": None,
            }
        )
    return rows


def derive_guarantee_record(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = as_list(as_dict(tables.get("PD03")).get("records"))
    for idx, rec_any in enumerate(records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        if not fields:
            continue
        guarantee_id = field_value(get_field(fields, "PD03AI01")) or f"pd03_{idx + 1}"
        guarantee_type, guarantee_type_code = labeled_value_and_code(get_field(fields, "PD03AD01"))
        responsibility_type, responsibility_type_code = labeled_value_and_code(get_field(fields, "PD03AD02"))
        business_type, business_type_code = labeled_value_and_code(get_field(fields, "PD03AD05"))
        five_classification, five_classification_code = labeled_value_and_code(get_field(fields, "PD03AD07"))
        rows.append(
            {
                "report_id": report_id,
                "guarantee_id": str(guarantee_id),
                "guarantee_type": guarantee_type,
                "guarantee_type_code": guarantee_type_code,
                "responsibility_type": responsibility_type,
                "responsibility_type_code": responsibility_type_code,
                "related_account_id": field_value(get_field(fields, "PD03AI02")),
                "institution_name": field_value(get_field(fields, "PD03AI03")),
                "business_type": business_type,
                "business_type_code": business_type_code,
                "amount": field_value(get_field(fields, "PD03AJ01")),
                "balance": field_value(get_field(fields, "PD03AJ02")),
                "five_classification": five_classification,
                "five_classification_code": five_classification_code,
                "overdue_total": field_value(get_field(fields, "PD03AJ03")),
                "overdue_principal": None,
                "start_date": field_value(get_field(fields, "PD03AR01")),
                "end_date": field_value(get_field(fields, "PD03AR02")),
                "source_json_path": f"tables.PD03.records[{idx}].fields",
                "pdf_page": None,
            }
        )
    return rows


def derive_public_record(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = as_list(as_dict(tables.get("PCE")).get("records"))
    for idx, rec_any in enumerate(records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        if not fields:
            continue
        rows.append(
            {
                "report_id": report_id,
                "record_type": "被执行记录",
                "record_date": field_value(get_field(fields, "PF03AR01")),
                "amount": field_value(get_field(fields, "PF03AJ01")),
                "status": field_value(get_field(fields, "PF03AQ03")),
                "description": field_value(get_field(fields, "PF03AQ02")),
                "source_json_path": f"tables.PCE.records[{idx}].fields",
                "pdf_page": None,
            }
        )
    return rows


def derive_objection_record(report_id: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = as_list(as_dict(tables.get("POS")).get("records"))
    for idx, rec_any in enumerate(records):
        rec = as_dict(rec_any)
        fields = as_dict(rec.get("fields"))
        if not fields:
            continue
        objection_text = str(field_value(get_field(fields, "PG010Q01")) or "").strip()
        status_label, status_code = labeled_value_and_code(get_field(fields, "PG010D03"))
        is_in_transit = any(x in objection_text for x in ("异议处理期", "异议处理中", "正处在异议处理期", "处理中"))
        is_info_missing_annotation = "信息缺失" in objection_text
        is_objection_candidate = is_in_transit or ("异议" in objection_text and not is_info_missing_annotation)
        annotation_category = "other_annotation"
        if is_info_missing_annotation:
            annotation_category = "information_missing_annotation"
        elif is_objection_candidate:
            annotation_category = "objection_candidate"
        rows.append(
            {
                "report_id": report_id,
                "objection_type": status_label,
                "objection_type_code": status_code,
                "related_account_id": None,
                "objection_text": objection_text or None,
                "add_date": field_value(get_field(fields, "PG010R01")),
                "status": status_label,
                "status_code": status_code,
                "annotation_category": annotation_category,
                "is_objection_candidate": is_objection_candidate,
                "is_in_transit": is_in_transit,
                "source_json_path": f"tables.POS.records[{idx}].fields",
                "pdf_page": None,
            }
        )
    return rows


def derive_core_tables(enriched_obj: dict[str, Any], report_id: str | None = None) -> dict[str, Any]:
    tables = as_dict(enriched_obj.get("tables"))
    source_files = as_list(enriched_obj.get("source_files"))
    rid = normalize_report_id(report_id or field_value(get_field(as_dict(as_dict(tables.get("PA01")).get("fields")), "PA01AI01")))

    out_tables = {
        "report_basic": derive_report_basic(rid, tables, source_files),
        "identity_info": derive_identity_info(rid, tables),
        "residence_info": derive_residence_info(rid, tables),
        "occupation_info": derive_occupation_info(rid, tables),
        "credit_summary": derive_credit_summary(rid, tables),
        "credit_account": derive_credit_account(rid, tables),
        "account_history": derive_account_history(rid, tables),
        "query_record": derive_query_record(rid, tables),
        "special_transaction": derive_special_transaction(rid, tables),
        "guarantee_record": derive_guarantee_record(rid, tables),
        "public_record": derive_public_record(rid, tables),
        "objection_record": derive_objection_record(rid, tables),
    }

    return {
        "schema_version": "core_tables.v3",
        "report_type": "individual",
        "generated_at": now_iso(),
        "report_id": rid,
        "table_stats": {k: len(v) for k, v in out_tables.items()},
        "tables": out_tables,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enriched",
        type=Path,
        default=Path("output/individual.standard.enriched_labels.json"),
        help="Path to enriched standard JSON.",
    )
    parser.add_argument(
        "--report-id",
        type=str,
        default="",
        help="Optional report_id override.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output/individual.core_tables.json"),
        help="Output path for derived core tables JSON.",
    )
    args = parser.parse_args()

    enriched_obj = json.loads(args.enriched.read_text(encoding="utf-8"))
    payload = derive_core_tables(enriched_obj, report_id=(args.report_id or None))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload.get("table_stats", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
