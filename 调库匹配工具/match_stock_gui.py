# -*- coding: utf-8 -*-
"""
调库匹配 v2.0 —— 自动匹配 + 人工复核 + 确认写回 桌面工具
工作流：选文件 → 自动匹配(后台) → 逐行人工复核 → 完成写回(先备份/检查)
"""

import os
import re
import sys
import shutil
import traceback
from datetime import datetime

import pandas as pd
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QLineEdit, QListWidget,
    QListWidgetItem, QHBoxLayout, QVBoxLayout, QGridLayout, QSplitter,
    QFrame, QScrollArea, QFileDialog, QMessageBox, QInputDialog,
    QProgressDialog, QStatusBar, QMenuBar, QToolBar, QFormLayout,
    QSizePolicy, QApplication, QAbstractItemView, QComboBox, QCheckBox, QMenu,
)

# 本地模块（PyInstaller 冻结时通过 sys._MEIPASS 也能导入）
from match_stock import Matcher, norm_basic
from loader import (
    load_stock_index_robust,
    load_combo_sku_mapping_robust,
    resolve_combo_inventory,
    load_sales_rows_robust,
    load_presale_specs_robust,
    write_sales_inventory_values,
    write_presale_days_values,
)
from mapping_memory import (
    load_mapping_memory,
    save_mapping_memory,
    remember_mapping,
    resolve_remembered_mapping,
)
from candidates import build_candidates, build_pool, build_run_index
from settings import Settings
from review_state import save_state, load_state, clear_state, is_valid_state, migrate_items
from review_logic import (
    DECISION_ADOPT,
    DECISION_KEEP,
    DECISION_ZERO,
    DECISION_CUSTOM,
    final_write,
    summarize_items,
    unresolved_items,
    apply_decision,
    PRESALE_STATUS,
    REVIEW_STATUSES,
)
from widgets import (
    CandidateCard, StatLabel, MappingEditorDialog,
    COLOR_CONFIRMED, COLOR_SUGGEST, COLOR_PENDING, COLOR_PRESALE, COLOR_SKIPPED,
    COLOR_KEEP, COLOR_ADOPT, COLOR_ZERO, COLOR_CUSTOM,
    COLOR_AUTO_ZERO, COLOR_PRESALE_BONUS,
)

APP_VERSION = "2.4.0"
AUTO_STATUS_DONE = "已确认"     # 高置信度自动命中
AUTO_STATUS_ADV  = "建议"       # 低置信度建议复核
AUTO_STATUS_PEND = "待手选"     # 未匹配，需人工选择
AUTO_STATUS_PRESALE = PRESALE_STATUS

DECISION_NONE = None

STATUS_COLORS = {
    "已确认": COLOR_CONFIRMED,
    "建议": COLOR_SUGGEST,
    "待手选": COLOR_PENDING,
    AUTO_STATUS_PRESALE: COLOR_PRESALE,
    DECISION_ADOPT: COLOR_ADOPT,
    DECISION_KEEP: COLOR_KEEP,
    DECISION_ZERO: COLOR_ZERO,
    DECISION_CUSTOM: COLOR_CUSTOM,
}


def _app_dir():
    """返回脚本目录或冻结后 EXE 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# ==================== 后台自动匹配线程 ====================

class AutoMatchWorker(QThread):
    progress = Signal(int, str)      # (百分比, 消息)
    succeeded = Signal(list, str, str, str)    # (items, 库存表, 预售资料, 组合表)
    failed = Signal(str)

    def __init__(self, sales_path, stock_path, presale_path,
                 include_presale=False, mapping_memory=None, combo_path="",
                 presale_bonus_enabled=True, low_stock_zero_enabled=True, parent=None):
        super().__init__(parent)
        self.sales_path = sales_path
        self.stock_path = stock_path
        self.presale_path = presale_path
        self.include_presale = bool(include_presale)
        self.presale_bonus_enabled = bool(presale_bonus_enabled)
        self.low_stock_zero_enabled = bool(low_stock_zero_enabled)
        self.mapping_memory = mapping_memory if mapping_memory is not None else load_mapping_memory()
        self.combo_path = combo_path or ""
        self.items = []

    def run(self):
        try:
            self.progress.emit(2, "读取库存表...")
            exact, norm, meta = load_stock_index_robust(self.stock_path)
            self.progress.emit(15, f"库存表已载入（{meta['rows']}条SKU），读取销售资料...")
            rows = load_sales_rows_robust(self.sales_path)
            if not rows:
                raise ValueError("销售资料没有可处理的数据行")
            self.progress.emit(22, "读取出货天数资料...")
            presale_specs, presale_meta = load_presale_specs_robust(self.presale_path)
            combo_mapping = {}
            combo_meta = {
                "rows": 0, "unique_combos": 0, "component_rows": 0,
                "duplicate_combos": 0, "skipped_rows": 0, "sheet": "",
            }
            if self.combo_path:
                self.progress.emit(25, "读取组合 SKU 表...")
                combo_mapping, combo_meta = load_combo_sku_mapping_robust(self.combo_path)
            matcher = Matcher(exact, norm)
            pool = build_pool(exact)
            run_index = build_run_index(exact)

            total = len(rows)
            match_progress_start = 27 if self.combo_path else 22
            items = []
            for i, rec in enumerate(rows):
                f, e = rec["f"], rec["e"]
                no_stock_tag = "无备货" in f
                spec = rec.get("spec", "")
                presale_days = presale_specs.get(spec)
                is_presale = presale_days is not None
                presale_enabled = is_presale and self.include_presale
                memory_hit = False
                combo_hit = False
                combo_result = None
                low_stock_zero = False
                presale_bonus = 0

                remembered = resolve_remembered_mapping(f, self.mapping_memory, exact, norm)
                if remembered is not None:
                    sku, av = remembered
                    st = "OK"
                    memory_hit = True
                    desc = f"历史记忆匹配：{sku}"
                else:
                    st, sku, av, desc = matcher.match_one(f, tag="F")

                # L8: E列主商品货号兜底
                if (not memory_hit and st not in ("OK", "部分匹配")
                        and e and e.lower() != "nan"):
                    st2, sku2, av2, desc2 = matcher.match_one(e, tag="E")
                    if st2 == "OK":
                        st, sku, av, desc = "OK", sku2, av2, f"E列兜底: {desc2}"
                    elif st2 == "部分匹配":
                        st, sku, av, desc = "部分匹配", sku2, av2, f"E列兜底: {desc2}"

                # 组合表是低优先级兜底：普通规则已经命中时不查询；
                # 货号含 zuhe 或普通规则未命中时，用 F列组合自定义 SKU 查 B->C。
                combo_requested = bool(re.search(r"zuhe", f, re.IGNORECASE)) \
                    or st not in ("OK", "部分匹配")
                if combo_mapping and combo_requested:
                    combo_result = resolve_combo_inventory(
                        f, combo_mapping, meta.get("system_index", {}))
                    if combo_result["status"] == "OK":
                        st = "组合表"
                        sku = " + ".join(combo_result["system_skus"])
                        av = combo_result["available"]
                        combo_hit = True
                        desc = (
                            f"组合表兜底：B列组合自定义SKU {f!r} -> "
                            f"C列子系统SKU {', '.join(combo_result['system_skus'])}；"
                            f"组合可用库存 {av}")
                    elif st not in ("OK", "部分匹配"):
                        desc = f"{desc}；组合表查询：{combo_result['reason']}"

                if st == "OK":
                    auto_status = AUTO_STATUS_DONE
                    auto_av = av
                elif st in ("部分匹配", "组合表"):
                    auto_status = AUTO_STATUS_ADV
                    auto_av = av
                else:
                    auto_status = AUTO_STATUS_PEND
                    auto_av = None

                # 规则只改变自动建议值；是否自动写回由预售参与开关和复核动作决定。
                if auto_av is not None:
                    if is_presale and self.presale_bonus_enabled:
                        auto_av = auto_av + 9999
                        presale_bonus = 9999
                        desc += "；预售订单库存自动加 9999"
                    elif (not is_presale and self.low_stock_zero_enabled
                          and auto_av < 10):
                        low_stock_zero = True
                        desc += f"；匹配库存 {auto_av} 小于 10，自动调为 0"
                        auto_av = 0
                        auto_status = AUTO_STATUS_DONE
                if is_presale:
                    mode = "已开启" if self.include_presale else "未开启"
                    desc = f"预售订单（{mode}自动调库）：{desc}"
                    if not self.include_presale:
                        auto_status = AUTO_STATUS_PRESALE
                # 候选卡片展示最终将采用的库存值（含预售加量/低库存调零）。
                av = auto_av
                cands = build_candidates(f, e, exact, norm, matcher, pool, run_index,
                                         top_n=6, auto_match=(st, sku, av, desc))
                items.append({
                    "row": rec["row"],
                    "sales_sheet": rec.get("sheet", "Sheet1"),
                    "cid": rec["cid"],
                    "name": rec["name"],
                    "spec": spec,
                    "f": rec["f"],
                    "e": rec["e"],
                    "i_old": rec["i_old"],
                    "auto_status": auto_status,
                    "auto_sku": sku or "",
                    "auto_av": auto_av,
                    "auto_desc": desc,
                    "candidates": cands,
                    "decision": DECISION_NONE,
                    "user_av": None,
                    "matched_sku": "",
                    "user_desc": "",
                    "no_stock_tag": no_stock_tag,
                    "is_presale": is_presale,
                    "presale_days": presale_days if is_presale else None,
                    "presale_enabled": presale_enabled,
                    "presale_bonus_enabled": self.presale_bonus_enabled,
                    "low_stock_zero_enabled": self.low_stock_zero_enabled,
                    "close_presale": False,
                    "presale_source_rows": presale_meta.get("rows_by_spec", {}).get(spec, []) if is_presale else [],
                    "presale_source_sheet": presale_meta.get("sheet", "") if is_presale else "",
                    "presale_days_col": presale_meta.get("days_col") if is_presale else None,
                    "remembered_mapping": memory_hit,
                    "combo_hit": combo_hit,
                    "combo_checked": combo_result is not None,
                    "combo_status": combo_result.get("status", "") if combo_result else "",
                    "combo_system_skus": combo_result.get("system_skus", []) if combo_result else [],
                    "combo_components": combo_result.get("components", []) if combo_result else [],
                    "low_stock_zero": low_stock_zero,
                    "presale_bonus": presale_bonus,
                })
                if (i + 1) % 200 == 0 or i + 1 == total:
                    self.progress.emit(
                        match_progress_start
                        + int((100 - match_progress_start) * (i + 1) / total),
                        f"自动匹配中 {i+1}/{total}")
            self.items = items
            self.progress.emit(100, f"完成，共 {total} 行")
            self.succeeded.emit(
                items,
                f"{meta['sheet']} | {meta['rows']}条SKU",
                f"{presale_meta['sheet']} | {presale_meta['unique_specs']}条预售规格",
                (f"{combo_meta['sheet']} | {combo_meta['unique_combos']}个组合"
                 if self.combo_path else "未选择"),
            )
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


# ==================== 主窗口 ====================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.items = []                # 全部行
        self.filtered = []             # 列表显示索引（含搜索过滤）
        self.idx = -1                  # filtered 中的当前下标
        self.exact = None
        self.norm = None
        self.matcher = None
        self.pool = None
        self.run_index = None
        self.sales_path = ""
        self.stock_path = ""
        self.presale_path = ""
        self.combo_path = ""
        self.sales_sheet = "Sheet1"
        self.stock_meta = ""
        self.presale_meta = ""
        self.combo_meta = ""
        self._selected_card = None
        self._worker = None
        self._in_review = False
        self.mapping_memory = load_mapping_memory()
        self.selected_indices = set()

        self.setWindowTitle(f"调库匹配 v{APP_VERSION}")
        self.resize(*self.settings.get_window()[:2])
        self._build_ui()
        self._refresh_stats()
        self._set_controls_enabled(False)
        QTimer.singleShot(0, self._startup_check)

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        # 菜单
        menubar = self.menuBar()
        m_file = menubar.addMenu("文件(&F)")
        a_open_sales = m_file.addAction("选择销售资料...")
        a_open_sales.triggered.connect(self.choose_sales)
        a_open_stock = m_file.addAction("选择库存表...")
        a_open_stock.triggered.connect(self.choose_stock)
        a_open_presale = m_file.addAction("选择出货天数资料...")
        a_open_presale.triggered.connect(self.choose_presale)
        a_open_combo = m_file.addAction("选择组合 SKU 表...")
        a_open_combo.triggered.connect(self.choose_combo)
        a_manage_mappings = m_file.addAction("管理历史映射...")
        a_manage_mappings.triggered.connect(self.manage_mappings)
        m_file.addSeparator()
        a_report = m_file.addAction("打开最近报告...")
        a_report.triggered.connect(self.open_last_report)
        m_file.addSeparator()
        a_quit = m_file.addAction("退出")
        a_quit.triggered.connect(self.close)

        m_op = menubar.addMenu("操作(&A)")
        a_start = m_op.addAction("开始自动匹配")
        a_start.triggered.connect(self.start_matching)
        a_finish = m_op.addAction("完成匹配")
        a_finish.triggered.connect(self.finish_writeback)
        a_cancel = m_op.addAction("取消本次复核")
        a_cancel.triggered.connect(self.cancel_review)

        # 资料区独立成两行，避免组合表长文件名挤压操作区。
        source_bar = QToolBar("资料")
        source_bar.setMovable(False)
        source_panel = QFrame()
        source_panel.setObjectName("sourcePanel")
        source_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        source_grid = QGridLayout(source_panel)
        source_grid.setContentsMargins(8, 3, 8, 3)
        source_grid.setHorizontalSpacing(12)
        source_grid.setVerticalSpacing(2)

        self.lbl_sales = QLabel("销售资料: 未选择")
        self.lbl_stock = QLabel("库存表: 未选择")
        self.lbl_presale = QLabel("出货天数: 未选择")
        self.lbl_combo = QLabel("组合 SKU 表: 未选择")
        for label in (self.lbl_sales, self.lbl_stock, self.lbl_presale, self.lbl_combo):
            label.setStyleSheet("color:#7D746C;")
            label.setMinimumWidth(150)
            label.setMaximumWidth(320)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_choose_sales = QPushButton("选择销售资料")
        self.btn_choose_sales.clicked.connect(self.choose_sales)
        self.btn_choose_stock = QPushButton("选择库存表")
        self.btn_choose_stock.clicked.connect(self.choose_stock)
        self.btn_choose_presale = QPushButton("选择出货天数资料")
        self.btn_choose_presale.clicked.connect(self.choose_presale)
        self.btn_choose_combo = QPushButton("选择组合 SKU 表")
        self.btn_choose_combo.clicked.connect(self.choose_combo)
        source_grid.addWidget(self.btn_choose_sales, 0, 0)
        source_grid.addWidget(self.lbl_sales, 0, 1)
        source_grid.addWidget(self.btn_choose_stock, 0, 2)
        source_grid.addWidget(self.lbl_stock, 0, 3)
        source_grid.addWidget(self.btn_choose_presale, 1, 0)
        source_grid.addWidget(self.lbl_presale, 1, 1)
        source_grid.addWidget(self.btn_choose_combo, 1, 2)
        source_grid.addWidget(self.lbl_combo, 1, 3)
        source_grid.setColumnStretch(1, 1)
        source_grid.setColumnStretch(3, 1)
        source_bar.addWidget(source_panel)
        self.addToolBar(source_bar)

        # 操作设置独立成一行，资料导入后不会改变按钮宽度。
        action_bar = QToolBar("操作设置")
        action_bar.setMovable(False)
        self.chk_include_presale = QCheckBox("参与预售订单调库")
        self.chk_include_presale.setToolTip("默认关闭；开启后预售订单才会匹配并写入库存")
        self.chk_presale_bonus = QCheckBox("预售库存+9999")
        self.chk_presale_bonus.setChecked(True)
        self.chk_presale_bonus.setToolTip("勾选后，预售订单的自动匹配值增加 9999；关闭后使用原始匹配库存")
        self.chk_low_stock_zero = QCheckBox("库存<10自动调0")
        self.chk_low_stock_zero.setChecked(True)
        self.chk_low_stock_zero.setToolTip("勾选后，普通商品匹配库存小于 10 时自动建议为 0")
        self.btn_manage_mappings = QPushButton("管理历史映射")
        self.btn_manage_mappings.clicked.connect(self.manage_mappings)
        action_bar.addWidget(self.chk_include_presale)
        action_bar.addSeparator()
        btn_start = QPushButton("▶ 开始匹配")
        btn_start.clicked.connect(self.start_matching)
        self.btn_start = btn_start
        # 优先保证开始匹配可见；较次要的管理按钮在窄窗口时进入工具栏溢出菜单。
        action_bar.addWidget(btn_start)
        action_bar.addSeparator()
        action_bar.addWidget(self.chk_presale_bonus)
        action_bar.addWidget(self.chk_low_stock_zero)
        action_bar.addSeparator()
        action_bar.addWidget(self.btn_manage_mappings)
        self.addToolBar(action_bar)

        # 中央三栏
        splitter = QSplitter(Qt.Horizontal)

        # --- 左栏：搜索 + 列表 ---
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索货号 / 商品名 / 商品ID")
        self.search.textChanged.connect(self._apply_filter)
        ll.addWidget(self.search)
        self.status_filter = QComboBox()
        self.status_filter.addItems([
            "全部状态", "建议", "待手选", "预售单号",
            "自动调0", "预售+9999", "已处理", "已确认",
        ])
        self.status_filter.currentTextChanged.connect(lambda _text: self._apply_filter())
        ll.addWidget(self.status_filter)

        select_tools = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_clear_selection = QPushButton("取消全选")
        self.lbl_selected = QLabel("已选 0")
        self.btn_select_all.clicked.connect(self._select_all_visible)
        self.btn_clear_selection.clicked.connect(self._clear_selection)
        select_tools.addWidget(self.btn_select_all)
        select_tools.addWidget(self.btn_clear_selection)
        select_tools.addWidget(self.lbl_selected)
        ll.addLayout(select_tools)

        self.btn_batch = QPushButton("批量操作")
        batch_menu = QMenu(self.btn_batch)
        batch_menu.addAction("批量采用自动匹配值", lambda: self._batch_decide(DECISION_ADOPT))
        batch_menu.addAction("批量保留原值", lambda: self._batch_decide(DECISION_KEEP))
        batch_menu.addAction("批量调为0", lambda: self._batch_decide(DECISION_ZERO))
        batch_menu.addAction("批量手动输入库存", self._batch_custom)
        batch_menu.addSeparator()
        batch_menu.addAction("批量关闭预售", lambda: self._batch_toggle_presale(True))
        batch_menu.addAction("批量保持预售", lambda: self._batch_toggle_presale(False))
        self.btn_batch.setMenu(batch_menu)
        ll.addWidget(self.btn_batch)
        self.listw = QListWidget()
        self.listw.setSelectionMode(QAbstractItemView.SingleSelection)
        self.listw.currentItemChanged.connect(self._on_list_select)
        self.listw.itemDoubleClicked.connect(self._copy_item_sku)
        self.listw.itemChanged.connect(self._on_item_check_changed)
        ll.addWidget(self.listw)
        left.setMinimumWidth(280)
        splitter.addWidget(left)

        # --- 中栏：详情 + 候选卡片 ---
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(8, 8, 8, 8)

        self.lbl_info = QLabel("加载数据后开始复核")
        self.lbl_info.setWordWrap(True)
        f = QFont(); f.setPointSize(11); f.setBold(True)
        self.lbl_info.setFont(f)
        cl.addWidget(self.lbl_info)

        self.lbl_desc = QLabel("")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color:#9e9e9e;")
        cl.addWidget(self.lbl_desc)

        self.chk_close_presale = QCheckBox("关闭预售（预售天数改为1）")
        self.chk_close_presale.setVisible(False)
        self.chk_close_presale.toggled.connect(self._on_close_presale_toggled)
        cl.addWidget(self.chk_close_presale)

        self.hint = QLabel("单击候选卡片预览，双击直接采用；也可以使用底部四个复核动作")
        self.hint.setStyleSheet("color:#7D746C;")
        cl.addWidget(self.hint)

        # 候选卡片滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.cards_host = QWidget()
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setSpacing(10)
        self.cards_grid.setContentsMargins(0, 4, 0, 4)
        self.card_widgets = []
        scroll.setWidget(self.cards_host)
        cl.addWidget(scroll, 1)

        center.setMinimumWidth(520)
        splitter.addWidget(center)

        # --- 右栏：统计 ---
        right = QWidget()
        right.setFixedWidth(190)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)
        rl.addWidget(QLabel("<b>复核进度</b>"))
        self.stat = {}
        for key, color in (("自动采用", COLOR_CONFIRMED), ("保留原值", COLOR_KEEP),
                           ("调为0", COLOR_ZERO), ("手动输入", COLOR_CUSTOM),
                           ("自动调0", COLOR_AUTO_ZERO), ("预售+9999", COLOR_PRESALE_BONUS),
                           ("建议", COLOR_SUGGEST), ("待手选", COLOR_PENDING),
                           (AUTO_STATUS_PRESALE, COLOR_PRESALE),
                           ("未处理", COLOR_PENDING)):
            lab = StatLabel(key, color)
            self.stat[key] = lab
            rl.addWidget(lab)
        rl.addStretch(1)
        splitter.addWidget(right)

        self.setCentralWidget(splitter)

    # 底部：操作按钮 + 完成匹配
        bottom = QWidget()
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(8, 4, 8, 4)
        self.btn_prev = QPushButton("◀ 上一项")
        self.btn_next = QPushButton("下一项 ▶")
        self.btn_adopt = QPushButton("采用自动匹配值")
        self.btn_keep = QPushButton("保留原值")
        self.btn_zero = QPushButton("调为 0")
        self.btn_custom = QPushButton("手动输入库存")
        for b in (self.btn_prev, self.btn_next, self.btn_adopt,
                  self.btn_keep, self.btn_zero, self.btn_custom):
            b.clicked.connect(self._on_action)
            bl.addWidget(b)
        bl.addStretch(1)
        self.btn_finish = QPushButton("完成匹配")
        self.btn_finish.clicked.connect(self.finish_writeback)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.cancel_review)
        self.btn_adopt.setObjectName("primaryAction")
        self.btn_finish.setObjectName("finishAction")
        bl.addWidget(self.btn_finish)
        bl.addWidget(self.btn_cancel)
        self.statusBar()                # 创建状态栏
        self.statusBar().addWidget(bottom, 1)
        self.statusBar().setSizeGripEnabled(True)
        self.lbl_status = QLabel("就绪")
        self.statusBar().addPermanentWidget(self.lbl_status)

    def _set_controls_enabled(self, enabled: bool):
        for b in (self.btn_prev, self.btn_next, self.btn_adopt, self.btn_zero,
                  self.btn_custom, self.btn_keep, self.btn_finish,
                  self.btn_cancel):
            b.setEnabled(enabled)
        self.btn_select_all.setEnabled(enabled)
        self.btn_clear_selection.setEnabled(enabled)
        self.btn_batch.setEnabled(enabled)
        self.chk_include_presale.setEnabled(not enabled)
        self.chk_presale_bonus.setEnabled(not enabled)
        self.chk_low_stock_zero.setEnabled(not enabled)
        self.chk_close_presale.setEnabled(enabled)
        if not enabled:
            self.chk_close_presale.setVisible(False)
        self.btn_manage_mappings.setEnabled(True)
        self._refresh_selection_label()

    # ---------------- 启动 ----------------
    def _startup_check(self):
        st = load_state()
        if is_valid_state(st, self.settings.get_last_sales(), self.settings.get_last_presale(),
                          self.settings.get_last_combo()):
            ans = QMessageBox.question(
                self, "恢复上次进度",
                f"检测到未完成的复核状态（{st.get('saved_at','')}，{len(st['items'])} 行）。\n"
                "是否恢复上次进度？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ans == QMessageBox.Yes:
                self._load_state_into_ui(st)
                return
        self.lbl_status.setText("请在主界面选择销售资料、库存表和出货天数资料")

    # ---------------- 文件选择 ----------------
    def choose_sales(self):
        last = self.settings.get_last_sales()
        start = os.path.dirname(last) if last and os.path.exists(last) else os.path.expanduser("~")
        p, _ = QFileDialog.getOpenFileName(
            self, "选择销售资料 (xlsx)", start, "Excel 文件 (*.xlsx *.xls)")
        if not p:
            if not self.sales_path:
                self.statusBar().showMessage("未选择销售资料", 4000)
            return
        self.sales_path = p
        self.lbl_sales.setText(f"销售资料: {os.path.basename(p)}")
        self.lbl_sales.setToolTip(p)
        self.settings.set_paths(p, self.stock_path, self.presale_path, self.combo_path)
        self._auto_offer_start()

    def choose_stock(self):
        last = self.settings.get_last_stock()
        start = os.path.dirname(last) if last and os.path.exists(last) else os.path.expanduser("~")
        p, _ = QFileDialog.getOpenFileName(
            self, "选择库存表 (xls)", start, "Excel 文件 (*.xls *.xlsx)")
        if not p:
            return
        self.stock_path = p
        self.lbl_stock.setText(f"库存表: {os.path.basename(p)}")
        self.lbl_stock.setToolTip(p)
        self.settings.set_paths(self.sales_path, p, self.presale_path, self.combo_path)
        self._auto_offer_start()

    def choose_presale(self):
        last = self.settings.get_last_presale()
        start = os.path.dirname(last) if last and os.path.exists(last) else os.path.expanduser("~")
        p, _ = QFileDialog.getOpenFileName(
            self, "选择出货天数资料 (xlsx)", start, "Excel 文件 (*.xlsx *.xls)")
        if not p:
            return
        self.presale_path = p
        self.lbl_presale.setText(f"出货天数: {os.path.basename(p)}")
        self.lbl_presale.setToolTip(p)
        self.settings.set_paths(self.sales_path, self.stock_path, p, self.combo_path)
        self._auto_offer_start()

    def choose_combo(self):
        last = self.settings.get_last_combo()
        if last and os.path.exists(last):
            start = os.path.dirname(last)
        elif os.path.isdir(r"D:\download"):
            start = r"D:\download"
        else:
            start = os.path.expanduser("~")
        p, _ = QFileDialog.getOpenFileName(
            self, "选择组合 SKU 表 (CSV)", start, "CSV 文件 (*.csv);;所有文件 (*.*)")
        if not p:
            return
        self.combo_path = p
        self.lbl_combo.setText(f"组合 SKU 表: {os.path.basename(p)}")
        self.lbl_combo.setToolTip(p)
        self.settings.set_paths(self.sales_path, self.stock_path, self.presale_path, p)
        self.statusBar().showMessage("组合 SKU 表已选择，将在匹配失败或 zuhe 货号时作为兜底", 6000)

    def manage_mappings(self):
        dialog = MappingEditorDialog(self.mapping_memory, self)
        if dialog.exec() != dialog.Accepted:
            return
        self.mapping_memory = dialog.mappings()
        save_mapping_memory(self.mapping_memory)
        self.statusBar().showMessage(
            f"历史映射已保存：{len(self.mapping_memory)} 条，下次自动匹配时生效", 6000)

    def _auto_offer_start(self):
        if self.sales_path and self.stock_path and self.presale_path:
            ans = QMessageBox.question(self, "开始匹配", "文件已就绪，立即开始自动匹配？",
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ans == QMessageBox.Yes:
                self.start_matching()

    # ---------------- 自动匹配 ----------------
    def start_matching(self):
        if self._worker and self._worker.isRunning():
            return
        if not self.sales_path or not self.stock_path or not self.presale_path:
            QMessageBox.warning(self, "提示", "请先选择销售资料、库存表和出货天数资料")
            return
        if self.items and self._in_review:
            ans = QMessageBox.question(self, "重新匹配",
                                       "当前有复核数据，重新匹配将丢弃已有操作，是否继续？",
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        self._set_controls_enabled(False)
        self.lbl_status.setText("正在自动匹配...")
        prog = QProgressDialog("正在自动匹配...", None, 0, 100, self)
        prog.setWindowTitle("自动匹配")
        prog.setWindowModality(Qt.WindowModal)
        prog.setAutoClose(False)
        prog.setMinimumDuration(0)

        self.selected_indices.clear()
        self._worker = AutoMatchWorker(
            self.sales_path,
            self.stock_path,
            self.presale_path,
            include_presale=self.chk_include_presale.isChecked(),
            mapping_memory=self.mapping_memory,
            combo_path=self.combo_path,
            presale_bonus_enabled=self.chk_presale_bonus.isChecked(),
            low_stock_zero_enabled=self.chk_low_stock_zero.isChecked(),
        )
        self._worker.progress.connect(lambda v, m: (prog.setValue(v), prog.setLabelText(m)))
        self._worker.failed.connect(lambda e: (prog.close(), self._on_match_failed(e)))
        self._worker.succeeded.connect(
            lambda items, stock_meta, presale_meta, combo_meta: (
                prog.close(), self._on_match_done(
                    items, stock_meta, presale_meta, combo_meta)))
        self._worker.start()

    def _on_match_failed(self, err):
        self.lbl_status.setText("匹配失败")
        self._set_controls_enabled(False)
        QMessageBox.critical(self, "匹配失败", err[:2000])

    def _on_match_done(self, items, stock_meta, presale_meta, combo_meta="未选择"):
        self.items = items
        self.selected_indices.clear()
        if self.items:
            self.sales_sheet = self.items[0].get("sales_sheet", "Sheet1")
        self.stock_meta = stock_meta
        self.presale_meta = presale_meta
        self.combo_meta = combo_meta
        self._in_review = True
        self.chk_include_presale.blockSignals(True)
        self.chk_include_presale.setChecked(
            any(it.get("is_presale") and it.get("presale_enabled") for it in self.items)
        )
        self.chk_include_presale.blockSignals(False)
        saved_presale_bonus = next(
            (it.get("presale_bonus_enabled") for it in self.items
             if "presale_bonus_enabled" in it), True)
        saved_low_stock_zero = next(
            (it.get("low_stock_zero_enabled") for it in self.items
             if "low_stock_zero_enabled" in it), True)
        self.chk_presale_bonus.setChecked(bool(saved_presale_bonus))
        self.chk_low_stock_zero.setChecked(bool(saved_low_stock_zero))
        self._apply_filter(reset=True)
        self._set_controls_enabled(True)
        self.lbl_status.setText(
            f"匹配完成，进入复核模式（库存表: {stock_meta}；预售: {presale_meta}；"
            f"组合表: {combo_meta}）")
        save_state(self.sales_path, self.stock_path, self.presale_path, items, self.combo_path)
        # 跳到第一个待处理
        n = self._first_unresolved()
        if n is not None:
            self.idx = n
            self._sync_list_selection()
            self._show_current()
        self._refresh_stats()
        self.statusBar().showMessage(f"自动匹配完成：{len(items)} 行", 6000)

    # ---------------- 列表与导航 ----------------
    def _apply_filter(self, reset=False):
        kw = self.search.text().strip().lower()
        status_filter = self.status_filter.currentText() if hasattr(self, "status_filter") else "全部状态"
        if not self.items:
            self.listw.clear()
            self.filtered = []
            return
        def matches(i):
            it = self.items[i]
            text_match = not kw or any(
                kw in str(it.get(key, "")).lower()
                for key in ("f", "e", "spec", "cid", "name")
            )
            if status_filter == "已处理":
                status_match = it.get("decision") is not None
            elif status_filter == "已确认":
                status_match = it.get("decision") == DECISION_ADOPT or (
                    it.get("decision") is None and it.get("auto_status") == AUTO_STATUS_DONE
                )
            elif status_filter in (AUTO_STATUS_ADV, AUTO_STATUS_PEND):
                status_match = it.get("decision") is None and it.get("auto_status") == status_filter
            elif status_filter == AUTO_STATUS_PRESALE:
                status_match = it.get("is_presale") is True
            elif status_filter == "自动调0":
                status_match = bool(it.get("low_stock_zero"))
            elif status_filter == "预售+9999":
                status_match = bool(it.get("presale_bonus"))
            else:
                status_match = True
            return text_match and status_match

        self.filtered = [i for i in range(len(self.items)) if matches(i)]
        self._rebuild_list()

    def _status_symbol(self, it):
        if it.get("is_presale"):
            return AUTO_STATUS_PRESALE
        if it["decision"] in (DECISION_ADOPT, DECISION_KEEP, DECISION_ZERO, DECISION_CUSTOM):
            return it["decision"]
        if it["auto_status"] == AUTO_STATUS_DONE:
            return "已确认"
        if it["auto_status"] == AUTO_STATUS_ADV:
            return "建议"
        return "待手选"

    def _is_batch_target(self, it):
        if it.get("is_presale"):
            return True
        return (it.get("decision") is None
                and it.get("auto_status") in REVIEW_STATUSES)

    def _prune_selection(self):
        self.selected_indices = {
            i for i in self.selected_indices
            if 0 <= i < len(self.items) and self._is_batch_target(self.items[i])
        }

    def _refresh_selection_label(self):
        if not hasattr(self, "lbl_selected"):
            return
        self.lbl_selected.setText(f"已选 {len(self.selected_indices)}")

    def _rebuild_list(self):
        self._prune_selection()
        self.listw.blockSignals(True)
        self.listw.clear()
        for i in self.filtered:
            it = self.items[i]
            sym = self._status_symbol(it)
            tag = " ⚠无备货" if it["no_stock_tag"] and not it["decision"] else ""
            _should_write, final_value, _action = final_write(it)
            if (it.get("is_presale") and not it.get("presale_enabled")
                    and it.get("decision") is None):
                show_av = it.get("auto_av")
                auto_tag = " | 预售自动关闭"
            else:
                show_av = final_value
                auto_tag = ""
            show_av = "" if show_av is None else str(show_av)
            close_tag = " | 将关闭预售" if it.get("close_presale") else ""
            rule_tags = []
            if it.get("low_stock_zero"):
                rule_tags.append("自动调0")
            if it.get("presale_bonus"):
                rule_tags.append("预售+9999")
            rule_tag = f" | {' / '.join(rule_tags)}" if rule_tags else ""
            text = f"[{sym}] {it['f']}{tag}{close_tag}{auto_tag}{rule_tag}  |  库存:{show_av}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, i)
            if self._is_batch_target(it):
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if i in self.selected_indices else Qt.Unchecked)
            color = STATUS_COLORS.get(sym, STATUS_COLORS.get(it["auto_status"], COLOR_PENDING))
            item.setForeground(QColor(color))
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        if self.idx in self.filtered:
            self.listw.setCurrentRow(self.filtered.index(self.idx))
        elif self.filtered:
            self.idx = self.filtered[0]
            self.listw.setCurrentRow(0)
        else:
            self.idx = -1
        self._refresh_selection_label()

    def _on_item_check_changed(self, item):
        index = item.data(Qt.UserRole)
        if index is None:
            return
        index = int(index)
        if item.checkState() == Qt.Checked:
            self.selected_indices.add(index)
        else:
            self.selected_indices.discard(index)
        self._refresh_selection_label()

    def _copy_item_sku(self, item):
        """双击左侧列表行时复制销售资料 F 列货号。"""
        index = item.data(Qt.UserRole)
        if index is None:
            return
        index = int(index)
        if not (0 <= index < len(self.items)):
            return
        sku = str(self.items[index].get("f", ""))
        QApplication.clipboard().setText(sku)
        self.statusBar().showMessage(f"已复制货号：{sku}", 3000)

    def _select_all_visible(self):
        self.selected_indices.update(
            i for i in self.filtered if self._is_batch_target(self.items[i]))
        self._rebuild_list()

    def _clear_selection(self):
        self.selected_indices.clear()
        self._rebuild_list()

    def _on_list_select(self, cur, _prev):
        if cur is None:
            return
        row = self.listw.row(cur)
        if 0 <= row < len(self.filtered):
            self.idx = self.filtered[row]
            self._show_current()

    def _sync_list_selection(self):
        if self.idx in self.filtered:
            self.listw.setCurrentRow(self.filtered.index(self.idx))

    def _first_unresolved(self):
        for i, it in enumerate(self.items):
            if it["decision"] is None and it["auto_status"] in (AUTO_STATUS_ADV, AUTO_STATUS_PEND):
                return i
        return None

    def _show_current(self):
        if not self.items or self.idx < 0:
            return
        it = self.items[self.idx]
        sym = self._status_symbol(it)
        if it.get("is_presale"):
            self.chk_close_presale.blockSignals(True)
            self.chk_close_presale.setChecked(bool(it.get("close_presale")))
            self.chk_close_presale.blockSignals(False)
            self.chk_close_presale.setVisible(True)
            self.lbl_info.setText(
                f"{sym} | 规格编号: {it.get('spec') or '-'}  | 货号: {it['f']}  | "
                f"自动库存: {it.get('auto_av') if it.get('auto_av') is not None else '-'}  | "
                f"原库存: {it['i_old']}  | 出货天数: {it.get('presale_days')}")
            _should_write, final_value, action = final_write(it)
            desc = f"{it['auto_desc']}  | 当前动作: {action}  | 最终库存: " \
                   f"{final_value if final_value is not None else '-'}"
            if it.get("close_presale"):
                desc += "  | 关闭预售后出货天数将改为 1"
            self.lbl_desc.setText(desc)
            if it.get("presale_enabled"):
                self.hint.setText("预售调库已开启：可以确认库存，也可以单独勾选是否关闭预售")
            else:
                self.hint.setText(
                    "预售自动调库当前关闭：不会自动写入；仍可手动采用匹配值、保留原值、调0或输入库存")
            self._render_cards(it)
            for button in (self.btn_adopt, self.btn_keep, self.btn_zero, self.btn_custom):
                button.setEnabled(self._in_review)
            self._refresh_stats()
            return

        self.chk_close_presale.blockSignals(True)
        self.chk_close_presale.setChecked(False)
        self.chk_close_presale.blockSignals(False)
        self.chk_close_presale.setVisible(False)
        self.hint.setText("单击候选卡片预览，双击直接采用；也可以使用底部四个复核动作")
        for button in (self.btn_adopt, self.btn_keep, self.btn_zero, self.btn_custom):
            button.setEnabled(self._in_review)
        av_disp = it["user_av"] if it["decision"] else (
            it["auto_av"] if it["auto_av"] is not None else it["i_old"])
        self.lbl_info.setText(
            f"{sym} | 货号: {it['f']}  |  主货号: {it['e'] or '-'}  |  "
            f"自动库存: {it['auto_av'] if it['auto_av'] is not None else '-'}  |  原库存: {it['i_old']}")
        desc = it["auto_desc"] or ""
        _should_write, final_value, action = final_write(it)
        desc += f"  | 当前动作: {action}  | 最终值: {final_value if final_value is not None else '-'}"
        if it["no_stock_tag"] and not it["decision"]:
            desc += "  ⚠ 货号含'无备货'标注，请确认"
        self.lbl_desc.setText(desc)
        self._render_cards(it)
        self._refresh_stats()

    # ---------------- 候选卡片 ----------------
    def _render_cards(self, it):
        # 清空
        for w in self.card_widgets:
            self.cards_grid.removeWidget(w)
            w.hide()
            w.deleteLater()
        self.card_widgets = []
        # 重新布局
        cands = it["candidates"] or []
        if not cands:
            if it.get("is_presale") and not it.get("presale_enabled"):
                text = "预售自动调库未开启；仍可使用保留原值、调为0或手动输入库存。"
            else:
                text = "无候选。可点[匹配为0]或[自定义数值]或[跳过]。"
            lbl = QLabel(text)
            lbl.setStyleSheet("color:#888;")
            self.cards_grid.addWidget(lbl, 0, 0)
            self.card_widgets.append(lbl)
            return
        cols = 3
        self._selected_card = None
        for j, (sku, av, score, tag) in enumerate(cands):
            card = CandidateCard(sku, av, score, tag)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            r, c = divmod(j, cols)
            self.cards_grid.addWidget(card, r, c)
            self.card_widgets.append(card)
        for c in range(cols):
            self.cards_grid.setColumnStretch(c, 1)

    def _on_card_clicked(self, card):
        for w in self.card_widgets:
            if isinstance(w, CandidateCard):
                w.set_selected(w is card)
        self._selected_card = card

    def _on_card_double_clicked(self, card):
        self._on_card_clicked(card)
        self._decide_adopt()

    # ---------------- 决策动作 ----------------
    def _on_action(self):
        sender = self.sender()
        if sender is self.btn_prev:
            self._nav(-1)
        elif sender is self.btn_next:
            self._nav(1)
        elif sender is self.btn_adopt:
            self._decide_adopt()
        elif sender is self.btn_keep:
            self._decide_keep()
        elif sender is self.btn_zero:
            self._decide_zero()
        elif sender is self.btn_custom:
            self._decide_custom()

    def _nav(self, delta):
        if not self.filtered:
            return
        pos = self.filtered.index(self.idx) if self.idx in self.filtered else 0
        pos = (pos + delta) % len(self.filtered)
        self.idx = self.filtered[pos]
        self.listw.setCurrentRow(pos)
        self._show_current()

    def _decide_adopt(self):
        it = self.items[self.idx]
        if self._selected_card is not None:
            apply_decision(it, DECISION_ADOPT, value=self._selected_card.av,
                           auto_sku=self._selected_card.sku)
            if self._selected_card.tag != "组合表" and not it.get("combo_hit"):
                self._remember_current_mapping(self._selected_card.sku)
        elif it["auto_av"] is not None:
            apply_decision(it, DECISION_ADOPT)
            if it.get("auto_sku") and not it.get("combo_hit"):
                self._remember_current_mapping(it["auto_sku"])
        else:
            QMessageBox.information(self, "提示", "当前行没有自动匹配值，请先选择候选卡片或使用其他动作")
            return
        self._after_decision()

    def _decide_keep(self):
        it = self.items[self.idx]
        apply_decision(it, DECISION_KEEP)
        self._after_decision()

    def _decide_zero(self):
        it = self.items[self.idx]
        apply_decision(it, DECISION_ZERO)
        self._after_decision()

    def _decide_custom(self):
        it = self.items[self.idx]
        cur = it["auto_av"] if it["auto_av"] is not None else 0
        val, ok = QInputDialog.getInt(self, "手动输入库存", "输入非负整数:", cur, 0, 999999999)
        if not ok:
            return
        apply_decision(it, DECISION_CUSTOM, value=val)
        self._after_decision()

    def _remember_current_mapping(self, stock_sku):
        """保存人工确认的 F 列货号映射，供下次匹配直接复用。"""
        if not self.items or self.idx < 0 or not stock_sku:
            return
        try:
            remember_mapping(self.mapping_memory, self.items[self.idx].get("f", ""), stock_sku)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"历史映射保存失败：{exc}", 6000)

    def _selected_batch_indices(self):
        self._prune_selection()
        return sorted(self.selected_indices)

    def _batch_decide(self, decision):
        """对当前勾选的待复核行执行同一个库存动作。"""
        indices = self._selected_batch_indices()
        if not indices:
            QMessageBox.information(self, "批量操作", "请先在左侧列表勾选待处理行")
            return

        eligible = []
        skipped_no_value = 0
        for i in indices:
            it = self.items[i]
            if decision == DECISION_ADOPT and it.get("auto_av") is None:
                skipped_no_value += 1
                continue
            eligible.append(i)

        if decision == DECISION_CUSTOM:
            cur = 0
            values = [self.items[i].get("auto_av") for i in eligible]
            values = [v for v in values if isinstance(v, (int, float)) and v >= 0]
            if values:
                cur = int(values[0])
            value, ok = QInputDialog.getInt(
                self, "批量手动输入库存", "为选中行输入非负整数:", cur, 0, 999999999)
            if not ok:
                return
        else:
            value = None

        changed = 0
        for i in eligible:
            it = self.items[i]
            try:
                apply_decision(it, decision, value=value)
            except ValueError:
                continue
            changed += 1
            if decision == DECISION_ADOPT and it.get("auto_sku") and not it.get("combo_hit"):
                try:
                    remember_mapping(self.mapping_memory, it.get("f", ""), it["auto_sku"])
                except (OSError, ValueError):
                    pass

        self.selected_indices.difference_update(eligible)
        if changed:
            save_state(self.sales_path, self.stock_path, self.presale_path, self.items, self.combo_path)
            self._rebuild_list()
            self._refresh_stats()
            self._show_current()
        msg = f"已批量处理 {changed} 行"
        if skipped_no_value:
            msg += f"；{skipped_no_value} 行没有自动匹配值，未采用"
        if not changed:
            QMessageBox.information(self, "批量操作", msg)
        else:
            self.statusBar().showMessage(msg, 6000)

    def _batch_custom(self):
        self._batch_decide(DECISION_CUSTOM)

    def _batch_toggle_presale(self, close):
        indices = self._selected_batch_indices()
        targets = [i for i in indices if self.items[i].get("is_presale")]
        if not targets:
            QMessageBox.information(self, "批量操作", "请先勾选预售订单")
            return
        for i in targets:
            self.items[i]["close_presale"] = bool(close)
        self.selected_indices.difference_update(targets)
        save_state(self.sales_path, self.stock_path, self.presale_path, self.items, self.combo_path)
        self._rebuild_list()
        self._refresh_stats()
        self._show_current()
        self.statusBar().showMessage(
            f"已批量{'关闭' if close else '保持'} {len(targets)} 个预售订单", 6000)

    def _on_close_presale_toggled(self, checked):
        if not self.items or self.idx < 0:
            return
        it = self.items[self.idx]
        if not it.get("is_presale"):
            return
        it["close_presale"] = bool(checked)
        save_state(self.sales_path, self.stock_path, self.presale_path, self.items, self.combo_path)
        self._rebuild_list()
        self._refresh_stats()

    def _after_decision(self):
        save_state(self.sales_path, self.stock_path, self.presale_path, self.items, self.combo_path)
        self._rebuild_list()
        self._refresh_stats()
        # 自动跳到下一个未处理
        nxt = None
        for i in range(self.idx + 1, len(self.items)):
            if self.items[i]["decision"] is None and self.items[i]["auto_status"] in (AUTO_STATUS_ADV, AUTO_STATUS_PEND):
                nxt = i
                break
        if nxt is None:
            for i in range(self.idx + 1, len(self.items)):
                if (not self.items[i].get("is_presale")
                        and self.items[i]["decision"] is None):
                    nxt = i
                    break
        if nxt is not None:
            self.idx = nxt
            self._sync_list_selection()
            self._show_current()
        else:
            self._show_current()

    # ---------------- 统计 ----------------
    def _refresh_stats(self):
        c = summarize_items(self.items)
        for key, lab in self.stat.items():
            lab.set_value(c.get(key, 0))
        total = len(self.items)
        done = total - len(unresolved_items(self.items))
        self.lbl_status.setText(
            f"已处理 {done}/{total}  |  待处理 {total-done}  | 库存表: {self.stock_meta or '未加载'} | 预售: {self.presale_meta or '未加载'}")

    # ---------------- 完成匹配 ----------------
    def finish_writeback(self):
        if not self.items:
            QMessageBox.information(self, "提示", "还没有复核数据")
            return
        if not self._in_review:
            return
        unresolved = unresolved_items(self.items)
        presale_count = sum(1 for it in self.items if it.get("is_presale"))
        msg = ""
        if unresolved:
            msg = (f"⚠ 还有 {len(unresolved)} 行未处理（建议/待手选），"
                   f"完成匹配后将保持原值（不修改库存）。\n预售单 {presale_count} 行；勾选关闭预售的订单会把出货天数改为1。\n是否继续？")
        else:
            msg = (f"确认完成 {len(self.items)} 行库存匹配并更新销售资料？\n"
                   f"预售单 {presale_count} 行；勾选关闭预售的订单会把出货天数改为1。\n完成前会自动备份原文件。")
        ans = QMessageBox.question(self, "确认完成匹配", msg,
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ans != QMessageBox.Yes:
            return

        # 检查文件是否被占用
        try:
            f = open(self.sales_path, "a")
            f.close()
        except PermissionError:
            QMessageBox.critical(self, "无法完成匹配", "销售资料正在被 Excel 打开，请先关闭后重试。")
            return
        try:
            f = open(self.presale_path, "a")
            f.close()
        except PermissionError:
            QMessageBox.critical(self, "无法完成匹配", "出货天数资料正在被 Excel 打开，请先关闭后重试。")
            return

        # 备份
        out_dir = os.path.join(_app_dir(), "backup")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = os.path.join(out_dir, f"销售资料-备份-{ts}.xlsx")
        shutil.copy2(self.sales_path, bak)
        presale_bak = os.path.join(out_dir, f"出货天数资料-备份-{ts}.xlsx")
        if os.path.abspath(self.presale_path) != os.path.abspath(self.sales_path):
            shutil.copy2(self.presale_path, presale_bak)
        else:
            presale_bak = bak

        # 计算每行最终值。未开启预售调库时，预售行保持原库存。
        sheet_name = self.items[0].get("sales_sheet", self.sales_sheet) if self.items else self.sales_sheet
        updates = {}
        presale_updates = {}
        for it in self.items:
            should_write, val, action = final_write(it)
            it["_final"] = val
            it["_final_action"] = action
            if should_write:
                updates[it["row"]] = val
            if it.get("is_presale"):
                it["_final_presale_days"] = 1 if it.get("close_presale") else it.get("presale_days")
                if it.get("close_presale"):
                    for source_row in it.get("presale_source_rows", []):
                        presale_updates[int(source_row)] = 1
        try:
            written = write_sales_inventory_values(self.sales_path, sheet_name, updates)
            presale_written = 0
            if presale_updates:
                first_presale = next((it for it in self.items if it.get("is_presale") and it.get("presale_source_rows")), None)
                if first_presale is None:
                    raise ValueError("找不到预售资料源行，无法写回出货天数")
                presale_written = write_presale_days_values(
                    self.presale_path,
                    first_presale.get("presale_source_sheet") or self.presale_meta,
                    first_presale.get("presale_days_col") or 9,
                    presale_updates,
                )
        except Exception as exc:
            QMessageBox.critical(self, "无法完成匹配", f"销售资料写入失败：{exc}")
            return

        # 报告
        report = self._export_report(bak, presale_bak, presale_written)
        clear_state()
        self._in_review = False
        self._set_controls_enabled(False)
        self.lbl_status.setText(f"匹配完成：已更新 {written} 行")
        box = QMessageBox(self)
        box.setWindowTitle("完成匹配")
        box.setText(
            f"完成匹配\n已更新库存 {written} 行（{len(self.items)-written} 行保持原值）\n"
            f"关闭预售写回 {presale_written} 行\n\n销售备份: {bak}\n"
            f"预售资料备份: {presale_bak}\n报告: {report}")
        btn_open = box.addButton("打开报告", QMessageBox.AcceptRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is btn_open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(report))

    def _export_report(self, bak, presale_bak="", presale_written=0) -> str:
        rep = []
        for it in self.items:
            rep.append({
                "Excel行号": it["row"],
                "商品ID": it["cid"],
                "商品名称": it["name"][:80],
                "规格编号": it.get("spec", ""),
                "是否预售单": "是" if it.get("is_presale") else "否",
                "出货天数": it.get("presale_days") if it.get("is_presale") else "",
                "商品货号(F列)": it["f"],
                "主商品货号(E列)": it["e"],
                "自动状态": it["auto_status"],
                "自动匹配SKU": it.get("auto_sku", ""),
                "可用库存": it["auto_av"] if it["auto_av"] is not None else "",
                "复核决定": it["decision"] or "未处理",
                "最终动作": it.get("_final_action", "未处理"),
                "最终写入库存": it.get("_final", it["i_old"]),
                "原卖家库存": it["i_old"],
                "历史记忆命中": "是" if it.get("remembered_mapping") else "否",
                "复核匹配SKU": it.get("matched_sku", ""),
                "组合表命中": "是" if it.get("combo_hit") else "否",
                "组合系统SKU": " + ".join(it.get("combo_system_skus", [])),
                "组合组件": "; ".join(
                    f"{row.get('system_sku_raw', row.get('system_sku', ''))}"
                    f" x{row.get('qty', 1)} -> 库存{row.get('available', '')}"
                    for row in it.get("combo_components", [])
                ),
                "低库存自动调零": "是" if it.get("low_stock_zero") else "否",
                "预售加库存": it.get("presale_bonus", 0) or "",
                "关闭预售": "是" if it.get("close_presale") else "否",
                "最终出货天数": it.get("_final_presale_days", it.get("presale_days", "")) if it.get("is_presale") else "",
                "匹配规则说明": it["auto_desc"],
                "复核说明": it.get("user_desc", ""),
            })
        out_dir = os.path.join(_app_dir(), "reports")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        report = os.path.join(out_dir, f"调库匹配明细报告-{ts}.csv")
        pd.DataFrame(rep).to_csv(report, index=False, encoding="utf-8-sig")
        self._last_report = report
        return report

    def open_last_report(self):
        if getattr(self, "_last_report", None) and os.path.exists(self._last_report):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_report))
        else:
            QMessageBox.information(self, "提示", "还没有生成报告")

    def cancel_review(self):
        if not self.items:
            return
        ans = QMessageBox.question(self, "取消复核",
                                   "取消本次复核？已有操作将保留在状态文件里，下次可恢复。",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans == QMessageBox.Yes:
            self.items = []
            self.filtered = []
            self.idx = -1
            self._in_review = False
            self.listw.clear()
            self.lbl_info.setText("已取消，可重新开始匹配")
            self._set_controls_enabled(False)
            self._refresh_stats()

    # ---------------- 状态恢复 ----------------
    def _load_state_into_ui(self, st):
        self.sales_path = st["sales_path"]
        self.stock_path = st["stock_path"]
        self.presale_path = st["presale_path"]
        self.combo_path = st.get("combo_path", "")
        self.lbl_sales.setText(f"销售资料: {os.path.basename(self.sales_path)}")
        self.lbl_stock.setText(f"库存表: {os.path.basename(self.stock_path)}")
        self.lbl_presale.setText(f"出货天数: {os.path.basename(self.presale_path)}")
        self.lbl_combo.setText(
            f"组合 SKU 表: {os.path.basename(self.combo_path)}"
            if self.combo_path else "组合 SKU 表: 未选择")
        self.lbl_combo.setToolTip(self.combo_path)
        self.items = migrate_items(st["items"])
        self.combo_meta = "已恢复"
        if self.items:
            self.sales_sheet = self.items[0].get("sales_sheet", "Sheet1")
        self._in_review = True
        self.chk_include_presale.blockSignals(True)
        self.chk_include_presale.setChecked(
            any(it.get("is_presale") and it.get("presale_enabled") for it in self.items)
        )
        self.chk_include_presale.blockSignals(False)
        saved_presale_bonus = next(
            (it.get("presale_bonus_enabled") for it in self.items
             if "presale_bonus_enabled" in it), True)
        saved_low_stock_zero = next(
            (it.get("low_stock_zero_enabled") for it in self.items
             if "low_stock_zero_enabled" in it), True)
        self.chk_presale_bonus.setChecked(bool(saved_presale_bonus))
        self.chk_low_stock_zero.setChecked(bool(saved_low_stock_zero))
        self._apply_filter(reset=True)
        self._set_controls_enabled(True)
        n = self._first_unresolved()
        if n is not None:
            self.idx = n
            self._sync_list_selection()
            self._show_current()
        self._refresh_stats()
        self.lbl_status.setText(f"已恢复上次进度（{len(self.items)} 行）")

    # ---------------- 关闭 ----------------
    def closeEvent(self, ev):
        try:
            g = self.geometry()
            self.settings.set_window(g.width(), g.height(), g.x(), g.y())
        except Exception:
            pass
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("调库匹配")
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow, QWidget { background:#F7F2EA; color:#2D2926; font-size:13px; }
        QFrame#sourcePanel { background:#FFFDF9; border:1px solid #E4DED5; border-radius:7px; }
        QToolBar { background:#FFFDF9; border:none; border-bottom:1px solid #E4DED5; padding:8px 12px; spacing:10px; }
        QMenuBar { background:#FFFDF9; color:#2D2926; border-bottom:1px solid #E4DED5; }
        QMenuBar::item:selected, QMenu::item:selected { background:#FFF1EC; color:#2D2926; }
        QMenu { background:#FFFDF9; border:1px solid #E4DED5; }
        QStatusBar { background:#FFFDF9; color:#7D746C; border-top:1px solid #E4DED5; }
        QListWidget { background:#FFFDF9; border:1px solid #E4DED5; border-radius:8px; padding:4px; }
        QListWidget::item { padding:8px 7px; border-bottom:1px solid #F0EBE4; }
        QListWidget::item:selected { background:#FFF1EC; color:#2D2926; border-left:3px solid #C96D5C; }
        QLineEdit, QComboBox { background:#FFFDF9; border:1px solid #DDD4CA; border-radius:7px; padding:7px 9px; color:#2D2926; }
        QLineEdit:focus, QComboBox:focus { border:1px solid #C96D5C; }
        QPushButton { background:#FFFDF9; border:1px solid #D9CFC5; border-radius:7px; padding:7px 12px; color:#4B4039; }
        QPushButton:hover { background:#FFF1EC; border-color:#C96D5C; }
        QPushButton:disabled { color:#B5AAA0; background:#F0EBE4; }
        QPushButton#primaryAction, QPushButton#finishAction { background:#C96D5C; border:1px solid #C96D5C; color:white; font-weight:700; }
        QPushButton#primaryAction:hover, QPushButton#finishAction:hover { background:#B85D4F; }
        QScrollArea { background:#F7F2EA; border:1px solid #E4DED5; border-radius:8px; }
        QLabel { color:#2D2926; }
        QSplitter::handle { background:#E4DED5; width:2px; }
        QProgressBar { background:#EEE8E0; border:0; border-radius:5px; text-align:center; color:#2D2926; }
        QProgressBar::chunk { background:#C96D5C; border-radius:5px; }
    """)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
