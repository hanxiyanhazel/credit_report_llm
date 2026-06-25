from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


SUMMARY_VIEW_METADATA: Dict[str, Dict[str, Any]] = {
    "v_report_context": {
        "description": "当前请求对应的报告上下文视图，提供统一外层 report_id 和报告日期锚点。",
        "columns": {
            "selected_report_id": "当前选中的报告ID（外层稳定ID）",
            "internal_report_id": "核心表原始内部报告ID",
            "report_time": "报告时间",
            "report_date": "报告日期",
        },
    },
    "v_outstanding_summary": {
        "description": "未结清/未销户概要视图，主口径与报告说明保持一致。",
        "columns": {
            "outstanding_account_count_total": "当前未结清/未销户账户总数",
            "outstanding_compensation_account_count": "被追偿账户数",
            "outstanding_credit_account_count": "贷款及卡账户数",
            "total_obligation_account_count": "含相关还款责任的相关负债账户总数",
            "outstanding_account_balance_total": "当前未结清/未销户账户余额合计",
            "outstanding_compensation_balance": "被追偿余额",
            "outstanding_credit_account_balance": "贷款及卡账户余额",
            "outstanding_loan_amount_total": "未结清贷款借款金额/授信金额合计",
            "outstanding_card_credit_total": "信用卡授信总额",
            "related_repayment_responsibility_balance": "相关还款责任余额",
            "related_repayment_responsibility_amount": "相关还款责任金额",
            "related_repayment_responsibility_count": "相关还款责任账户数",
            "liability_balance_total_including_related_responsibility": "含相关还款责任的相关负债余额合计",
            "calculation_basis": "计算口径标识",
        },
    },
    "v_query_summary_pc05": {
        "description": "查询记录概要视图，直接映射报告 PC05 概要汇总字段。",
        "columns": {
            "latest_query_date": "最近一次查询日期",
            "latest_query_org_code": "最近一次查询机构代码",
            "latest_query_reason": "最近一次查询原因",
            "month1_loan_org_count": "最近1个月贷款审批查询机构数",
            "month1_card_org_count": "最近1个月信用卡审批查询机构数",
            "month1_loan_query_count": "最近1个月贷款审批查询次数",
            "month1_card_query_count": "最近1个月信用卡审批查询次数",
            "month1_self_query_count": "最近1个月本人查询次数",
            "year2_post_loan_query_count": "最近2年贷后管理查询次数",
            "year2_guarantee_query_count": "最近2年担保资格审查查询次数",
            "year2_special_merchant_query_count": "最近2年特约商户实名审查次数",
        },
    },
}


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _is_int_like(v: Any) -> bool:
    if isinstance(v, bool):
        return True
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return float(v).is_integer()
    s = str(v or "").strip()
    if s == "":
        return False
    if not re.fullmatch(r"[+-]?\d+", s):
        return False
    try:
        n = int(s)
    except Exception:
        return False
    return -(2**63) <= n <= (2**63 - 1)


def _is_float_like(v: Any) -> bool:
    if isinstance(v, (int, float, bool)):
        return True
    s = str(v or "").strip().replace(",", "")
    if s == "":
        return False
    try:
        float(s)
        return True
    except Exception:
        return False


def _infer_column_type(values: Iterable[Any]) -> str:
    vals = [v for v in values if v not in (None, "")]
    if not vals:
        return "TEXT"
    if all(_is_int_like(v) for v in vals):
        return "INTEGER"
    if all(_is_float_like(v) for v in vals):
        return "REAL"
    return "TEXT"


def _normalize_value(v: Any, sql_type: str) -> Any:
    if v in (None, ""):
        return None
    if sql_type == "INTEGER":
        s = str(v).replace(",", "").strip()
        if s.lower() in {"true", "false"}:
            return 1 if s.lower() == "true" else 0
        return int(float(s))
    if sql_type == "REAL":
        s = str(v).replace(",", "").strip()
        if s.lower() in {"true", "false"}:
            return 1.0 if s.lower() == "true" else 0.0
        return float(s)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _report_context_from_core_tables(core_tables: Dict[str, Any]) -> Dict[str, str]:
    rows = ((core_tables.get("tables") or {}).get("report_basic") or [])
    first = dict(rows[0] or {}) if rows else {}
    report_time = str(first.get("report_time") or "").strip()
    report_date = ""
    if report_time:
        report_date = report_time.split("T", 1)[0]
    internal_report_id = str(first.get("report_id") or "").strip()
    return {
        "internal_report_id": internal_report_id,
        "report_time": report_time,
        "report_date": report_date,
    }


def build_sqlite_db(core_tables: Dict[str, Any], *, exposed_report_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    tables = (core_tables.get("tables") or {})
    report_ctx = _report_context_from_core_tables(core_tables)

    for table_name, rows in tables.items():
        rows = [dict(r or {}) for r in (rows or [])]
        if exposed_report_id:
            for row in rows:
                if "report_id" in row:
                    row["report_id"] = exposed_report_id
        columns: List[str] = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    columns.append(str(key))
        if not columns:
            continue

        column_types = {
            col: _infer_column_type((row.get(col) for row in rows))
            for col in columns
        }
        ddl = ", ".join(f'{_quote_ident(col)} {column_types[col]}' for col in columns)
        conn.execute(f'CREATE TABLE {_quote_ident(table_name)} ({ddl})')

        placeholders = ", ".join("?" for _ in columns)
        quoted_columns = ", ".join(_quote_ident(c) for c in columns)
        insert_sql = f'INSERT INTO {_quote_ident(table_name)} ({quoted_columns}) VALUES ({placeholders})'
        batch = [
            tuple(_normalize_value(row.get(col), column_types[col]) for col in columns)
            for row in rows
        ]
        if batch:
            conn.executemany(insert_sql, batch)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS _report_context (selected_report_id TEXT, internal_report_id TEXT, report_time TEXT, report_date TEXT)"
    )
    conn.execute(
        "INSERT INTO _report_context (selected_report_id, internal_report_id, report_time, report_date) VALUES (?, ?, ?, ?)",
        (
            str(exposed_report_id or ""),
            str(report_ctx.get("internal_report_id") or ""),
            str(report_ctx.get("report_time") or ""),
            str(report_ctx.get("report_date") or ""),
        ),
    )
    _create_semantic_views(conn)
    return conn


def _create_semantic_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE VIEW IF NOT EXISTS v_report_context AS
        SELECT selected_report_id, internal_report_id, report_time, report_date
        FROM _report_context;

        CREATE VIEW IF NOT EXISTS v_outstanding_summary AS
        WITH s AS (
          SELECT metric_key, CAST(metric_value AS REAL) AS metric_value
          FROM credit_summary
          WHERE metric_key LIKE 'PC02%'
        )
        SELECT
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02BS01'), 0) AS outstanding_compensation_account_count,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02ES02','PC02FS02','PC02GS02','PC02HS02','PC02IS02')), 0) AS outstanding_credit_account_count,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02BS01'), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02ES02','PC02FS02','PC02GS02','PC02HS02','PC02IS02')), 0) AS outstanding_account_count_total,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02KS02'), 0) AS related_repayment_responsibility_count,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02BS01'), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02ES02','PC02FS02','PC02GS02','PC02HS02','PC02IS02')), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02KS02'), 0) AS total_obligation_account_count,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02BJ01'), 0) AS outstanding_compensation_balance,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02EJ02','PC02FJ02','PC02GJ02')), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02HJ04','PC02IJ04')), 0) AS outstanding_credit_account_balance,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02EJ01','PC02FJ01','PC02GJ01')), 0) AS outstanding_loan_amount_total,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02HJ01','PC02IJ01')), 0) AS outstanding_card_credit_total,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02KJ02'), 0) AS related_repayment_responsibility_balance,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02KJ01'), 0) AS related_repayment_responsibility_amount,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02BJ01'), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02EJ02','PC02FJ02','PC02GJ02')), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02HJ04','PC02IJ04')), 0) AS outstanding_account_balance_total,
          COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02BJ01'), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02EJ02','PC02FJ02','PC02GJ02')), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key IN ('PC02HJ04','PC02IJ04')), 0)
            + COALESCE((SELECT SUM(metric_value) FROM s WHERE metric_key = 'PC02KJ02'), 0) AS liability_balance_total_including_related_responsibility,
          'pc02_summary_unsettled_or_uncancelled' AS calculation_basis;

        CREATE VIEW IF NOT EXISTS v_query_summary_pc05 AS
        WITH s AS (
          SELECT metric_key, metric_value
          FROM credit_summary
          WHERE metric_key LIKE 'PC05%'
        )
        SELECT
          (SELECT metric_value FROM s WHERE metric_key = 'PC05AR01' LIMIT 1) AS latest_query_date,
          (SELECT metric_value FROM s WHERE metric_key = 'PC05AI01' LIMIT 1) AS latest_query_org_code,
          (SELECT metric_value FROM s WHERE metric_key = 'PC05AQ01' LIMIT 1) AS latest_query_reason,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS01' LIMIT 1), 0) AS month1_loan_org_count,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS02' LIMIT 1), 0) AS month1_card_org_count,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS03' LIMIT 1), 0) AS month1_loan_query_count,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS04' LIMIT 1), 0) AS month1_card_query_count,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS05' LIMIT 1), 0) AS month1_self_query_count,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS06' LIMIT 1), 0) AS year2_post_loan_query_count,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS07' LIMIT 1), 0) AS year2_guarantee_query_count,
          COALESCE((SELECT CAST(metric_value AS REAL) FROM s WHERE metric_key = 'PC05BS08' LIMIT 1), 0) AS year2_special_merchant_query_count;
        """
    )


def build_schema_context(core_tables: Dict[str, Any], schema_metadata: Dict[str, Any], *, exposed_report_id: str) -> Dict[str, Any]:
    tables = (core_tables.get("tables") or {})
    report_ctx = _report_context_from_core_tables(core_tables)
    table_meta = {
        str(item.get("table")): item
        for item in (schema_metadata.get("tables") or [])
        if isinstance(item, dict) and item.get("table")
    }

    lines: List[str] = []
    table_summaries: List[Dict[str, Any]] = []
    for table_name, rows in tables.items():
        meta = table_meta.get(table_name, {})
        description = str(meta.get("description") or "")
        fields = meta.get("fields") or {}
        column_names = list(rows[0].keys()) if rows else []
        column_items: List[Dict[str, str]] = []
        field_parts = []
        for col in column_names[:16]:
            field_meta = fields.get(col) or {}
            name_cn = str(field_meta.get("name_cn") or "")
            column_items.append({"name": str(col), "name_cn": name_cn})
            if name_cn:
                field_parts.append(f"{col}({name_cn})")
            else:
                field_parts.append(str(col))
        field_text = ", ".join(field_parts)
        lines.append(f"- {table_name}: {description} 字段示例: {field_text}")
        table_summaries.append(
            {
                "table": table_name,
                "description": description,
                "columns": column_items,
            }
        )

    view_summaries: List[Dict[str, Any]] = []
    if SUMMARY_VIEW_METADATA:
        lines.append("- 语义视图：")
        for view_name, meta in SUMMARY_VIEW_METADATA.items():
            cols = ", ".join(f"{k}({v})" for k, v in meta["columns"].items())
            lines.append(f"  - {view_name}: {meta['description']}；字段: {cols}")
            view_summaries.append(
                {
                    "view": view_name,
                    "description": str(meta.get("description") or ""),
                    "columns": [{"name": str(k), "name_cn": str(v)} for k, v in (meta.get("columns") or {}).items()],
                }
            )

    business_rules = [
        f"当前 SQLite 会话只包含当前选中报告的数据；外层报告ID固定为 {exposed_report_id}，通常不需要再手写 report_id 过滤。",
        f"所有“近X个月/年”的时间窗口统一以报告日期 {report_ctx.get('report_date') or '未知'} 为锚点，不要使用 now/current_date。",
        "逾期历史优先查 account_history；普通逾期可结合 overdue_total > 0、overdue_months > 0 或 repay_type_code in ('1','2','3','4','5','6','7')。",
        "repay_type / repay_type_code 属于还款状态字段；overdue_months 属于逾期月数/严重程度字段。它们可用于筛选、分类或取最大值，但不能直接求和表示“逾期次数”。",
        "当前账户状态、贷款分类、机构类型优先查 credit_account。",
        "当前未结清/未销户概要问题优先查 v_outstanding_summary。",
        "查询记录概要优先查 v_query_summary_pc05；明细窗口统计优先查 query_record。",
        "借款金额(original_amount)、余额(balance)、授信额度(credit_limit)、债权/被追偿口径不能混算。",
    ]

    return {
        "schema_text": "\n".join(lines),
        "business_rules": business_rules,
        "view_metadata": SUMMARY_VIEW_METADATA,
        "table_summaries": table_summaries,
        "view_summaries": view_summaries,
        "report_context": {
            "selected_report_id": str(exposed_report_id or ""),
            "internal_report_id": str(report_ctx.get("internal_report_id") or ""),
            "report_time": str(report_ctx.get("report_time") or ""),
            "report_date": str(report_ctx.get("report_date") or ""),
        },
    }


def _normalize_sql_runtime_context(sql: str, *, selected_report_id: str, report_date: str) -> str:
    text = str(sql or "")
    if selected_report_id:
        text = re.sub(
            r"""(?i)\breport_id\s*=\s*(['"]).*?\1""",
            f"report_id = '{selected_report_id}'",
            text,
        )
    if report_date:
        text = re.sub(
            r"""(?i)date\s*\(\s*['"]now['"]\s*,""",
            f"date('{report_date}',",
            text,
        )
        text = re.sub(
            r"""(?i)\bcurrent_date\b""",
            f"'{report_date}'",
            text,
        )
        text = re.sub(
            r"""(?i)date\s*\(\s*['"]now['"]\s*\)""",
            f"date('{report_date}')",
            text,
        )
    return text


def sanitize_sql(sql: str, *, selected_report_id: str = "", report_date: str = "") -> str:
    text = str(sql or "").strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip().rstrip(";").strip()
    text = _normalize_sql_runtime_context(text, selected_report_id=selected_report_id, report_date=report_date)
    lower = text.lower()
    if "internal_report_id" in lower or "selected_report_id" in lower:
        raise ValueError("单报告模式下，SQL 不允许引用 selected_report_id 或 internal_report_id；如需时间锚点，只允许读取 v_report_context.report_date")
    if "join v_report_context" in lower and "report_id" in lower:
        raise ValueError("单报告模式下，SQL 不允许通过 report_id 与 v_report_context 关联；请直接使用 v_report_context.report_date 作为时间锚点")
    if not (lower.startswith("select") or lower.startswith("with")):
        raise ValueError("只允许 SELECT / WITH 查询")
    banned = [" insert ", " update ", " delete ", " drop ", " alter ", " attach ", " pragma ", " create "]
    wrapped = f" {lower} "
    for token in banned:
        if token in wrapped:
            raise ValueError("检测到不允许的 SQL 关键字")
    if ";" in text:
        raise ValueError("只允许单条 SQL")
    return text


def execute_readonly_sql(
    conn: sqlite3.Connection,
    sql: str,
    *,
    selected_report_id: str = "",
    report_date: str = "",
    limit: int = 200,
) -> Dict[str, Any]:
    safe_sql = sanitize_sql(sql, selected_report_id=selected_report_id, report_date=report_date)
    cur = conn.execute(safe_sql)
    columns = [d[0] for d in (cur.description or [])]
    rows = cur.fetchmany(limit + 1)
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]
    row_dicts = [dict(r) for r in rows]
    return {
        "sql": safe_sql,
        "columns": columns,
        "rows": row_dicts,
        "row_count": len(row_dicts),
        "truncated": truncated,
    }
