# -*- coding: utf-8 -*-
"""主界面文件选择入口测试。"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from match_stock_gui import MainWindow


def test_main_window_exposes_file_selection_buttons(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_startup_check", lambda self: None)
    window = MainWindow()

    assert window.btn_choose_sales.text() == "选择销售资料"
    assert window.btn_choose_stock.text() == "选择库存表"
    assert hasattr(window, "btn_choose_presale")
    assert window.btn_choose_presale.text() == "选择出货天数资料"
    assert "预售单号" in [window.status_filter.itemText(i) for i in range(window.status_filter.count())]

    window.close()
    app.processEvents()


def test_startup_without_resume_keeps_file_choice_in_main_window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    import match_stock_gui

    monkeypatch.setattr(match_stock_gui, "load_state", lambda: None)
    calls = []
    monkeypatch.setattr(MainWindow, "choose_sales", lambda self: calls.append("sales"))
    window = MainWindow()
    window._startup_check()

    assert calls == []
    assert "主界面" in window.lbl_status.text()
    window.close()
    app.processEvents()


def test_rerendering_cards_does_not_detach_old_cards_as_popup_windows(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_startup_check", lambda self: None)
    window = MainWindow()

    item = {"candidates": [("SKU-100", 8, 1.0, "自动") ]}
    window._render_cards(item)
    old_card = window.card_widgets[0]

    window._render_cards(item)

    assert old_card.parentWidget() is window.cards_host
    window.close()
    app.processEvents()


def test_completion_action_is_named_finish_matching(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_startup_check", lambda self: None)
    window = MainWindow()

    assert window.btn_finish.text() == "完成匹配"
    assert any(action.text() == "完成匹配" for action in window.menuBar().actions()[1].menu().actions())

    window.close()
    app.processEvents()


def test_presale_filter_can_switch_from_non_presale_row(monkeypatch):
    """从普通行切换到预售单号筛选时，列表应只显示预售行且不抛异常。"""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_startup_check", lambda self: None)
    window = MainWindow()
    window.items = [
        {
            "f": "normal", "e": "", "spec": "1", "cid": "1", "name": "普通",
            "auto_status": "已确认", "decision": None, "auto_av": 5, "i_old": 2,
            "candidates": [], "no_stock_tag": False, "is_presale": False,
            "auto_desc": "普通匹配",
        },
        {
            "f": "pre-sale", "e": "", "spec": "2", "cid": "2", "name": "预售",
            "auto_status": "预售单号", "decision": None, "auto_av": None, "i_old": 8,
            "candidates": [], "no_stock_tag": False, "is_presale": True,
            "presale_days": 30, "auto_desc": "预售单号",
        },
    ]
    window._in_review = True
    window.idx = 0
    window._apply_filter(reset=True)
    window.status_filter.blockSignals(True)
    window.status_filter.setCurrentText("预售单号")
    window.status_filter.blockSignals(False)
    window._apply_filter()

    assert window.filtered == [1]
    assert window.listw.count() == 1
    assert window.idx == 1
    window.idx = window.filtered[0]
    window._show_current()
    assert not window.btn_adopt.isEnabled()
    assert not window.btn_keep.isEnabled()
    assert not window.btn_zero.isEnabled()
    assert not window.btn_custom.isEnabled()
    window.close()
    app.processEvents()
