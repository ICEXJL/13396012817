# -*- coding: utf-8 -*-
"""review_state.py —— 复核会话状态读写（中断恢复用）"""
import json
import os
from datetime import datetime

from review_logic import migrate_decision

STATE_NAME = "review_state.json"


def _state_path() -> str:
    if getattr(__import__("sys"), "frozen", False):
        base = os.path.dirname(__import__("sys").executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, STATE_NAME)


def save_state(sales_path: str, stock_path: str, presale_path: str, items: list,
               combo_path: str = ""):
    """保存复核状态。items 为 dict 列表，必须 JSON 可序列化。"""
    payload = {
        "version": 4,
        "sales_path": sales_path,
        "stock_path": stock_path,
        "presale_path": presale_path,
        "combo_path": combo_path or "",
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }
    path = _state_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    try:
        os.replace(tmp, path)          # 原子替换，防写一半崩溃
    except OSError:
        # 某些环境(杀软/沙箱)不允许替换已有文件，回退直接覆盖
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.remove(tmp)
        except Exception:
            pass


def load_state():
    """返回 (payload_dict | None)"""
    path = _state_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_state():
    """写回成功后删除状态文件"""
    path = _state_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def migrate_items(items: list) -> list:
    """兼容旧版状态文件中的确认匹配/跳过动作。"""
    if not isinstance(items, list):
        return items
    return [migrate_decision(item) for item in items if isinstance(item, dict)]


def is_valid_state(state, sales_path: str, presale_path: str,
                   combo_path: str = "") -> bool:
    """校验状态是否可用于当前销售与出货天数资料（路径一致 + 有items）。"""
    if not state or not isinstance(state, dict):
        return False
    if state.get("sales_path") != sales_path:
        return False
    if state.get("presale_path") != presale_path:
        return False
    if state.get("combo_path", "") != (combo_path or ""):
        return False
    items = state.get("items")
    return isinstance(items, list) and len(items) > 0
