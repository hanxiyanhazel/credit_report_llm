# 个人信用报告口径台账（SQL落地版）

本文档用于固定“问题 -> 口径 -> 字段 -> SQL”的映射，避免后续手写 SQL 时口径漂移。

## 0. 全局约定

1. 默认报告范围：`WHERE report_id = :report_id`
2. 时间基准：`report_basic.report_time`
3. 金额口径：除特别说明外，按报告说明第18条，以人民币折算口径展示
4. 回答必须说明：统计范围包含什么、不包含什么
5. 同一问题可有多个口径时，输出“主口径 + 扩展口径”

---

## 1. 逾期情况（明细口径优先）

### 1.1 近24个月是否有逾期 / 逾期次数 / 逾期金额
- 默认口径：`account_history` 按“账户-月份”统计
- 逾期判定：`repay_type_code in ('1'..'7') OR overdue_total > 0 OR overdue_months > 0`
- 字段语义：
  - `repay_type`：还款状态中文标签，如“逾期180天以上”
  - `repay_type_code`：原始码值，如 `7`
  - `overdue_months`：逾期月数/严重程度字段，可用于筛选或取最大值，不得求和表示“逾期次数”
- SQL 模板：
```sql
SELECT
  COUNT(*) AS overdue_record_count,
  SUM(COALESCE(overdue_total, 0)) AS sum_overdue_total,
  SUM(COALESCE(overdue_principal, 0)) AS sum_overdue_principal,
  MAX(COALESCE(overdue_months, 0)) AS max_overdue_months
FROM account_history
WHERE report_id = :report_id
  AND period_date BETWEEN :report_time_minus_24m AND :report_time
  AND (COALESCE(overdue_total, 0) > 0 OR COALESCE(overdue_months, 0) > 0);
```
- 注意：概要“月份数/账户数”不可直接替代明细累计次数
- 注意：`SUM(overdue_months)` 不等于“逾期次数”

### 1.1A 多时间窗口复合汇总（普通逾期次数与金额）
- 题型：同一业务对象 + 多个时间窗口 + 多个指标
- 默认业务对象：`普通逾期记录`
- 默认时间窗：如近6个月 / 近12个月 / 近24个月（嵌套窗口）
- 默认统计对象：`account_history`
- 日期字段：`period_date`
- 金额字段：`overdue_total`
- 默认指标：
  - `逾期次数` -> 按账户-月份口径 `COUNT(*)`
  - `逾期/透支金额` -> `SUM(overdue_total)`
- 判定条件：`repay_type_code in ('1'..'7') OR overdue_total > 0 OR overdue_months > 0`
- SQL 生成方式：优先单条 CASE 聚合 SQL，同时返回多个窗口的次数与金额
- 注意：
  - `SUM(overdue_months)` 不等于“逾期次数”
  - 不与 B/D/G 类特殊风险状态混算

### 1.2 连续逾期期数
- 口径：按每个账户月份排序，仅当“月份连续（相差1个月）且 overdue_flag 连续”为同一连续段
- 备注：建议在后端代码层实现窗口函数或序列算法

### 1.3 逾期双轨口径（新增）
- 普通逾期轨：`repay_type_code in ('1'..'7')`（并结合 `overdue_months`）
- 特殊风险轨：`repay_type_code in ('B','D','G')`
- 规则：特殊风险轨单独展示，不混入普通逾期次数与连续期数

### 1.4 近X个月/近2年是否存在 B/D/G 类特殊风险状态
- 默认口径：`account_history` 按“账户-月份”扫描月度还款表现
- 判定条件：`repay_type_code in ('B','D','G')`
- 时间窗口：按报告日期精确回溯 `X` 个月或 `24` 个月
- 输出要求：
  - 主结论：存在 / 不存在
  - 如存在：列出命中的 `account_category / account_id / period_date / repay_type`
- SQL 模板：
```sql
SELECT
  account_category,
  account_id,
  period_date,
  repay_type,
  repay_type_code
FROM account_history
WHERE period_date >= :report_date_minus_xm
  AND period_date <= :report_date
  AND repay_type_code IN ('B','D','G')
ORDER BY period_date DESC, account_id;
```
- 注意：本题只检查 B/D/G 类特殊风险状态，不与 `1-7` 普通逾期状态混算

---

## 2. 授信情况（贷款）

### 2.0 多时间窗口复合汇总（新增贷款）
- 题型：同一业务对象 + 多个时间窗口 + 多个指标
- 默认业务对象：`新增贷款`
- 默认时间窗：近1个月 / 近3个月 / 近6个月（嵌套窗口）
- 默认统计对象：`credit_account`
- 日期字段：`open_date`
- 金额字段：`original_amount`
- 默认纳入：
  - `非循环贷账户`
  - `循环额度下分账户`
  - `循环贷账户`
- 默认排除：
  - `贷记卡账户`
  - `准贷记卡账户`
  - `被追偿信息`
  - `相关还款责任`
- SQL 生成方式：优先单条 CASE 聚合 SQL，同时返回多个窗口的笔数与金额
- 注意：
  - 金额按 `original_amount` 汇总，不自行混用授信额度
  - 若部分循环类账户 `original_amount = 0`，结果仅反映当前字段口径

### 2.0A 多时间窗口复合汇总（结清贷款）
- 题型：同一业务对象 + 多个时间窗口 + 多个指标
- 默认业务对象：`结清贷款`
- 默认时间窗：近1个月 / 近3个月 / 近6个月（嵌套窗口）
- 默认统计对象：`credit_account`
- 日期字段：`close_date`
- 状态条件：`account_status = '结清'`
- 金额字段：`original_amount`
- 默认纳入：
  - `非循环贷账户`
  - `循环额度下分账户`
  - `循环贷账户`
- 默认排除：
  - `贷记卡账户`
  - `准贷记卡账户`
  - `被追偿信息`
  - `相关还款责任`
- SQL 生成方式：优先单条 CASE 聚合 SQL，同时返回多个窗口的笔数与金额
- 注意：
  - 如缺少 `close_date` 字段，不得改用 `open_date`、`latest_repay_date` 等字段替代
  - 金额按 `original_amount` 汇总，不使用当前余额或授信额度
  - 若部分循环类账户 `original_amount` 为空或为0，结果仅反映当前字段口径

### 2.1 贷款总笔数 / 总借款金额 / 总余额
- 口径：`credit_account` 中贷款类账户
- 贷款类范围：`account_category IN ('非循环贷账户','循环额度下分账户','循环贷账户')`
- SQL 模板：
```sql
SELECT
  COUNT(*) AS loan_account_count,
  SUM(COALESCE(original_amount, 0)) AS loan_amount_total,
  SUM(COALESCE(balance, 0)) AS loan_balance_total
FROM credit_account
WHERE report_id = :report_id
  AND account_category IN ('非循环贷账户','循环额度下分账户','循环贷账户');
```

### 2.2 未结清借款金额（借款金额字段口径）
- 主口径：只统计“有借款金额字段意义”的贷款账户
- 范围：`非循环贷账户 + 循环额度下分账户`
- 过滤：`close_date IS NULL/空`
- 汇总规则：
  - 账户数/当前余额：按范围全部未结清账户统计
  - 借款金额：剔除 `account_status IN ('呆账','核销')` 后汇总
- SQL 模板：
```sql
SELECT
  account_category,
  COUNT(*) AS account_count,
  SUM(COALESCE(original_amount, 0)) AS loan_amount
FROM credit_account
WHERE report_id = :report_id
  AND account_category IN ('非循环贷账户','循环额度下分账户')
  AND (close_date IS NULL OR close_date = '')
  AND COALESCE(account_status, '') NOT IN ('呆账', '核销')
GROUP BY account_category;
```
- 解释：不含循环贷授信额度、卡已用额度、被追偿债权金额、相关还款责任

### 2.3 未结清授信总额（概要口径）
- 口径：`credit_summary` 的 `PC02EJ01 + PC02FJ01 + PC02GJ01`

### 2.4 贷款分类分布（可复用字段）
- 表：`credit_account`
- 字段：`loan_classification / is_loan_account / is_outstanding_account`
- 输出：分类账户数、借款金额、余额
- 备注：按业务种类+担保方式+机构关键词映射（住房/消费/经营/小贷/消费金融/信托/其他）

---

## 3. 授信情况（信用卡）

### 3.1 信用卡账户数 / 授信总额 / 已用或透支余额 / 使用率
- 口径来源：`credit_summary` (`PC02H*`, `PC02I*`)
- 关键字段：
  - 账户数：`PC02HS02 + PC02IS02`
  - 授信总额：`PC02HJ01 + PC02IJ01`
  - 已用/透支余额：`PC02HJ04 + PC02IJ04`
- 使用率：`已用/透支余额 ÷ 授信总额`
- 异常：授信总额=0 时，返回“无法计算”

### 3.2 个性化分期/展期事件
- 表：`special_transaction`
- 识别：`special_type/special_description` 命中“个性化分期/专项分期/展期”等关键词
- 输出：事件条数、分期条数、展期条数及样例明细

---

## 4. 身份信息与地址

### 4.1 通讯地址/户籍地址/居住地址/单位地址
- 来源：`base_info + PB03 + PB04`（目前为兜底逻辑）
- 规则：最新地址优先
- 注意：有脱敏时返回“无法准确判断同省市”

### 4.2 同省市判断（structured_query）
- 主口径：`identity_info + residence_info + occupation_info`
- 规则：最新居住地址 vs 最新单位地址，提取省市后比较
- 降级：地址脱敏或结构不完整时返回 `partially_answerable`

---

## 5. 查询情况

### 5.1 查询次数与原因分布（明细口径，窗口可变）
- 来源：`query_record`（PH01）
- 时间窗：按问题识别 `1/3/6/12/24个月`，自然月且含边界日
- 多窗口问题（如“近1年、近2年”）：返回并列窗口结果
- SQL 模板：
```sql
SELECT
  query_reason,
  COUNT(*) AS cnt
FROM query_record
WHERE report_id = :report_id
  AND query_date BETWEEN :report_date_minus_6m AND :report_date
GROUP BY query_reason
ORDER BY cnt DESC;
```
- 扩展统计：同时统计小额贷款/融资担保/融资租赁机构查询次数
- 兼容别名：融资租赁关键词同时匹配“融资租凭/租凭”等异常写法

### 5.2 最近1个月/最近2年查询概要（概要口径）
- 来源：`credit_summary` 的 `PC05BS*`
- 用途：回答概要类问题，不能替代明细口径累计

---

## 6. 五级分类

### 6.1 是否存在非正常五级分类
- 来源：`credit_account.five_classification`
- 异常集合：`关注/次级/可疑/损失`
- SQL 模板：
```sql
SELECT five_classification, COUNT(*) AS cnt
FROM credit_account
WHERE report_id = :report_id
  AND five_classification IN ('关注', '次级', '可疑', '损失')
GROUP BY five_classification;
```
- 当前 SQL demo 的默认处理：
  - 当前状态：优先检查 `credit_account.five_classification`
  - 历史记录：仅当结构化层存在可用的历史五级分类字段时才统计历史结果
- 回答要求：
  - 当前部分要明确回答“是否存在”及分布
  - 如果问题提到历史记录，而结构化层未识别到可用历史非正常五级分类记录，应明确提示“当前结构化数据未发现可直接命中的历史记录，历史口径存在字段覆盖限制”，不要直接回答“历史不存在”

---

## 7. 担保与相关还款责任

### 7.1 相关还款责任（非本人账户余额）
- 来源：`credit_summary` 的 `PC02KS02/PC02KJ01/PC02KJ02`
- 口径：单独展示，不并入“本人未结清账户余额”

---

## 8. 异议情况

### 8.1 是否存在在途异议 / 异议条数
- 来源：首页异议信息提示 + `objection_record`，`credit_summary(PG010S01)` 仅作结构化对账
- 对账规则：
  - 首页报告级在途异议总数优先从首页原文 `(\d+)笔异议且正在处理中` 提取
  - 若首页原文不可用，可回退到首页等价原始字段（如 `PA01ES01`）
  - `PG010S01` 仅作结构化对账，不直接作为首页在途异议总数
  - `objection_record` 用于明细定位和关键词在途识别
  - 明细需先剔除 `information_missing_annotation`（如“信用报告存在信息缺失”）再做异议候选计数
  - 概要与明细不一致时，返回“口径冲突（partially_answerable）”
- SQL 模板（结构化对账）：
```sql
SELECT SUM(COALESCE(metric_value, 0)) AS structured_objection_count_summary
FROM credit_summary
WHERE report_id = :report_id
  AND metric_key = 'PG010S01';
```
- SQL 模板（明细）：
```sql
SELECT
  COUNT(*) AS objection_count_detail,
  SUM(
    CASE
      WHEN objection_text LIKE '%处理期%'
        OR objection_text LIKE '%异议处理%'
        OR objection_text LIKE '%处理中%'
      THEN 1 ELSE 0
    END
  ) AS in_transit_count_detail
FROM objection_record
WHERE report_id = :report_id;
```
- 当前 SQL demo 的默认处理：
  - 主结论：是否存在在途征信异议
  - 优先依据：首页报告级在途异议总数 > 0，或 `objection_record.is_in_transit = true`
  - 明细中的 `objection_text` / `is_in_transit` 用于解释“异议处理期/处理中”证据
- 回答要求：
  - 不只回答 yes/no
  - 需区分：首页报告级在途异议总数、结构化对账值、明细定位条数
  - 明细条数不直接替代首页异议总数

---

## 9. 冲突处理规则（必须执行）

1. 查询类：明细(`PH01`)与概要(`PC05`)冲突时，默认主答明细并提示冲突  
2. 未结清余额：主口径不含 `PC02KJ02`，扩展口径才包含  
3. 借款金额问题：默认走“借款金额字段口径”，与授信总额口径分开  
4. 无法计算时禁止硬算，返回 `verifier_status=partially_answerable/not_answerable`

---

## 10. 变更记录（维护要求）

每次改口径必须更新：

1. 问题名称与 metric 名  
2. 统计范围（包含/不包含）  
3. 字段来源（表+字段）  
4. SQL 模板  
5. 与历史口径差异说明  
