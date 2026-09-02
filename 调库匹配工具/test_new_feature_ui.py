# -*- coding: utf-8 -*-
"""批量复核与预售开关的界面契约测试。"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QFrame

import match_stock_gui
from match_stock_gui import MainWindow
from review_logic import DECISION_ADOPT, DECISION_ZERO


def test_main_window_exposes_batch_and_presale_controls(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_startup_check", lambda self: None)
    window = MainWindow()

    assert window.btn_select_all.text() == "全选"
    assert window.btn_clear_selection.text() == "取消全选"
    assert window.btn_batch.text() == "批量操作"
    assert window.btn_manage_mappings.text() == "管理历史映射"
    assert window.chk_include_presale.text() == "参与预售订单调库"
    assert window.chk_include_presale.isChecked() is False
    assert window.chk_close_presale.text() == "关闭预售（预售天数改为1）"
    assert window.btn_choose_combo.text() == "选择组合 SKU 表"
    assert window.lbl_combo.text() == "组合 SKU 表: 未选择"
    assert window.findChild(QFrame, "sourcePanel") is not None

    window.close()
    app.processEvents()


def _review_row(f, status, *, auto_av=None, is_presale=False, enabled=False):
    return {
        "row": 2, "cid": f, "name": "测试商品", "spec": "700001", "f": f, "e": "",
        "i_old": 4, "auto_status": status, "auto_sku": "SKU-100", "auto_av": auto_av,
        "auto_desc": "测试匹配", "candidates": [], "decision": None, "user_av": None,
        "matched_sku": "", "user_desc": "", "no_stock_tag": False, "is_presale": is_presale,
        "presale_days": 7 if is_presale else None, "presale_enabled": enabled,
        "close_presale": False, "presale_source_rows": [4] if is_presale else [],
        "presale_source_sheet": "Sheet", "presale_days_col": 9,
    }


def test_batch_actions_select_unresolved_rows_and_leave_disabled_presale_unchanged(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_startup_check", lambda self: None)
    monkeypatch.setattr(match_stock_gui, "save_state", lambda *args: None)
    monkeypatch.setattr(match_stock_gui, "remember_mapping", lambda *args, **kwargs: None)
    window = MainWindow()
    window.items = [
        _review_row("suggest", "建议", auto_av=8),
        _review_row("pending", "待手选"),
        _review_row("presale", "预售单号", is_presale=True),
    ]
    window._in_review = True
    window._apply_filter(reset=True)
    window._select_all_visible()

    assert window.selected_indices == {0, 1, 2}
    window._batch_decide(DECISION_ZERO)

    assert window.items[0]["decision"] == DECISION_ZERO
    assert window.items[1]["decision"] == DECISION_ZERO
    assert window.items[2]["decision"] is None
    assert 2 in window.selected_indices

    window.close()
    app.processEvents()


def test_enabled_presale_can_be_batch_confirmed_and_closed(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_startup_check", lambda self: None)
    monkeypatch.setattr(match_stock_gui, "save_state", lambda *args: None)
    remembered = []
    monkeypatch.setattr(
        match_stock_gui, "remember_mapping",
        lambda mappings, sales_f, stock_sku: remembered.append((sales_f, stock_sku)),
    )
    window = MainWindow()
    window.items = [_review_row("presale", "建议", auto_av=12, is_presale=True, enabled=True)]
    window._in_review = True
    window._apply_filter(reset=True)
    window.selected_indices = {0}
    window._batch_decide(DECISION_ADOPT)

    assert window.items[0]["decision"] == DECISION_ADOPT
    assert remembered == [("presale", "SKU-100")]

    window.selected_indices = {0}
    window._batch_toggle_presale(True)
    assert window.items[0]["close_presale"] is True
    window.close()
    app.processEvents()
