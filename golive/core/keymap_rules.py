"""
keymap_rules.py — 中文 chart_name → 业务 key 规则映射

给定 BI 图表的中文名称（如"资金意图访问次数统计"），返回简短的英文业务 key
（如"fund_calls"），用于 BIDataAPI 多数据集场景下让前端按业务 key 取数。

设计原则：
- 不引入外部依赖（无 LLM、无拼音库）
- 规则优先级：复合短语 > 单字短语，避免被"次数"等高频词抢走
- 命中失败时返回空字符串，由调用方决定 fallback 策略（如 ref_N）
- 自动去重：同一组里命中同一个 key 时追加 _2 / _3 后缀

如果需要更高质量的命名，用户可通过 --bi-key-map 显式指定。
"""

# 域前缀（业务域）—— 出现在 chart_name 里就给个英文前缀
# 顺序无关，只匹配第一个命中的
DOMAIN_PREFIX: list[tuple[str, str]] = [
    # 财务/交易类
    ("资金", "fund"),
    ("发票", "inv"),
    ("订单", "order"),
    ("商家", "merchant"),
    ("退款", "refund"),
    ("支付", "pay"),
    ("交易", "trade"),
    ("流水", "flow"),
    ("收入", "rev"),
    ("成本", "cost"),
    ("预算", "budget"),
    ("报销", "expense"),
    # 用户/活跃类
    ("DAU", "dau"),
    ("MAU", "mau"),
    ("EDAU", "edau"),
    # 业务域
    ("社区", "comm"),
    ("内容", "content"),
    ("笔记", "note"),
    ("互动", "engage"),
    ("曝光", "expose"),
    ("意图", "intent"),
    ("活动", "act"),
    ("营销", "mkt"),
    ("广告", "ad"),
    # 兜底
    ("用户", "user"),
]

# 指标后缀 —— 复合短语必须排在前面，避免被单字短语抢走
# 例："访问次数趋势" 应匹配为 "calls_trend"，不是 "trend" 或 "calls"
METRIC_SUFFIX: list[tuple[str, str]] = [
    # 复合：xx + 趋势（优先级最高）
    ("访问次数趋势", "calls_trend"),
    ("访问人数趋势", "users_trend"),
    ("访问用户趋势", "users_trend"),
    ("次数趋势", "calls_trend"),
    ("人数趋势", "users_trend"),
    ("用户趋势", "users_trend"),
    # 复合：成功/失败 + xx
    ("成功率", "success_rate"),
    ("失败率", "fail_rate"),
    ("成功次数", "success_count"),
    ("失败次数", "fail_count"),
    ("成功用户", "success_users"),
    ("失败用户", "fail_users"),
    # 复合：访问 + xx
    ("访问次数", "calls"),
    ("访问人数", "users"),
    ("访问用户", "users"),
    # 复合：查询 + xx（覆盖"发票查询次数"这类命名）
    ("查询次数", "calls"),
    ("查询人数", "users"),
    ("查询用户数", "users"),
    ("查询用户", "users"),
    # 复合：xx + 用户数（处理"用户数"独立场景，与"用户"区分）
    ("用户数", "users"),
    # 单点指标
    ("使用概览", "overview"),
    ("概览", "overview"),
    ("分布", "dist"),
    ("排行", "rank"),
    ("汇总", "summary"),
    ("总数", "total"),
    # 兜底：单字指标
    ("趋势图", "trend"),
    ("趋势", "trend"),
    ("次数", "count"),
    ("人数", "users"),
    ("数量", "count"),
    ("Top", "top"),
]


def chart_name_to_key(name: str, used: set[str] | None = None) -> str:
    """
    把中文 chart_name 映射成业务 key（小写蛇形）。

    Args:
        name:  中文图表名（如"资金意图访问次数统计"）
        used:  已被占用的 key 集合（用于去重）；命中重复时追加 _2 / _3。
               如果为 None，不做去重。

    Returns:
        命中映射 → 蛇形英文 key（如"fund_calls"）
        无法映射 → 空字符串（由调用方走兜底策略）

    Examples:
        >>> chart_name_to_key("资金意图访问次数统计")
        'fund_calls'
        >>> chart_name_to_key("意图访问次数趋势图")
        'intent_calls_trend'
        >>> chart_name_to_key("发票查询成功次数统计")
        'inv_success_count'
        >>> chart_name_to_key("XXX 无法识别")
        ''
        >>> used = {'fund_calls'}
        >>> chart_name_to_key("资金意图访问次数统计", used)
        'fund_calls_2'
    """
    if not name:
        return ""

    prefix = next((en for cn, en in DOMAIN_PREFIX if cn in name), "")
    suffix = next((en for cn, en in METRIC_SUFFIX if cn in name), "")

    # 必须至少命中一个，否则返回空（让调用方走 ref_N 兜底）
    if not prefix and not suffix:
        return ""

    key = "_".join(p for p in (prefix, suffix) if p)

    # 去重
    if used is not None:
        base, n = key, 2
        while key in used:
            key = f"{base}_{n}"
            n += 1
        used.add(key)

    return key
