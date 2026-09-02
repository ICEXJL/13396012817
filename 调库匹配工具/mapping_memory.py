# -*- coding: utf-8 -*-
"""历史人工 SKU 映射的持久化与当前库存解析。"""

import json
import os
import re
import sys
import unicodedata
from datetime import datetime

from match_stock import clean_full


MAPPING_NAME = "sku_mapping_memory.json"


def _mapping_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, MAPPING_NAME)


def normalize_mapping_key(value) -> str:
    """用销售资料 F 列货号生成稳定的记忆键。"""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"\s+", " ", text)


def _records_to_mapping(records) -> dict:
    result = {}
    if isinstance(records, dict):
        records = [dict(value, sales_key=key) if isinstance(value, dict) else {}
                   for key, value in records.items()]
    if not isinstance(records, list):
        return result
    for record in records:
        if not isinstance(record, dict):
            continue
        sales_f = str(record.get("sales_f", "")).strip()
        stock_sku = str(record.get("stock_sku", "")).strip()
        key = normalize_mapping_key(record.get("sales_key") or sales_f)
        if not key or not stock_sku:
            continue
        result[key] = {
            "sales_f": sales_f or key,
            "stock_sku": stock_sku,
            "updated_at": str(record.get("updated_at", "")),
        }
    return result


def load_mapping_memory(path=None) -> dict:
    path = os.fspath(path or _mapping_path())
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return _records_to_mapping(payload.get("mappings", []) if isinstance(payload, dict) else payload)
    except (OSError, ValueError, TypeError):
        return {}


def save_mapping_memory(mappings: dict, path=None):
    path = os.fspath(path or _mapping_path())
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    records = []
    for key, record in sorted((mappings or {}).items()):
        if not isinstance(record, dict):
            continue
        stock_sku = str(record.get("stock_sku", "")).strip()
        if not key or not stock_sku:
            continue
        records.append({
            "sales_key": key,
            "sales_f": str(record.get("sales_f", key)).strip() or key,
            "stock_sku": stock_sku,
            "updated_at": str(record.get("updated_at", "")),
        })
    payload = {"version": 1, "mappings": records}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        try:
            os.remove(tmp)
        except OSError:
            pass


def remember_mapping(mappings: dict, sales_f, stock_sku, path=None) -> dict:
    key = normalize_mapping_key(sales_f)
    stock_sku = str(stock_sku or "").strip()
    if not key or not stock_sku:
        raise ValueError("销售货号和库存 SKU 不能为空")
    mappings[key] = {
        "sales_f": str(sales_f).strip(),
        "stock_sku": stock_sku,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_mapping_memory(mappings, path)
    return mappings[key]


def resolve_remembered_mapping(sales_f, mappings, exact, norm):
    """在当前库存索引中解析历史 SKU，返回 (当前原始SKU, 当前可用库存)。"""
    key = normalize_mapping_key(sales_f)
    record = (mappings or {}).get(key)
    if not isinstance(record, dict):
        return None
    stock_sku = str(record.get("stock_sku", "")).strip()
    if not stock_sku:
        return None
    direct = (exact or {}).get(stock_sku.lower())
    if direct is not None:
        return direct
    candidates = (norm or {}).get(clean_full(stock_sku), [])
    return candidates[0] if len(candidates) == 1 else None
