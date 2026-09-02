# -*- coding: utf-8 -*-
"""test_core.py —— 无头测试 GUI 核心逻辑（loader/candidates/自动匹配流程）"""
import sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"C:\Users\Administrator\Desktop\调库\调库匹配")

from match_stock import Matcher
from loader import load_stock_index_robust, load_sales_rows_robust
from candidates import build_candidates, build_pool, build_run_index

WORK_DIR = Path(r"C:\Users\Administrator\Desktop\调库")
SALES = str(WORK_DIR / "Shopee-PH09-销售资料.xlsx")
STOCK = str(max(WORK_DIR.glob("导出当前条件所有库存记录*.xls"),
                key=lambda path: path.stat().st_mtime))

t0 = time.time()
exact, norm, meta = load_stock_index_robust(STOCK)
print(f"[1] 库存表: sheet={meta['sheet']}, SKU={meta['rows']}个, 耗时{time.time()-t0:.1f}s")

t0 = time.time()
rows = load_sales_rows_robust(SALES)
print(f"[2] 销售资料: {len(rows)} 行, 耗时{time.time()-t0:.1f}s, 首行: {rows[0]}")

matcher = Matcher(exact, norm)
pool = build_pool(exact)
run_index = build_run_index(exact)
print(f"[3] 候选池 {len(pool)} 条, 数字索引 {len(run_index)} 组")

t0 = time.time()
stat = Counter()
items = []
for i, rec in enumerate(rows):
    f, e = rec["f"], rec["e"]
    st, sku, av, desc = matcher.match_one(f, tag="F")
    if st not in ("OK", "部分匹配") and e and e.lower() != "nan":
        st2, sku2, av2, desc2 = matcher.match_one(e, tag="E")
        if st2 == "OK":
            st, sku, av, desc = "OK", sku2, av2, f"E列兜底: {desc2}"
        elif st2 == "部分匹配":
            st, sku, av, desc = "部分匹配", sku2, av2, f"E列兜底: {desc2}"
    if st == "OK":
        auto_status = "已确认"
    elif st == "部分匹配":
        auto_status = "建议"
    else:
        auto_status = "待手选"
    cands = build_candidates(f, e, exact, norm, matcher, pool, run_index, top_n=6)
    stat[auto_status] += 1
    items.append({"f": f, "e": e, "status": auto_status, "cands": cands, "desc": desc})
print(f"[4] 自动匹配完成 耗时{time.time()-t0:.1f}s")
print("    状态分布:", dict(stat))

# 候选质量抽查
print("\n[5] 候选抽查:")
for it in items:
    if it["status"] == "待手选":
        print(f"  待手选: {it['f']!r}")
        for c in it["cands"][:3]:
            print(f"     候选: {c[0]!r} 库存={c[1]} score={c[2]} tag={c[3]}")
        break
for it in items:
    if it["status"] == "建议":
        print(f"  建议: {it['f']!r} -> {it['cands'][:2]}")
        break
for it in items:
    if it["status"] == "已确认" and it["cands"]:
        print(f"  已确认: {it['f']!r} -> 自动={it['desc'][:40]} | 候选数={len(it['cands'])}")
        break

# 空候选数量
no_cand = sum(1 for it in items if not it["cands"])
print(f"\n[6] 无候选行数: {no_cand}")
