from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from difflib import SequenceMatcher

from extraction_runtime import build_extraction_snippets, load_pdf_modules
from prompt_templates import (
    EXTRACTION_ANSWER_SYSTEM_PROMPT,
    QUESTION_ROUTER_SYSTEM_PROMPT,
    SQL_ANSWER_SYSTEM_PROMPT,
    SQL_PLANNER_SYSTEM_PROMPT,
)
from qwen_client import (
    QwenClient,
    build_extraction_answer_prompt,
    build_question_router_prompt,
    build_sql_answer_prompt,
    build_sql_planner_prompt,
)
from sql_runtime import build_schema_context, build_sqlite_db, execute_readonly_sql

SESSION_CONTEXTS: Dict[str, Dict[str, Any]] = {}

EXTRACT_FIELD_SPECS: List[Dict[str, Any]] = [
    {"key": "subject_name", "requested_label": "被查询者姓名", "aliases": ["被查询者姓名", "姓名", "名字"], "preferred_names": ["被查询者姓名"]},
    {"key": "subject_id_type", "requested_label": "被查询者证件类型", "aliases": ["被查询者证件类型", "证件类型", "证件", "证件类别", "证件累心", "证件类心"], "preferred_names": ["被查询者证件类型"]},
    {"key": "subject_id_no", "requested_label": "被查询者证件号码", "aliases": ["被查询者证件号码", "证件号码", "身份证号", "身份证号码"], "preferred_names": ["被查询者证件号码"]},
    {"key": "sex", "requested_label": "性别", "aliases": ["性别"], "preferred_names": ["性别"]},
    {"key": "birth_date", "requested_label": "出生日期", "aliases": ["出生日期", "生日"], "preferred_names": ["出生日期"]},
    {"key": "marital_status", "requested_label": "婚姻状况", "aliases": ["婚姻状况", "婚况"], "preferred_names": ["婚姻状况"]},
    {"key": "communication_address", "requested_label": "通讯地址", "aliases": ["通讯地址", "通信地址"], "preferred_names": ["通讯地址"]},
    {"key": "hukou_address", "requested_label": "户籍地址", "aliases": ["户籍地址", "户口地址"], "preferred_names": ["户籍地址"]},
    {"key": "residence_address", "requested_label": "居住地址", "aliases": ["居住地址"], "preferred_names": ["居住地址"]},
    {"key": "work_unit", "requested_label": "工作单位", "aliases": ["工作单位", "单位名称"], "preferred_names": ["工作单位"]},
    {"key": "unit_address", "requested_label": "单位地址", "aliases": ["单位地址"], "preferred_names": ["单位地址"]},
    {"key": "occupation", "requested_label": "职业", "aliases": ["职业"], "preferred_names": ["职业"]},
    {"key": "report_no", "requested_label": "报告编号", "aliases": ["报告编号"], "preferred_names": ["报告编号"]},
    {"key": "report_time", "requested_label": "报告时间", "aliases": ["报告时间"], "preferred_names": ["报告时间"]},
    {"key": "query_reason", "requested_label": "查询原因", "aliases": ["查询原因", "原因"], "preferred_names": ["查询原因代码"]},
]

COLUMN_LABELS = {
    "outstanding_account_count_total": "当前未结清/未销户账户总数",
    "outstanding_compensation_account_count": "被追偿账户数",
    "outstanding_credit_account_count": "贷款及卡账户数",
    "total_obligation_account_count": "含相关还款责任的相关负债账户总数",
    "outstanding_account_balance_total": "当前未结清/未销户账户余额合计",
    "outstanding_compensation_balance": "被追偿余额",
    "outstanding_credit_account_balance": "贷款及卡账户余额",
    "related_repayment_responsibility_balance": "相关还款责任余额",
    "liability_balance_total_including_related_responsibility": "含相关还款责任的相关负债余额合计",
    "latest_query_date": "最近一次查询日期",
    "month1_loan_query_count": "最近1个月贷款审批查询次数",
    "overdue_account_count": "逾期账户数",
    "special_risk_record_count": "特殊风险状态命中记录数",
    "account_count": "账户数",
    "total_balance": "余额合计",
    "loan_classification": "贷款分类",
    "account_category": "账户分类",
    "query_reason": "查询原因",
    "query_count": "查询次数",
    "period_date": "月份",
    "repay_type": "还款状态",
    "repay_type_code": "还款状态码",
    "current_non_normal_account_count": "当前非正常五级分类账户数",
    "historical_non_normal_record_count": "历史非正常五级分类记录数",
    "historical_affected_account_count": "历史非正常五级分类涉及账户数",
    "current_attention_count": "当前关注账户数",
    "current_substandard_count": "当前次级账户数",
    "current_doubtful_count": "当前可疑账户数",
    "current_loss_count": "当前损失账户数",
    "report_level_in_transit_objection_count": "首页在途异议总数",
    "structured_objection_count_summary": "结构化异议概要条数",
    "objection_in_transit_detail_count": "在途异议明细条数",
    "objection_candidate_detail_count": "异议候选明细条数",
    "summary_matches_report_level": "结构化概要与首页总数是否一致",
    "has_in_transit_objection": "是否存在在途异议",
}

KEYWORD_TO_TABLES: List[tuple[Sequence[str], List[str], List[str], List[str]]] = [
    (("逾期", "B/D/G", "特殊风险"), ["account_history", "credit_account"], ["v_report_context"], [
        "近X个月/年的时间窗口统一以报告日期为锚点。",
        "逾期历史优先查 account_history。",
        "逾期账户数优先使用 COUNT(DISTINCT account_id)；逾期记录数优先使用 COUNT(*)。",
        "如果问题出现“逾期次数”，默认按账户-月份口径的 COUNT(*) 处理，不要对 overdue_months 或 repay_type_code 求和。",
        "逾期金额默认使用 SUM(overdue_total)；overdue_months 只用于筛选或取最大值，不用于表示次数。",
        "普通逾期与特殊风险状态不能混算。",
        "如果同一问题同时出现多个时间窗口和多个指标，可使用一条 CASE 聚合 SQL 一次返回多个窗口结果。",
        "当前数据库只包含当前报告数据，本题禁止使用 report_id、selected_report_id、internal_report_id 做 join 或过滤；如需时间锚点，只允许读取 v_report_context.report_date。",
    ]),
    (("新增贷款", "结清贷款", "开立日期", "关闭日期", "结清日期"), ["credit_account"], ["v_report_context"], [
        "新增贷款默认按贷款类账户的开立日期 open_date 落入窗口统计。",
        "结清贷款默认按贷款类账户的关闭/结清日期 close_date 落入窗口统计，并要求 account_status='结清'。",
        "默认纳入：非循环贷账户、循环额度下分账户、循环贷账户；默认排除：贷记卡账户、准贷记卡账户、被追偿信息、相关还款责任。",
        "新增贷款笔数默认按 COUNT(*)；新增贷款金额默认按 SUM(original_amount)。",
        "结清贷款笔数默认按 COUNT(*)；结清贷款金额默认按 SUM(original_amount)，不混用当前余额或授信额度。",
        "若同一问题同时出现多个时间窗口和多个指标，优先使用一条 CASE 聚合 SQL 同时返回多个窗口结果。",
        "金额字段保持 original_amount 口径，不自行混用授信额度。",
    ]),
    (("未结清", "未销户", "负债", "余额", "借款金额"), ["credit_account", "credit_summary"], ["v_report_context", "v_outstanding_summary"], [
        "当前未结清/未销户问题优先使用 v_outstanding_summary。",
        "借款金额、余额、授信额度、债权金额不能混算。",
        "相关还款责任默认作为扩展口径，不直接替代主口径。",
    ]),
    (("查询",), ["query_record", "credit_summary"], ["v_report_context", "v_query_summary_pc05"], [
        "查询明细窗口统计优先查 query_record；固定概要窗口优先查 v_query_summary_pc05。",
        "近X个月/年的时间窗口统一以报告日期为锚点。",
        "本人查询可能只出现在概要中。",
    ]),
    (("信用卡", "分期", "展期"), ["credit_account", "special_transaction", "credit_summary"], ["v_report_context"], [
        "信用卡额度、已用额度、透支余额字段不能混用。",
        "大额专项分期不等于个性化分期或展期。",
    ]),
    (("异议", "在途异议", "征信异议", "处理中"), ["credit_summary", "objection_record"], ["v_report_context"], [
        "是否有在途征信异议，优先依据首页异议概要和异议明细中的处理中/处理期标识共同判断。",
        "首页在途异议总数优先从首页异议信息提示原文提取；credit_summary 中的 PG010S01 仅作结构化对账参考。",
        "在途判断优先参考 objection_record.is_in_transit；如无该字段，再看 objection_text 是否命中“处理期/处理中/异议处理”。",
        "异议信息属于存在性判断与数量提取问题，不走金额汇总逻辑。",
    ]),
    (("五级分类", "非正常", "关注", "次级", "可疑", "损失"), ["credit_account", "account_history"], ["v_report_context"], [
        "贷款五级分类问题优先检查贷款账户当前五级分类字段 five_classification。",
        "贷款范围默认包括非循环贷账户、循环额度下分账户和循环贷账户；默认排除贷记卡、准贷记卡、被追偿信息、相关还款责任。",
        "非正常五级分类默认指：关注、次级、可疑、损失。",
        "如果问题同时提到“当前和历史记录”，当前部分优先查 credit_account；历史部分只有在结构化层存在可用历史五级分类记录时才统计，否则需提示历史判断受字段覆盖限制。",
    ]),
    (("地址", "居住", "户籍", "通讯", "单位"), ["identity_info", "residence_info", "occupation_info"], ["v_report_context"], [
        "地址同省市判断需要同时拿到居住地址和单位地址。",
        "地址脱敏或无法解析省市时，应返回无法判断。",
    ]),
]


@lru_cache(maxsize=1)
def _load_schema_metadata() -> Dict[str, Any]:
    app_dir = Path(__file__).resolve().parent
    path = app_dir / "semantic" / "schema_metadata.json"
    return json.loads(path.read_text(encoding="utf-8"))


async def run_agent_turn(
    *,
    messages: List[Dict[str, str]],
    report_json: Dict[str, Any],
    core_tables_json: Dict[str, Any] | None,
    raw_pdf_path: str | None,
    raw_xml_path: str | None,
    report_id: str,
    session_id: str,
    qwen_client: QwenClient,
    debug: bool = False,
) -> Dict[str, Any]:
    _ = report_json
    question = _last_user_question(messages)
    if not question:
        return {
            "answer": "请先输入你的问题。",
            "answer_mode": "sql_query",
            "confidence": "low",
            "evidence_paths": [],
            "verifier_status": "not_answerable",
            "cannot_answer_reason": "empty_question",
            "question_type": "SQL_QUERY",
            "query_plan": None,
            "query_result": None,
            "prompt_trace": None,
            "debug": {"planner_source": "none"} if debug else None,
        }

    previous_context = SESSION_CONTEXTS.get(session_id, {})
    recent_messages = messages[-6:]
    route_payload = {"question": question, "recent_messages": recent_messages}
    route_source = "llm" if qwen_client.configured else "heuristic"
    route_info = None
    if qwen_client.configured:
        try:
            route_info = await qwen_client.route_question(route_payload)
        except Exception:
            route_info = None
    if not route_info:
        route_source = "heuristic"
        route_info = _route_question_locally(question)
    if "异议" in question:
        route_info = {"mode": "sql", "target_modules": [], "reason": "forced_sql_objection"}
        route_source = "forced_sql"
    if "五级分类" in question:
        route_info = {"mode": "sql", "target_modules": [], "reason": "forced_sql_five_classification"}
        route_source = "forced_sql"

    if route_info and route_info.get("mode") == "extract" and raw_pdf_path:
        return await _run_extraction_turn(
            question=question,
            report_id=report_id,
            session_id=session_id,
            raw_pdf_path=raw_pdf_path,
            report_json=report_json,
            previous_context=previous_context,
            route_payload=route_payload,
            route_info=route_info,
            qwen_client=qwen_client,
            debug=debug,
            route_source=route_source,
        )

    if not core_tables_json:
        return {
            "answer": "当前报告缺少核心表产物，SQL 版 demo 暂时无法回答。请先完成解析与核心表生成。",
            "answer_mode": "sql_query",
            "confidence": "low",
            "evidence_paths": [],
            "verifier_status": "not_answerable",
            "cannot_answer_reason": "missing_core_tables",
            "question_type": "SQL_QUERY",
            "query_plan": None,
            "query_result": None,
            "prompt_trace": None,
            "debug": {"planner_source": "none"} if debug else None,
        }

    conn = build_sqlite_db(core_tables_json, exposed_report_id=report_id)
    schema_context = build_schema_context(core_tables_json, _load_schema_metadata(), exposed_report_id=report_id)
    planner_context = _build_planner_context(question=question, previous_context=previous_context, schema_context=schema_context)

    planner_payload = {
        "question": question,
        "recent_messages": recent_messages,
        "previous_context": previous_context,
        "report_context": _build_planner_report_context(schema_context.get("report_context") or {}),
        "available_tables": planner_context["available_tables"],
        "available_views": planner_context["available_views"],
        "planner_rules": planner_context["planner_rules"],
    }
    local_candidate_plan = _plan_sql_locally(question=question, previous_context=previous_context)
    planner_source = "llm" if qwen_client.configured else "local"
    query_plan = None
    if local_candidate_plan and str(local_candidate_plan.get("question_type") or "") == "multi_window_summary":
        planner_source = "local"
        query_plan = local_candidate_plan
    elif qwen_client.configured:
        try:
            query_plan = await qwen_client.generate_sql_plan(planner_payload)
        except Exception:
            query_plan = None
    if not query_plan:
        planner_source = "local"
        query_plan = local_candidate_plan or _plan_sql_locally(question=question, previous_context=previous_context)

    if not query_plan or not str(query_plan.get("sql") or "").strip():
        conn.close()
        return {
            "answer": "SQL 版 demo 目前还没能为这个问题生成可执行查询。可以换一种更明确的问法，或者先问单一指标问题。",
            "answer_mode": "sql_query",
            "confidence": "low",
            "evidence_paths": [],
            "verifier_status": "not_answerable",
            "cannot_answer_reason": "sql_plan_not_generated",
            "question_type": "SQL_QUERY",
            "query_plan": query_plan,
            "query_result": None,
            "prompt_trace": {
                "planner_system_prompt": SQL_PLANNER_SYSTEM_PROMPT,
                "planner_prompt_text": build_sql_planner_prompt(planner_payload),
                "planner_output": query_plan,
            },
            "debug": {"planner_source": planner_source} if debug else None,
        }

    try:
        report_ctx = schema_context.get("report_context") or {}
        query_result = execute_readonly_sql(
            conn,
            str(query_plan.get("sql") or ""),
            selected_report_id=str(report_ctx.get("selected_report_id") or ""),
            report_date=str(report_ctx.get("report_date") or ""),
        )
        if str(query_plan.get("business_object") or "") == "objection_in_transit":
            _augment_objection_in_transit_result(
                query_result=query_result,
                raw_pdf_path=raw_pdf_path,
                raw_xml_path=raw_xml_path,
            )
        verifier_status = "answerable"
        cannot_answer_reason = ""
    except Exception as exc:
        query_result = {"sql": str(query_plan.get("sql") or ""), "error": str(exc), "columns": [], "rows": []}
        verifier_status = "not_answerable"
        cannot_answer_reason = "sql_execution_failed"

    answer_payload = {
        "question": question,
        "sql": str(query_result.get("sql") or query_plan.get("sql") or ""),
        "query_result": query_result,
        "field_labels": _build_field_labels(query_result=query_result, schema_context=schema_context),
        "scope_note": _build_scope_note(question=question, query_plan=query_plan, planner_context=planner_context),
        "scope_facts": _build_scope_facts(query_plan=query_plan, planner_context=planner_context),
        "limitation_note": _build_limitation_note(
            question=question,
            query_plan=query_plan,
            query_result=query_result,
            cannot_answer_reason=cannot_answer_reason,
        ),
        "preferred_format": "table" if str(query_plan.get("question_type") or "") == "multi_window_summary" else "",
    }
    prompt_trace = {
        "planner_system_prompt": SQL_PLANNER_SYSTEM_PROMPT,
        "planner_prompt_text": build_sql_planner_prompt(planner_payload),
        "planner_output": query_plan,
        "answer_system_prompt": SQL_ANSWER_SYSTEM_PROMPT,
        "answer_prompt_text": build_sql_answer_prompt(answer_payload),
        "session_context_in": previous_context,
        "planner_payload": planner_payload,
        "answer_payload": answer_payload,
    }

    answer = None
    if verifier_status == "answerable" and qwen_client.configured:
        try:
            answer = await qwen_client.generate_sql_answer(answer_payload)
        except Exception:
            answer = None
    if answer and not _accept_generated_sql_answer(
        question=question,
        query_plan=query_plan,
        query_result=query_result,
        answer=answer,
    ):
        answer = None
    if not answer:
        answer = _build_local_sql_answer(
            question=question,
            query_plan=query_plan,
            query_result=query_result,
            cannot_answer_reason=cannot_answer_reason,
        )

    SESSION_CONTEXTS[session_id] = {
        "report_id": report_id,
        "last_question": question,
        "last_sql": query_result.get("sql") or query_plan.get("sql") or "",
        "last_account_set_sql": _derive_followup_scope_sql(
            question=question,
            query_plan=query_plan,
            query_result=query_result,
        ),
        "last_query_goal_cn": query_plan.get("query_goal_cn") or "",
        "last_result_preview": {
            "columns": list(query_result.get("columns") or []),
            "rows": list(query_result.get("rows") or [])[:10],
            "row_count": int(query_result.get("row_count") or 0),
        },
    }

    result = {
        "answer": answer,
        "answer_mode": "sql_query",
        "confidence": "high" if verifier_status == "answerable" else "low",
        "evidence_paths": [],
        "verifier_status": verifier_status,
        "cannot_answer_reason": cannot_answer_reason,
        "question_type": str(query_plan.get("question_type") or "SQL_QUERY"),
        "query_plan": query_plan,
        "query_result": query_result,
        "prompt_trace": prompt_trace,
    }
    if debug:
        result["debug"] = {
            "planner_source": planner_source,
            "qwen_configured": qwen_client.configured,
            "session_context_out": SESSION_CONTEXTS.get(session_id, {}),
        }
    conn.close()
    return result


def _last_user_question(messages: List[Dict[str, str]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "").strip()
    return ""


def _extract_window_months(question: str, default_months: int = 24) -> int:
    q = question or ""
    if "1个月" in q or "一个月" in q:
        return 1
    if "3个月" in q or "三个月" in q:
        return 3
    if "6个月" in q or "半年" in q:
        return 6
    if "12个月" in q or "1年" in q or "一年" in q:
        return 12
    if "24个月" in q or "2年" in q or "两年" in q:
        return 24
    if "15个月" in q:
        return 15
    return default_months


def _extract_window_months_list(question: str, default_months: Optional[int] = None) -> List[int]:
    q = str(question or "")
    phrase_map = [
        ("24个月", 24),
        ("2年", 24),
        ("两年", 24),
        ("12个月", 12),
        ("1年", 12),
        ("一年", 12),
        ("6个月", 6),
        ("六个月", 6),
        ("半年", 6),
        ("3个月", 3),
        ("三个月", 3),
        ("1个月", 1),
        ("一个月", 1),
    ]
    hits: List[tuple[int, int]] = []
    for phrase, months in phrase_map:
        idx = q.find(phrase)
        if idx >= 0:
            hits.append((idx, months))
    if not hits:
        return [default_months] if default_months is not None else []
    hits.sort(key=lambda x: x[0])
    out: List[int] = []
    for _, months in hits:
        if months not in out:
            out.append(months)
    return out


def _extract_report_level_in_transit_objection_info(
    *,
    raw_pdf_path: str | None,
    raw_xml_path: str | None,
) -> Dict[str, Any]:
    pattern = re.compile(r"(\d+)\s*笔异议且正在处理中")
    if raw_pdf_path:
        try:
            modules = load_pdf_modules(str(raw_pdf_path))
            report_header = str(modules.get("report_header") or "")
            m = pattern.search(report_header)
            if m:
                return {
                    "count": int(m.group(1)),
                    "source": "pdf_report_header_regex",
                    "evidence": m.group(0),
                }
        except Exception:
            pass
    if raw_xml_path:
        try:
            xml_text = Path(str(raw_xml_path)).read_text(encoding="utf-8", errors="ignore")
            m = pattern.search(xml_text)
            if m:
                return {
                    "count": int(m.group(1)),
                    "source": "xml_raw_regex",
                    "evidence": m.group(0),
                }
            # Fallback: homepage header field in raw XML when homepage display text is unavailable.
            m2 = re.search(r"<PA01ES01>\s*(\d+)\s*</PA01ES01>", xml_text)
            if m2:
                return {
                    "count": int(m2.group(1)),
                    "source": "xml_header_field_pa01es01",
                    "evidence": f"PA01ES01={m2.group(1)}",
                }
        except Exception:
            pass
    return {"count": None, "source": "not_found", "evidence": ""}


def _augment_objection_in_transit_result(
    *,
    query_result: Dict[str, Any],
    raw_pdf_path: str | None,
    raw_xml_path: str | None,
) -> None:
    rows = list(query_result.get("rows") or [])
    if not rows:
        return
    row = dict(rows[0] or {})
    report_level = _extract_report_level_in_transit_objection_info(
        raw_pdf_path=raw_pdf_path,
        raw_xml_path=raw_xml_path,
    )
    report_count = report_level.get("count")
    report_count_int = int(report_count) if report_count is not None else 0
    structured_count = int(row.get("structured_objection_count_summary") or 0)
    detail_count = int(row.get("objection_in_transit_detail_count") or 0)
    row["report_level_in_transit_objection_count"] = report_count_int if report_count is not None else None
    row["report_level_in_transit_objection_count_source"] = str(report_level.get("source") or "")
    row["report_level_in_transit_objection_evidence"] = str(report_level.get("evidence") or "")
    row["summary_matches_report_level"] = (
        1 if (report_count is not None and structured_count == report_count_int) else 0
    ) if report_count is not None else None
    row["has_in_transit_objection"] = 1 if (report_count_int > 0 or detail_count > 0) else 0
    rows[0] = row
    query_result["rows"] = rows
    columns = list(query_result.get("columns") or [])
    injected_columns = [
        "report_level_in_transit_objection_count",
        "summary_matches_report_level",
        "has_in_transit_objection",
    ]
    for col in injected_columns:
        if col not in columns:
            columns.append(col)
    query_result["columns"] = columns


def _route_question_locally(question: str) -> Dict[str, Any]:
    q = str(question or "")
    if "异议" in q:
        return {"mode": "sql", "target_modules": [], "reason": "force_sql_objection"}
    if "五级分类" in q:
        return {"mode": "sql", "target_modules": [], "reason": "force_sql_five_classification"}
    extract_markers = ("提取", "按以下格式", "按照以下格式", "列出", "整理")
    sql_markers = ("多少", "合计", "占比", "近", "分别", "分布", "计算")
    if any(m in q for m in extract_markers) or (
        any(m in q for m in ("基本信息", "身份信息", "信息概要", "查询记录概要", "户籍地址", "通讯地址", "居住地址"))
        and not any(m in q for m in sql_markers)
    ):
        return {
            "mode": "extract",
            "target_modules": _select_extract_modules(question),
            "reason": "heuristic_extract",
        }
    if any(m in q for m in sql_markers):
        return {"mode": "sql", "target_modules": [], "reason": "heuristic_sql"}
    return {"mode": "sql", "target_modules": [], "reason": "default_sql"}


def _select_extract_modules(question: str) -> List[str]:
    q = str(question or "")
    modules: List[str] = []
    if "首页" in q or "报告编号" in q or "报告时间" in q or "查询原因" in q:
        modules.append("report_header")
    if "基本信息" in q or "身份信息" in q or any(x in q for x in ("姓名", "证件", "性别", "婚姻", "户籍地址", "通讯地址")):
        modules.append("basic_info_bundle")
    if "居住信息" in q and "basic_info_bundle" not in modules:
        modules.append("residence_info")
    if "职业信息" in q and "basic_info_bundle" not in modules:
        modules.append("occupation_info")
    if "信息概要" in q:
        modules.append("overview_summary")
    if "查询记录概要" in q:
        modules.append("query_summary")
    if not modules:
        modules = ["basic_info_bundle"]
    deduped: List[str] = []
    for module in modules:
        if module not in deduped:
            deduped.append(module)
    return deduped


async def _run_extraction_turn(
    *,
    question: str,
    report_id: str,
    session_id: str,
    raw_pdf_path: str,
    report_json: Dict[str, Any],
    previous_context: Dict[str, Any],
    route_payload: Dict[str, Any],
    route_info: Dict[str, Any],
    qwen_client: QwenClient,
    debug: bool,
    route_source: str,
) -> Dict[str, Any]:
    modules = load_pdf_modules(str(raw_pdf_path))
    target_modules = [str(x) for x in (route_info.get("target_modules") or []) if str(x).strip()] or _select_extract_modules(question)
    snippets = build_extraction_snippets(modules, target_modules)
    structured_fields = _resolve_structured_extract_fields(question=question, report_json=report_json)
    answer_payload = {
        "question": question,
        "structured_fields": structured_fields,
        "snippets": snippets,
    }
    prompt_trace = {
        "planner_system_prompt": QUESTION_ROUTER_SYSTEM_PROMPT,
        "planner_prompt_text": build_question_router_prompt(route_payload),
        "planner_output": route_info,
        "answer_system_prompt": EXTRACTION_ANSWER_SYSTEM_PROMPT,
        "answer_prompt_text": build_extraction_answer_prompt(answer_payload),
        "session_context_in": previous_context,
        "answer_payload": answer_payload,
    }
    answer = None
    if qwen_client.configured:
        try:
            answer = await qwen_client.generate_extraction_answer(answer_payload)
        except Exception:
            answer = None
    if not answer:
        answer = _build_local_extraction_answer_with_fields(
            question=question,
            structured_fields=structured_fields,
            snippets=snippets,
        )
    SESSION_CONTEXTS[session_id] = {
        "report_id": report_id,
        "last_question": question,
        "last_extract_modules": target_modules,
        "last_result_preview": snippets[:4],
    }
    result = {
        "answer": answer,
        "answer_mode": "direct_extract",
        "confidence": "high" if snippets else "low",
        "evidence_paths": [f"pdf_module:{x}" for x in target_modules],
        "verifier_status": "answerable" if snippets else "partially_answerable",
        "cannot_answer_reason": "" if snippets else "extract_modules_not_found",
        "question_type": "DIRECT_EXTRACT",
        "query_plan": {
            "mode": "extract",
            "target_modules": target_modules,
            "route_reason": route_info.get("reason") or "",
        },
        "query_result": {
            "target_modules": target_modules,
            "structured_fields": structured_fields,
            "snippet_count": len(snippets),
            "snippets": snippets,
        },
        "prompt_trace": prompt_trace,
    }
    if debug:
        result["debug"] = {
            "route_source": route_source,
            "qwen_configured": qwen_client.configured,
            "session_context_out": SESSION_CONTEXTS.get(session_id, {}),
        }
    return result


def _build_planner_context(*, question: str, previous_context: Dict[str, Any], schema_context: Dict[str, Any]) -> Dict[str, Any]:
    q = str(question or "")
    selected_tables: List[str] = []
    selected_views: List[str] = ["v_report_context"]
    selected_rules: List[str] = [
        "当前数据库中只包含当前选中报告的数据，本题不要手写 report_id、selected_report_id 或 internal_report_id 过滤/关联。",
        "所有近X个月/年的时间窗口统一以报告日期为锚点，不要使用 now/current_date。",
    ]

    for keywords, tables, views, rules in KEYWORD_TO_TABLES:
        if any(k in q for k in keywords):
            for t in tables:
                if t not in selected_tables:
                    selected_tables.append(t)
            for v in views:
                if v not in selected_views:
                    selected_views.append(v)
            for r in rules:
                if r not in selected_rules:
                    selected_rules.append(r)

    if not selected_tables:
        selected_tables = ["credit_account", "account_history", "query_record"]

    if previous_context.get("last_sql"):
        selected_rules.append("如果用户使用“这些账户/这些记录”等指代，可结合 previous_context 复用上一轮结果范围。")
    if previous_context.get("last_account_set_sql"):
        selected_rules.append("如果用户追问“这些账户”的分类或金额，优先基于 previous_context.last_account_set_sql 继续查询。")

    deduped_rules: List[str] = []
    for rule in selected_rules:
        if rule not in deduped_rules:
            deduped_rules.append(rule)

    available_tables = _pick_table_summaries(schema_context.get("table_summaries") or [], selected_tables)
    available_views = _pick_view_summaries(schema_context.get("view_summaries") or [], selected_views)
    return {
        "available_tables": available_tables,
        "available_views": available_views,
        "planner_rules": deduped_rules[:8],
    }


def _build_planner_report_context(report_context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "report_date": str(report_context.get("report_date") or ""),
        "single_report_only": True,
        "report_filter_mode": "none",
    }


def _pick_table_summaries(table_summaries: List[Dict[str, Any]], selected_tables: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    selected = set(selected_tables)
    for item in table_summaries:
        if str(item.get("table") or "") not in selected:
            continue
        cols = list(item.get("columns") or [])[:12]
        out.append(
            {
                "table": item.get("table"),
                "description": item.get("description") or "",
                "columns": cols,
            }
        )
    return out


def _pick_view_summaries(view_summaries: List[Dict[str, Any]], selected_views: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    selected = set(selected_views)
    for item in view_summaries:
        if str(item.get("view") or "") not in selected:
            continue
        cols = list(item.get("columns") or [])[:12]
        if str(item.get("view") or "") == "v_report_context":
            cols = [col for col in cols if str(col.get("name") or "") == "report_date"]
        out.append(
            {
                "view": item.get("view"),
                "description": item.get("description") or "",
                "columns": cols,
            }
        )
    return out


def _build_field_labels(*, query_result: Dict[str, Any], schema_context: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    columns = list(query_result.get("columns") or [])
    if not columns:
        return labels
    schema_label_map = dict(COLUMN_LABELS)
    for view in schema_context.get("view_summaries") or []:
        for col in view.get("columns") or []:
            name = str(col.get("name") or "")
            name_cn = str(col.get("name_cn") or "")
            if name and name_cn:
                schema_label_map.setdefault(name, name_cn)
    for table in schema_context.get("table_summaries") or []:
        for col in table.get("columns") or []:
            name = str(col.get("name") or "")
            name_cn = str(col.get("name_cn") or "")
            if name and name_cn:
                schema_label_map.setdefault(name, name_cn)
    for col in columns:
        m_cnt = re.fullmatch(r"cnt_(\d+)m", str(col))
        if m_cnt:
            labels.append(f"{col}: 近{m_cnt.group(1)}个月数量")
            continue
        m_amt = re.fullmatch(r"amt_(\d+)m", str(col))
        if m_amt:
            labels.append(f"{col}: 近{m_amt.group(1)}个月金额")
            continue
        labels.append(f"{col}: {schema_label_map.get(col, col)}")
    return labels[:12]


def _build_scope_note(*, question: str, query_plan: Dict[str, Any], planner_context: Dict[str, Any]) -> str:
    parts: List[str] = []
    if query_plan.get("query_goal_cn"):
        parts.append(str(query_plan.get("query_goal_cn") or ""))
    for key in ("time_window_policy", "business_scope", "metric_definition"):
        value = str(query_plan.get(key) or "").strip()
        if value:
            parts.append(value)
    exclusions = [str(x) for x in (query_plan.get("exclusions") or []) if str(x).strip()]
    if exclusions:
        parts.append("不包括" + "、".join(exclusions) + "。")
    if str(query_plan.get("question_type") or "") == "multi_window_summary":
        business_object = str(query_plan.get("business_object") or "")
        if business_object == "new_loan":
            if not str(query_plan.get("time_window_policy") or "").strip():
                parts.append("本次统计以报告日期为锚点，按账户开立日期判断新增贷款。")
            if not str(query_plan.get("business_scope") or "").strip():
                parts.append("贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户，不包括贷记卡、准贷记卡、被追偿信息及相关还款责任。")
            if not str(query_plan.get("metric_definition") or "").strip():
                parts.append("金额按 original_amount（借款金额）汇总，未混用授信额度；若部分循环类账户该字段为0，结果仅反映当前字段口径。")
            return " ".join(parts).strip()
        if business_object == "settled_loan":
            if not str(query_plan.get("time_window_policy") or "").strip():
                parts.append("本次统计以报告日期为锚点，按账户结清日期判断是否落入统计窗口。")
            if not str(query_plan.get("business_scope") or "").strip():
                parts.append("贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户，且账户状态为结清。")
            if not str(query_plan.get("metric_definition") or "").strip():
                parts.append("金额按被结清账户的原始借款金额 original_amount 汇总，未使用当前余额或授信额度。")
            return " ".join(parts).strip()
        if business_object == "overdue_record":
            if not str(query_plan.get("time_window_policy") or "").strip():
                parts.append("本次统计以报告日期为锚点，按账户-月份口径检查月度还款表现。")
            if not str(query_plan.get("metric_definition") or "").strip():
                parts.append("逾期次数按命中普通逾期条件的账户-月份记录数统计，逾期金额按 overdue_total 汇总。")
            if not exclusions:
                parts.append("普通逾期与 B/D/G 类特殊风险状态不混算。")
            return " ".join(parts).strip()
    if str(query_plan.get("business_object") or "") == "loan_five_classification":
        if not str(query_plan.get("business_scope") or "").strip():
            parts.append("贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户。")
        if not str(query_plan.get("metric_definition") or "").strip():
            parts.append("非正常五级分类指关注、次级、可疑、损失；当前部分按贷款账户五级分类判断，历史部分仅在结构化层存在可用历史五级分类记录时统计。")
        if not exclusions:
            parts.append("不包括贷记卡、准贷记卡、被追偿信息及相关还款责任。")
        return " ".join(parts).strip()
    if str(query_plan.get("business_object") or "") == "objection_in_transit":
        if not str(query_plan.get("business_scope") or "").strip():
            parts.append("统计对象包括首页异议信息提示中的报告级在途异议总数，以及异议/标注明细中的在处理期定位记录。")
        if not str(query_plan.get("metric_definition") or "").strip():
            parts.append("首页报告级在途异议总数优先从首页原文提取；结构化概要字段仅作对账参考。明细中的在处理期记录只用于定位，不直接替代首页总数。")
        if not exclusions:
            parts.append("信息缺失类提示不单独计作异议候选。")
        return " ".join(parts).strip()
    q = question or ""
    if "B/D/G" in q or "特殊风险" in q:
        parts.append("时间窗口统一以报告日期为锚点；本次检查基于月度还款表现中的还款状态字段。")
        parts.append("当前结果检查的是 repay_type_code 是否命中 B、D、G，不与 1-7 普通逾期状态混算。")
    elif "逾期" in q:
        parts.append("时间窗口统一以报告日期为锚点；本次结果仅代表本次 SQL 查询口径。")
        if "逾期账户有多少" in q or "逾期账户数" in q:
            parts.append("当前返回的是发生过逾期的去重账户数，不是按账户-月份统计的逾期记录数。")
    elif "未结清" in q or "未销户" in q:
        parts.append("当前未结清/未销户问题优先参考概要视图口径。")
    elif "查询" in q:
        parts.append("查询类问题需区分查询概要口径与查询明细口径。")
    elif "信用卡" in q:
        parts.append("信用卡相关字段需区分授信额度、已用额度与透支余额。")
    if not parts and planner_context.get("planner_rules"):
        parts.append(str(planner_context["planner_rules"][0]))
    return " ".join(parts).strip()


def _build_scope_facts(*, query_plan: Dict[str, Any], planner_context: Dict[str, Any]) -> Dict[str, Any]:
    exclusions = [str(x) for x in (query_plan.get("exclusions") or []) if str(x).strip()]
    return {
        "question_type": str(query_plan.get("question_type") or ""),
        "business_object": str(query_plan.get("business_object") or ""),
        "time_windows": [str(x) for x in (query_plan.get("time_windows") or []) if str(x).strip()],
        "metrics": [str(x) for x in (query_plan.get("metrics") or []) if str(x).strip()],
        "date_field": str(query_plan.get("date_field") or ""),
        "amount_field": str(query_plan.get("amount_field") or ""),
        "time_window_policy": str(query_plan.get("time_window_policy") or "").strip(),
        "business_scope": str(query_plan.get("business_scope") or "").strip(),
        "metric_definition": str(query_plan.get("metric_definition") or "").strip(),
        "exclusions": exclusions,
        "fallback_rule_hint": str((planner_context.get("planner_rules") or [""])[0] or "").strip(),
    }


def _accept_generated_sql_answer(
    *,
    question: str,
    query_plan: Dict[str, Any],
    query_result: Dict[str, Any],
    answer: str,
) -> bool:
    _ = question
    business_object = str(query_plan.get("business_object") or "")
    if business_object == "objection_in_transit":
        rows = list(query_result.get("rows") or [])
        row = dict(rows[0] or {}) if rows else {}
        report_level_count = row.get("report_level_in_transit_objection_count")
        detail_count = row.get("objection_in_transit_detail_count")
        answer_text = str(answer or "")
        if report_level_count not in (None, ""):
            report_level_text = str(int(report_level_count))
            if report_level_text not in answer_text:
                return False
        if detail_count not in (None, ""):
            detail_text = str(int(detail_count))
            if detail_text in answer_text and ("明细" not in answer_text and "定位" not in answer_text):
                return False
        if "总数" in answer_text and detail_count not in (None, "") and str(int(detail_count)) in answer_text and (
            report_level_count in (None, "") or str(int(report_level_count)) not in answer_text
        ):
            return False
    return True


def _build_limitation_note(
    *,
    question: str,
    query_plan: Dict[str, Any],
    query_result: Dict[str, Any],
    cannot_answer_reason: str,
) -> str:
    if cannot_answer_reason:
        return f"当前查询存在限制：{cannot_answer_reason}。"
    if query_result.get("truncated"):
        return "查询结果行数较多，当前回答基于截断后的结果摘要。"
    rows = list(query_result.get("rows") or [])
    if str(query_plan.get("question_type") or "") == "multi_window_summary":
        if str(query_plan.get("business_object") or "") == "new_loan":
            return "时间窗口为嵌套窗口（近1个月包含在近3个月内，近3个月包含在近6个月内）；金额按借款金额字段 original_amount 汇总。"
        if str(query_plan.get("business_object") or "") == "settled_loan":
            return "时间窗口为嵌套窗口（近1个月包含在近3个月内，近3个月包含在近6个月内）；当前按 close_date 统计结清时点，金额按 original_amount 汇总。"
        if str(query_plan.get("business_object") or "") == "overdue_record":
            return "时间窗口为嵌套窗口；逾期次数按账户-月份记录数统计，不是去重账户数，也不是对 overdue_months 求和。"
    if str(query_plan.get("business_object") or "") == "objection_in_transit":
        return "首页异议概要为总提示，异议明细用于定位和解释；明细条数不直接替代首页异议总数。"
    if str(query_plan.get("business_object") or "") == "loan_five_classification":
        return "当前五级分类可直接判断；历史部分仅能基于当前结构化层已展开的历史五级分类字段统计，若历史记录为0，不等于业务上绝对不存在。"
    if not rows:
        if "B/D/G" in question or "特殊风险" in question:
            return "本次 SQL 未查询到还款状态为 B、D 或 G 的月度记录。"
        return "本次 SQL 未查询到符合条件的数据。"
    q = question or ""
    sql = str(query_result.get("sql") or query_plan.get("sql") or "")
    if ("逾期账户有多少" in q or "逾期账户数" in q) and "COUNT(DISTINCT account_id) AS overdue_account_count" in sql:
        return "这类问法存在口径歧义：当前结果是去重账户数；如果按账户-月份口径统计普通逾期记录数，结果会不同，需单独查询。"
    return ""


def _plan_sql_locally(*, question: str, previous_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    q = question or ""
    months = _extract_window_months(q)
    window_list = _extract_window_months_list(q)
    if ("新增贷款" in q) and len(window_list) > 1 and ("笔数" in q or "金额" in q):
        return _build_multi_window_new_loan_plan(window_list)
    if ("结清贷款" in q or "已结清贷款" in q or "结清的贷款" in q) and len(window_list) > 1 and ("笔数" in q or "金额" in q):
        return _build_multi_window_settled_loan_plan(window_list)
    if ("逾期" in q) and len(window_list) > 1 and ("次数" in q and "金额" in q):
        return _build_multi_window_overdue_plan(window_list)
    if "异议" in q:
        return _build_objection_in_transit_plan(q)
    if "五级分类" in q:
        return _build_five_classification_plan(q)
    if "B/D/G" in q or "特殊风险" in q:
        return {
            "sql": (
                "SELECT account_category, account_id, period_date, repay_type, repay_type_code "
                "FROM account_history "
                f"WHERE period_date >= date((SELECT report_date FROM v_report_context), '-{months} months') "
                f"AND period_date <= date((SELECT report_date FROM v_report_context)) "
                "AND repay_type_code IN ('B','D','G') "
                "ORDER BY period_date DESC, account_id"
            ),
            "query_goal_cn": f"检查近{months}个月内月度还款表现是否命中 B/D/G 类特殊风险状态，并返回命中明细",
            "time_window_policy": f"本次检查以报告日期为锚点，覆盖近{months}个月窗口内各账户的月度还款表现。",
            "business_scope": "统计对象为各账户的月度还款表现记录。",
            "metric_definition": "B/D/G 按还款状态字段进行命中判断，不与 1–7 逾期状态合并计算；只要任一账户任一月份出现 B、D 或 G，即判断为存在特殊风险状态。",
            "exclusions": ["1–7 普通逾期状态"],
            "used_previous_context": False,
            "notes": ["local_fallback_sql"],
        }
    if "当前未结清账户" in q and ("多少" in q or "几个" in q or "账户数" in q):
        return {
            "sql": (
                "SELECT outstanding_account_count_total, "
                "outstanding_compensation_account_count, "
                "outstanding_credit_account_count, "
                "total_obligation_account_count "
                "FROM v_outstanding_summary"
            ),
            "query_goal_cn": "查询当前未结清/未销户账户总数及扩展口径账户数",
            "used_previous_context": False,
            "notes": ["local_fallback_sql"],
        }
    if "当前未结清账户余额" in q or ("未结清账户" in q and "余额" in q):
        return {
            "sql": (
                "SELECT outstanding_account_balance_total, "
                "outstanding_compensation_balance, "
                "outstanding_credit_account_balance, "
                "related_repayment_responsibility_balance, "
                "liability_balance_total_including_related_responsibility "
                "FROM v_outstanding_summary"
            ),
            "query_goal_cn": "查询当前未结清/未销户账户余额及扩展口径余额",
            "used_previous_context": False,
            "notes": ["local_fallback_sql"],
        }
    if "逾期账户有多少" in q:
        return {
            "sql": (
                "SELECT COUNT(DISTINCT account_id) AS overdue_account_count "
                "FROM account_history "
                f"WHERE overdue_total > 0 "
                f"AND period_date >= date((SELECT report_date FROM v_report_context), '-{months} months') "
                f"AND period_date <= date((SELECT report_date FROM v_report_context))"
            ),
            "query_goal_cn": f"统计近{months}个月逾期账户数",
            "used_previous_context": False,
            "notes": ["local_fallback_sql"],
        }
    if "这些账户" in q and ("分类" in q or "多少钱" in q) and (previous_context.get("last_account_set_sql") or previous_context.get("last_sql")):
        base_sql = str(previous_context.get("last_account_set_sql") or previous_context.get("last_sql") or "")
        return {
            "sql": (
                "SELECT ca.loan_classification, COUNT(DISTINCT ca.account_id) AS account_count, "
                "ROUND(SUM(COALESCE(ca.balance, 0)), 2) AS total_balance "
                "FROM credit_account ca "
                "WHERE ca.account_id IN ("
                f"SELECT DISTINCT account_id FROM ({base_sql}) AS prev"
                ") "
                "GROUP BY ca.loan_classification "
                "ORDER BY total_balance DESC"
            ),
            "query_goal_cn": "沿用上一轮账户范围，按贷款分类汇总账户数和余额",
            "used_previous_context": True,
            "notes": ["local_followup_sql"],
        }
    return None


def _build_multi_window_new_loan_plan(window_list: List[int]) -> Dict[str, Any]:
    windows = sorted(set(int(x) for x in window_list))
    report_date_expr = "date((SELECT report_date FROM v_report_context))"
    select_parts: List[str] = []
    for months in windows:
        lower_expr = f"date({report_date_expr}, '-{months} months')"
        cond = f"(date(open_date) >= {lower_expr} AND date(open_date) <= {report_date_expr})"
        select_parts.append(f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS cnt_{months}m")
        select_parts.append(f"ROUND(SUM(CASE WHEN {cond} THEN COALESCE(original_amount, 0) ELSE 0 END), 2) AS amt_{months}m")
    sql = (
        "SELECT "
        + ", ".join(select_parts)
        + " FROM credit_account "
          "WHERE account_category IN ('非循环贷账户','循环额度下分账户','循环贷账户') "
          "AND open_date IS NOT NULL AND open_date <> '' "
          f"AND date(open_date) <= {report_date_expr}"
    )
    return {
        "question_type": "multi_window_summary",
        "business_object": "new_loan",
        "time_windows": [f"{m}m" for m in windows],
        "metrics": ["count", "amount_sum"],
        "date_field": "open_date",
        "amount_field": "original_amount",
        "time_window_policy": "本次统计以报告日期为锚点，近1个月、近3个月、近6个月均为从报告日期向前精准倒推的嵌套时间窗口，并按开立日期落入窗口判断。",
        "business_scope": "贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户。",
        "metric_definition": "新增贷款笔数按账户数统计，新增贷款金额按借款金额字段 original_amount 汇总；当前按借款金额统计，未混用授信额度。",
        "exclusions": ["贷记卡账户", "准贷记卡账户", "被追偿信息", "相关还款责任"],
        "filters": {
            "account_scope": ["非循环贷账户", "循环额度下分账户", "循环贷账户"],
            "exclude": ["贷记卡账户", "准贷记卡账户", "被追偿信息", "相关还款责任"],
        },
        "sql": sql,
        "query_goal_cn": f"统计近{ '、'.join(str(m) for m in windows) }个月新增贷款笔数和新增贷款金额",
        "used_previous_context": False,
        "notes": ["local_multi_window_summary"],
    }


def _build_multi_window_settled_loan_plan(window_list: List[int]) -> Dict[str, Any]:
    windows = sorted(set(int(x) for x in window_list))
    report_date_expr = "date((SELECT report_date FROM v_report_context))"
    select_parts: List[str] = []
    for months in windows:
        lower_expr = f"date({report_date_expr}, '-{months} months')"
        cond = (
            f"(date(close_date) >= {lower_expr} AND date(close_date) <= {report_date_expr} "
            "AND COALESCE(account_status, '') = '结清')"
        )
        select_parts.append(f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS cnt_{months}m")
        select_parts.append(f"ROUND(SUM(CASE WHEN {cond} THEN COALESCE(original_amount, 0) ELSE 0 END), 2) AS amt_{months}m")
    sql = (
        "SELECT "
        + ", ".join(select_parts)
        + " FROM credit_account "
          "WHERE account_category IN ('非循环贷账户','循环额度下分账户','循环贷账户') "
          "AND close_date IS NOT NULL AND close_date <> '' "
          f"AND date(close_date) <= {report_date_expr}"
    )
    return {
        "question_type": "multi_window_summary",
        "business_object": "settled_loan",
        "time_windows": [f"{m}m" for m in windows],
        "metrics": ["count", "amount_sum"],
        "date_field": "close_date",
        "amount_field": "original_amount",
        "time_window_policy": "本次统计以报告日期为锚点，近1个月、近3个月、近6个月均为从报告日期向前精准倒推的嵌套时间窗口，并按结清日期落入窗口判断。",
        "business_scope": "贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户，且账户状态为结清。",
        "metric_definition": "结清贷款笔数按账户数统计，结清贷款合计金额按被结清账户的原始借款金额 original_amount 汇总；当前未使用当前余额或授信额度。",
        "exclusions": ["贷记卡账户", "准贷记卡账户", "被追偿信息", "相关还款责任"],
        "filters": {
            "account_scope": ["非循环贷账户", "循环额度下分账户", "循环贷账户"],
            "status_condition": "account_status = '结清'",
            "exclude": ["贷记卡账户", "准贷记卡账户", "被追偿信息", "相关还款责任"],
        },
        "sql": sql,
        "query_goal_cn": f"统计近{ '、'.join(str(m) for m in windows) }个月结清贷款笔数和结清贷款合计金额",
        "used_previous_context": False,
        "notes": ["local_multi_window_summary"],
    }


def _build_five_classification_plan(question: str) -> Dict[str, Any]:
    include_history = ("历史" in question) or ("当前和历史" in question)
    loan_scope = "account_category IN ('非循环贷账户','循环额度下分账户','循环贷账户')"
    non_normal = "('关注','次级','可疑','损失')"
    sql = (
        "SELECT "
        f"(SELECT COUNT(DISTINCT account_id) FROM credit_account WHERE {loan_scope} AND five_classification IN {non_normal}) AS current_non_normal_account_count, "
        f"(SELECT COUNT(*) FROM account_history WHERE account_id IN (SELECT account_id FROM credit_account WHERE {loan_scope}) AND five_classification IN {non_normal}) AS historical_non_normal_record_count, "
        f"(SELECT COUNT(DISTINCT account_id) FROM account_history WHERE account_id IN (SELECT account_id FROM credit_account WHERE {loan_scope}) AND five_classification IN {non_normal}) AS historical_affected_account_count, "
        f"(SELECT COUNT(DISTINCT account_id) FROM credit_account WHERE {loan_scope} AND five_classification = '关注') AS current_attention_count, "
        f"(SELECT COUNT(DISTINCT account_id) FROM credit_account WHERE {loan_scope} AND five_classification = '次级') AS current_substandard_count, "
        f"(SELECT COUNT(DISTINCT account_id) FROM credit_account WHERE {loan_scope} AND five_classification = '可疑') AS current_doubtful_count, "
        f"(SELECT COUNT(DISTINCT account_id) FROM credit_account WHERE {loan_scope} AND five_classification = '损失') AS current_loss_count"
    )
    return {
        "question_type": "status_existence_check",
        "business_object": "loan_five_classification",
        "metrics": ["exists", "count", "distribution"],
        "date_field": "",
        "amount_field": "",
        "time_window_policy": "当前五级分类按当前账户状态判断；如问题涉及历史记录，仅在结构化层存在可用历史五级分类记录时才统计历史结果。",
        "business_scope": "贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户。",
        "metric_definition": "非正常五级分类指关注、次级、可疑、损失；当前部分按贷款账户的 five_classification 判断，历史部分按 account_history 中可用的五级分类记录统计。",
        "exclusions": ["贷记卡账户", "准贷记卡账户", "被追偿信息", "相关还款责任"],
        "filters": {
            "account_scope": ["非循环贷账户", "循环额度下分账户", "循环贷账户"],
            "non_normal_values": ["关注", "次级", "可疑", "损失"],
            "include_history": include_history,
        },
        "sql": sql,
        "query_goal_cn": "检查贷款五级分类是否存在非正常状态，并统计当前分布及历史记录命中情况",
        "used_previous_context": False,
        "notes": ["local_five_classification_check"],
    }


def _build_objection_in_transit_plan(question: str) -> Dict[str, Any]:
    return {
        "question_type": "status_existence_check",
        "business_object": "objection_in_transit",
        "metrics": ["exists", "count"],
        "date_field": "",
        "amount_field": "",
        "time_window_policy": "本次判断基于报告当前展示的异议概要与异议标注明细，不涉及金额统计。",
        "business_scope": "统计对象包括首页异议信息提示中的报告级在途异议总数，以及异议/标注明细中的在处理期定位记录。",
        "metric_definition": "首页报告级在途异议总数优先从首页原文提取；结构化概要字段仅用于对账。异议明细中的 is_in_transit 只用于定位在处理期记录，不直接替代首页总数。",
        "exclusions": ["information_missing_annotation 类信息缺失提示不单独作为异议候选计数"],
        "filters": {
            "report_level_source": "homepage_text_or_pa01es01",
            "structured_summary_metric_key": "PG010S01",
            "detail_in_transit_field": "is_in_transit",
            "detail_keywords": ["处理期", "处理中", "异议处理"],
        },
        "sql": (
            "SELECT "
            "(SELECT COALESCE(SUM(COALESCE(metric_value, 0)), 0) FROM credit_summary WHERE metric_key = 'PG010S01') AS structured_objection_count_summary, "
            "(SELECT COUNT(*) FROM objection_record WHERE COALESCE(is_in_transit, 0) = 1) AS objection_in_transit_detail_count, "
            "(SELECT COUNT(*) FROM objection_record WHERE COALESCE(is_objection_candidate, 0) = 1) AS objection_candidate_detail_count, "
            "CASE "
            "WHEN (SELECT COALESCE(SUM(COALESCE(metric_value, 0)), 0) FROM credit_summary WHERE metric_key = 'PG010S01') > 0 "
            "  OR (SELECT COUNT(*) FROM objection_record WHERE COALESCE(is_in_transit, 0) = 1) > 0 "
            "THEN 1 ELSE 0 END AS has_in_transit_objection"
        ),
        "query_goal_cn": "判断是否存在在途征信异议，并区分首页报告级异议总数、结构化概要对账值与在途异议明细定位数",
        "used_previous_context": False,
        "notes": ["local_objection_in_transit_check"],
    }


def _build_multi_window_overdue_plan(window_list: List[int]) -> Dict[str, Any]:
    windows = sorted(set(int(x) for x in window_list))
    report_date_expr = "date((SELECT report_date FROM v_report_context))"
    overdue_cond = "(repay_type_code IN ('1','2','3','4','5','6','7') OR COALESCE(overdue_total, 0) > 0 OR COALESCE(overdue_months, 0) > 0)"
    select_parts: List[str] = []
    for months in windows:
        lower_expr = f"date({report_date_expr}, '-{months} months')"
        cond = f"(date(period_date) >= {lower_expr} AND date(period_date) <= {report_date_expr} AND {overdue_cond})"
        select_parts.append(f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS cnt_{months}m")
        select_parts.append(f"ROUND(SUM(CASE WHEN {cond} THEN COALESCE(overdue_total, 0) ELSE 0 END), 2) AS amt_{months}m")
    sql = (
        "SELECT "
        + ", ".join(select_parts)
        + " FROM account_history "
          "WHERE period_date IS NOT NULL AND period_date <> '' "
          f"AND date(period_date) <= {report_date_expr}"
    )
    return {
        "question_type": "multi_window_summary",
        "business_object": "overdue_record",
        "time_windows": [f"{m}m" for m in windows],
        "metrics": ["count", "amount_sum"],
        "date_field": "period_date",
        "amount_field": "overdue_total",
        "time_window_policy": "本次统计以报告日期为锚点，按近X个月精准时间窗口统计月度还款表现。",
        "business_scope": "统计对象为各账户的月度还款表现记录。",
        "metric_definition": "逾期次数按账户-月份计数，即同一账户同一月份命中普通逾期条件计为1次；还款状态数字仅表示逾期程度，不直接累加。逾期金额按对应月份的逾期/透支总额汇总。",
        "exclusions": ["B/D/G 类特殊风险状态"],
        "filters": {
            "overdue_scope": "ordinary_overdue_only",
            "exclude": ["B/D/G 类特殊风险状态"],
        },
        "sql": sql,
        "query_goal_cn": f"统计近{ '、'.join(str(m) for m in windows) }个月普通逾期次数和逾期/透支金额",
        "used_previous_context": False,
        "notes": ["local_multi_window_summary"],
    }


def _fmt_value(v: Any) -> str:
    if isinstance(v, float):
        if float(v).is_integer():
            return str(int(v))
        return f"{v:,.2f}"
    if isinstance(v, int):
        return str(v)
    return str(v)


def _fmt_amount(v: Any) -> str:
    try:
        num = float(v or 0)
    except Exception:
        return str(v)
    if num.is_integer():
        return f"{int(num):,}"
    return f"{num:,.2f}"


def _window_label_from_token(token: str) -> str:
    m = re.fullmatch(r"(\d+)m", str(token or ""))
    if not m:
        return str(token or "")
    return f"近{m.group(1)}个月"


def _build_local_sql_answer(*, question: str, query_plan: Dict[str, Any], query_result: Dict[str, Any], cannot_answer_reason: str) -> str:
    if cannot_answer_reason:
        return f"SQL 查询执行失败，当前无法回答。原因：{cannot_answer_reason}。"
    rows = list(query_result.get("rows") or [])
    columns = list(query_result.get("columns") or [])
    if not rows:
        if "B/D/G" in question or "特殊风险" in question:
            return (
                "近2年内未发现 B/D/G 类特殊风险状态。"
                "本次检查以报告日期为锚点，逐账户逐月份扫描月度还款表现中的还款状态字段，未发现状态为 B、D 或 G 的记录。"
            )
        return "未查询到符合条件的数据。"
    if str(query_plan.get("question_type") or "") == "multi_window_summary":
        row = rows[0] if rows else {}
        business_object = str(query_plan.get("business_object") or "")
        time_windows = [str(x) for x in (query_plan.get("time_windows") or []) if str(x).strip()]
        if business_object == "new_loan":
            lines = ["| 时间窗口 | 新增贷款笔数 | 新增贷款金额 |", "|---|---:|---:|"]
            for token in time_windows:
                m = re.fullmatch(r"(\d+)m", token)
                if not m:
                    continue
                months = m.group(1)
                cnt = _fmt_value(row.get(f"cnt_{months}m"))
                amt = _fmt_amount(row.get(f"amt_{months}m"))
                lines.append(f"| {_window_label_from_token(token)} | {cnt}笔 | {amt}元 |")
            lines.append("")
            lines.append("本次统计以报告日期为锚点，按账户开立日期判断新增贷款。近1个月、近3个月、近6个月均为从报告日期向前精准倒推的嵌套时间窗口。贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户，不包括贷记卡、准贷记卡、被追偿信息及相关还款责任。金额按借款金额汇总，未混用授信额度。")
            return "\n".join(lines)
        if business_object == "settled_loan":
            lines = ["| 时间窗口 | 结清贷款笔数 | 结清贷款合计金额 |", "|---|---:|---:|"]
            for token in time_windows:
                m = re.fullmatch(r"(\d+)m", token)
                if not m:
                    continue
                months = m.group(1)
                cnt = _fmt_value(row.get(f"cnt_{months}m"))
                amt = _fmt_amount(row.get(f"amt_{months}m"))
                lines.append(f"| {_window_label_from_token(token)} | {cnt}笔 | {amt}元 |")
            lines.append("")
            lines.append("本次统计以报告日期为锚点，按账户结清日期判断是否落入统计窗口；近1个月、近3个月、近6个月为嵌套窗口。贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户，不包括贷记卡、准贷记卡、被追偿信息及相关还款责任。金额按被结清账户的原始借款金额汇总，未使用当前余额或授信额度。")
            return "\n".join(lines)
        if business_object == "overdue_record":
            lines = ["| 时间窗口 | 逾期次数 | 逾期/透支金额 |", "|---|---:|---:|"]
            for token in time_windows:
                m = re.fullmatch(r"(\d+)m", token)
                if not m:
                    continue
                months = m.group(1)
                cnt = _fmt_value(row.get(f"cnt_{months}m"))
                amt = _fmt_amount(row.get(f"amt_{months}m"))
                lines.append(f"| {_window_label_from_token(token)} | {cnt}次 | {amt}元 |")
            lines.append("")
            lines.append("本次统计以报告日期为锚点，按精准时间窗口统计月度还款表现。逾期次数按账户-月份计数，即同一账户同一月份命中普通逾期条件计为1次；还款状态数字仅表示逾期程度，不直接累加。逾期/透支金额按对应月份的逾期/透支总额汇总，不与 B/D/G 类特殊风险状态混算。")
            return "\n".join(lines)
    if str(query_plan.get("business_object") or "") == "loan_five_classification":
        row = rows[0] if rows else {}
        current_count = int(row.get("current_non_normal_account_count") or 0)
        hist_record_count = int(row.get("historical_non_normal_record_count") or 0)
        hist_account_count = int(row.get("historical_affected_account_count") or 0)
        attention = int(row.get("current_attention_count") or 0)
        substandard = int(row.get("current_substandard_count") or 0)
        doubtful = int(row.get("current_doubtful_count") or 0)
        loss = int(row.get("current_loss_count") or 0)
        lines: List[str] = []
        if current_count > 0:
            lines.append(f"当前贷款账户存在非正常五级分类，共 {current_count} 个账户。")
            dist_parts = []
            if attention:
                dist_parts.append(f"关注 {attention} 个")
            if substandard:
                dist_parts.append(f"次级 {substandard} 个")
            if doubtful:
                dist_parts.append(f"可疑 {doubtful} 个")
            if loss:
                dist_parts.append(f"损失 {loss} 个")
            if dist_parts:
                lines.append("当前分布为：" + "，".join(dist_parts) + "。")
        else:
            lines.append("当前贷款账户未发现非正常五级分类。")
        if "历史" in question or "当前和历史" in question:
            if hist_record_count > 0:
                lines.append(f"历史记录中发现非正常五级分类记录 {hist_record_count} 条，涉及 {hist_account_count} 个账户。")
            else:
                lines.append("历史记录部分，当前结构化数据未识别到非正常五级分类历史记录。")
                lines.append("这表示当前结构化层未发现可直接命中的历史非正常五级分类记录，不等于业务上可以据此认定历史绝对不存在。")
        lines.append("本次判断的贷款范围包括非循环贷账户、循环额度下分账户和循环贷账户，不包括贷记卡、准贷记卡、被追偿信息及相关还款责任。")
        return "\n".join(lines)
    if str(query_plan.get("business_object") or "") == "objection_in_transit":
        row = rows[0] if rows else {}
        report_level_count = row.get("report_level_in_transit_objection_count")
        report_level_count = int(report_level_count) if report_level_count not in (None, "") else None
        structured_count = int(row.get("structured_objection_count_summary") or 0)
        in_transit_count = int(row.get("objection_in_transit_detail_count") or 0)
        candidate_count = int(row.get("objection_candidate_detail_count") or 0)
        has_flag = int(row.get("has_in_transit_objection") or 0)
        summary_match = row.get("summary_matches_report_level")
        if has_flag > 0:
            lines = ["存在在途征信异议。"]
            if report_level_count is not None:
                lines.append(f"首页异议信息提示识别到报告级在途异议总数为 {report_level_count} 条；异议明细中定位到 {in_transit_count} 条处于异议处理期的记录。")
            else:
                lines.append(f"首页原文未能稳定抽取报告级在途异议总数；异议明细中定位到 {in_transit_count} 条处于异议处理期的记录。")
            lines.append(f"结构化异议概要对账值为 {structured_count} 条。")
            if summary_match in (0, "0"):
                lines.append("首页报告级总数与结构化异议概要值不一致，当前优先采用首页提示口径。")
            if candidate_count and candidate_count != in_transit_count:
                lines.append(f"另外，异议候选明细共 {candidate_count} 条，部分为非在途提示。")
            lines.append("本次判断优先依据首页异议信息提示中的报告级在途异议总数，以及异议明细中的“处理中/处理期”定位标识；明细定位条数不直接替代首页总数。")
            return "\n".join(lines)
        return "未发现明确的在途征信异议。当前判断优先依据首页异议概要与异议明细中的在处理期标识；若后续补充到更完整的异议字段，结果可能进一步校正。"
    if "B/D/G" in question or "特殊风险" in question:
        lines = ["近2年内存在 B/D/G 类特殊风险状态。"]
        lines.append("本次检查以报告日期为锚点，逐账户逐月份扫描月度还款表现中的还款状态字段。")
        lines.append("命中明细如下：")
        for row in rows[:8]:
            account_category = _fmt_value(row.get("account_category"))
            account_id = _fmt_value(row.get("account_id"))
            period_date = _fmt_value(row.get("period_date"))
            repay_type = _fmt_value(row.get("repay_type"))
            lines.append(f"- {account_category}，账户 {account_id}，{period_date}，还款状态 {repay_type}")
        if len(rows) > 8:
            lines.append(f"另有 {len(rows) - 8} 条命中记录未在正文展开。")
        lines.append("当前口径单独检查 B/D/G 类特殊风险状态，不与 1-7 普通逾期状态混算。")
        return "\n".join(lines)
    if len(rows) == 1 and len(columns) == 1:
        col = columns[0]
        label = COLUMN_LABELS.get(col, col)
        if col == "overdue_account_count" and ("逾期账户有多少" in question or "逾期账户数" in question):
            return (
                f"{label}为 {_fmt_value(rows[0].get(col))}。"
                "当前返回的是发生过逾期的去重账户数，不是按账户-月份统计的逾期记录数。"
                "如果需要记录口径，应单独查询“逾期记录有多少条”。"
            )
        return f"{label}为 {_fmt_value(rows[0].get(col))}。"
    if len(rows) == 1:
        parts = [f"{COLUMN_LABELS.get(col, col)}={_fmt_value(rows[0].get(col))}" for col in columns]
        return "查询结果如下：" + "；".join(parts) + "。"
    preview = rows[:8]
    lines = ["已执行 SQL 查询，结果摘要如下："]
    for row in preview:
        parts = [f"{COLUMN_LABELS.get(col, col)}={_fmt_value(row.get(col))}" for col in columns]
        lines.append("- " + "；".join(parts))
    if query_result.get("truncated"):
        lines.append("结果行数较多，前端元数据中保留了更多明细。")
    return "\n".join(lines)


def _build_local_extraction_answer(*, question: str, snippets: List[Dict[str, str]]) -> str:
    return _build_local_extraction_answer_with_fields(question=question, structured_fields=[], snippets=snippets)


def _build_local_extraction_answer_with_fields(*, question: str, structured_fields: List[Dict[str, Any]], snippets: List[Dict[str, str]]) -> str:
    if structured_fields:
        lines: List[str] = []
        raw = question.replace("\\n", "\n")
        if "基本信息" in raw or "身份信息" in raw:
            lines.append("一、基本信息")
            lines.append("")
            lines.append("身份信息：")
        for item in structured_fields:
            lines.append(f"- {item.get('requested_label')}：{item.get('value')}")
        if snippets:
            lines.append("")
            lines.append("补充说明：以上字段优先取自 XML 解析后的结构化字段，PDF 展示内容用于补充校验。")
        return "\n".join(lines).strip()
    if not snippets:
        return "当前没有定位到可直接提取的报告模块。请换一种更明确的问法，或指定要提取“基本信息”“信息概要”“查询记录概要”等模块。"
    lines = ["已定位到相关报告模块，以下为直接提取内容："]
    for item in snippets[:4]:
        title = str(item.get("module_name_cn") or item.get("module") or "")
        text = str(item.get("text") or "").strip()
        preview = text[:1200].strip()
        lines.append(f"\n【{title}】\n{preview}")
    lines.append("\n当前为展示层直接提取结果，未对字段做重新计算。")
    return "\n".join(lines)


def _flatten_enriched_field_pool(report_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def add_entry(*, table_code: str, path: str, field_obj: Dict[str, Any]) -> None:
        field_name = str(field_obj.get("field_name") or "").strip()
        if not field_name:
            return
        value = field_obj.get("value")
        label = field_obj.get("label")
        display_value = label if label not in (None, "") else value
        if isinstance(display_value, (list, dict)) or display_value in (None, ""):
            return
        out.append(
            {
                "table_code": table_code,
                "field_code": str(field_obj.get("field_code") or ""),
                "field_name": field_name,
                "value": str(display_value),
                "raw_value": value,
                "label": label,
                "path": path,
            }
        )

    tables = (report_json.get("tables") or {}) if isinstance(report_json, dict) else {}
    for table_code, table_obj in tables.items():
        fields = (table_obj or {}).get("fields") or {}
        for field_code, field_obj in fields.items():
            if isinstance(field_obj, dict):
                add_entry(table_code=str(table_code), path=f"tables.{table_code}.fields.{field_code}", field_obj=field_obj)
        for record_idx, record in enumerate((table_obj or {}).get("records") or [], 1):
            record_fields = (record or {}).get("fields") or {}
            for field_code, field_obj in record_fields.items():
                if isinstance(field_obj, dict):
                    add_entry(
                        table_code=str(table_code),
                        path=f"tables.{table_code}.records[{record_idx}].fields.{field_code}",
                        field_obj=field_obj,
                    )
    return out


def _resolve_structured_extract_fields(*, question: str, report_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    pool = _flatten_enriched_field_pool(report_json)
    if not pool:
        return []
    results: List[Dict[str, Any]] = []
    normalized_question = re.sub(r"\s+", "", str(question or ""))
    for spec in EXTRACT_FIELD_SPECS:
        aliases = [str(x) for x in spec.get("aliases") or []]
        if not any(alias in normalized_question for alias in aliases):
            # fuzzy fallback for slight typos, e.g. 证件累心
            if max((SequenceMatcher(None, alias, normalized_question).ratio() for alias in aliases), default=0.0) < 0.18:
                continue
        match = _find_best_field_match(spec=spec, pool=pool)
        if not match:
            continue
        results.append(
            {
                "requested_label": spec.get("requested_label"),
                "field_name": match.get("field_name"),
                "value": match.get("value"),
                "source": "xml_structured",
                "path": match.get("path"),
            }
        )
    return results


def _find_best_field_match(*, spec: Dict[str, Any], pool: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    preferred_names = [str(x) for x in spec.get("preferred_names") or []]
    for name in preferred_names:
        exact = [item for item in pool if str(item.get("field_name") or "") == name]
        if exact:
            return exact[0]
    requested_label = str(spec.get("requested_label") or "")
    scored: List[tuple[float, Dict[str, Any]]] = []
    for item in pool:
        fname = str(item.get("field_name") or "")
        score = SequenceMatcher(None, requested_label, fname).ratio()
        if score >= 0.45:
            scored.append((score, item))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _derive_followup_scope_sql(*, question: str, query_plan: Dict[str, Any], query_result: Dict[str, Any]) -> str:
    q = str(question or "")
    sql = str(query_result.get("sql") or query_plan.get("sql") or "").strip()
    if not sql:
        return ""
    if "逾期账户有多少" in q and "COUNT(DISTINCT account_id) AS overdue_account_count" in sql:
        months = _extract_window_months(q)
        return (
            "SELECT DISTINCT account_id "
            "FROM account_history "
            "WHERE overdue_total > 0 "
            f"AND period_date >= date((SELECT report_date FROM v_report_context), '-{months} months') "
            "AND period_date <= date((SELECT report_date FROM v_report_context))"
        )
    return ""
