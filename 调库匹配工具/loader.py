# -*- coding: utf-8 -*-
"""loader.py —— 稳健的文件读取：自动识别工作表与列名（兼容用户任选文件）"""
import csv
import io
import math
import os
import re
import shutil
import tempfile
import unicodedata
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import pandas as pd
from openpyxl import load_workbook

from match_stock import clean_full, STOCK_COL_SKU, STOCK_COL_AV


_VALID_PANES = {"bottomLeft", "bottomRight", "topLeft", "topRight"}
_ACTIVE_PANE_RE = re.compile(
    rb'(<pane\b[^>]*\bactivePane=["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)


def _make_tolerant_xlsx(source_path):
    """为非法 worksheet pane 值创建临时副本，返回 (读取路径, 临时路径)。"""
    try:
        source = ZipFile(source_path, "r")
    except (BadZipFile, OSError):
        return source_path, None

    entries = []
    changed = False
    with source:
        for entry in source.infolist():
            data = source.read(entry.filename)
            if entry.filename.startswith("xl/worksheets/") and entry.filename.endswith(".xml"):
                def normalize(match):
                    nonlocal changed
                    value = match.group(2).decode("utf-8")
                    if value in _VALID_PANES:
                        return match.group(0)
                    changed = True
                    return match.group(1) + b"topLeft" + match.group(3)

                data = _ACTIVE_PANE_RE.sub(normalize, data)
            entries.append((entry, data))

    if not changed:
        return source_path, None

    handle = tempfile.NamedTemporaryFile(prefix="diao-ku-", suffix=".xlsx", delete=False)
    temp_path = handle.name
    handle.close()
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as target:
            for entry, data in entries:
                target.writestr(entry, data)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    return temp_path, temp_path


def _find_col(cols, *targets, contains=False):
    """在列名列表中找目标列，返回列索引或 None。targets 按优先级。"""
    clean = [str(c).strip() for c in cols]
    for t in targets:
        for i, c in enumerate(clean):
            if c == t or (contains and t in c):
                return i
    return None


def normalize_spec_code(value) -> str:
    """规范化规格编号，兼容 Excel 把纯数字编号读成 123.0 的情况。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return re.sub(r"^(\d+)\.0+$", r"\1", text)


def normalize_stock_identifier(value) -> str:
    """规范化库存表/组合表中的系统 SKU，保留字符串中的前导零。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value).strip()
    if text.lower() in ("", "nan", "none"):
        return ""
    text = re.sub(r"\.0+$", "", text)
    text = unicodedata.normalize("NFKC", text).strip().lower()
    return re.sub(r"\s+", " ", text)


def normalize_combo_key(value) -> str:
    """规范化组合表 B 列组合自定义 SKU。"""
    return normalize_stock_identifier(value)


# ==================== 库存表（.xls/.xlsx 均可） ====================

def load_stock_index_robust(xls_path: str):
    """
    自动定位含"自定义SKU"的工作表，构建:
      exact: 小写SKU -> (原始SKU, 可用库存)    （22212 个唯一）
      norm : clean_full(SKU) -> [(原始SKU, 可用库存), ...]
    可用库存列优先"可用库存"，缺则"当前库存"。
    """
    xl = pd.ExcelFile(xls_path)
    sheet = None
    for sn in xl.sheet_names:
        try:
            df = pd.read_excel(xls_path, sheet_name=sn, header=0, nrows=3)
            cols = [str(c) for c in df.columns]
            if any("自定义SKU" in c for c in cols):
                sheet = sn
                break
        except Exception:
            continue
    if sheet is None:
        sheet = xl.sheet_names[0]
    df = pd.read_excel(xls_path, sheet_name=sheet, header=0)
    cols = [str(c) for c in df.columns]
    sku_col = _find_col(cols, "自定义SKU")
    av_col = _find_col(cols, "可用库存", "当前库存")
    if sku_col is None:
        raise ValueError(f"库存表未找到'自定义SKU'列，实际列: {cols[:12]}")
    if av_col is None:
        av_col = sku_col + 1
        print(f"[loader] 库存表未找到库存列，回退第{av_col+1}列")

    system_col = _find_col(cols, "系统SKU")

    exact = {}
    norm = {}
    system_index = {}
    raw_count = 0
    for sku, av, system_sku in zip(
            df.iloc[:, sku_col].tolist(),
            pd.to_numeric(df.iloc[:, av_col], errors="coerce").tolist(),
            df.iloc[:, system_col].tolist() if system_col is not None
            else [None] * len(df)):
        s = str(sku).strip() if sku is not None else ""
        av = 0 if pd.isna(av) else int(av) if float(av).is_integer() else float(av)
        if s and s.lower() != "nan":
            raw_count += 1
            exact.setdefault(s.lower(), (s, av))
            nk = clean_full(s)
            if nk:
                norm.setdefault(nk, []).append((s, av))

        system_key = normalize_stock_identifier(system_sku)
        if system_key:
            system_index.setdefault(system_key, []).append((
                str(system_sku).strip(), s if s.lower() != "nan" else "", av))
    return exact, norm, {
        "sheet": sheet,
        "rows": raw_count,
        "system_index": system_index,
        "system_col": system_col,
        "system_rows": sum(len(v) for v in system_index.values()),
        "system_unique": len(system_index),
        "system_duplicates": sum(1 for v in system_index.values() if len(v) > 1),
    }


def _read_combo_csv_rows(csv_path: str):
    """读取组合 SKU 导出文件，兼容 UTF-16/UTF-8 及制表符/逗号分隔。"""
    with open(csv_path, "rb") as handle:
        raw = handle.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    elif raw.startswith(b"\xef\xbb\xbf"):
        encodings = ("utf-8-sig", "gb18030")
    else:
        encodings = ("utf-8-sig", "gb18030", "utf-16")
    last_error = None
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    else:
        raise ValueError(f"组合 SKU 表编码无法识别：{last_error}")

    first_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = "\t" if first_line.count("\t") >= first_line.count(",") else ","
    return csv.reader(io.StringIO(text), delimiter=delimiter)


def load_combo_sku_mapping_robust(csv_path: str):
    """读取组合表 B列组合自定义SKU -> C列子系统SKU + SkuNum 索引。"""
    if not csv_path:
        return {}, {
            "rows": 0, "unique_combos": 0, "component_rows": 0,
            "duplicate_combos": 0, "sheet": "",
        }
    reader = _read_combo_csv_rows(csv_path)
    try:
        headers = next(reader)
    except StopIteration:
        raise ValueError("组合 SKU 表为空")

    normalized_headers = [normalize_combo_key(value) for value in headers]

    def find_header(name):
        target = normalize_combo_key(name)
        for index, header in enumerate(normalized_headers):
            if header == target:
                return index
        return None

    combo_col = find_header("组合自定义SKU")
    system_col = find_header("子系统SKU")
    qty_col = find_header("SkuNum")
    if combo_col is None or system_col is None:
        raise ValueError("组合 SKU 表必须包含‘组合自定义SKU’和‘子系统SKU’列")

    raw_rows = 0
    skipped_rows = 0
    mapping = {}
    for source_row, values in enumerate(reader, start=2):
        raw_rows += 1
        if len(values) <= max(combo_col, system_col):
            skipped_rows += 1
            continue
        combo_raw = str(values[combo_col]).strip()
        combo_key = normalize_combo_key(combo_raw)
        system_raw = str(values[system_col]).strip()
        system_key = normalize_stock_identifier(system_raw)
        if not combo_key or not system_key:
            skipped_rows += 1
            continue
        qty = 1.0
        if qty_col is not None and len(values) > qty_col:
            parsed = pd.to_numeric(values[qty_col], errors="coerce")
            if not pd.isna(parsed) and float(parsed) > 0:
                qty = float(parsed)
        if qty.is_integer():
            qty = int(qty)
        mapping.setdefault(combo_key, []).append({
            "system_sku": system_key,
            "system_sku_raw": system_raw,
            "qty": qty,
            "source_row": source_row,
        })

    # 同一组合下同一子系统 SKU 的多条记录合并，避免重复行把结果算错。
    for combo_key, components in list(mapping.items()):
        merged = {}
        for component in components:
            key = component["system_sku"]
            if key not in merged:
                merged[key] = dict(component)
            else:
                merged[key]["qty"] += component["qty"]
        mapping[combo_key] = list(merged.values())

    return mapping, {
        "rows": raw_rows,
        "unique_combos": len(mapping),
        "component_rows": sum(len(v) for v in mapping.values()),
        "duplicate_combos": sum(1 for v in mapping.values() if len(v) > 1),
        "skipped_rows": skipped_rows,
        "sheet": os.path.basename(csv_path),
    }


def resolve_combo_inventory(combo_key: str, combo_mapping: dict,
                            system_index: dict):
    """按组合表组件和库存表系统 SKU 计算组合可用库存。"""
    key = normalize_combo_key(combo_key)
    components = (combo_mapping or {}).get(key)
    if not components:
        return {
            "status": "NOT_FOUND", "combo_key": key, "available": None,
            "system_skus": [], "components": [],
            "reason": "组合表未找到该组合自定义 SKU",
        }

    resolved = []
    missing = []
    ambiguous = []
    for component in components:
        system_sku = component["system_sku"]
        options = (system_index or {}).get(system_sku, [])
        if not options:
            missing.append(system_sku)
            continue
        if len(options) != 1:
            ambiguous.append(system_sku)
            continue
        system_raw, custom_sku, available = options[0]
        qty = component.get("qty", 1) or 1
        capacity = math.floor(float(available) / float(qty))
        resolved.append({
            "system_sku": system_sku,
            "system_sku_raw": system_raw,
            "custom_sku": custom_sku,
            "qty": qty,
            "available": available,
            "capacity": capacity,
            "source_row": component.get("source_row"),
        })

    if missing:
        status = "MISSING_STOCK"
        reason = "仓库表未找到子系统 SKU：" + ", ".join(missing)
    elif ambiguous:
        status = "AMBIGUOUS_STOCK"
        reason = "仓库表中子系统 SKU 重复：" + ", ".join(ambiguous)
    else:
        status = "OK"
        reason = ""

    return {
        "status": status,
        "combo_key": key,
        "available": min((row["capacity"] for row in resolved), default=None)
        if status == "OK" else None,
        "system_skus": [row["system_sku_raw"] for row in resolved]
                         + missing + ambiguous,
        "components": resolved,
        "reason": reason,
    }


# ==================== 销售资料（xlsx） ====================

def load_sales_rows_robust(xlsx_path: str):
    """
    自动定位表头（含"商品货号"）与数据列（商品ID/商品名称/主商品货号/商品货号/卖家库存），
    返回 rows: [{row, cid, name, f, e, i_old}, ...]（row 为 Excel 绝对行号，用于写回）
    """
    safe_path, temp_path = _make_tolerant_xlsx(xlsx_path)
    wb = None
    try:
        wb = load_workbook(safe_path, read_only=True, data_only=True)
        result = []
        for ws in wb.worksheets:
            # 部分平台导出的文件会把 dimension 错写成 A1，需按实际 XML 行重算范围。
            if hasattr(ws, "reset_dimensions"):
                ws.reset_dimensions()
            # 一次性流式读取全部行（read-only 模式不可随机 ws[row] 索引，会崩溃）
            all_rows = list(ws.iter_rows(min_row=1, max_col=12, values_only=True))
            header_row_idx = None
            header_cells = None
            for r_idx, row in enumerate(all_rows[:8], start=1):   # 表头一般在前 8 行
                if any(isinstance(v, str) and "商品货号" in v for v in row):
                    header_row_idx = r_idx
                    header_cells = list(row)
                    break
            if header_row_idx is None:
                continue
            # 列定位：优先精确匹配，其次包含
            idx_cid = _find_col(header_cells, "商品ID")
            idx_name = _find_col(header_cells, "商品名称")
            idx_spec = _find_col(header_cells, "规格编号")
            idx_e = _find_col(header_cells, "主商品货号")
            idx_f = _find_col(header_cells, "商品货号")
            idx_i = _find_col(header_cells, "卖家库存", "库存")
            if idx_f is None:
                continue
            for r_idx, vals in enumerate(all_rows[header_row_idx:], start=header_row_idx):
                cid = vals[idx_cid] if idx_cid is not None else None
                if cid is None or str(cid).strip() in ("", "nan"):
                    continue
                result.append({
                    "row": r_idx + 1,     # Excel 绝对行号（iter_rows 从1开始，enumerate start 与行号对齐）
                    "sheet": ws.title,
                    "cid": str(cid).strip(),
                    "name": str(vals[idx_name]).strip() if idx_name is not None and vals[idx_name] is not None else "",
                    "spec": normalize_spec_code(vals[idx_spec]) if idx_spec is not None else "",
                    "f": str(vals[idx_f]).strip() if vals[idx_f] is not None else "",
                    "e": str(vals[idx_e]).strip() if idx_e is not None and vals[idx_e] is not None else "",
                    "i_old": vals[idx_i] if idx_i is not None else None,
                })
            if result:
                return result
        raise ValueError("销售资料未找到含'商品货号'表头的工作表")
    finally:
        if wb is not None:
            wb.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


# ==================== 出货天数资料（xlsx） ====================

def load_presale_specs_robust(xlsx_path: str):
    """
    自动定位“规格编号”和“出货天数”表头，返回：
      - {规格编号: 出货天数}，仅保留出货天数大于 1 的预售规格
      - 读取元数据（工作表、预售源行数、预售规格数）
    """
    safe_path, temp_path = _make_tolerant_xlsx(xlsx_path)
    wb = None
    try:
        wb = load_workbook(safe_path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            if hasattr(ws, "reset_dimensions"):
                ws.reset_dimensions()
            all_rows = list(ws.iter_rows(min_row=1, max_col=12, values_only=True))
            header_row_idx = None
            header_cells = None
            for r_idx, row in enumerate(all_rows[:8], start=1):
                cells = list(row)
                if (_find_col(cells, "规格编号") is not None
                        and _find_col(cells, "出货天数") is not None):
                    header_row_idx = r_idx
                    header_cells = cells
                    break
            if header_row_idx is None:
                continue

            idx_spec = _find_col(header_cells, "规格编号")
            idx_days = _find_col(header_cells, "出货天数")
            presale_specs = {}
            source_rows = 0
            rows_by_spec = {}
            for excel_row, vals in enumerate(
                    all_rows[header_row_idx:], start=header_row_idx + 1):
                spec = normalize_spec_code(vals[idx_spec])
                days = pd.to_numeric(vals[idx_days], errors="coerce")
                if not spec or pd.isna(days) or days <= 1:
                    continue
                days = int(days) if float(days).is_integer() else float(days)
                source_rows += 1
                presale_specs[spec] = max(presale_specs.get(spec, days), days)
                rows_by_spec.setdefault(spec, []).append(excel_row)
            return presale_specs, {
                "sheet": ws.title,
                "source_rows": source_rows,
                "unique_specs": len(presale_specs),
                "rows_by_spec": rows_by_spec,
                "days_col": idx_days + 1,
            }
        raise ValueError("出货天数资料未找到同时含'规格编号'和'出货天数'表头的工作表")
    finally:
        if wb is not None:
            wb.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def write_sales_inventory_values(xlsx_path: str, sheet_name: str, updates: dict) -> int:
    """写入销售资料 I 列库存，兼容含非法 pane 的平台导出文件。"""
    safe_path, temp_path = _make_tolerant_xlsx(xlsx_path)
    wb = None
    try:
        wb = load_workbook(safe_path)
        ws = wb[sheet_name]
        for row, value in updates.items():
            ws.cell(row=int(row), column=9, value=value)
        wb.save(safe_path)
        wb.close()
        wb = None
        if temp_path:
            shutil.copy2(temp_path, xlsx_path)
        return len(updates)
    finally:
        if wb is not None:
            wb.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def write_presale_days_values(xlsx_path: str, sheet_name: str,
                              days_col: int, updates: dict) -> int:
    """把指定预售源行的出货天数写为确认值，兼容异常 pane 文件。"""
    safe_path, temp_path = _make_tolerant_xlsx(xlsx_path)
    wb = None
    try:
        wb = load_workbook(safe_path)
        ws = wb[sheet_name]
        for row, value in updates.items():
            ws.cell(row=int(row), column=int(days_col), value=value)
        wb.save(safe_path)
        wb.close()
        wb = None
        if temp_path:
            shutil.copy2(temp_path, xlsx_path)
        return len(updates)
    finally:
        if wb is not None:
            wb.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
