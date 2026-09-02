# -*- coding: utf-8 -*-
"""复核动作纯逻辑测试。"""

from review_logic import (
    DECISION_ADOPT,
    DECISION_KEEP,
    DECISION_ZERO,
    DECISION_CUSTOM,
    apply_decision,
    final_write,
    migrate_decision,
    summarize_items,
    unresolved_items,
)


def item(auto_status="已确认", auto_av=18, i_old=12):
    return {
        "auto_status": auto_status,
        "auto_av": auto_av,
        "auto_sku": "51500621-black",
        "i_old": i_old,
        "decision": None,
        "user_av": None,
        "matched_sku": "",
        "user_desc": "",
    }


def test_auto_confirm_uses_auto_value_without_explicit_decision():
    ok, value, action = final_write(item())
    assert (ok, value, action) == (True, 18, "自动采用")


def test_suggest_without_decision_keeps_original_and_is_unresolved():
    row = item(auto_status="建议")
    ok, value, action = final_write(row)
    assert (ok, value, action) == (False, 12, "未处理")
    assert unresolved_items([row]) == [row]


def test_four_decisions_produce_expected_write_values():
    adopted = item(auto_status="待手选", auto_av=9)
    apply_decision(adopted, DECISION_ADOPT, auto_sku="51500621-red", value=9)
    assert final_write(adopted) == (True, 9, "采用自动值")

    kept = item(auto_status="建议")
    apply_decision(kept, DECISION_KEEP)
    assert final_write(kept) == (False, 12, "保留原值")

    zero = item(auto_status="待手选")
    apply_decision(zero, DECISION_ZERO)
    assert final_write(zero) == (True, 0, "调为0")

    custom = item(auto_status="待手选")
    apply_decision(custom, DECISION_CUSTOM, value=321)
    assert final_write(custom) == (True, 321, "手动输入")


def test_apply_decision_rejects_invalid_custom_values():
    row = item(auto_status="待手选")
    for value in (-1, 1.5, "321"):
        try:
            apply_decision(row, DECISION_CUSTOM, value=value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid value accepted: {value!r}")


def test_invalid_adopt_does_not_leave_a_partial_decision():
    row = item(auto_status="待手选", auto_av=None)
    try:
        apply_decision(row, DECISION_ADOPT)
    except ValueError:
        pass
    else:
        raise AssertionError("adopt without an automatic value should fail")
    assert row["decision"] is None


def test_summary_counts_explicit_actions_and_auto_defaults():
    rows = [item(), item("建议"), item("待手选")]
    rows[0]["low_stock_zero"] = True
    apply_decision(rows[1], DECISION_KEEP)
    apply_decision(rows[2], DECISION_ZERO)
    assert summarize_items(rows) == {
        "自动采用": 1,
        "保留原值": 1,
        "调为0": 1,
        "手动输入": 0,
        "自动调0": 1,
        "预售+9999": 0,
        "建议": 0,
        "待手选": 0,
        "预售单号": 0,
        "未处理": 0,
    }


def test_disabled_presale_item_stays_pending_without_manual_decision():
    """默认关闭自动预售调库时，未手动处理的预售行保持原库存。"""
    presale = item(auto_status="预售单号", auto_av=None, i_old=12)
    presale["is_presale"] = True

    assert final_write(presale) == (False, 12, "预售单号-不参与调库")
    assert unresolved_items([presale]) == []
    assert summarize_items([presale])["预售单号"] == 1


def test_disabled_presale_item_can_be_manually_written():
    """自动预售调库关闭时，运营仍可在复核阶段手动采用匹配库存。"""
    presale = item(auto_status="预售单号", auto_av=10008, i_old=12)
    presale["is_presale"] = True
    presale["presale_enabled"] = False
    presale["presale_bonus"] = 9999

    apply_decision(presale, DECISION_ADOPT)

    assert final_write(presale) == (True, 10008, "采用自动值")
    assert summarize_items([presale])["预售单号"] == 0
    assert summarize_items([presale])["预售+9999"] == 1


def test_enabled_presale_item_can_be_reviewed_and_written():
    presale = item(auto_status="已确认", auto_av=17, i_old=12)
    presale["is_presale"] = True
    presale["presale_enabled"] = True

    apply_decision(presale, DECISION_ADOPT)

    assert final_write(presale) == (True, 17, "采用自动值")


def test_migrate_legacy_decisions():
    old_confirm = item()
    old_confirm["decision"] = "确认匹配"
    old_confirm["user_av"] = 18
    assert migrate_decision(old_confirm)["decision"] == DECISION_ADOPT

    old_skip = item("建议")
    old_skip["decision"] = "跳过"
    assert migrate_decision(old_skip)["decision"] == DECISION_KEEP
