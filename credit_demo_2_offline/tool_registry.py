from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from prompt_templates import OUT_OF_SCOPE_TEMPLATE


QUESTION_TYPES = [
    "OUT_OF_SCOPE",
    "INDV_OVERDUE_ANALYSIS",
    "INDV_CREDIT_LOAN_SUMMARY",
    "INDV_CREDIT_LOAN_CHANGE",
    "INDV_CREDIT_CARD_SUMMARY",
    "INDV_CREDIT_CARD_RISK_EVENTS",
    "INDV_IDENTITY_ADDRESS_PROFILE",
    "INDV_EMPLOYER_KEYWORD_RISK",
    "INDV_QUERY_ANALYSIS",
    "INDV_FIVE_LEVEL_CLASSIFICATION",
    "INDV_GUARANTEE_ANALYSIS",
    "INDV_DISPUTE_STATUS",
]


def classify_question_local(question: str) -> str:
    q = (question or "").strip()
    if not q:
        return "OUT_OF_SCOPE"
    greeting_tokens = {"你好", "您好", "hi", "hello", "在吗", "有人吗", "早上好", "下午好", "晚上好"}
    if q.lower() in greeting_tokens or any(tok in q.lower() for tok in ["你好", "您好", "hello", "hi"]):
        return "OUT_OF_SCOPE"
    domain_keywords = [
        "征信",
        "贷款",
        "信用卡",
        "逾期",
        "查询",
        "五级分类",
        "担保",
        "异议",
        "地址",
        "工作单位",
        "额度",
    ]
    if not any(k in q for k in domain_keywords):
        return "OUT_OF_SCOPE"
    if "担保资格审查查询" in q or ("查询" in q and "担保资格审查" in q):
        return "INDV_QUERY_ANALYSIS"
    if "异议" in q:
        return "INDV_DISPUTE_STATUS"
    if "五级分类" in q:
        return "INDV_FIVE_LEVEL_CLASSIFICATION"
    if any(k in q for k in ("通讯地址", "户籍地址", "居住地址", "单位地址")):
        return "INDV_IDENTITY_ADDRESS_PROFILE"
    if "工作单位" in q and any(k in q for k in ("关键词", "地产", "融资担保", "投资咨询")):
        return "INDV_EMPLOYER_KEYWORD_RISK"
    if "信用卡" in q:
        if any(k in q for k in ("个性化分期", "展期", "负面")):
            return "INDV_CREDIT_CARD_RISK_EVENTS"
        return "INDV_CREDIT_CARD_SUMMARY"
    if any(k in q for k in ("新增贷款", "结清贷款")):
        return "INDV_CREDIT_LOAN_CHANGE"
    if "担保贷款" in q or (("担保" in q) and ("查询" not in q)):
        return "INDV_GUARANTEE_ANALYSIS"
    if "查询" in q or "贷款审批" in q:
        return "INDV_QUERY_ANALYSIS"
    if "逾期" in q:
        return "INDV_OVERDUE_ANALYSIS"
    if any(k in q for k in ("贷款总笔数", "总余额", "授信情况", "总金额")):
        return "INDV_CREDIT_LOAN_SUMMARY"
    return "INDV_QUERY_ANALYSIS"


def answer_question(question_type: str, question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    handlers = {
        "OUT_OF_SCOPE": _answer_out_of_scope,
        "INDV_QUERY_ANALYSIS": _answer_query,
        "INDV_FIVE_LEVEL_CLASSIFICATION": _answer_five_level,
        "INDV_DISPUTE_STATUS": _answer_dispute,
        "INDV_CREDIT_LOAN_SUMMARY": _answer_loan_summary,
        "INDV_CREDIT_LOAN_CHANGE": _answer_loan_change,
        "INDV_CREDIT_CARD_SUMMARY": _answer_card_summary,
        "INDV_CREDIT_CARD_RISK_EVENTS": _answer_card_risk_events,
        "INDV_IDENTITY_ADDRESS_PROFILE": _answer_address_profile,
        "INDV_EMPLOYER_KEYWORD_RISK": _answer_employer_keyword,
        "INDV_OVERDUE_ANALYSIS": _answer_overdue,
        "INDV_GUARANTEE_ANALYSIS": _answer_guarantee,
    }
    handler = handlers.get(question_type, _answer_fallback)
    result = handler(question, report)
    result["question_type"] = question_type
    return result


def _answer_fallback(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "answer": "当前问题超出个人报告 V1 能力范围，请换一个更具体的提问。",
        "confidence": "low",
        "evidence_paths": [],
        "verifier_status": "not_answerable",
        "cannot_answer_reason": "question_type_not_supported_in_v1",
    }


def _answer_out_of_scope(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "answer": OUT_OF_SCOPE_TEMPLATE,
        "confidence": "high",
        "evidence_paths": [],
        "verifier_status": "not_answerable",
        "cannot_answer_reason": "out_of_scope_or_greeting",
    }


def _answer_query(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pc05 = (((report.get("tables") or {}).get("PC05") or {}).get("fields") or {})
    q = question or ""
    if "最近一次查询" in q:
        date_v = _get_value(pc05, "PC05AR01")
        org = _get_label_or_code(pc05, "PC05AD01")
        reason = _get_label_or_code(pc05, "PC05AQ01")
        return {
            "answer": f"最近一次查询日期为 {date_v}，机构类型为 {org}，查询原因为 {reason}。",
            "confidence": "high",
            "evidence_paths": [
                "tables.PC05.fields.PC05AR01.value",
                "tables.PC05.fields.PC05AD01",
                "tables.PC05.fields.PC05AQ01",
            ],
            "verifier_status": "answerable",
            "cannot_answer_reason": "",
        }
    if "贷款审批查询机构数" in q:
        v = _get_value(pc05, "PC05BS01")
        return {
            "answer": f"最近一个月贷款审批查询机构数为 {v}。",
            "confidence": "high",
            "evidence_paths": ["tables.PC05.fields.PC05BS01.value"],
            "verifier_status": "answerable",
            "cannot_answer_reason": "",
        }
    if "担保资格审查查询次数" in q:
        v = _get_value(pc05, "PC05BS07")
        return {
            "answer": f"最近两年担保资格审查查询次数为 {v} 次。",
            "confidence": "high",
            "evidence_paths": ["tables.PC05.fields.PC05BS07.value"],
            "verifier_status": "answerable",
            "cannot_answer_reason": "",
        }
    v = _get_value(pc05, "PC05BS03")
    return {
        "answer": f"最近一个月贷款审批查询次数为 {v} 次。",
        "confidence": "high",
        "evidence_paths": ["tables.PC05.fields.PC05BS03.value"],
        "verifier_status": "answerable",
        "cannot_answer_reason": "",
    }


def _answer_five_level(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pd = (((report.get("tables") or {}).get("PD01") or {}).get("records") or [])
    abnormal = []
    for i, rec in enumerate(pd):
        fields = rec.get("fields") or {}
        f = fields.get("PD01BD03") or {}
        label = str(f.get("label") or "").strip()
        code = str(f.get("code") or "").strip()
        if code and label and label != "正常":
            abnormal.append((i, code, label))
    if abnormal:
        i, code, label = abnormal[0]
        return {
            "answer": f"存在非正常五级分类，至少命中 1 条（{label}）。",
            "confidence": "high",
            "evidence_paths": [f"tables.PD01.records[{i}].fields.PD01BD03"],
            "verifier_status": "answerable",
            "cannot_answer_reason": "",
        }
    return {
        "answer": "当前未发现非正常五级分类。",
        "confidence": "medium",
        "evidence_paths": ["tables.PD01.records[].fields.PD01BD03"],
        "verifier_status": "answerable",
        "cannot_answer_reason": "",
    }


def _answer_dispute(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pos = ((report.get("tables") or {}).get("POS") or {})
    summary = pos.get("summary_fields") or {}
    records = pos.get("records") or []
    count = _to_int(((summary.get("PG010S01") or {}).get("value")))
    hit_idx = None
    for i, rec in enumerate(records):
        txt = str(((rec.get("fields") or {}).get("PG010Q01") or {}).get("value") or "")
        if "处理期" in txt:
            hit_idx = i
            break
    if count > 0 and hit_idx is not None:
        return {
            "answer": "存在在途征信异议（命中“异议处理期”表述）。",
            "confidence": "medium",
            "evidence_paths": [
                "tables.POS.summary_fields.PG010S01.value",
                f"tables.POS.records[{hit_idx}].fields.PG010Q01.value",
            ],
            "verifier_status": "partially_answerable",
            "cannot_answer_reason": "status_code_not_fully_standardized",
        }
    if count > 0:
        return {
            "answer": f"存在异议记录（{count} 条），但当前无法精确判断是否全部在途。",
            "confidence": "low",
            "evidence_paths": ["tables.POS.summary_fields.PG010S01.value"],
            "verifier_status": "partially_answerable",
            "cannot_answer_reason": "in_transit_status_not_explicit",
        }
    return {
        "answer": "未发现异议记录。",
        "confidence": "medium",
        "evidence_paths": ["tables.POS.summary_fields.PG010S01.value"],
        "verifier_status": "answerable",
        "cannot_answer_reason": "",
    }


def _answer_loan_summary(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pd = (((report.get("tables") or {}).get("PD01") or {}).get("records") or [])
    loan_codes = {"D1", "R1", "R4"}
    cnt = 0
    sum_amt = Decimal("0")
    sum_bal = Decimal("0")
    for rec in pd:
        fields = rec.get("fields") or {}
        ad01 = str(((fields.get("PD01AD01") or {}).get("code")) or "")
        if ad01 not in loan_codes:
            continue
        cnt += 1
        sum_amt += _to_decimal(((fields.get("PD01AJ01") or {}).get("value")))
        sum_bal += _to_decimal(((fields.get("PD01BJ01") or {}).get("value")))
    return {
        "answer": f"贷款总笔数 {cnt} 笔，总金额 {int(sum_amt)}，总余额 {int(sum_bal)}。",
        "confidence": "high",
        "evidence_paths": [
            "tables.PD01.records[].fields.PD01AD01",
            "tables.PD01.records[].fields.PD01AJ01.value",
            "tables.PD01.records[].fields.PD01BJ01.value",
        ],
        "verifier_status": "answerable",
        "cannot_answer_reason": "",
    }


def _answer_loan_change(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pd = (((report.get("tables") or {}).get("PD01") or {}).get("records") or [])
    pa = (((report.get("tables") or {}).get("PA01") or {}).get("fields") or {})
    base = _parse_datetime(_get_value(pa, "PA01AR01"))
    if not base:
        return {
            "answer": "无法确定报告时点，暂不能计算新增/结清贷款窗口统计。",
            "confidence": "low",
            "evidence_paths": ["tables.PA01.fields.PA01AR01.value"],
            "verifier_status": "not_answerable",
            "cannot_answer_reason": "report_time_missing",
        }
    windows = [30, 90, 180]
    loan_codes = {"D1", "R1", "R4"}
    is_close = "结清" in (question or "")
    date_field = "PD01BR01" if is_close else "PD01AR01"
    stats: Dict[int, Tuple[int, Decimal]] = {w: (0, Decimal("0")) for w in windows}
    for rec in pd:
        fields = rec.get("fields") or {}
        ad01 = str(((fields.get("PD01AD01") or {}).get("code")) or "")
        if ad01 not in loan_codes:
            continue
        d = _parse_datetime(_get_value(fields, date_field))
        if not d:
            continue
        amt = _to_decimal(_get_value(fields, "PD01AJ01"))
        for w in windows:
            start = base - timedelta(days=w)
            if start.date() <= d.date() <= base.date():
                c, s = stats[w]
                stats[w] = (c + 1, s + amt)
    label = "结清贷款" if is_close else "新增贷款"
    answer = (
        f"{label}统计：近1个月 {stats[30][0]} 笔/{int(stats[30][1])}，"
        f"近3个月 {stats[90][0]} 笔/{int(stats[90][1])}，"
        f"近6个月 {stats[180][0]} 笔/{int(stats[180][1])}。"
    )
    return {
        "answer": answer,
        "confidence": "high",
        "evidence_paths": [
            f"tables.PD01.records[].fields.{date_field}.value",
            "tables.PD01.records[].fields.PD01AJ01.value",
            "tables.PA01.fields.PA01AR01.value",
        ],
        "verifier_status": "answerable",
        "cannot_answer_reason": "",
    }


def _answer_card_summary(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pd = (((report.get("tables") or {}).get("PD01") or {}).get("records") or [])
    card_codes = {"R2", "R3"}
    cnt = 0
    sum_limit = Decimal("0")
    sum_used = Decimal("0")
    for rec in pd:
        fields = rec.get("fields") or {}
        ad01 = str(((fields.get("PD01AD01") or {}).get("code")) or "")
        if ad01 not in card_codes:
            continue
        cnt += 1
        sum_limit += _to_decimal(_get_value(fields, "PD01AJ02"))
        sum_used += _to_decimal(_get_value(fields, "PD01BJ01"))
    if "额度使用率" in (question or "") or "平均用卡" in (question or ""):
        if sum_limit == 0:
            return {
                "answer": "额度字段缺失，无法计算额度使用率。",
                "confidence": "low",
                "evidence_paths": ["tables.PD01.records[].fields.PD01AJ02.value"],
                "verifier_status": "not_answerable",
                "cannot_answer_reason": "card_limit_missing",
            }
        rate = (sum_used / sum_limit) * Decimal("100")
        return {
            "answer": f"当前可计算额度使用率约 {rate.quantize(Decimal('0.01'))}%；近6个月平均用卡金额缺少逐月序列，暂无法精确计算。",
            "confidence": "medium",
            "evidence_paths": [
                "tables.PD01.records[].fields.PD01BJ01.value",
                "tables.PD01.records[].fields.PD01AJ02.value",
            ],
            "verifier_status": "partially_answerable",
            "cannot_answer_reason": "missing_monthly_card_series",
        }
    return {
        "answer": f"信用卡数量 {cnt}，总额度约 {int(sum_limit)}。",
        "confidence": "medium",
        "evidence_paths": [
            "tables.PD01.records[].fields.PD01AD01",
            "tables.PD01.records[].fields.PD01AJ02.value",
        ],
        "verifier_status": "partially_answerable",
        "cannot_answer_reason": "card_limit_field_uses_proxy_definition",
    }


def _answer_card_risk_events(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pd = (((report.get("tables") or {}).get("PD01") or {}).get("records") or [])
    keywords = ("个性化分期", "展期", "特殊")
    hits = 0
    for rec in pd:
        fields = rec.get("fields") or {}
        val = str((fields.get("PD01ZH") or {}).get("value") or "")
        if any(k in val for k in keywords):
            hits += 1
    if hits > 0:
        return {
            "answer": f"检测到疑似信用卡负面事件 {hits} 条（个性化分期/展期/特殊安排类）。",
            "confidence": "medium",
            "evidence_paths": ["tables.PD01.records[].fields.PD01ZH.value"],
            "verifier_status": "partially_answerable",
            "cannot_answer_reason": "",
        }
    return {
        "answer": "当前未检测到明确的信用卡个性化分期/展期事件。",
        "confidence": "low",
        "evidence_paths": ["tables.PD01.records[].fields.PD01ZH.value"],
        "verifier_status": "partially_answerable",
        "cannot_answer_reason": "sparse_or_noisy_special_trade_records",
    }


def _answer_address_profile(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    tables = report.get("tables") or {}
    pb01 = ((tables.get("PB01") or {}).get("fields") or {})
    pb03 = ((tables.get("PB03") or {}).get("records") or [])
    pb04 = ((tables.get("PB04") or {}).get("records") or [])

    comm = _get_value(pb01, "PB01AQ02")
    hukou = _get_value(pb01, "PB01AQ03")

    live_addr = _latest_addr(pb03, "PB030Q01", "PB030R01")
    work_addr = _latest_addr(pb04, "PB040Q02", "PB040R02")

    same = _same_province_city(live_addr, work_addr)
    if same is None:
        relation = "无法判断是否同省同市"
        status = "partially_answerable"
        reason = "address_parse_failed_or_missing"
    elif same:
        relation = "居住地址与单位地址在同一省市"
        status = "answerable"
        reason = ""
    else:
        relation = "居住地址与单位地址不在同一省市"
        status = "partially_answerable"
        reason = "multi_address_or_noisy_work_address"

    return {
        "answer": (
            f"通讯地址：{comm}；户籍地址：{hukou}；"
            f"居住地址（最新）：{live_addr}；单位地址（最新）：{work_addr}。{relation}。"
        ),
        "confidence": "medium",
        "evidence_paths": [
            "tables.PB01.fields.PB01AQ02.value",
            "tables.PB01.fields.PB01AQ03.value",
            "tables.PB03.records[].fields.PB030Q01.value",
            "tables.PB04.records[].fields.PB040Q02.value",
        ],
        "verifier_status": status,
        "cannot_answer_reason": reason,
    }


def _answer_employer_keyword(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pb04 = (((report.get("tables") or {}).get("PB04") or {}).get("records") or [])
    keywords = ["地产", "投资咨询", "融资担保", "小额贷款", "资产管理"]
    hits: List[str] = []
    for rec in pb04:
        name = str(((rec.get("fields") or {}).get("PB040Q01") or {}).get("value") or "")
        for kw in keywords:
            if kw in name:
                hits.append(f"{name}（{kw}）")
    if hits:
        text = "；".join(hits[:5])
        return {
            "answer": f"工作单位命中关键词：{text}。",
            "confidence": "high",
            "evidence_paths": ["tables.PB04.records[].fields.PB040Q01.value"],
            "verifier_status": "answerable",
            "cannot_answer_reason": "",
        }
    return {
        "answer": "当前未命中地产/投资咨询/融资担保等关键词。",
        "confidence": "medium",
        "evidence_paths": ["tables.PB04.records[].fields.PB040Q01.value"],
        "verifier_status": "answerable",
        "cannot_answer_reason": "company_names_may_be_masked_or_abbreviated",
    }


def _answer_overdue(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    if "连续逾期" in (question or ""):
        return {
            "answer": "当前结果缺少完整逐月还款序列，暂无法精确计算最大连续逾期期数。",
            "confidence": "low",
            "evidence_paths": ["tables.PD01.records[].fields.PD01BD04"],
            "verifier_status": "not_answerable",
            "cannot_answer_reason": "missing_monthly_sequence",
        }
    pd = (((report.get("tables") or {}).get("PD01") or {}).get("records") or [])
    hit_cnt = 0
    exposure = Decimal("0")
    by_biz: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "exposure": Decimal("0"), "sample_idx": None})
    for rec in pd:
        fields = rec.get("fields") or {}
        bd04 = fields.get("PD01BD04") or {}
        code = str(bd04.get("code") or "").strip()
        if code and code not in {"N", "*"}:
            hit_cnt += 1
            bal = _to_decimal(_get_value(fields, "PD01BJ01"))
            exposure += bal
            biz = str((fields.get("PD01AD03") or {}).get("label") or (fields.get("PD01AD03") or {}).get("code") or "未知业务")
            agg = by_biz[biz]
            agg["count"] += 1
            agg["exposure"] += bal
            if agg["sample_idx"] is None:
                agg["sample_idx"] = hit_cnt - 1

    detail_keywords = ("业务种类", "业务类型", "明细", "分类", "分布")
    want_biz_detail = any(k in (question or "") for k in detail_keywords)
    if want_biz_detail:
        if hit_cnt == 0:
            return {
                "answer": "当前口径下未命中逾期记录，因此暂无可展示的逾期业务种类明细。",
                "confidence": "medium",
                "evidence_paths": [
                    "tables.PD01.records[].fields.PD01BD04",
                    "tables.PD01.records[].fields.PD01AD03",
                ],
                "verifier_status": "answerable",
                "cannot_answer_reason": "",
            }
        ranked = sorted(by_biz.items(), key=lambda x: (x[1]["count"], x[1]["exposure"]), reverse=True)
        lines = []
        for biz, agg in ranked[:5]:
            lines.append(f"{biz}: {agg['count']}条，风险敞口约{int(agg['exposure'])}")
        return {
            "answer": (
                f"可以，当前逾期业务种类明细（按命中条数排序）如下：\n"
                + "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
                + f"\n合计命中 {hit_cnt} 条，风险敞口约 {int(exposure)}。"
            ),
            "confidence": "medium",
            "evidence_paths": [
                "tables.PD01.records[].fields.PD01BD04",
                "tables.PD01.records[].fields.PD01AD03",
                "tables.PD01.records[].fields.PD01BJ01.value",
            ],
            "verifier_status": "partially_answerable",
            "cannot_answer_reason": "proxy_overdue_metric_without_full_24m_series",
        }
    return {
        "answer": (
            f"存在逾期迹象；按当前口径累计命中 {hit_cnt} 条，相关风险敞口约 {int(exposure)}。"
            "如需我可以继续按业务种类拆分展示逾期明细。"
        ),
        "confidence": "medium",
        "evidence_paths": [
            "tables.PD01.records[].fields.PD01BD04",
            "tables.PD01.records[].fields.PD01BJ01.value",
        ],
        "verifier_status": "partially_answerable",
        "cannot_answer_reason": "proxy_overdue_metric_without_full_24m_series",
    }


def _answer_guarantee(question: str, report: Dict[str, Any]) -> Dict[str, Any]:
    pd03 = (((report.get("tables") or {}).get("PD03") or {}).get("records") or [])
    if not pd03:
        return {
            "answer": "当前样例的担保明细字段较稀疏，暂无法稳定输出担保总额与逾期明细。",
            "confidence": "low",
            "evidence_paths": ["tables.PD03.records[]"],
            "verifier_status": "not_answerable",
            "cannot_answer_reason": "pd03_sparse_fields",
        }
    return {
        "answer": f"检测到担保记录 {len(pd03)} 条；担保统计口径待补充后可输出总额与逾期明细。",
        "confidence": "low",
        "evidence_paths": ["tables.PD03.records[]"],
        "verifier_status": "partially_answerable",
        "cannot_answer_reason": "pd03_fields_not_fully_mapped",
    }


def _get_value(field_map: Dict[str, Any], code: str) -> Any:
    return (field_map.get(code) or {}).get("value")


def _get_label_or_code(field_map: Dict[str, Any], code: str) -> str:
    f = field_map.get(code) or {}
    return str(f.get("label") or f.get("value") or f.get("code") or "")


def _to_int(v: Any) -> int:
    try:
        return int(str(v).replace(",", "").strip())
    except Exception:
        return 0


def _to_decimal(v: Any) -> Decimal:
    if v in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(v).replace(",", "").strip())
    except Exception:
        return Decimal("0")


def _parse_datetime(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    s = str(v).strip()
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _latest_addr(records: List[Dict[str, Any]], addr_field: str, date_field: str) -> str:
    best_addr = ""
    best_dt: Optional[datetime] = None
    for rec in records:
        fields = rec.get("fields") or {}
        addr = str(((fields.get(addr_field) or {}).get("value")) or "").strip()
        dt = _parse_datetime((fields.get(date_field) or {}).get("value"))
        if not addr:
            continue
        if best_dt is None or (dt is not None and dt > best_dt):
            best_addr = addr
            best_dt = dt
    return best_addr


def _extract_province_city(addr: str) -> Tuple[str, str]:
    text = str(addr or "")
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


def _same_province_city(addr_a: str, addr_b: str) -> Optional[bool]:
    if not addr_a or not addr_b:
        return None
    pa, ca = _extract_province_city(addr_a)
    pb, cb = _extract_province_city(addr_b)
    if not pa or not pb:
        return None
    if ca and cb:
        return pa == pb and ca == cb
    return pa == pb
