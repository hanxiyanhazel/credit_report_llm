#!/usr/bin/env python3
"""Structured query regression checks for individual report (v1 baseline)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from structured_query import try_structured_query


def _load_core_tables(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _report_id(core_tables: Dict[str, Any]) -> str:
    rid = str(core_tables.get("report_id") or "")
    if rid:
        return rid
    rows = ((core_tables.get("tables") or {}).get("report_basic") or [])
    if rows:
        return str((rows[0] or {}).get("report_id") or "")
    return ""


def _check_cases(core_tables: Dict[str, Any], report_id: str) -> List[str]:
    failures: List[str] = []
    cases = [
        {"q": "近6个月逾期次数和金额是多少？", "metric": "overdue_window_stats", "status": "partially_answerable"},
        {"q": "近1年、近2年最多连续逾期期数是多少？", "metric": "overdue_multi_window_stats", "status": "partially_answerable"},
        {"q": "近2年有没有B/D/G这类特殊风险状态？", "metric": "overdue_window_stats"},
        {"q": "当前未结清账户有多少个？", "metric": "outstanding_account_count_summary", "status": "answerable"},
        {"q": "当前未结清账户余额合计是多少？", "metric": "outstanding_balance_summary", "status": "answerable"},
        {"q": "当前未结清贷款借款金额合计是多少？", "metric": "outstanding_loan_amount_summary", "status": "answerable"},
        {"q": "帮我汇总一下未结清账户数、余额、借款金额三项指标。", "metric": "outstanding_three_metrics_summary", "status": "answerable"},
        {"q": "未结清贷款分类分布是什么？", "metric": "loan_classification_summary", "status": "answerable"},
        {"q": "贷款总笔数、总金额、总余额是多少？", "metric": "loan_summary_core", "status": "answerable"},
        {"q": "近1个月查询次数是多少？", "metric": "query_window_stats", "status": "answerable"},
        {"q": "近2年查询次数是多少？", "metric": "query_window_stats", "status": "partially_answerable"},
        {"q": "近1年、近2年查询次数是多少？", "metric": "query_multi_window_stats", "status": "partially_answerable"},
        {"q": "最近1个月查询记录概要是什么？", "metric": "query_summary_pc05", "status": "answerable"},
        {"q": "有没有在途异议？", "metric": "objection_summary", "status": "partially_answerable"},
        {"q": "是否存在非正常五级分类？", "metric": "five_classification_status", "status": "answerable"},
        {"q": "担保余额是多少？", "metric": "related_repayment_summary", "status": "answerable"},
        {"q": "居住地址和单位地址是否同省市？", "metric": "address_consistency_profile"},
        {"q": "通讯地址、户籍地址、居住地址、单位地址分别是什么？", "metric": "address_consistency_profile"},
        {"q": "近两年信用卡是否有个性化分期或展期？", "metric": "card_special_events"},
        {"q": "信用卡数量、总额度、已用额度、使用率是多少？", "metric": "card_summary_pc02"},
    ]

    for idx, case in enumerate(cases, start=1):
        q = case["q"]
        result = try_structured_query(question=q, core_tables=core_tables, report_id=report_id)
        if not result:
            failures.append(f"[{idx}] no_match: {q}")
            continue
        metric = str((result.get("query_plan") or {}).get("metric_name") or "")
        if metric != case["metric"]:
            failures.append(f"[{idx}] metric_mismatch: {q} -> got={metric}, expected={case['metric']}")
        expected_status = case.get("status")
        if expected_status and result.get("verifier_status") != expected_status:
            failures.append(
                f"[{idx}] status_mismatch: {q} -> got={result.get('verifier_status')}, expected={expected_status}"
            )

    # numeric guards to prevent silent regression
    checks = [
        (
            "当前未结清账户有多少个？",
            lambda r: int((r.get("query_result") or {}).get("outstanding_account_count_total", -1)) == 419,
            "outstanding_account_count_total!=419",
        ),
        (
            "当前未结清账户余额合计是多少？",
            lambda r: int(round(float((r.get("query_result") or {}).get("outstanding_account_balance_total", -1)))) == 50554468,
            "outstanding_account_balance_total!=50554468",
        ),
        (
            "当前未结清贷款借款金额合计是多少？",
            lambda r: int(round(float((r.get("query_result") or {}).get("total_loan_amount", -1)))) == 57866026,
            "total_loan_amount!=57866026",
        ),
        (
            "近6个月查询次数和原因分布是什么？",
            lambda r: int((r.get("query_result") or {}).get("query_count", -1)) == 57,
            "query_count_6m!=57",
        ),
        (
            "近6个月逾期次数和金额是多少？",
            lambda r: int((r.get("query_result") or {}).get("ordinary_overdue_record_count", -1)) == 19,
            "ordinary_overdue_record_count_6m!=19",
        ),
    ]
    for q, fn, msg in checks:
        r = try_structured_query(question=q, core_tables=core_tables, report_id=report_id)
        if not r or not fn(r):
            failures.append(f"[numeric] {msg} for question: {q}")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--core-tables",
        type=Path,
        default=Path("data/builtin/builtin_individual_001/artifacts/individual.core_tables.json"),
        help="Path to individual.core_tables.json",
    )
    args = parser.parse_args()

    core_tables = _load_core_tables(args.core_tables)
    report_id = _report_id(core_tables)
    if not report_id:
        raise SystemExit("missing report_id")

    failures = _check_cases(core_tables, report_id)
    if failures:
        print("REGRESSION FAILED")
        for item in failures:
            print("-", item)
        raise SystemExit(1)
    print("REGRESSION PASSED (20 question cases + numeric guards)")


if __name__ == "__main__":
    main()
