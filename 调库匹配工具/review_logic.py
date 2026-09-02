# -*- coding: utf-8 -*-
"""复核动作与最终写回值的纯逻辑。"""

DECISION_ADOPT = "采用自动值"
DECISION_KEEP = "保留原值"
DECISION_ZERO = "调为0"
DECISION_CUSTOM = "手动输入"

ACTION_LABELS = {
    DECISION_ADOPT: "采用自动值",
    DECISION_KEEP: "保留原值",
    DECISION_ZERO: "调为0",
    DECISION_CUSTOM: "手动输入",
}

LEGACY_DECISIONS = {
    "确认匹配": DECISION_ADOPT,
    "跳过": DECISION_KEEP,
}

AUTO_DONE = "已确认"
PRESALE_STATUS = "预售单号"
REVIEW_STATUSES = ("建议", "待手选")
SUMMARY_KEYS = ("自动采用", "保留原值", "调为0", "手动输入", "建议", "待手选", "预售单号", "未处理")


def _non_negative_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("库存必须是非负整数")
    return value


def _non_negative_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError("库存必须是非负数")
    return value


def apply_decision(row, decision, *, value=None, auto_sku=None):
    """将一个复核动作写入行字典，并返回该行。"""
    if row.get("is_presale") and not row.get("presale_enabled"):
        raise ValueError("预售单号不允许调整库存")
    if decision not in ACTION_LABELS:
        raise ValueError(f"未知复核动作: {decision}")

    if decision == DECISION_ADOPT:
        if value is None:
            value = row.get("auto_av")
        if value is None:
            raise ValueError("当前行没有可采用的自动匹配库存")
        _non_negative_number(value)
    elif decision == DECISION_KEEP:
        value = None
    elif decision == DECISION_ZERO:
        value = 0
    elif decision == DECISION_CUSTOM:
        value = _non_negative_int(value)

    row["decision"] = decision
    row["matched_sku"] = ""
    if decision == DECISION_ADOPT:
        row["user_av"] = value
        row["matched_sku"] = auto_sku or row.get("auto_sku", "")
        row["user_desc"] = f"采用匹配值 -> {row['matched_sku'] or '自动结果'} ({value})"
    elif decision == DECISION_KEEP:
        row["user_av"] = None
        row["user_desc"] = "保留原值"
    elif decision == DECISION_ZERO:
        row["user_av"] = 0
        row["user_desc"] = "调为0"
    elif decision == DECISION_CUSTOM:
        row["user_av"] = value
        row["user_desc"] = f"手动输入 {value}"

    return row


def final_write(row):
    """返回 (是否写入单元格, 最终值, 动作标签)。"""
    decision = row.get("decision")
    old_value = row.get("i_old")

    if row.get("is_presale") and not row.get("presale_enabled"):
        return False, old_value, "预售单号-不参与调库"

    if decision == DECISION_ADOPT:
        value = row.get("user_av")
        if value is None:
            value = row.get("auto_av")
        if value is None:
            return False, old_value, "未处理"
        return True, value, "采用自动值"
    if decision == DECISION_KEEP:
        return False, old_value, "保留原值"
    if decision == DECISION_ZERO:
        return True, 0, "调为0"
    if decision == DECISION_CUSTOM:
        value = row.get("user_av")
        if value is None:
            return False, old_value, "未处理"
        return True, value, "手动输入"

    if row.get("auto_status") == AUTO_DONE and row.get("auto_av") is not None:
        return True, row["auto_av"], "自动采用"
    return False, old_value, "未处理"


def unresolved_items(items):
    """返回没有明确动作且需要人工关注的行。"""
    return [
        row for row in items
        if (row.get("presale_enabled") or not row.get("is_presale"))
        and row.get("decision") is None
        and row.get("auto_status") in REVIEW_STATUSES
    ]


def summarize_items(items):
    """按最终动作和自动状态汇总行数，始终返回固定键。"""
    summary = {key: 0 for key in SUMMARY_KEYS}
    for row in items:
        if ((row.get("is_presale") and not row.get("presale_enabled"))
                or row.get("auto_status") == PRESALE_STATUS):
            summary[PRESALE_STATUS] += 1
            continue
        _should_write, _value, action = final_write(row)
        if action in ("自动采用", "采用自动值"):
            summary["自动采用"] += 1
        elif action in ("保留原值", "调为0", "手动输入"):
            summary[action] += 1
        elif row.get("auto_status") in REVIEW_STATUSES:
            summary[row["auto_status"]] += 1
        else:
            summary["未处理"] += 1
    return summary


def migrate_decision(row):
    """把旧版 GUI 保存的动作名迁移到当前四动作定义。"""
    old = row.get("decision")
    if old in LEGACY_DECISIONS:
        row["decision"] = LEGACY_DECISIONS[old]
        if row["decision"] == DECISION_KEEP:
            row["user_av"] = None
            row["user_desc"] = "保留原值"
        elif not row.get("user_desc"):
            row["user_desc"] = "采用自动值"
    return row
