from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class StructuredQueryResult:
    answer: str
    confidence: str
    evidence_paths: List[str]
    verifier_status: str
    cannot_answer_reason: str
    query_plan: Dict[str, Any]
    query_result: Dict[str, Any]
    answer_mode: str = "structured_query"
    question_type: str = "STRUCTURED_QUERY"


def _app_dir() -> Path:
    return Path(__file__).resolve().parent


def load_semantic_assets() -> Dict[str, Any]:
    semantic_dir = _app_dir() / "semantic"
    schema_text = (semantic_dir / "schema_metadata.json").read_text(encoding="utf-8")
    metric_text = (semantic_dir / "metric_catalog.json").read_text(encoding="utf-8")
    import json

    return {"schema_metadata": json.loads(schema_text), "metric_catalog": json.loads(metric_text)}


def _parse_date(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    s = str(v).strip()
    fmts = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m", "%Y/%m")
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _shift_months(d: date, months: int) -> date:
    total_month = d.year * 12 + (d.month - 1) + months
    y = total_month // 12
    m = total_month % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _to_float(v: Any) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return 0.0


def _to_int(v: Any) -> int:
    if v in (None, ""):
        return 0
    try:
        return int(float(str(v).replace(",", "").strip()))
    except Exception:
        return 0


def _format_amount(v: float) -> str:
    return f"{v:,.2f}"


def _report_time(core_tables: Dict[str, Any]) -> Optional[datetime]:
    rows = ((core_tables.get("tables") or {}).get("report_basic") or [])
    if not rows:
        return None
    return _parse_date((rows[0] or {}).get("report_time"))


def _extract_window_months(q: str, *, default_months: int = 6) -> int:
    if any(x in q for x in ("近1个月", "最近1个月", "近一个月", "最近一个月", "1个月")):
        return 1
    if any(x in q for x in ("近3个月", "最近3个月", "三个月", "3个月")):
        return 3
    if any(x in q for x in ("近6个月", "最近6个月", "半年", "6个月")):
        return 6
    if any(x in q for x in ("近1年", "最近1年", "一年", "12个月")):
        return 12
    if any(x in q for x in ("近2年", "最近2年", "两年", "2年", "24个月")):
        return 24
    return default_months


def _extract_window_months_list(q: str, *, default_months: int = 6) -> List[int]:
    out: List[int] = []
    if any(x in q for x in ("近1个月", "最近1个月", "近一个月", "最近一个月", "1个月")):
        out.append(1)
    if any(x in q for x in ("近3个月", "最近3个月", "三个月", "3个月")):
        out.append(3)
    if any(x in q for x in ("近6个月", "最近6个月", "半年", "6个月")):
        out.append(6)
    if any(x in q for x in ("近1年", "最近1年", "一年", "12个月")):
        out.append(12)
    if any(x in q for x in ("近2年", "最近2年", "两年", "2年", "24个月")):
        out.append(24)
    if not out:
        out.append(default_months)
    # keep order stable and unique
    seen = set()
    uniq: List[int] = []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def _is_overdue_status_code(v: Any) -> bool:
    s = str(v or "").strip()
    return s in {"1", "2", "3", "4", "5", "6", "7"}


def _is_special_risk_status_code(v: Any) -> bool:
    s = str(v or "").strip().upper()
    return s in {"B", "D", "G"}


def _repay_type_code(row: Dict[str, Any]) -> str:
    code = str((row or {}).get("repay_type_code") or "").strip()
    if code:
        return code
    return str((row or {}).get("repay_type") or "").strip()


def _contains_any(q: str, keywords: List[str]) -> bool:
    return any(k in q for k in keywords)


def _parse_query_context(question: str) -> Dict[str, Any]:
    q = (question or "").strip()
    windows = _extract_window_months_list(q, default_months=6)
    domain = "general"
    if "逾期" in q or _contains_any(q, ["B/D/G", "B状态", "D状态", "G状态", "特殊风险状态", "呆账状态"]):
        domain = "overdue"
    elif "查询" in q:
        domain = "query"
    elif _contains_any(q, ["五级分类", "关注", "次级", "可疑", "损失"]):
        domain = "asset_quality"
    elif "异议" in q:
        domain = "objection"
    elif "担保" in q and "查询" not in q:
        domain = "guarantee"
    elif "信用卡" in q and _contains_any(q, ["个性化分期", "展期", "负面", "特殊交易"]):
        domain = "card_special"
    elif _contains_any(q, ["信用卡", "额度", "透支", "已用额度", "用卡"]):
        domain = "card"
    elif _contains_any(q, ["地址", "居住", "户籍", "通讯地址", "单位地址", "同省", "同市"]):
        domain = "identity"
    elif _contains_any(q, ["新增贷款", "结清贷款", "贷款", "借款金额", "未结清", "授信", "余额"]):
        domain = "loan_account"

    intent = "aggregate"
    if _contains_any(q, ["是否", "有无", "有没有"]):
        intent = "judge"
    if _contains_any(q, ["明细", "列出", "哪些", "清单", "逐条"]):
        intent = "detail"
    if _contains_any(q, ["汇总", "合计", "总额", "总数", "次数", "占比", "统计", "多少", "几"]):
        intent = "aggregate"

    scope = "auto"
    if _contains_any(q, ["概要", "汇总项", "首页", "最近一次查询"]):
        scope = "summary"
    if _contains_any(q, ["明细", "逐笔", "逐条"]):
        scope = "detail"
    if scope == "summary" and _contains_any(q, ["明细", "逐笔", "逐条"]):
        scope = "hybrid"
    return {"domain": domain, "intent": intent, "scope": scope, "time_window_months_list": windows}


def _month_serial(d: datetime) -> int:
    return d.year * 12 + d.month


def _make_plan(question: str) -> Optional[Dict[str, Any]]:
    q = (question or "").strip()
    if not q:
        return None
    ctx = _parse_query_context(q)
    scope = str(ctx.get("scope") or "auto")
    window_list = [int(x) for x in (ctx.get("time_window_months_list") or [6]) if int(x) > 0]
    if not window_list:
        window_list = [6]

    has_loan_amount_kw = any(x in q for x in ("借款金额", "贷款金额"))
    has_credit_total_kw = ("授信总额" in q)
    has_amount_kw = has_loan_amount_kw or has_credit_total_kw or ("金额" in q)
    has_balance_kw = any(x in q for x in ("余额", "已用额度", "透支余额", "透支"))
    has_count_kw = any(x in q for x in ("多少", "几", "数量", "账户数"))
    if "最近一次查询" in q:
        return {
            "domain": "query",
            "intent": "summary",
            "target_table": "credit_summary",
            "metric_name": "query_latest_pc05",
            "filters": {},
            "metrics": ["latest_query_date", "latest_query_org", "latest_query_reason"],
            "question_text": q,
        }
    if ("查询" in q) and (
        ("最近一个月" in q) or ("最近1个月" in q) or ("最近两年" in q) or ("最近2年" in q) or scope == "summary"
    ):
        return {
            "domain": "query",
            "intent": "summary",
            "target_table": "credit_summary",
            "metric_name": "query_summary_pc05",
            "filters": {},
            "metrics": ["pc05_summary"],
            "question_text": q,
        }
    if any(x in q for x in ("贷款审批查询机构数", "担保资格审查查询次数", "贷款审批查询次数")):
        return {
            "domain": "query",
            "intent": "summary",
            "target_table": "credit_summary",
            "metric_name": "query_summary_pc05",
            "filters": {},
            "metrics": ["pc05_summary"],
            "question_text": q,
        }
    if ctx.get("domain") == "overdue":
        if not _contains_any(q, ["近", "最近", "个月", "半年", "一年", "两年", "2年", "1年", "12", "24"]):
            window_list = [24]
        window_months = window_list[0]
        return {
            "domain": "overdue",
            "intent": str(ctx.get("intent") or "aggregate"),
            "target_table": "account_history",
            "metric_name": "overdue_multi_window_stats" if len(window_list) > 1 else "overdue_window_stats",
            "time_window_months": window_months,
            "time_window_months_list": window_list,
            "filters": {"overdue_total_gt": 0},
            "metrics": [
                "count_records",
                "sum_overdue_total",
                "sum_overdue_principal",
                "max_overdue_months",
                "max_consecutive_overdue_months",
            ],
            "question_text": q,
        }
    if ctx.get("domain") == "query" and (
        scope != "summary" or _contains_any(q, ["近", "最近", "个月", "半年", "一年", "两年", "2年", "1年"])
    ):
        window_months = window_list[0]
        return {
            "domain": "query",
            "intent": str(ctx.get("intent") or "aggregate"),
            "target_table": "query_record",
            "metric_name": "query_multi_window_stats" if len(window_list) > 1 else "query_window_stats",
            "time_window_months": window_months,
            "time_window_months_list": window_list,
            "filters": {},
            "metrics": ["count_records"],
            "question_text": q,
        }
    if ctx.get("domain") == "asset_quality":
        return {
            "domain": "asset_quality",
            "intent": "aggregate",
            "target_table": "credit_account",
            "metric_name": "five_classification_status",
            "filters": {},
            "metrics": ["abnormal_count"],
            "question_text": q,
        }
    if ctx.get("domain") == "objection":
        return {
            "domain": "objection",
            "intent": "aggregate",
            "target_table": "objection_record",
            "metric_name": "objection_summary",
            "filters": {},
            "metrics": ["count_objections", "count_in_transit"],
        }
    if ctx.get("domain") == "guarantee":
        return {
            "domain": "guarantee",
            "intent": "summary",
            "target_table": "credit_summary",
            "metric_name": "related_repayment_summary",
            "filters": {},
            "metrics": ["related_resp_count", "related_resp_balance"],
        }
    if ctx.get("domain") == "card_special":
        return {
            "domain": "card_special",
            "intent": "aggregate",
            "target_table": "special_transaction",
            "metric_name": "card_special_events",
            "filters": {"card_only": True},
            "metrics": ["count_negative_events", "count_installment", "count_extension"],
            "question_text": q,
        }
    if ctx.get("domain") == "identity" and _contains_any(q, ["同省", "同市", "居住地址", "单位地址", "通讯地址", "户籍地址"]):
        return {
            "domain": "identity",
            "intent": "summary",
            "target_table": "residence_info",
            "metric_name": "address_consistency_profile",
            "filters": {"latest_record_preferred": True},
            "metrics": ["has_same_province_city", "communication_address", "hukou_address", "latest_residence_address", "latest_work_address"],
            "question_text": q,
        }
    if ctx.get("domain") == "card" and any(x in q for x in ("额度", "使用率", "透支", "总额", "数量")):
        return {
            "domain": "card",
            "intent": "summary",
            "target_table": "credit_summary",
            "metric_name": "card_summary_pc02",
            "filters": {},
            "metrics": ["card_account_count", "card_credit_total", "card_used_total", "usage_rate"],
        }
    if ("新增贷款" in q) or (("结清贷款" in q) and ("未结清" not in q)):
        return {
            "domain": "loan",
            "intent": "window_stats",
            "target_table": "credit_account",
            "metric_name": "loan_change_windows",
            "filters": {"is_close": ("结清" in q)},
            "metrics": ["count_30_90_180", "amount_30_90_180"],
        }
    if _contains_any(q, ["贷款分类", "分布", "住房", "消费", "经营", "小额", "消费金融", "信托"]) and ("查询" not in q):
        return {
            "domain": "loan",
            "intent": "aggregate",
            "target_table": "credit_account",
            "metric_name": "loan_classification_summary",
            "filters": {"outstanding_only": ("未结清" in q)},
            "metrics": ["count_accounts", "sum_original_amount", "sum_balance"],
            "question_text": q,
        }
    if any(x in q for x in ("贷款总笔数", "总金额", "总余额", "授信情况")):
        return {
            "domain": "loan",
            "intent": "aggregate",
            "target_table": "credit_account",
            "metric_name": "loan_summary_core",
            "filters": {},
            "metrics": ["count_accounts", "sum_original_amount", "sum_balance"],
        }
    if "未结清" in q and has_loan_amount_kw and ("余额" in q) and any(x in q for x in ("账户数", "账户", "多少", "汇总", "三项", "三个")):
        return {
            "domain": "account",
            "intent": "aggregate",
            "target_table": "credit_summary",
            "metric_name": "outstanding_three_metrics_summary",
            "filters": {"dual_scope": True},
            "metrics": ["account_count", "balance_total", "loan_amount_total"],
            "question_text": q,
        }
    if "未结清" in q and has_loan_amount_kw:
        return {
            "domain": "account",
            "intent": "aggregate",
            "target_table": "credit_account",
            "metric_name": "outstanding_loan_amount_summary",
            "filters": {"detail_field_based": True},
            "metrics": ["sum_loan_amount"],
            "question_text": q,
        }
    if "未结清" in q and has_credit_total_kw:
        return {
            "domain": "account",
            "intent": "aggregate",
            "target_table": "credit_summary",
            "metric_name": "outstanding_loan_credit_total_summary",
            "filters": {"use_pc02_summary_first": True},
            "metrics": ["sum_credit_total"],
            "question_text": q,
        }
    if "未结清" in q and has_count_kw and (not has_balance_kw) and (not has_amount_kw):
        return {
            "domain": "account",
            "intent": "aggregate",
            "target_table": "credit_summary",
            "metric_name": "outstanding_account_count_summary",
            "filters": {"use_pc02_summary_first": True},
            "metrics": ["count_accounts"],
            "question_text": q,
        }
    if "未结清" in q and has_balance_kw:
        return {
            "domain": "account",
            "intent": "aggregate",
            "target_table": "credit_summary",
            "metric_name": "outstanding_balance_summary",
            "filters": {"use_pc02_summary_first": True},
            "metrics": ["sum_balance", "count_accounts"],
            "question_text": q,
        }
    if ("当前" in q and "余额" in q and "汇总" in q):
        return {
            "domain": "account",
            "intent": "aggregate",
            "target_table": "credit_account",
            "metric_name": "outstanding_balance_summary",
            "filters": {"outstanding_only": True},
            "metrics": ["count_accounts", "sum_balance", "sum_original_amount"],
        }
    return None


def _validate_plan(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> Optional[str]:
    if not plan:
        return "empty_plan"
    if not report_id:
        return "missing_report_id"
    tables = (core_tables.get("tables") or {})
    target = plan.get("target_table")
    if target not in {
        "account_history",
        "query_record",
        "credit_account",
        "credit_summary",
        "objection_record",
        "residence_info",
        "occupation_info",
        "identity_info",
        "special_transaction",
    }:
        return "target_table_not_allowed"
    if target not in tables:
        return "target_table_missing"
    if len(tables.get(target) or []) == 0:
        return "target_table_empty"
    return None


def _resolve_effective_report_id(core_tables: Dict[str, Any], report_id: str) -> str:
    tables = core_tables.get("tables") or {}
    if not report_id:
        return str(core_tables.get("report_id") or "")
    # If external report_id doesn't match row-level ids, fall back to the core table's own report_id.
    if str(core_tables.get("report_id") or "") == report_id:
        return report_id
    seen_ids = set()
    for tname in (
        "report_basic",
        "credit_summary",
        "credit_account",
        "account_history",
        "query_record",
        "objection_record",
        "identity_info",
        "residence_info",
        "occupation_info",
        "special_transaction",
    ):
        for row in (tables.get(tname) or []):
            rid = str((row or {}).get("report_id") or "")
            if rid:
                seen_ids.add(rid)
                if len(seen_ids) > 1:
                    break
        if len(seen_ids) > 1:
            break
    if len(seen_ids) == 1 and report_id not in seen_ids:
        return next(iter(seen_ids))
    return report_id


def _run_overdue_24m(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("account_history") or []
    rt = _report_time(core_tables) or datetime.now()
    window_months = int(plan.get("time_window_months") or 24)
    cutoff_date = _shift_months(rt.date(), -window_months)
    ordinary_filtered = []
    by_account_ordinary: Dict[str, List[Dict[str, Any]]] = {}
    special_filtered = []
    special_status_dist: Dict[str, int] = {}
    for r in rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        d = _parse_date(r.get("period_date"))
        if d is None:
            continue
        row_date = d.date()
        if row_date < cutoff_date or row_date > rt.date():
            continue
        overdue_total = _to_float(r.get("overdue_total"))
        overdue_months = _to_int(r.get("overdue_months"))
        repay_type = _repay_type_code(r)
        special_flag = _is_special_risk_status_code(repay_type)
        definite_non_overdue = repay_type in {"N", "C", "*", "#"}
        ordinary_flag = (
            _is_overdue_status_code(repay_type)
            or overdue_months > 0
            or (overdue_total > 0 and (not special_flag) and (not definite_non_overdue))
        )
        if ordinary_flag:
            ordinary_filtered.append(r)
            acc = str(r.get("account_id") or "")
            by_account_ordinary.setdefault(acc, []).append(r)
        if special_flag:
            special_filtered.append(r)
            key = repay_type.upper()
            special_status_dist[key] = special_status_dist.get(key, 0) + 1

    # 辅指标：账户内按月份计算最长连续普通逾期段（仅普通逾期1-7/逾期月数字段）
    max_consecutive_overdue = 0
    for acc_rows in by_account_ordinary.values():
        sorted_rows = sorted(
            acc_rows,
            key=lambda x: (_parse_date(x.get("period_date")) or datetime.min),
        )
        cur = 0
        best = 0
        prev_month = None
        for r in sorted_rows:
            overdue_months = _to_int(r.get("overdue_months"))
            repay_type = _repay_type_code(r)
            flag = _is_overdue_status_code(repay_type) or overdue_months > 0
            d = _parse_date(r.get("period_date"))
            month_no = _month_serial(d) if d else None
            is_consecutive = (prev_month is not None and month_no is not None and month_no - prev_month == 1)
            if flag:
                cur = cur + 1 if is_consecutive else 1
                best = max(best, cur)
            else:
                cur = 0
            prev_month = month_no
        max_consecutive_overdue = max(max_consecutive_overdue, best)

    # 主指标（业务口径）：最多连续逾期期数按还款状态1-7最大值取，
    # overdue_months 作为兜底（避免状态码缺失导致低估）。
    max_overdue_terms_by_status = 0
    for r in ordinary_filtered:
        repay_type = _repay_type_code(r)
        status_term = int(repay_type) if _is_overdue_status_code(repay_type) else 0
        overdue_month_term = _to_int(r.get("overdue_months"))
        max_overdue_terms_by_status = max(max_overdue_terms_by_status, status_term, overdue_month_term)

    count_records = len(ordinary_filtered)
    overdue_total_values = [r.get("overdue_total") for r in ordinary_filtered if r.get("overdue_total") not in (None, "")]
    overdue_principal_values = [r.get("overdue_principal") for r in ordinary_filtered if r.get("overdue_principal") not in (None, "")]
    sum_overdue_total = round(sum(_to_float(v) for v in overdue_total_values), 2)
    sum_overdue_principal = round(sum(_to_float(v) for v in overdue_principal_values), 2)
    max_overdue_months = max((_to_int(r.get("overdue_months")) for r in ordinary_filtered), default=0)
    result = {
        "window_months": window_months,
        "window_start_date": str(cutoff_date),
        "window_end_date": str(rt.date()),
        "ordinary_overdue_record_count": count_records,
        "ordinary_sum_overdue_total": sum_overdue_total,
        "ordinary_sum_overdue_principal": sum_overdue_principal,
        "ordinary_max_overdue_months": max_overdue_months,
        "ordinary_max_overdue_terms_by_status": max_overdue_terms_by_status,
        "ordinary_max_consecutive_overdue_months": max_consecutive_overdue,
        "ordinary_overdue_total_value_count": len(overdue_total_values),
        "ordinary_overdue_principal_value_count": len(overdue_principal_values),
        "special_risk_record_count": len(special_filtered),
        "special_risk_status_distribution": sorted(special_status_dist.items(), key=lambda x: x[1], reverse=True),
        "calculation_basis": "ordinary_and_special_dual_track",
    }
    special_text = (
        f"特殊风险状态（B/D/G）命中 {len(special_filtered)} 条"
        + (f"，分布：{'，'.join(f'{k}({v})' for k, v in sorted(special_status_dist.items(), key=lambda x: x[1], reverse=True))}" if special_status_dist else "")
        + "。"
    )
    if count_records == 0:
        answer = f"近{window_months}个月未检出普通逾期记录（1-7，按账户-月份口径）。{special_text}"
    else:
        if len(overdue_total_values) == 0 and len(overdue_principal_values) == 0:
            answer = (
                f"近{window_months}个月存在普通逾期记录，共 {count_records} 条（1-7，按账户-月份口径），"
                f"最多连续逾期期数（按状态最大值口径）为 {max_overdue_terms_by_status} 期；"
                f"补充：按自然月连续逾期段口径为 {max_consecutive_overdue}。"
                f"但当前逾期金额字段缺失，无法给出可靠金额合计。{special_text}"
            )
            return StructuredQueryResult(
                answer=answer,
                confidence="medium",
                evidence_paths=["tables.account_history[*].period_date", "tables.account_history[*].overdue_months", "tables.account_history[*].repay_type"],
                verifier_status="partially_answerable",
                cannot_answer_reason="overdue_amount_fields_missing",
                query_plan=plan,
                query_result=result,
            )
        if len(overdue_principal_values) == 0:
            answer = (
                f"近{window_months}个月存在普通逾期记录，共 {count_records} 条（1-7，按账户-月份口径），逾期金额合计 {sum_overdue_total:.2f}，"
                f"最多连续逾期期数（按状态最大值口径）为 {max_overdue_terms_by_status} 期；"
                f"补充：按自然月连续逾期段口径为 {max_consecutive_overdue}。"
                f"当前缺少逾期本金字段，无法给出可靠逾期本金合计。{special_text}"
            )
            return StructuredQueryResult(
                answer=answer,
                confidence="medium",
                evidence_paths=["tables.account_history[*].period_date", "tables.account_history[*].overdue_total", "tables.account_history[*].repay_type"],
                verifier_status="partially_answerable",
                cannot_answer_reason="overdue_principal_fields_missing",
                query_plan=plan,
                query_result=result,
            )
        answer = (
            f"近{window_months}个月存在普通逾期记录，共 {count_records} 条（1-7，按账户-月份口径），"
            f"逾期金额合计 {sum_overdue_total:.2f}，逾期本金合计 {sum_overdue_principal:.2f}，"
            f"最多连续逾期期数（按状态最大值口径）为 {max_overdue_terms_by_status} 期；"
            f"补充：按自然月连续逾期段口径为 {max_consecutive_overdue}。{special_text}"
        )
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=["tables.account_history[*].period_date", "tables.account_history[*].overdue_total", "tables.account_history[*].repay_type"],
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result=result,
    )


def _run_query_count_6m(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("query_record") or []
    rt = _report_time(core_tables) or datetime.now()
    report_date = rt.date()
    window_months = int(plan.get("time_window_months") or 6)
    cutoff_date = _shift_months(report_date, -window_months)
    filtered = []
    for r in rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        d = _parse_date(r.get("query_date"))
        if d is None:
            continue
        row_date = d.date()
        if row_date < cutoff_date or row_date > report_date:
            continue
        filtered.append(r)
    count_records = len(filtered)
    reason_dist: Dict[str, int] = {}
    small_loan_cnt = 0
    financing_guarantee_cnt = 0
    financing_lease_cnt = 0
    for r in filtered:
        key = str(r.get("query_reason") or "未知")
        reason_dist[key] = reason_dist.get(key, 0) + 1
        org_type = str(r.get("query_type") or "")
        org_name = str(r.get("query_institution") or "")
        text = f"{org_type}|{org_name}"
        if any(x in text for x in ("小额贷款", "小贷")):
            small_loan_cnt += 1
        if any(x in text for x in ("融资担保", "担保公司")):
            financing_guarantee_cnt += 1
        if any(x in text for x in ("融资租赁", "融资租凭", "租赁", "租凭")):
            financing_lease_cnt += 1
    sorted_reasons = sorted(reason_dist.items(), key=lambda x: x[1], reverse=True)
    pc05_rows = (core_tables.get("tables") or {}).get("credit_summary") or []
    pc05_metric: Dict[str, int] = {}
    for r in pc05_rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        key = str(r.get("metric_key") or "")
        if not key.startswith("PC05"):
            continue
        pc05_metric[key] = _to_int(r.get("metric_value"))

    # Reconcile PH01 detail stats vs PC05 summary stats where comparable.
    reason_cnt = {k: v for k, v in sorted_reasons}
    reconciliation = {"status": "not_comparable", "basis": "ph01_detail_scope_vs_pc05_summary_scope", "comparisons": []}
    if window_months == 1:
        detail_loan = int(reason_cnt.get("贷款审批", 0))
        detail_card = int(reason_cnt.get("信用卡审批", 0))
        detail_total_loan_card = detail_loan + detail_card
        summary_loan = int(pc05_metric.get("PC05BS03", 0))
        summary_card = int(pc05_metric.get("PC05BS04", 0))
        summary_self = int(pc05_metric.get("PC05BS05", 0))
        summary_total_loan_card = summary_loan + summary_card
        comps = [
            {"name": "loan_approval_count_1m", "detail": detail_loan, "summary": summary_loan, "delta": detail_loan - summary_loan},
            {"name": "card_approval_count_1m", "detail": detail_card, "summary": summary_card, "delta": detail_card - summary_card},
            {
                "name": "loan_card_total_1m",
                "detail": detail_total_loan_card,
                "summary": summary_total_loan_card,
                "delta": detail_total_loan_card - summary_total_loan_card,
            },
        ]
        mismatch = any(x.get("delta") != 0 for x in comps)
        reconciliation = {
            "status": "mismatch" if mismatch else "matched",
            "basis": "loan_and_card_reasons_comparable",
            "summary_self_query_count_1m": summary_self,
            "comparisons": comps,
        }
    elif window_months == 24:
        detail_post_loan = int(reason_cnt.get("贷后管理", 0))
        detail_guarantee = int(reason_cnt.get("担保资格审查", 0))
        detail_special_merchant = int(reason_cnt.get("特约商户实名审查", 0))
        summary_post_loan = int(pc05_metric.get("PC05BS06", 0))
        summary_guarantee = int(pc05_metric.get("PC05BS07", 0))
        summary_special_merchant = int(pc05_metric.get("PC05BS08", 0))
        comps = [
            {"name": "post_loan_count_24m", "detail": detail_post_loan, "summary": summary_post_loan, "delta": detail_post_loan - summary_post_loan},
            {"name": "guarantee_review_count_24m", "detail": detail_guarantee, "summary": summary_guarantee, "delta": detail_guarantee - summary_guarantee},
            {
                "name": "special_merchant_realname_count_24m",
                "detail": detail_special_merchant,
                "summary": summary_special_merchant,
                "delta": detail_special_merchant - summary_special_merchant,
            },
        ]
        mismatch = any(x.get("delta") != 0 for x in comps)
        reconciliation = {"status": "mismatch" if mismatch else "matched", "basis": "query_reason_comparable_subset", "comparisons": comps}

    result = {
        "query_count": count_records,
        "reason_distribution": sorted_reasons,
        "small_loan_query_count": small_loan_cnt,
        "financing_guarantee_query_count": financing_guarantee_cnt,
        "financing_lease_query_count": financing_lease_cnt,
        "time_window": {"type": "calendar_month", "months": window_months, "start_date": str(cutoff_date), "end_date": str(report_date)},
        "calculation_basis": "query_record_detail_scope",
        "summary_detail_reconciliation": reconciliation,
    }
    answer = f"按查询记录明细口径，近{window_months}个月查询次数为 {count_records} 次。"
    if sorted_reasons:
        answer += "原因分布为：" + "，".join(f"{k}({v})" for k, v in sorted_reasons) + "。"
    answer += f"其中小额贷款相关机构 {small_loan_cnt} 次，融资担保相关机构 {financing_guarantee_cnt} 次，融资租赁相关机构 {financing_lease_cnt} 次。"
    verifier_status = "answerable"
    cannot_answer_reason = ""
    if reconciliation.get("status") == "mismatch":
        verifier_status = "partially_answerable"
        cannot_answer_reason = "query_scope_mismatch_pc05_vs_ph01"
        answer += " 同时，与查询记录概要（PC05）可比口径存在差异，请以口径说明为准并人工核验。"
    return StructuredQueryResult(
        answer=answer,
        confidence="high" if verifier_status == "answerable" else "medium",
        evidence_paths=["tables.query_record[*].query_date", "tables.credit_summary[metric_key=PC05*]"],
        verifier_status=verifier_status,
        cannot_answer_reason=cannot_answer_reason,
        query_plan=plan,
        query_result=result,
    )


def _run_overdue_multi_window(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    windows = [int(x) for x in (plan.get("time_window_months_list") or []) if int(x) > 0]
    if not windows:
        windows = [24]
    details = []
    answer_parts = []
    worst_status = "answerable"
    worst_reason = ""
    for m in windows:
        sub_plan = dict(plan)
        sub_plan["metric_name"] = "overdue_window_stats"
        sub_plan["time_window_months"] = m
        r = _run_overdue_24m(sub_plan, core_tables, report_id)
        details.append({"months": m, "query_result": r.query_result, "answer": r.answer, "verifier_status": r.verifier_status, "cannot_answer_reason": r.cannot_answer_reason})
        answer_parts.append(f"近{m}个月：\n{r.answer}")
        if r.verifier_status == "not_answerable":
            worst_status = "not_answerable"
            worst_reason = r.cannot_answer_reason or worst_reason
        elif r.verifier_status == "partially_answerable" and worst_status == "answerable":
            worst_status = "partially_answerable"
            worst_reason = r.cannot_answer_reason or worst_reason
    return StructuredQueryResult(
        answer="\n\n".join(answer_parts),
        confidence="high" if worst_status == "answerable" else "medium",
        evidence_paths=["tables.account_history[*].period_date", "tables.account_history[*].repay_type", "tables.account_history[*].overdue_total"],
        verifier_status=worst_status,
        cannot_answer_reason=worst_reason,
        query_plan=plan,
        query_result={"windows": details, "calculation_basis": "account_month_detail_scope"},
    )


def _run_query_multi_window(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    windows = [int(x) for x in (plan.get("time_window_months_list") or []) if int(x) > 0]
    if not windows:
        windows = [6]
    details = []
    answer_parts = []
    worst_status = "answerable"
    worst_reason = ""
    for m in windows:
        sub_plan = dict(plan)
        sub_plan["metric_name"] = "query_window_stats"
        sub_plan["time_window_months"] = m
        r = _run_query_count_6m(sub_plan, core_tables, report_id)
        details.append({"months": m, "query_result": r.query_result, "answer": r.answer})
        answer_parts.append(f"近{m}个月：{r.query_result.get('query_count', 0)} 次")
        if r.verifier_status == "not_answerable":
            worst_status = "not_answerable"
            worst_reason = r.cannot_answer_reason or worst_reason
        elif r.verifier_status == "partially_answerable" and worst_status == "answerable":
            worst_status = "partially_answerable"
            worst_reason = r.cannot_answer_reason or worst_reason
    summary = "\n".join(answer_parts)
    return StructuredQueryResult(
        answer=f"按查询记录明细口径统计：\n{summary}",
        confidence="high" if worst_status == "answerable" else "medium",
        evidence_paths=["tables.query_record[*].query_date", "tables.query_record[*].query_reason"],
        verifier_status=worst_status,
        cannot_answer_reason=worst_reason,
        query_plan=plan,
        query_result={"windows": details, "calculation_basis": "query_record_detail_scope"},
    )


def _run_query_pc05_summary(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("credit_summary") or []
    matched = [r for r in rows if str(r.get("report_id") or "") == report_id and str(r.get("metric_key") or "").startswith("PC05")]
    metric = {str(r.get("metric_key")): r.get("metric_value") for r in matched}
    q = str(plan.get("question_text") or "")
    if str(plan.get("metric_name") or "") == "query_latest_pc05":
        reason = metric.get("PC05AQ01")
        if reason in (None, "", "--"):
            qrows = (core_tables.get("tables") or {}).get("query_record") or []
            latest = None
            latest_dt = None
            for r in qrows:
                if str(r.get("report_id") or "") != report_id:
                    continue
                d = _parse_date(r.get("query_date"))
                if d is None:
                    continue
                if latest_dt is None or d > latest_dt:
                    latest_dt = d
                    latest = r
            if latest is not None:
                reason = latest.get("query_reason") or reason
        answer = (
            f"最近一次查询日期为 {metric.get('PC05AR01', '--')}，"
            f"查询机构代码为 {metric.get('PC05AI01', '--')}，"
            f"查询原因为 {reason or '--'}。"
        )
    elif "贷款审批查询机构数" in q:
        answer = f"最近一个月贷款审批查询机构数为 {metric.get('PC05BS01', '--')}。"
    elif "担保资格审查查询次数" in q:
        answer = f"最近两年担保资格审查查询次数为 {metric.get('PC05BS07', '--')} 次。"
    elif "贷款审批查询次数" in q:
        answer = f"最近一个月贷款审批查询次数为 {metric.get('PC05BS03', '--')} 次。"
    else:
        answer = (
            "查询记录概要："
            f"最近1个月机构数-贷款审批 {metric.get('PC05BS01', '--')}、信用卡审批 {metric.get('PC05BS02', '--')}；"
            f"最近1个月查询次数-贷款审批 {metric.get('PC05BS03', '--')}、信用卡审批 {metric.get('PC05BS04', '--')}、本人查询 {metric.get('PC05BS05', '--')}；"
            f"最近2年查询次数-贷后管理 {metric.get('PC05BS06', '--')}、担保资格审查 {metric.get('PC05BS07', '--')}、特约商户实名审查 {metric.get('PC05BS08', '--')}。"
        )
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=["tables.credit_summary[metric_key=PC05*]"],
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result={"pc05_metrics": metric},
    )


def _run_five_classification(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    tables = core_tables.get("tables") or {}
    account_rows = tables.get("credit_account") or []
    guarantee_rows = tables.get("guarantee_record") or []
    summary_rows = tables.get("credit_summary") or []
    q = str(plan.get("question_text") or "")
    want_related_scope = any(x in q for x in ("相关还款责任", "担保责任", "为他人担保", "包含担保"))

    abnormal_labels = {"关注", "次级", "可疑", "损失"}

    personal_abnormal = []
    for r in account_rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        level = str(r.get("five_classification") or "").strip()
        if level in abnormal_labels:
            personal_abnormal.append(level)
    personal_counts: Dict[str, int] = {}
    for lv in personal_abnormal:
        personal_counts[lv] = personal_counts.get(lv, 0) + 1

    related_abnormal = []
    for r in guarantee_rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        level = str(r.get("five_classification") or "").strip()
        if level in abnormal_labels:
            related_abnormal.append(level)
    related_counts: Dict[str, int] = {}
    for lv in related_abnormal:
        related_counts[lv] = related_counts.get(lv, 0) + 1

    expected_related_count = _to_int(
        sum(
            _to_float(r.get("metric_value"))
            for r in summary_rows
            if str(r.get("report_id") or "") == report_id and str(r.get("metric_key") or "") == "PC02KS02"
        )
    )
    related_scope_reliable = not (expected_related_count > 0 and len(guarantee_rows) == 0)

    if personal_counts:
        personal_detail = "，".join(f"{k}{v}条" for k, v in sorted(personal_counts.items(), key=lambda x: x[1], reverse=True))
        personal_text = f"本人名下信贷账户口径：存在非正常五级分类，共 {len(personal_abnormal)} 条（{personal_detail}）。"
    else:
        personal_text = "本人名下信贷账户口径：未发现非正常五级分类。"

    if related_scope_reliable:
        if related_counts:
            related_detail = "，".join(f"{k}{v}条" for k, v in sorted(related_counts.items(), key=lambda x: x[1], reverse=True))
            related_text = f"相关还款责任口径：存在非正常五级分类，共 {len(related_abnormal)} 条（{related_detail}）。"
        else:
            related_text = "相关还款责任口径：未发现非正常五级分类。"
        related_status_note = "相关还款责任口径当前链路可用。"
    else:
        related_text = (
            "相关还款责任口径：当前链路不可靠，相关还款责任明细字段解析不足，"
            "无法给出可信的非正常五级分类结论。"
        )
        related_status_note = "相关还款责任口径当前链路不可靠。"

    answer = personal_text + " " + related_text

    if want_related_scope and (not related_scope_reliable):
        verifier_status = "partially_answerable"
        reason = "related_repayment_scope_parse_incomplete"
        confidence = "medium"
    else:
        verifier_status = "answerable"
        reason = ""
        confidence = "high"

    return StructuredQueryResult(
        answer=answer,
        confidence=confidence,
        evidence_paths=["tables.credit_account[*].five_classification", "tables.guarantee_record[*].five_classification", "tables.credit_summary[metric_key=PC02KS02]"],
        verifier_status=verifier_status,
        cannot_answer_reason=reason,
        query_plan=plan,
        query_result={
            "scope_personal_accounts": {
                "abnormal_count": len(personal_abnormal),
                "classification_distribution": personal_counts,
            },
            "scope_related_repayment": {
                "expected_related_account_count_summary": expected_related_count,
                "parsed_related_record_count": len(guarantee_rows),
                "abnormal_count": len(related_abnormal),
                "classification_distribution": related_counts,
                "reliable": related_scope_reliable,
                "note": related_status_note,
            },
            "default_scope": "personal_accounts_only",
        },
    )


def _run_objection_summary(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("objection_record") or []
    summary_rows = (core_tables.get("tables") or {}).get("credit_summary") or []
    matched = [r for r in rows if str(r.get("report_id") or "") == report_id]
    summary_matched = [
        r
        for r in summary_rows
        if str(r.get("report_id") or "") == report_id and str(r.get("metric_key") or "") == "PG010S01"
    ]
    summary_count = _to_int(sum(_to_float(r.get("metric_value")) for r in summary_matched))
    in_transit = []
    detail_candidates = []
    info_missing_annotations = 0
    for r in matched:
        if bool(r.get("is_in_transit")):
            in_transit.append(r)
        text = str(r.get("objection_text") or "")
        cat = str(r.get("annotation_category") or "")
        if cat == "information_missing_annotation" or ("信息缺失" in text):
            info_missing_annotations += 1
            continue
        if bool(r.get("is_objection_candidate")):
            detail_candidates.append(r)
            continue
        if any(x in text for x in ("处理期", "异议处理", "处理中", "在途", "异议")) and ("信息缺失" not in text):
            detail_candidates.append(r)
    detail_count = len(detail_candidates)
    if summary_count == 0 and detail_count == 0:
        answer = "未发现异议记录。"
        verifier_status = "answerable"
        reason = ""
    elif summary_count > 0 and detail_count == 0:
        answer = (
            f"异议信息概要显示 {summary_count} 笔，但明细表未解析到异议记录。"
            "该问题暂按概要口径可答，建议核查异议明细解析。"
        )
        verifier_status = "partially_answerable"
        reason = "objection_detail_missing_but_summary_exists"
    elif summary_count > 0 and detail_count != summary_count:
        answer = (
            f"异议信息存在口径差异：概要显示 {summary_count} 笔，明细解析到 {detail_count} 条，"
            f"其中命中“在处理期/处理中”关键词 {len(in_transit)} 条。"
            "建议以概要笔数作为总量口径，明细用于定位账户。"
        )
        verifier_status = "partially_answerable"
        reason = "objection_summary_detail_mismatch"
    elif in_transit:
        answer = f"存在异议记录 {detail_count} 条，其中命中“在处理期/处理中”关键词 {len(in_transit)} 条。"
        verifier_status = "partially_answerable"
        reason = "status_code_not_fully_standardized"
    else:
        answer = f"存在异议记录 {detail_count} 条，但未命中“在处理期/处理中”关键词。"
        verifier_status = "partially_answerable"
        reason = "in_transit_status_not_explicit"
    return StructuredQueryResult(
        answer=answer,
        confidence="high" if verifier_status == "answerable" else "medium",
        evidence_paths=["tables.credit_summary[metric_key=PG010S01]", "tables.objection_record[*].objection_text"],
        verifier_status=verifier_status,
        cannot_answer_reason=reason,
        query_plan=plan,
        query_result={
            "objection_count_summary": summary_count,
            "objection_count_detail_candidate": detail_count,
            "in_transit_count_detail_keyword": len(in_transit),
            "information_missing_annotation_count_detail": info_missing_annotations,
            "calculation_basis": "summary_and_detail_reconciled_scope",
        },
    )


def _run_related_repayment_summary(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("credit_summary") or []
    matched = [r for r in rows if str(r.get("report_id") or "") == report_id]
    count = _to_int(sum(_to_float(r.get("metric_value")) for r in matched if str(r.get("metric_key")) == "PC02KS02"))
    amount = round(sum(_to_float(r.get("metric_value")) for r in matched if str(r.get("metric_key")) == "PC02KJ01"), 2)
    balance = round(sum(_to_float(r.get("metric_value")) for r in matched if str(r.get("metric_key")) == "PC02KJ02"), 2)
    answer = f"相关还款责任（担保/代偿相关）账户数 {count}，还款责任金额 {_format_amount(amount)} 元，余额 {_format_amount(balance)} 元。"
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=["tables.credit_summary[metric_key=PC02KS02]", "tables.credit_summary[metric_key=PC02KJ01]", "tables.credit_summary[metric_key=PC02KJ02]"],
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result={"related_repayment_count": count, "related_repayment_amount": amount, "related_repayment_balance": balance},
    )


def _run_card_summary(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("credit_summary") or []
    matched = [r for r in rows if str(r.get("report_id") or "") == report_id]
    card_account_count = _to_int(
        sum(
            _to_float(r.get("metric_value"))
            for r in matched
            if str(r.get("metric_key")) in {"PC02HS02", "PC02IS02"}
        )
    )
    card_credit_total = round(
        sum(
            _to_float(r.get("metric_value"))
            for r in matched
            if str(r.get("metric_key")) in {"PC02HJ01", "PC02IJ01"}
        ),
        2,
    )
    card_used_total = round(
        sum(
            _to_float(r.get("metric_value"))
            for r in matched
            if str(r.get("metric_key")) in {"PC02HJ04", "PC02IJ04"}
        ),
        2,
    )
    usage_rate = round((card_used_total / card_credit_total) * 100, 2) if card_credit_total > 0 else None
    if usage_rate is None:
        answer = f"信用卡账户数 {card_account_count}，已用/透支余额 {_format_amount(card_used_total)} 元；授信总额缺失或为0，无法计算额度使用率。"
        verifier_status = "partially_answerable"
        reason = "card_credit_total_missing_or_zero"
    else:
        answer = (
            f"信用卡账户数 {card_account_count}，授信总额 {_format_amount(card_credit_total)} 元，"
            f"已用/透支余额 {_format_amount(card_used_total)} 元，额度使用率约 {usage_rate:.2f}%。"
        )
        verifier_status = "answerable"
        reason = ""
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=["tables.credit_summary[metric_key=PC02HS02]", "tables.credit_summary[metric_key=PC02IS02]", "tables.credit_summary[metric_key=PC02HJ01]", "tables.credit_summary[metric_key=PC02IJ01]", "tables.credit_summary[metric_key=PC02HJ04]", "tables.credit_summary[metric_key=PC02IJ04]"],
        verifier_status=verifier_status,
        cannot_answer_reason=reason,
        query_plan=plan,
        query_result={"card_account_count": card_account_count, "card_credit_total": card_credit_total, "card_used_total": card_used_total, "usage_rate_pct": usage_rate},
    )


def _is_loan_category(account_category: str) -> bool:
    return account_category in {"非循环贷账户", "循环额度下分账户", "循环贷账户"}


def _run_loan_summary_core(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("credit_account") or []
    filtered = [r for r in rows if str(r.get("report_id") or "") == report_id and _is_loan_category(str(r.get("account_category") or ""))]
    count_accounts = len(filtered)
    sum_original = round(sum(_to_float(r.get("original_amount")) for r in filtered), 2)
    sum_balance = round(sum(_to_float(r.get("balance")) for r in filtered), 2)
    answer = f"贷款账户共 {count_accounts} 笔，借款金额合计 {_format_amount(sum_original)} 元，余额合计 {_format_amount(sum_balance)} 元。"
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=["tables.credit_account[*].account_category", "tables.credit_account[*].original_amount", "tables.credit_account[*].balance"],
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result={"loan_account_count": count_accounts, "loan_amount_total": sum_original, "loan_balance_total": sum_balance},
    )


def _run_loan_classification_summary(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("credit_account") or []
    outstanding_only = bool((plan.get("filters") or {}).get("outstanding_only"))
    agg: Dict[str, Dict[str, float]] = {}
    for r in rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        if not bool(r.get("is_loan_account")):
            continue
        if outstanding_only and (not bool(r.get("is_outstanding_account"))):
            continue
        cls = str(r.get("loan_classification") or "其他贷款")
        agg.setdefault(cls, {"count": 0.0, "sum_original_amount": 0.0, "sum_balance": 0.0})
        agg[cls]["count"] += 1
        agg[cls]["sum_original_amount"] += _to_float(r.get("original_amount"))
        agg[cls]["sum_balance"] += _to_float(r.get("balance"))

    ranked = sorted(
        [
            {
                "loan_classification": k,
                "account_count": int(v["count"]),
                "sum_original_amount": round(v["sum_original_amount"], 2),
                "sum_balance": round(v["sum_balance"], 2),
            }
            for k, v in agg.items()
        ],
        key=lambda x: (x["sum_original_amount"], x["sum_balance"], x["account_count"]),
        reverse=True,
    )
    total_count = sum(x["account_count"] for x in ranked)
    total_amount = round(sum(x["sum_original_amount"] for x in ranked), 2)
    total_balance = round(sum(x["sum_balance"] for x in ranked), 2)
    scope_text = "未结清贷款口径" if outstanding_only else "贷款全量口径（含已结清）"
    if ranked:
        top_text = "；".join(
            f"{x['loan_classification']}：{x['account_count']}个/{_format_amount(x['sum_original_amount'])}元/余额{_format_amount(x['sum_balance'])}元"
            for x in ranked[:8]
        )
        answer = (
            f"按{scope_text}统计：贷款账户共 {total_count} 个，借款金额合计 {_format_amount(total_amount)} 元，余额合计 {_format_amount(total_balance)} 元。"
            f"分类明细：{top_text}。"
        )
    else:
        answer = f"按{scope_text}统计，未命中可用贷款分类记录。"
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=["tables.credit_account[*].loan_classification", "tables.credit_account[*].original_amount", "tables.credit_account[*].balance"],
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result={
            "scope": "outstanding_only" if outstanding_only else "all_loans",
            "total_account_count": total_count,
            "total_original_amount": total_amount,
            "total_balance": total_balance,
            "classification_breakdown": ranked,
            "calculation_basis": "credit_account_derived_classification",
        },
    )


def _extract_province_city(addr: str) -> tuple[str, str]:
    text = str(addr or "").strip()
    if not text or "*" in text or "******" in text:
        return "", ""
    if "省" in text:
        prov = text.split("省", 1)[0] + "省"
        rest = text.split("省", 1)[1]
    elif "市" in text:
        prov = text.split("市", 1)[0] + "市"
        rest = text.split("市", 1)[1]
    else:
        return "", ""
    city = ""
    if "市" in rest:
        city = rest.split("市", 1)[0] + "市"
    elif "州" in rest:
        city = rest.split("州", 1)[0] + "州"
    return prov, city


def _latest_row_by_date(rows: List[Dict[str, Any]], date_key: str) -> Optional[Dict[str, Any]]:
    best = None
    best_dt = None
    for r in rows:
        d = _parse_date(r.get(date_key))
        if best_dt is None or (d is not None and d > best_dt):
            best = r
            best_dt = d
    return best


def _run_address_consistency_profile(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    tables = core_tables.get("tables") or {}
    id_rows = [r for r in (tables.get("identity_info") or []) if str(r.get("report_id") or "") == report_id]
    res_rows = [r for r in (tables.get("residence_info") or []) if str(r.get("report_id") or "") == report_id]
    occ_rows = [r for r in (tables.get("occupation_info") or []) if str(r.get("report_id") or "") == report_id]
    id_row = id_rows[0] if id_rows else {}
    latest_res = _latest_row_by_date(res_rows, "update_date") or {}
    latest_occ = _latest_row_by_date(occ_rows, "update_date") or {}

    comm_addr = str(id_row.get("communication_address") or "")
    hukou_addr = str(id_row.get("hukou_address") or "")
    residence_addr = str(latest_res.get("residence_address") or "")
    work_addr = str(latest_occ.get("company_address") or "")

    r_prov, r_city = _extract_province_city(residence_addr)
    w_prov, w_city = _extract_province_city(work_addr)
    same = None
    if r_prov and w_prov:
        if r_city and w_city:
            same = (r_prov == w_prov and r_city == w_city)
        else:
            same = (r_prov == w_prov)

    if same is None:
        answer = (
            f"通讯地址：{comm_addr}；户籍地址：{hukou_addr}；居住地址（最新）：{residence_addr}；单位地址（最新）：{work_addr}。"
            "地址存在脱敏或缺失，无法准确判断是否同省市。"
        )
        status = "partially_answerable"
        reason = "address_masked_or_incomplete"
    elif same:
        answer = (
            f"通讯地址：{comm_addr}；户籍地址：{hukou_addr}；居住地址（最新）：{residence_addr}；单位地址（最新）：{work_addr}。"
            "居住地址与单位地址在同一省市。"
        )
        status = "answerable"
        reason = ""
    else:
        answer = (
            f"通讯地址：{comm_addr}；户籍地址：{hukou_addr}；居住地址（最新）：{residence_addr}；单位地址（最新）：{work_addr}。"
            "居住地址与单位地址不在同一省市。"
        )
        status = "answerable"
        reason = ""
    return StructuredQueryResult(
        answer=answer,
        confidence="high" if status == "answerable" else "medium",
        evidence_paths=["tables.identity_info", "tables.residence_info[*].residence_address", "tables.occupation_info[*].company_address"],
        verifier_status=status,
        cannot_answer_reason=reason,
        query_plan=plan,
        query_result={
            "communication_address": comm_addr,
            "hukou_address": hukou_addr,
            "latest_residence_address": residence_addr,
            "latest_work_address": work_addr,
            "residence_province_city": {"province": r_prov, "city": r_city},
            "work_province_city": {"province": w_prov, "city": w_city},
            "same_province_city": same,
            "calculation_basis": "latest_residence_and_latest_occupation_address",
        },
    )


def _run_card_special_events(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("special_transaction") or []
    card_only = bool((plan.get("filters") or {}).get("card_only"))
    filtered = []
    for r in rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        if card_only and (not bool(r.get("is_card_related"))):
            continue
        filtered.append(r)
    neg = [r for r in filtered if bool(r.get("is_negative_event"))]
    install = [r for r in filtered if bool(r.get("has_personalized_installment"))]
    ext = [r for r in filtered if bool(r.get("has_extension"))]
    if neg:
        answer = (
            f"近两年检测到信用卡相关特殊事件 {len(neg)} 条，其中个性化分期/专项分期 {len(install)} 条，展期 {len(ext)} 条。"
            "可继续展开明细账户与日期。"
        )
        status = "answerable"
    else:
        answer = "当前未检测到明确的信用卡个性化分期/展期等负面特殊事件。"
        status = "partially_answerable"
    sample = [
        {
            "account_id": r.get("account_id"),
            "special_type": r.get("special_type"),
            "special_description": r.get("special_description"),
            "special_date": r.get("special_date"),
        }
        for r in neg[:20]
    ]
    return StructuredQueryResult(
        answer=answer,
        confidence="high" if neg else "medium",
        evidence_paths=["tables.special_transaction[*].special_type", "tables.special_transaction[*].special_description", "tables.special_transaction[*].special_date"],
        verifier_status=status,
        cannot_answer_reason="" if neg else "no_explicit_card_special_negative_event",
        query_plan=plan,
        query_result={
            "negative_event_count": len(neg),
            "personalized_installment_count": len(install),
            "extension_count": len(ext),
            "sample_events": sample,
            "calculation_basis": "special_transaction_card_scope",
        },
    )


def _run_loan_change_windows(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("credit_account") or []
    rt = _report_time(core_tables) or datetime.now()
    is_close = bool((plan.get("filters") or {}).get("is_close"))
    date_field = "close_date" if is_close else "open_date"
    windows = [30, 90, 180]
    stats: Dict[int, Dict[str, float]] = {w: {"count": 0, "amount": 0.0} for w in windows}
    for r in rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        if not _is_loan_category(str(r.get("account_category") or "")):
            continue
        d = _parse_date(r.get(date_field))
        if d is None:
            continue
        amt = _to_float(r.get("original_amount"))
        for w in windows:
            if (rt - timedelta(days=w)).date() <= d.date() <= rt.date():
                stats[w]["count"] += 1
                stats[w]["amount"] += amt
    label = "结清贷款" if is_close else "新增贷款"
    answer = (
        f"{label}统计：近1个月 {int(stats[30]['count'])} 笔/{_format_amount(stats[30]['amount'])} 元，"
        f"近3个月 {int(stats[90]['count'])} 笔/{_format_amount(stats[90]['amount'])} 元，"
        f"近6个月 {int(stats[180]['count'])} 笔/{_format_amount(stats[180]['amount'])} 元。"
    )
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=[f"tables.credit_account[*].{date_field}", "tables.credit_account[*].original_amount"],
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result={"window_stats": stats, "date_field": date_field},
    )


def _run_outstanding_loan_amount_detail(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    rows = (core_tables.get("tables") or {}).get("credit_account") or []
    nr_rows = []
    sub_rows = []
    nr_rows_for_amount = []
    sub_rows_for_amount = []
    for r in rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        cat = str(r.get("account_category") or "")
        close_date = r.get("close_date")
        status = str(r.get("account_status") or "")
        # 借款金额字段口径：未结清（close_date为空），按明细借款金额字段统计
        if close_date not in (None, ""):
            continue
        if cat == "非循环贷账户":
            nr_rows.append(r)
            if status not in {"呆账", "核销"}:
                nr_rows_for_amount.append(r)
        elif cat == "循环额度下分账户":
            sub_rows.append(r)
            if status not in {"呆账", "核销"}:
                sub_rows_for_amount.append(r)

    def s(rows_any: List[Dict[str, Any]]) -> float:
        return round(sum(_to_float(x.get("original_amount")) for x in rows_any), 2)

    nr_cnt, nr_amt = len(nr_rows), s(nr_rows_for_amount)
    sub_cnt, sub_amt = len(sub_rows), s(sub_rows_for_amount)
    # 当前余额按 balance 字段汇总
    nr_bal = round(sum(_to_float(x.get("balance")) for x in nr_rows), 2)
    sub_bal = round(sum(_to_float(x.get("balance")) for x in sub_rows), 2)
    total_cnt, total_amt = nr_cnt + sub_cnt, round(nr_amt + sub_amt, 2)
    total_bal = round(nr_bal + sub_bal, 2)
    answer = (
        f"按借款金额字段口径统计：当前有借款金额字段的未结清贷款账户共 {total_cnt} 个，当前余额合计 {_format_amount(total_bal)} 元，借款金额合计 {_format_amount(total_amt)} 元。"
        f"其中非循环贷账户 {nr_cnt} 个，借款金额 {_format_amount(nr_amt)} 元；"
        f"循环额度下分账户 {sub_cnt} 个，借款金额 {_format_amount(sub_amt)} 元。"
    )
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=["tables.credit_account[*].account_category", "tables.credit_account[*].original_amount", "tables.credit_account[*].close_date", "tables.credit_account[*].account_status"],
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result={
            "non_revolving_account_count": nr_cnt,
            "non_revolving_loan_amount": nr_amt,
            "non_revolving_balance": nr_bal,
            "sub_account_count": sub_cnt,
            "sub_account_loan_amount": sub_amt,
            "sub_account_balance": sub_bal,
            "total_loan_account_count": total_cnt,
            "total_loan_balance": total_bal,
            "total_loan_amount": total_amt,
            "calculation_basis": "credit_account_original_amount_detail_scope",
        },
    )


def _run_outstanding_three_metrics(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    balance_plan = dict(plan)
    balance_plan["metric_name"] = "outstanding_balance_summary"
    loan_plan = dict(plan)
    loan_plan["metric_name"] = "outstanding_loan_amount_summary"
    bal = _run_outstanding_balance(balance_plan, core_tables, report_id)
    loan = _run_outstanding_loan_amount_detail(loan_plan, core_tables, report_id)
    b = bal.query_result
    l = loan.query_result
    answer = (
        f"截至报告时间，当前未结清负债账户共 {int(b.get('outstanding_account_count_total', 0))} 个，"
        f"余额/已用额度/透支余额合计 {_format_amount(_to_float(b.get('outstanding_account_balance_total')))} 元；"
        f"其中有借款金额字段的未结清贷款账户共 {int(l.get('total_loan_account_count', 0))} 个，"
        f"当前余额合计 {_format_amount(_to_float(l.get('total_loan_balance')))} 元，借款金额合计 {_format_amount(_to_float(l.get('total_loan_amount')))} 元。"
    )
    return StructuredQueryResult(
        answer=answer,
        confidence="high",
        evidence_paths=list(dict.fromkeys(bal.evidence_paths + loan.evidence_paths)),
        verifier_status="answerable",
        cannot_answer_reason="",
        query_plan=plan,
        query_result={
            "scope_all_outstanding": b,
            "scope_loan_amount_field": l,
            "calculation_basis": "dual_scope_summary_v1",
        },
    )


def _run_outstanding_balance(plan: Dict[str, Any], core_tables: Dict[str, Any], report_id: str) -> StructuredQueryResult:
    summary_rows = (core_tables.get("tables") or {}).get("credit_summary") or []
    # 按报告说明口径优先使用 PC02 信贷交易授信及负债信息概要（未结清/未销户）
    if summary_rows:
        matched = [r for r in summary_rows if str(r.get("report_id") or "") == report_id]
        has_pc02 = any(str(r.get("metric_key") or "").startswith("PC02") for r in matched)
        if matched and has_pc02:
            def sum_metric(metric_key: str) -> float:
                return round(
                    sum(_to_float(r.get("metric_value")) for r in matched if str(r.get("metric_key") or "") == metric_key),
                    2,
                )

            # Account-balance components under PC02 summary
            compensation_balance = round(sum_metric("PC02BJ01"), 2)  # 被追偿余额
            loan_balance = round(sum_metric("PC02EJ02") + sum_metric("PC02FJ02") + sum_metric("PC02GJ02"), 2)
            card_used = round(sum_metric("PC02HJ04") + sum_metric("PC02IJ04"), 2)
            loan_amount_total = round(sum_metric("PC02EJ01") + sum_metric("PC02FJ01") + sum_metric("PC02GJ01"), 2)
            card_credit_total = round(sum_metric("PC02HJ01") + sum_metric("PC02IJ01"), 2)
            related_resp_balance = round(sum_metric("PC02KJ02"), 2)
            related_resp_amount = round(sum_metric("PC02KJ01"), 2)
            # “未结清账户余额”口径：被追偿 + 借贷账户 + 卡账户，不含“相关还款责任”
            account_balance_total = round(compensation_balance + loan_balance + card_used, 2)
            # “相关负债”扩展口径：在账户余额基础上加相关还款责任余额
            liability_balance_total = round(account_balance_total + related_resp_balance, 2)

            # Account counts under unsettled/uncancelled summary scopes
            compensation_account_count = _to_int(sum_metric("PC02BS01"))
            credit_account_count = _to_int(sum_metric("PC02ES02") + sum_metric("PC02FS02") + sum_metric("PC02GS02") + sum_metric("PC02HS02") + sum_metric("PC02IS02"))
            account_count_total = compensation_account_count + credit_account_count
            related_resp_count = _to_int(sum_metric("PC02KS02"))
            total_obligation_count = account_count_total + related_resp_count

            result = {
                "outstanding_account_balance_total": account_balance_total,
                "outstanding_compensation_balance": compensation_balance,
                "outstanding_credit_account_balance": loan_balance + card_used,
                "outstanding_loan_amount_total": loan_amount_total,
                "outstanding_card_credit_total": card_credit_total,
                "outstanding_compensation_account_count": compensation_account_count,
                "outstanding_credit_account_count": credit_account_count,
                "outstanding_account_count_total": account_count_total,
                "related_repayment_responsibility_balance": related_resp_balance,
                "related_repayment_responsibility_amount": related_resp_amount,
                "related_repayment_responsibility_count": related_resp_count,
                "liability_balance_total_including_related_responsibility": liability_balance_total,
                "total_obligation_account_count": total_obligation_count,
                "calculation_basis": "pc02_summary_unsettled_or_uncancelled",
                "report_note_alignment": "report_note_7",
            }
            metric_name = str(plan.get("metric_name") or "")
            if metric_name == "outstanding_account_count_summary":
                answer = (
                    "按报告说明口径（信贷交易授信及负债信息概要=未结清/未销户）统计："
                    f"当前未结清/未销户账户数为 {account_count_total} 个（含被追偿 {compensation_account_count} 个 + 借贷/卡账户 {credit_account_count} 个）。"
                    f"若按相关负债口径（含相关还款责任），则为 {total_obligation_count} 个。"
                )
            elif metric_name == "outstanding_loan_credit_total_summary":
                answer = (
                    "按报告说明口径（信贷交易授信及负债信息概要=未结清/未销户）统计："
                    f"当前未结清借贷账户借款金额（授信总额）合计 {_format_amount(loan_amount_total)} 元。"
                    f"其中非循环贷/循环额度下分账户/循环贷分别来自 PC02EJ01、PC02FJ01、PC02GJ01。"
                    f"该口径不包含被追偿余额和相关还款责任金额。"
                )
            else:
                answer = (
                    f"按报告说明口径（信贷交易授信及负债信息概要=未结清/未销户）统计："
                    f"当前未结清/未销户账户余额合计 {_format_amount(account_balance_total)} 元。"
                    f"其中被追偿余额 {_format_amount(compensation_balance)} 元，借贷+卡账户余额 {_format_amount(loan_balance + card_used)} 元。"
                    f"若按相关负债口径（含相关还款责任），则为 {_format_amount(liability_balance_total)} 元。"
                )
            return StructuredQueryResult(
                answer=answer,
                confidence="high",
                evidence_paths=[
                    "tables.credit_summary[metric_key=PC02EJ02]",
                    "tables.credit_summary[metric_key=PC02FJ02]",
                    "tables.credit_summary[metric_key=PC02GJ02]",
                    "tables.credit_summary[metric_key=PC02HJ04]",
                    "tables.credit_summary[metric_key=PC02IJ04]",
                    "tables.credit_summary[metric_key=PC02KJ02]",
                ],
                verifier_status="answerable",
                cannot_answer_reason="",
                query_plan=plan,
                query_result=result,
            )

    rows = (core_tables.get("tables") or {}).get("credit_account") or []
    filtered = []
    for r in rows:
        if str(r.get("report_id") or "") != report_id:
            continue
        status = str(r.get("account_status") or "")
        close_date = r.get("close_date")
        is_outstanding = ("结清" not in status) if status else (close_date in (None, ""))
        if is_outstanding:
            filtered.append(r)
    count_accounts = len(filtered)
    sum_balance = round(sum(_to_float(r.get("balance")) for r in filtered), 2)
    sum_original_amount = round(sum(_to_float(r.get("original_amount")) for r in filtered), 2)
    result = {
        "outstanding_account_count": count_accounts,
        "sum_balance": sum_balance,
        "sum_original_amount": sum_original_amount,
    }
    answer = (
        f"按未结清代理口径统计，当前账户数 {count_accounts}，"
        f"余额合计 {sum_balance:.2f}，借款金额合计 {sum_original_amount:.2f}。"
    )
    return StructuredQueryResult(
        answer=answer,
        confidence="medium",
        evidence_paths=["tables.credit_account[*].account_status", "tables.credit_account[*].balance"],
        verifier_status="partially_answerable",
        cannot_answer_reason="outstanding_status_uses_proxy_rule",
        query_plan=plan,
        query_result=result,
    )


def try_structured_query(*, question: str, core_tables: Optional[Dict[str, Any]], report_id: str) -> Optional[Dict[str, Any]]:
    if not core_tables:
        return None
    effective_report_id = _resolve_effective_report_id(core_tables, report_id)
    plan = _make_plan(question)
    if not plan:
        return None
    invalid = _validate_plan(plan, core_tables, effective_report_id)
    if invalid:
        return {
            "answer": "当前问题已识别为结构化查询，但查询计划未通过校验。",
            "confidence": "low",
            "evidence_paths": [],
            "verifier_status": "not_answerable",
            "cannot_answer_reason": invalid,
            "query_plan": plan,
            "query_result": {},
            "answer_mode": "structured_query",
            "question_type": "STRUCTURED_QUERY",
        }

    metric_name = str(plan.get("metric_name") or "")
    if metric_name == "overdue_window_stats":
        r = _run_overdue_24m(plan, core_tables, effective_report_id)
    elif metric_name == "overdue_multi_window_stats":
        r = _run_overdue_multi_window(plan, core_tables, effective_report_id)
    elif metric_name == "query_window_stats":
        r = _run_query_count_6m(plan, core_tables, effective_report_id)
    elif metric_name == "query_multi_window_stats":
        r = _run_query_multi_window(plan, core_tables, effective_report_id)
    elif metric_name in {"query_summary_pc05", "query_latest_pc05"}:
        r = _run_query_pc05_summary(plan, core_tables, effective_report_id)
    elif metric_name == "five_classification_status":
        r = _run_five_classification(plan, core_tables, effective_report_id)
    elif metric_name == "objection_summary":
        r = _run_objection_summary(plan, core_tables, effective_report_id)
    elif metric_name == "related_repayment_summary":
        r = _run_related_repayment_summary(plan, core_tables, effective_report_id)
    elif metric_name == "card_summary_pc02":
        r = _run_card_summary(plan, core_tables, effective_report_id)
    elif metric_name == "card_special_events":
        r = _run_card_special_events(plan, core_tables, effective_report_id)
    elif metric_name == "loan_summary_core":
        r = _run_loan_summary_core(plan, core_tables, effective_report_id)
    elif metric_name == "loan_classification_summary":
        r = _run_loan_classification_summary(plan, core_tables, effective_report_id)
    elif metric_name == "loan_change_windows":
        r = _run_loan_change_windows(plan, core_tables, effective_report_id)
    elif metric_name == "address_consistency_profile":
        r = _run_address_consistency_profile(plan, core_tables, effective_report_id)
    elif metric_name == "outstanding_three_metrics_summary":
        r = _run_outstanding_three_metrics(plan, core_tables, effective_report_id)
    elif metric_name == "outstanding_loan_amount_summary":
        r = _run_outstanding_loan_amount_detail(plan, core_tables, effective_report_id)
    elif metric_name in {"outstanding_balance_summary", "outstanding_account_count_summary", "outstanding_loan_credit_total_summary"}:
        r = _run_outstanding_balance(plan, core_tables, effective_report_id)
    else:
        return None

    return {
        "answer": r.answer,
        "confidence": r.confidence,
        "evidence_paths": r.evidence_paths,
        "verifier_status": r.verifier_status,
        "cannot_answer_reason": r.cannot_answer_reason,
        "query_plan": r.query_plan,
        "query_result": r.query_result,
        "answer_mode": r.answer_mode,
        "question_type": r.question_type,
        "effective_report_id": effective_report_id,
    }
