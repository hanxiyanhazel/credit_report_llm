from __future__ import annotations

from typing import Any, Dict, List


_DEFAULT_PROFILE: Dict[str, Any] = {
    "report_field_background": (
        "该问题通常结合信息概要与信贷交易明细理解，重点看账户状态、金额字段和时间范围字段。"
    ),
    "system_scope": (
        "本系统先基于核心表计算结构化结果，再做中文解释；统计范围以 query_plan 和 query_result 为准。"
    ),
    "pitfalls": [
        "不要混用不同统计口径（概要口径与明细口径要分开说明）。",
        "字段缺失时不强行计算，需明确给出“无法可靠计算”的限制。",
    ],
    "pdf_snippets": ["报告说明以字段定义和模块口径为准，解释层仅用于说明，不替代结构化计算。"],
}


_METRIC_PROFILES: Dict[str, Dict[str, Any]] = {
    "overdue_window_stats": {
        "report_field_background": (
            "逾期问题通常看借贷账户还款表现模块，重点字段是还款状态、当期逾期/透支金额、账户月份维度记录。"
        ),
        "system_scope": (
            "本系统按账户-月份统计普通逾期，并将特殊风险状态单独统计；连续逾期期数默认按状态最大值口径解释，必要时补充自然月连续段。"
        ),
        "pitfalls": [
            "普通逾期与特殊风险状态不能混算。",
            "逾期条数不等于连续逾期期数。",
            "缺少逐月逾期本金字段时，不能给出可靠逾期本金合计。",
        ],
        "pdf_snippets": ["模板结构中，还款表现以账户-月份展示状态码及逾期/透支金额。"],
    },
    "overdue_multi_window_stats": {
        "report_field_background": (
            "逾期窗口问题看还款表现明细与违约概要，核心是时间窗内状态分布与金额合计。"
        ),
        "system_scope": (
            "本系统按问题识别窗口并分别计算，普通逾期、特殊风险状态分轨输出，窗口间结果不混算。"
        ),
        "pitfalls": [
            "跨窗口比较时要保持同一口径。",
            "不能把概要最长逾期和明细逾期条数混作同一指标。",
        ],
        "pdf_snippets": ["模板结构中，还款表现以账户-月份展示状态码及逾期/透支金额。"],
    },
    "query_window_stats": {
        "report_field_background": (
            "查询统计问题通常看查询记录明细与查询记录概要两个模块，二者用途不同。"
        ),
        "system_scope": (
            "本系统按查询明细做可变窗口统计，并在需要时补充概要口径说明。"
        ),
        "pitfalls": [
            "查询概要与查询明细不可直接互相替代。",
            "本人查询可能只出现在概要中，不一定逐条出现在明细。",
        ],
        "pdf_snippets": ["模板结构中，查询记录概要与查询记录明细分开展示，口径用途不同。"],
    },
    "query_multi_window_stats": {
        "report_field_background": (
            "多时间窗查询问题主要依赖查询记录明细，并参考概要进行口径对照。"
        ),
        "system_scope": (
            "本系统按各窗口分别回算查询次数及原因分布，统一使用明细时间过滤逻辑。"
        ),
        "pitfalls": [
            "不同窗口结果不能直接相减推断其他口径。",
            "若用户要求包含本人查询，应明确是否采用概要口径。",
        ],
        "pdf_snippets": ["模板结构中，查询记录概要与查询记录明细分开展示，口径用途不同。"],
    },
    "query_summary_pc05": {
        "report_field_background": "该问题对应查询记录概要模块，属于报告给定汇总口径。",
        "system_scope": "本系统直接读取概要字段，不回推明细补数。",
        "pitfalls": ["概要口径仅适用于其定义窗口，不能外推到其他窗口。"],
        "pdf_snippets": ["模板结构中，查询记录概要为汇总展示模块。"],
    },
    "outstanding_balance_summary": {
        "report_field_background": "未结清账户问题通常看授信及负债信息概要，字段包括账户数与余额类字段。",
        "system_scope": "本系统优先采用未结清/未销户概要口径计算账户数和余额；相关还款责任作为扩展口径单列。",
        "pitfalls": [
            "历史账户提示口径不能替代当前未结清口径。",
            "余额与借款金额、授信额度不可混称。",
        ],
        "pdf_snippets": ["报告说明：授信及负债信息概要展示的是未结清/未销户信息。"],
    },
    "outstanding_account_count_summary": {
        "report_field_background": "当前未结清账户数应从授信及负债信息概要读取。",
        "system_scope": "本系统按未结清/未销户概要口径统计账户数。",
        "pitfalls": ["不能用历史累计账户数回答当前未结清账户数。"],
        "pdf_snippets": ["报告说明：授信及负债信息概要展示的是未结清/未销户信息。"],
    },
    "outstanding_loan_amount_summary": {
        "report_field_background": "借款金额问题应区分借款金额字段与授信额度、余额字段。",
        "system_scope": "本系统按借款金额字段口径汇总贷款账户，不把不等价字段强行并入借款金额。",
        "pitfalls": ["借款金额、授信额度、余额、债权金额不可混算。"],
        "pdf_snippets": ["模板结构中，不同账户类型的金额字段语义存在差异。"],
    },
    "outstanding_three_metrics_summary": {
        "report_field_background": "三项联动问题涉及未结清账户数、余额、借款金额三个不同指标。",
        "system_scope": "本系统分别计算三项指标后再合并回答，保持各指标独立口径。",
        "pitfalls": ["三项指标字段语义不同，不能用单一字段替代全部指标。"],
        "pdf_snippets": ["报告说明：授信及负债信息概要用于未结清/未销户展示。"],
    },
    "card_summary_pc02": {
        "report_field_background": "信用卡问题通常看贷记卡与准贷记卡汇总字段，关注额度、已用额度、透支余额。",
        "system_scope": "本系统合并贷记卡与准贷记卡统计使用金额；授信总额缺失时不强算使用率。",
        "pitfalls": [
            "已用额度与透支余额字段不能互换。",
            "授信总额为零或缺失时，使用率应标记不可可靠计算。",
        ],
        "pdf_snippets": ["模板结构中，信用卡分为贷记卡与准贷记卡并分字段展示。"],
    },
    "card_special_events": {
        "report_field_background": "信用卡特殊事项需结合特殊交易或说明字段判断。",
        "system_scope": "本系统仅在出现明确特殊事项标记时输出命中结果。",
        "pitfalls": ["大额专项分期不等同个性化分期或展期。"],
        "pdf_snippets": ["模板结构中，大额专项分期字段属于分期类业务展示。"],
    },
    "five_classification_status": {
        "report_field_background": "五级分类问题看账户分类字段，区分正常与非正常类别。",
        "system_scope": "本系统按账户五级分类字段识别非正常记录，并区分本人账户与相关还款责任范围。",
        "pitfalls": ["回答需明确统计范围，避免把不同责任范围混为一个结论。"],
        "pdf_snippets": ["模板结构中，账户明细可展示五级分类。"],
    },
    "related_repayment_summary": {
        "report_field_background": "担保问题应看相关还款责任信息模块，不是贷款担保方式字段。",
        "system_scope": "本系统按相关还款责任口径统计余额与责任规模，并与本人贷款口径分离。",
        "pitfalls": ["本人贷款担保方式不等于本人对外担保责任。"],
        "pdf_snippets": ["模板结构中，相关还款责任模块独立展示为个人/企业责任信息。"],
    },
    "address_consistency_profile": {
        "report_field_background": "地址一致性问题需要身份信息、居住信息、职业信息三个模块联合判断。",
        "system_scope": "本系统优先取最新地址信息比较省市一致性，地址缺失或脱敏时返回无法判断。",
        "pitfalls": ["地址字段不可解析省市时不能强行判断同省市。"],
        "pdf_snippets": ["模板结构中，居住信息和职业信息可能多条并含脱敏内容。"],
    },
    "objection_summary": {
        "report_field_background": "异议问题看首页异议信息提示与账户异议标注两个位置。",
        "system_scope": "本系统优先使用首页异议总提示判断是否在途，明细标注作为补充说明。",
        "pitfalls": ["明细异议条数不可覆盖首页异议总提示。"],
        "pdf_snippets": ["模板结构中，异议信息提示用于总量判断，明细用于逐条补充。"],
    },
}

_METRIC_FIELD_LABELS: Dict[str, Dict[str, str]] = {
    "overdue_window_stats": {
        "window_months": "统计时间窗口（月）",
        "window_start_date": "窗口起始日期",
        "window_end_date": "窗口结束日期",
        "ordinary_overdue_record_count": "普通逾期记录条数（账户-月份）",
        "ordinary_sum_overdue_total": "普通逾期/透支金额合计",
        "ordinary_sum_overdue_principal": "普通逾期本金合计（若字段可得）",
        "ordinary_max_overdue_terms_by_status": "最多连续逾期期数（状态最大值口径）",
        "ordinary_max_consecutive_overdue_months": "最多连续逾期期数（自然月连续段口径）",
        "special_risk_record_count": "特殊风险状态记录条数（B/D/G）",
    },
    "overdue_multi_window_stats": {
        "windows": "多窗口统计结果列表",
        "months": "窗口月份（如12、24）",
        "query_result": "该窗口下的逾期统计明细",
        "ordinary_overdue_record_count": "普通逾期记录条数（账户-月份）",
        "ordinary_sum_overdue_total": "普通逾期/透支金额合计",
        "ordinary_max_overdue_terms_by_status": "最多连续逾期期数（状态最大值口径）",
        "ordinary_max_consecutive_overdue_months": "最多连续逾期期数（自然月连续段口径）",
        "special_risk_record_count": "特殊风险状态记录条数（B/D/G）",
    },
    "outstanding_account_count_summary": {
        "outstanding_account_count_total": "当前未结清/未销户账户总数",
        "outstanding_compensation_account_count": "被追偿账户数",
        "outstanding_credit_account_count": "贷款及卡账户数",
        "total_obligation_account_count": "含相关还款责任的相关负债账户总数",
    },
    "outstanding_balance_summary": {
        "outstanding_account_balance_total": "当前未结清/未销户账户余额合计",
        "outstanding_compensation_balance": "被追偿余额",
        "outstanding_credit_account_balance": "贷款及卡账户余额",
        "related_repayment_responsibility_balance": "相关还款责任余额",
        "liability_balance_total_including_related_responsibility": "含相关还款责任的相关负债余额合计",
    },
    "outstanding_three_metrics_summary": {
        "outstanding_account_count_total": "当前未结清/未销户账户总数",
        "outstanding_account_balance_total": "当前未结清/未销户账户余额合计",
        "outstanding_loan_amount_total": "未结清贷款借款金额合计（字段口径）",
    },
}


def build_query_result_field_guide(*, query_plan: Dict[str, Any], query_result: Dict[str, Any]) -> List[str]:
    metric_name = str(query_plan.get("metric_name") or "")
    label_map = dict(_METRIC_FIELD_LABELS.get(metric_name) or {})
    if not label_map:
        return []
    guide: List[str] = []
    for k in query_result.keys():
        if k in label_map:
            guide.append(f"{k}: {label_map[k]}")
    return guide[:12]


def build_explanation_context(*, question: str, query_plan: Dict[str, Any]) -> Dict[str, Any]:
    metric_name = str(query_plan.get("metric_name") or "")
    profile = dict(_DEFAULT_PROFILE)
    profile.update(_METRIC_PROFILES.get(metric_name, {}))

    # dynamic adjustments
    q = (question or "").strip()
    if "个性化分期" in q or "展期" in q:
        profile["pitfalls"] = list(profile.get("pitfalls") or []) + ["仅出现分期类字段不代表命中特殊负面事项。"]
    if "未结清" in q and "借款金额" in q:
        profile["pitfalls"] = list(profile.get("pitfalls") or []) + ["借款金额口径与余额口径需分开展示。"]

    return {
        "report_field_background": str(profile.get("report_field_background") or ""),
        "system_scope": str(profile.get("system_scope") or ""),
        "pitfalls": [str(x) for x in (profile.get("pitfalls") or [])][:4],
        "pdf_snippets": [str(x) for x in (profile.get("pdf_snippets") or [])][:3],
        # Internal guard is for model instruction only and must never be shown verbatim.
        "internal_guard": "数字真值以query_result为准，不得改写。",
    }
