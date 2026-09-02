# -*- coding: utf-8 -*-
"""GUI 自定义控件：候选卡片与统计标签。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from datetime import datetime

from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QDialogButtonBox, QMessageBox, QAbstractItemView,
)

from mapping_memory import normalize_mapping_key

COLOR_CONFIRMED = "#668F82"
COLOR_SUGGEST = "#83A8A2"
COLOR_PENDING = "#D39A5D"
COLOR_PRESALE = "#9B7786"
COLOR_SKIPPED = "#8B7B72"
COLOR_KEEP = "#8B7B72"
COLOR_ADOPT = "#C96D5C"
COLOR_ZERO = "#A87663"
COLOR_CUSTOM = "#B68156"
COLOR_AUTO_ZERO = "#C65F5A"
COLOR_PRESALE_BONUS = "#5F87A3"
COLOR_CARD_BG = "#FFFDF9"
COLOR_CARD_SEL = "#FFF1EC"
COLOR_TEXT = "#2D2926"
COLOR_TEXT_DIM = "#7D746C"
COLOR_ACCENT = "#C96D5C"
COLOR_BORDER = "#E4DED5"


class CandidateCard(QFrame):
    """单张候选 SKU 卡片：单击选择，双击直接采用。"""

    clicked = Signal(object)
    double_clicked = Signal(object)

    def __init__(self, sku: str, av, score: float, tag: str = "", parent=None):
        super().__init__(parent)
        self.sku = sku
        self.av = av
        self.score = score
        self.tag = tag
        self.selected = False
        self.setObjectName("candidateCard")
        self.setFixedSize(190, 104)
        self.setCursor(Qt.PointingHandCursor)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(5)

        top = QHBoxLayout()
        self.lbl_sku = QLabel(self.sku)
        self.lbl_sku.setWordWrap(True)
        self.lbl_sku.setStyleSheet(f"color:{COLOR_TEXT}; font-size:12px; font-weight:600;")
        self.lbl_score = QLabel(f"{self.score:.0%}" if self.score <= 1 else "自动")
        self.lbl_score.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_score.setStyleSheet(f"color:{COLOR_ACCENT}; font-size:10px; font-weight:700;")
        top.addWidget(self.lbl_sku, 1)
        top.addWidget(self.lbl_score, 0)
        lay.addLayout(top)

        bot = QHBoxLayout()
        self.lbl_av = QLabel(str(self.av))
        font = QFont()
        font.setPointSize(17)
        font.setBold(True)
        self.lbl_av.setFont(font)
        self.lbl_av.setStyleSheet(f"color:{COLOR_ACCENT};")
        self.lbl_tag = QLabel(self.tag)
        self.lbl_tag.setStyleSheet(f"color:{COLOR_TEXT_DIM}; font-size:10px;")
        bot.addWidget(self.lbl_av, 0)
        bot.addWidget(self.lbl_tag, 0, Qt.AlignBottom)
        bot.addStretch(1)
        lay.addLayout(bot)

    def _apply_style(self):
        if self.selected:
            self.setStyleSheet(
                f"QFrame#candidateCard{{background:{COLOR_CARD_SEL}; border:2px solid {COLOR_ACCENT};"
                "border-radius:8px;}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#candidateCard{{background:{COLOR_CARD_BG}; border:1px solid {COLOR_BORDER};"
                "border-radius:8px;}"
            )
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_selected(self, selected: bool):
        self.selected = selected
        self._apply_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self)
        super().mouseDoubleClickEvent(event)


class StatLabel(QLabel):
    """统计栏中的名称与数字。"""

    def __init__(self, name: str, color: str = COLOR_TEXT):
        super().__init__()
        self.name = name
        self._color = color
        self._value = 0
        self.refresh()

    def refresh(self):
        self.setText(f"{self.name}  <b style='color:{self._color}'>{self._value}</b>")
        self.setTextFormat(Qt.RichText)

    def set_value(self, value):
        self._value = value
        self.refresh()


class MappingEditorDialog(QDialog):
    """运营维护历史销售货号与库存 SKU 映射。"""

    def __init__(self, mappings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理历史映射")
        self.resize(720, 460)
        self._mappings = {}
        self._build_ui()
        self._load_mappings(mappings or {})

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["销售货号（F列）", "对应库存 SKU", "更新时间"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        tools = QHBoxLayout()
        self.btn_add = QPushButton("新增映射")
        self.btn_delete = QPushButton("删除选中")
        self.btn_add.clicked.connect(self._add_row)
        self.btn_delete.clicked.connect(self._delete_row)
        tools.addWidget(self.btn_add)
        tools.addWidget(self.btn_delete)
        tools.addStretch(1)
        layout.addLayout(tools)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self)
        self.buttons.button(QDialogButtonBox.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _load_mappings(self, mappings):
        self.table.setRowCount(0)
        for key, record in sorted(mappings.items()):
            if not isinstance(record, dict):
                continue
            self._append_row(
                record.get("sales_f", key),
                record.get("stock_sku", ""),
                record.get("updated_at", ""),
            )

    def _append_row(self, sales_f="", stock_sku="", updated_at=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(sales_f)))
        self.table.setItem(row, 1, QTableWidgetItem(str(stock_sku)))
        self.table.setItem(row, 2, QTableWidgetItem(str(updated_at)))
        self.table.item(row, 2).setFlags(self.table.item(row, 2).flags() & ~Qt.ItemIsEditable)
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))

    def _add_row(self):
        self._append_row()

    def _delete_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _accept_if_valid(self):
        result = {}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in range(self.table.rowCount()):
            sales_f = self.table.item(row, 0).text().strip()
            stock_sku = self.table.item(row, 1).text().strip()
            if not sales_f and not stock_sku:
                continue
            if not sales_f or not stock_sku:
                QMessageBox.warning(self, "无法保存", f"第 {row + 1} 行的销售货号和库存 SKU 必须同时填写。")
                return
            key = normalize_mapping_key(sales_f)
            if key in result:
                QMessageBox.warning(self, "无法保存", f"销售货号重复：{sales_f}")
                return
            result[key] = {
                "sales_f": sales_f,
                "stock_sku": stock_sku,
                "updated_at": now,
            }
        self._mappings = result
        self.accept()

    def mappings(self):
        return dict(self._mappings)
