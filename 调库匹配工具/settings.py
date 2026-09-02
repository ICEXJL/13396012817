# -*- coding: utf-8 -*-
"""settings.py —— settings.ini 读写：记住上次文件路径、窗口位置尺寸"""
import configparser
import os

APP_NAME = "调库匹配"
SETTINGS_NAME = "settings.ini"


def _settings_path() -> str:
    """EXE/脚本所在目录（可移植：随程序走）"""
    if getattr(__import__("sys"), "frozen", False):
        base = os.path.dirname(__import__("sys").executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, SETTINGS_NAME)


class Settings:
    def __init__(self):
        self.path = _settings_path()
        self.cfg = configparser.ConfigParser()
        self.cfg.optionxform = str          # 保留键大小写
        if os.path.exists(self.path):
            try:
                self.cfg.read(self.path, encoding="utf-8")
            except Exception:
                pass

    # ---------- 路径 ----------
    def get_last_sales(self) -> str:
        return self.cfg.get("paths", "last_sales", fallback="")

    def get_last_stock(self) -> str:
        return self.cfg.get("paths", "last_stock", fallback="")

    def get_last_presale(self) -> str:
        return self.cfg.get("paths", "last_presale", fallback="")

    def get_last_combo(self) -> str:
        return self.cfg.get("paths", "last_combo", fallback="")

    def set_paths(self, sales: str, stock: str, presale: str = "", combo: str = ""):
        if not self.cfg.has_section("paths"):
            self.cfg.add_section("paths")
        self.cfg.set("paths", "last_sales", sales or "")
        self.cfg.set("paths", "last_stock", stock or "")
        self.cfg.set("paths", "last_presale", presale or "")
        self.cfg.set("paths", "last_combo", combo or "")
        self.save()

    # ---------- 窗口 ----------
    def get_window(self):
        try:
            return (
                int(self.cfg.get("window", "w")),
                int(self.cfg.get("window", "h")),
                int(self.cfg.get("window", "x")),
                int(self.cfg.get("window", "y")),
            )
        except Exception:
            return (1280, 800, None, None)

    def set_window(self, w, h, x, y):
        if not self.cfg.has_section("window"):
            self.cfg.add_section("window")
        self.cfg.set("window", "w", str(w))
        self.cfg.set("window", "h", str(h))
        if x is not None and y is not None:
            self.cfg.set("window", "x", str(x))
            self.cfg.set("window", "y", str(y))
        self.save()

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                self.cfg.write(f)
        except Exception:
            pass
