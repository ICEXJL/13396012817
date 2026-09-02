# -*- coding: utf-8 -*-
"""EXE 构建配置回归测试。"""

from pathlib import Path


BUILD_SCRIPT = Path(__file__).with_name("build_exe.ps1")


def test_build_includes_windows_icu_dependencies_for_pyside6():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "--noupx" in script
    assert "diaoku_match" in script
    assert "displayExeName" in script
    for dll_name in ("icu.dll", "icuin.dll", "icuuc.dll"):
        assert f"System32\\{dll_name};." in script
