# 调库匹配工具

用于根据销售资料、库存表和出货天数资料表匹配库存，并在复核后写回销售资料。

## 使用

直接运行 `dist/调库匹配.exe`，按照 `调库使用说明.txt` 操作。组合 SKU CSV 作为低优先级兜底文件，在主界面需要时选择。

## 源码运行

需要 Python、PySide6、pandas、openpyxl 和 PyInstaller。安装依赖后运行：

```powershell
python match_stock_gui.py
```

构建 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

运行时生成的备份、报告、历史映射和窗口设置保存在本地，不提交到仓库。
