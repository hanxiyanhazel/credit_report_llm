from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
from config import SETTINGS, Settings
from prompt_templates import (
    EXTRACTION_ANSWER_SYSTEM_PROMPT,
    QUESTION_ROUTER_SYSTEM_PROMPT,
    SQL_ANSWER_SYSTEM_PROMPT,
    SQL_PLANNER_SYSTEM_PROMPT,
)


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def build_sql_planner_prompt(payload: Dict[str, Any]) -> str:
    question = str(payload.get("question") or "")
    planner_rules = [str(x) for x in (payload.get("planner_rules") or []) if str(x).strip()]
    previous_context = payload.get("previous_context") or {}
    recent_messages = payload.get("recent_messages") or []
    report_context = payload.get("report_context") or {}
    available_tables = payload.get("available_tables") or []
    available_views = payload.get("available_views") or []
    planner_rules_text = "\n".join(f"- {x}" for x in planner_rules) if planner_rules else "- 无"
    previous_context_text = json.dumps(previous_context, ensure_ascii=False, indent=2) if previous_context else "{}"
    recent_messages_text = json.dumps(recent_messages, ensure_ascii=False, indent=2) if recent_messages else "[]"
    report_context_text = json.dumps(report_context, ensure_ascii=False, indent=2) if report_context else "{}"
    tables_text = _format_available_tables(available_tables)
    views_text = _format_available_views(available_views)
    return (
        f"【用户问题】\n{question}\n\n"
        f"【最近对话】\n{recent_messages_text}\n\n"
        f"【previous_context】\n{previous_context_text}\n\n"
        f"【report_context】\n{report_context_text}\n\n"
        f"【可用表】\n{tables_text}\n\n"
        f"【可用视图】\n{views_text}\n\n"
        f"【本题查询规则】\n{planner_rules_text}\n\n"
        "【规划要求】\n"
        "1. 直接生成一条能回答问题的 SQLite 查询。\n"
        "2. 如果是追问，优先复用 previous_context 对应的上一轮范围。\n"
        "3. 尽量优先使用可用视图；只有视图不够时，再查基础表。\n"
        "4. 如果问题同时包含多个时间窗口和多个指标，优先用一条 CASE 聚合 SQL 一次返回多个窗口结果。\n"
        "5. 结果列请使用有业务意义的英文别名，如 overdue_account_count, total_balance, cnt_1m, amt_1m。\n"
        "6. 返回 JSON，不要返回解释文本。"
    )


def build_question_router_prompt(payload: Dict[str, Any]) -> str:
    question = str(payload.get("question") or "")
    recent_messages = payload.get("recent_messages") or []
    recent_messages_text = json.dumps(recent_messages, ensure_ascii=False, indent=2) if recent_messages else "[]"
    return (
        f"【用户问题】\n{question}\n\n"
        f"【最近对话】\n{recent_messages_text}\n\n"
        "【判断要求】\n"
        "1. 如果用户主要是在要报告展示内容本身，优先输出 extract。\n"
        "2. 如果用户主要是在要统计、合计、近X个月计算、分组汇总，优先输出 sql。\n"
        "3. 如果用户主要是在问口径、字段含义、说明文字，优先输出 explain。\n"
        "4. 只有 mode=extract 时才填写 target_modules。"
    )


def build_sql_answer_prompt(payload: Dict[str, Any]) -> str:
    question = str(payload.get("question") or "")
    sql = str(payload.get("sql") or "")
    raw_query_result = dict(payload.get("query_result") or {})
    query_result = {k: v for k, v in raw_query_result.items() if k != "sql"}
    field_labels = [str(x) for x in (payload.get("field_labels") or []) if str(x).strip()]
    scope_note = str(payload.get("scope_note") or "").strip()
    scope_facts = dict(payload.get("scope_facts") or {})
    limitation_note = str(payload.get("limitation_note") or "").strip()
    preferred_format = str(payload.get("preferred_format") or "").strip()
    field_labels_text = "\n".join(f"- {x}" for x in field_labels) if field_labels else "- 无"
    exclusions = [str(x) for x in (scope_facts.get("exclusions") or []) if str(x).strip()]
    scope_lines = [
        f"- 时间窗口口径：{str(scope_facts.get('time_window_policy') or '').strip() or '未提供'}",
        f"- 业务对象口径：{str(scope_facts.get('business_scope') or '').strip() or '未提供'}",
        f"- 指标计算口径：{str(scope_facts.get('metric_definition') or '').strip() or '未提供'}",
        f"- 排除范围或限制：{'、'.join(exclusions) if exclusions else '无明确排除范围'}",
    ]
    scope_facts_text = "\n".join(scope_lines)
    business_object = str(scope_facts.get("business_object") or "")
    special_output_rules = ""
    if business_object == "objection_in_transit":
        special_output_rules = (
            "\n【本题特别要求】\n"
            "1. 如果查询结果同时提供“首页报告级在途异议总数”和“明细定位条数”，必须优先以首页报告级总数回答是否存在在途异议。\n"
            "2. objection_in_transit_detail_count 仅表示明细中定位到的在处理期记录条数，不得表述为异议总数。\n"
            "3. structured_objection_count_summary 仅表示结构化概要对账值，不得替代首页报告级总数。\n"
            "4. 如首页总数与结构化概要对账值不一致，应明确说明当前优先采用首页提示口径。\n"
        )
    return (
        f"【用户问题】\n{question}\n\n"
        f"【已执行 SQL】\n{sql}\n\n"
        f"【查询结果】\n{json.dumps(query_result, ensure_ascii=False, indent=2)}\n\n"
        f"【结果字段释义】\n{field_labels_text}\n\n"
        f"【本题统计口径摘要】\n{scope_note or '- 无'}\n\n"
        f"【口径事实】\n{scope_facts_text}\n\n"
        f"【限制与提醒】\n{limitation_note or '- 无'}\n\n"
        f"{special_output_rules}"
        "【输出要求】\n"
        "1. 先直接回答用户问题，不要复述全部 SQL 结果。\n"
        "2. 优先解释与问题直接对应的结果列；其他列只在必要时补充。\n"
        "3. 结果后必须补一段简短“统计口径说明”，至少覆盖时间窗口口径、业务对象口径、指标计算口径，必要时补充排除范围或限制。\n"
        "4. 口径说明必须基于已提供的口径事实组织自然语言，不要逐条照抄字段名。\n"
        "5. 简单问题自然写成 1-3 段；分组或对比问题再分点展示。\n"
        "6. 如果是多时间窗口多指标问题，优先先给表格，再给简短口径说明。\n"
        "7. 金额可加千分位并补充“元”。\n"
        "8. 如果结果为空或有限制，要明确说明。\n"
        f"9. {'优先按 Markdown 表格输出。' if preferred_format == 'table' else '无需强制表格格式。'}\n"
        "10. 不要输出 JSON，不要输出内部控制语句。"
    )


def build_extraction_answer_prompt(payload: Dict[str, Any]) -> str:
    question = str(payload.get("question") or "")
    snippets = payload.get("snippets") or []
    structured_fields = payload.get("structured_fields") or []
    structured_lines: List[str] = []
    for item in structured_fields:
        structured_lines.append(
            f"- {item.get('requested_label')}: 候选值={item.get('value')}；字段名={item.get('field_name')}；来源={item.get('source')}"
        )
    structured_text = "\n".join(structured_lines) if structured_lines else "- 无"
    snippet_texts: List[str] = []
    for item in snippets:
        module_name_cn = str(item.get("module_name_cn") or item.get("module") or "")
        text = str(item.get("text") or "").strip()
        snippet_texts.append(f"【{module_name_cn}】\n{text}")
    blocks = "\n\n".join(snippet_texts) if snippet_texts else "【无可用模块文本】"
    return (
        f"【用户问题】\n{question}\n\n"
        f"【结构化字段候选】\n{structured_text}\n\n"
        f"【可用报告模块文本】\n{blocks}\n\n"
        "【提取要求】\n"
        "0. 如果结构化字段候选已经给出了明确值，优先使用结构化值；PDF 模块文本用于校验、补充和兜底。\n"
        "1. 如果用户给了字段模板或章节结构，请按该结构输出。\n"
        "2. 如果文本中未找到某字段，请明确写“未找到”。\n"
        "3. 不要总结成泛泛描述，要尽量按字段或模块提取。"
    )


def _format_available_tables(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "- 无"
    lines: List[str] = []
    for item in items:
        table = str(item.get("table") or "")
        desc = str(item.get("description") or "")
        cols = []
        for col in (item.get("columns") or [])[:12]:
            name = str(col.get("name") or "")
            name_cn = str(col.get("name_cn") or "")
            cols.append(f"{name}({name_cn})" if name_cn else name)
        lines.append(f"- {table}: {desc} 关键字段: {', '.join(cols)}")
    return "\n".join(lines)


def _format_available_views(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "- 无"
    lines: List[str] = []
    for item in items:
        view = str(item.get("view") or "")
        desc = str(item.get("description") or "")
        cols = []
        for col in (item.get("columns") or [])[:12]:
            name = str(col.get("name") or "")
            name_cn = str(col.get("name_cn") or "")
            cols.append(f"{name}({name_cn})" if name_cn else name)
        lines.append(f"- {view}: {desc} 关键字段: {', '.join(cols)}")
    return "\n".join(lines)


class QwenClient:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        cfg = settings or SETTINGS
        self.api_base = cfg.qwen_api_base
        self.api_key = cfg.qwen_api_key
        self.model = cfg.qwen_model
        self.timeout = cfg.qwen_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)

    async def _chat(self, *, system: str, user: str, temperature: float = 0.0) -> Optional[str]:
        if not self.configured:
            return None
        url = f"{self.api_base.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            return None
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        content = str((choices[0].get("message") or {}).get("content") or "").strip()
        return content or None

    async def generate_sql_plan(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        user = build_sql_planner_prompt(payload)
        content = await self._chat(system=SQL_PLANNER_SYSTEM_PROMPT, user=user, temperature=0.0)
        if not content:
            return None
        parsed = _extract_json_object(content)
        if not parsed:
            return None
        sql = str(parsed.get("sql") or "").strip()
        if not sql:
            return None
        return {
            "sql": sql,
            "query_goal_cn": str(parsed.get("query_goal_cn") or ""),
            "used_previous_context": bool(parsed.get("used_previous_context")),
            "notes": [str(x) for x in (parsed.get("notes") or []) if str(x).strip()],
            "question_type": str(parsed.get("question_type") or ""),
            "business_object": str(parsed.get("business_object") or ""),
            "time_windows": [str(x) for x in (parsed.get("time_windows") or []) if str(x).strip()],
            "metrics": [str(x) for x in (parsed.get("metrics") or []) if str(x).strip()],
            "date_field": str(parsed.get("date_field") or ""),
            "amount_field": str(parsed.get("amount_field") or ""),
            "time_window_policy": str(parsed.get("time_window_policy") or ""),
            "business_scope": str(parsed.get("business_scope") or ""),
            "metric_definition": str(parsed.get("metric_definition") or ""),
            "exclusions": [str(x) for x in (parsed.get("exclusions") or []) if str(x).strip()],
            "raw_response": content,
        }

    async def generate_sql_answer(self, payload: Dict[str, Any]) -> Optional[str]:
        user = build_sql_answer_prompt(payload)
        return await self._chat(system=SQL_ANSWER_SYSTEM_PROMPT, user=user, temperature=0.1)

    async def route_question(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        user = build_question_router_prompt(payload)
        content = await self._chat(system=QUESTION_ROUTER_SYSTEM_PROMPT, user=user, temperature=0.0)
        parsed = _extract_json_object(content or "")
        if not parsed:
            return None
        mode = str(parsed.get("mode") or "").strip()
        if mode not in {"extract", "sql", "explain"}:
            return None
        return {
            "mode": mode,
            "target_modules": [str(x) for x in (parsed.get("target_modules") or []) if str(x).strip()],
            "reason": str(parsed.get("reason") or ""),
            "raw_response": content or "",
        }

    async def generate_extraction_answer(self, payload: Dict[str, Any]) -> Optional[str]:
        user = build_extraction_answer_prompt(payload)
        return await self._chat(system=EXTRACTION_ANSWER_SYSTEM_PROMPT, user=user, temperature=0.1)
