# -*- coding: utf-8 -*-
"""
调库匹配工具：根据 Shopee-PH09-销售资料.xlsx 的 F列(商品货号)，
到 导出当前条件所有库存记录*.xls 的 G列(自定义SKU) 中匹配可用库存，更新 I列(卖家库存)。

匹配策略（按优先级逐级尝试，全部记录明细）：
  L0 原始精准       —— 原样字符串直接命中库存SKU
  L1 规范化精准     —— 小写 + 全角转半角 + 压缩空格 + 去尾点 后精准命中
  L2 去前缀英文     —— 去掉开头的英文字母（如 b51500621-xxx -> 51500621-xxx）
  L3 去1a前缀       —— 去掉开头的 1a 前缀
  L4 去乘数/数量词  —— 去掉 *2/*3pcs/50pcs/1pack/10pairs/(20pcs)/4pcs- 等乘数与数量词
  L5 全量规范化     —— 上述规则组合迭代清理后，规范化索引唯一命中
  L6 前缀兜底       —— 货号是某个库存SKU规范化后的唯一前缀（需含6位以上数字，避免误匹配）
  L7 +号组合拆分    —— 有两个以上有效货号部件时先于 L4 按 + 拆分，各部分分别走 L1~L6；全命中取 min(可用库存)（可配置），部分命中标记
  L8 E列主商品货号兜底 —— F列无法匹配时，用 E列(主商品货号) 走完整管线
  未匹配            —— 全部规则均失败（输出原因）

约定：
  - 库存表自定义SKU 唯一（已验证 22212 个无重复），直接建字典查询
  - 可用库存缺失按 0 处理
  - 含"无备货"标注的货号：去掉标注后匹配，写入匹配到的可用库存，状态标记"无备货标注"供复核
  - 多候选（规范化后命中多个库存SKU）不写入，报告中列出全部候选
  - 写回前自动备份原文件

作者：WorkBuddy | 日期：2026-08-24
"""

import os
import re
import sys
import shutil
import unicodedata
from collections import Counter
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook

# ==================== 配置 ====================
WORK_DIR   = r"C:\Users\Administrator\Desktop\调库"
SALES_XLSX = os.path.join(WORK_DIR, "Shopee-PH09-销售资料.xlsx")                 # 销售资料（目标文件）
STOCK_XLS  = os.path.join(WORK_DIR, "导出当前条件所有库存记录2026年8月24日-244573.xls")  # 库存记录（数据源）
OUT_DIR    = os.path.join(WORK_DIR, "调库匹配")

SALES_SHEET   = "Sheet1"        # 销售资料工作表
STOCK_SHEET   = "ds"            # 库存记录工作表
SALES_COL_F   = "商品货号"        # F列：商品货号
SALES_COL_E   = "主商品货号"      # E列：主商品货号
SALES_COL_I   = "卖家库存"        # I列：待更新库存
STOCK_COL_SKU = "自定义SKU"       # G列：自定义SKU
STOCK_COL_AV  = "可用库存"        # 可用库存列

COMBINE_MODE = "min"            # +号组合拆分后的聚合方式: "min"=取最小(保守) | "sum"=求和
USE_E_FALLBACK = True           # 是否启用 E列主商品货号 兜底
USE_PREFIX_FALLBACK = True      # 是否启用 前缀兜底
MIN_PREFIX_LEN = 6              # 前缀兜底要求清理后货号最小长度
REPORT_NAME = "调库匹配明细报告.csv"

# ==================== 规范化函数 ====================

def norm_basic(s: str) -> str:
    """基础规范化：全角->半角、小写、去首尾空白、压缩空格（不去尾点，尾点由调用方按需处理）"""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()

# 乘数/数量词规则（按顺序迭代应用直到稳定）
QTY_PATTERNS = [
    # 1) 尾部 *N / *Npcs（含全角＊、x、×）
    (r"\s*[＊*x×]\s*\d+\s*(?:pcs|pc|pcs|pack)?\s*$", ""),
    # 2) 尾部 *N
    (r"\s*[＊*x×]\s*\d+\s*$", ""),
    # 3) 括号内数量 (50pcs) / （50pcs）
    (r"\(\s*\d+\s*(?:pcs|pc|pcs|pack|pairs?)\s*\)", ""),
    # 4) 中间 -3pcs Color：去数量词，保留颜色/规格描述以便继续匹配
    (r"-\s*\d+\s*(?:pcs|pc|pack|pairs?|bag|roll|set|sheets|clips|layer|group)\b\s+(?=[a-z])", "-"),
    # 4) 尾部 -50pcs / 5layer / 2group / 1bag/10pcs 等（数量词后到结尾）
    (r"[\s\-]\d+\s*(?:pcs|pc|pcs|pack|pairs?|bag|roll|set|sheets|clips|layer|group)\b.*$", ""),
    # 5) 空格 + 数量词（尾部）
    (r"\s+\d+\s*(?:pcs|pc|pcs|pack|pairs?|bag|roll|set|sheets|clips|layer|group)\b.*$", ""),
    # 6) 前置 4pcs- / 100pcs  形式
    (r"^\d+\s*(?:pcs|pc|pcs|pack|pairs?|set)\s*[-]?\s*", ""),
    # 7) 前置 3*No Clips / 10*Brushes（星号后跟字母才删，避免误伤尺寸 30*60cm）
    (r"^\d+\s*[*x×]\s*(?=[a-z])", ""),
    # 8) 中间 -3*No Clips（星号后跟字母）
    (r"[\s\-]\d+\s*[*x×]\s*(?=[a-z])", ""),
    # 9) 前置 1-28600055（1~2位数字+横线）
    (r"^\d{1,2}[-]", ""),
    # 10) 组合词 zuhe
    (r"\bzuhe\b", ""),
    # 11) 无备货 标注
    (r"\b无备货\b", ""),
]

def strip_qty(s: str) -> str:
    """迭代去除乘数/数量词，直到字符串稳定"""
    prev = None
    while prev != s:
        prev = s
        for pat, rep in QTY_PATTERNS:
            s = re.sub(pat, rep, s, flags=re.IGNORECASE)
    return s.strip()

def strip_prefix_en(s: str) -> str:
    """去掉前缀英文字母（仅当字母后紧跟数字或空格+数字，如 b51500621 -> 51500621）"""
    return re.sub(r"^[a-z]+(?=\s*\d)", "", s)

def strip_1a(s: str) -> str:
    """去掉 1a 前缀"""
    return re.sub(r"^1a(?=[\s\-])", "", s)

def clean_full(s: str) -> str:
    """全量清理：基础规范化 + 去前缀英文 + 去1a + 去乘数，再基础规范化并去掉尾点"""
    s = norm_basic(s)
    s = strip_prefix_en(s)
    s = strip_1a(s)
    s = strip_qty(s)
    s = norm_basic(s)
    return s.rstrip(".")


# ==================== 数据读取 ====================

def load_stock_index(xls_path: str):
    """读取库存表，构建: 精确字典(sku_lower -> (原始SKU, 可用库存)) + 规范化索引(norm_key -> [(原始SKU, 可用库存)])"""
    df = pd.read_excel(xls_path, sheet_name=STOCK_SHEET, header=0)
    exact = {}      # 规范化后精确匹配索引
    norm = {}       # 全量清理后索引（多候选）
    raw_count = 0
    for sku, av in zip(df[STOCK_COL_SKU].tolist(), pd.to_numeric(df[STOCK_COL_AV], errors="coerce").tolist()):
        s = str(sku).strip() if sku is not None else ""
        if not s or s.lower() == "nan":
            continue
        raw_count += 1
        av = 0 if pd.isna(av) else int(av) if float(av).is_integer() else float(av)
        exact.setdefault(s.lower(), (s, av))
        nk = clean_full(s)
        if nk:                                   # 空key会污染索引（bug修复点）
            norm.setdefault(nk, []).append((s, av))
    print(f"[库存] 读取 {raw_count} 条自定义SKU（去重后 {len(exact)} 个）")
    return exact, norm


def load_sales_rows(xlsx_path: str):
    """读取销售资料，返回数据行列表 [(行号, F货号, E主货号, I原库存, 商品ID, 商品名称)]（openpyxl 保证行号与源文件一致）"""
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[SALES_SHEET]
    rows = []
    for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_col=10), start=1):
        if r_idx <= 3:           # 跳过表头/必填说明/空行
            continue
        cid  = row[0].value      # A 商品ID
        name = row[1].value      # B 商品名称
        e    = row[4].value      # E 主商品货号
        f    = row[5].value      # F 商品货号
        i    = row[8].value      # I 卖家库存
        if cid is None or str(cid).strip() in ("", "nan"):
            continue
        rows.append({
            "row": r_idx,
            "cid": str(cid).strip(),
            "name": str(name).strip() if name is not None else "",
            "f": str(f).strip() if f is not None else "",
            "e": str(e).strip() if e is not None else "",
            "i_old": i,
        })
    wb.close()
    print(f"[销售] 读取 {len(rows)} 条数据行")
    return rows


# ==================== 匹配管线 ====================

class Matcher:
    def __init__(self, exact, norm):
        self.exact = exact
        self.norm = norm

    def _lookup(self, k):
        """先查精确字典（原始小写，兼容尾点两种形态）；否则查规范化索引（要求唯一）"""
        for cand in (k, k.rstrip(".")):
            if cand in self.exact:
                return self.exact[cand], "exact"
        for cand in (k, k.rstrip(".")):
            cands = self.norm.get(cand, [])
            if len(cands) == 1:
                return cands[0], "norm"
            if len(cands) > 1:
                return None, cands
        return None, []

    def _resolve_multi(self, cands, h_orig):
        """
        多候选择优：按 候选原始SKU 与 原货号 的词元重叠度选最优。
        仅当最优分严格大于次优分才采用，否则保持多候选（不写入）。
        """
        def tokens(s):
            toks = set(re.findall(r"[a-z0-9]+", s.lower()))
            toks.discard("pcs"); toks.discard("pc"); toks.discard("1")
            return toks

        orig = tokens(h_orig)
        scored = []
        for s, av in cands:
            ov = len(tokens(s) & orig)
            scored.append((ov, s, av))
        scored.sort(key=lambda x: (-x[0], x[1]))
        if len(scored) >= 2 and scored[0][0] > scored[1][0]:
            return scored[0]
        return None

    def _lookup_unique_prefix(self, key):
        """仅在包含主 SKU 数字且唯一时，用清理后的前缀匹配库存 SKU。"""
        if not key or len(key) < MIN_PREFIX_LEN or not re.search(r"\d{6,}", key):
            return None
        matches = set()
        for norm_key, entries in self.norm.items():
            if norm_key != key and norm_key.startswith(key) and len(norm_key) > len(key):
                matches.update(entries)
        if len(matches) == 1:
            return next(iter(matches))
        return None

    def match_one(self, h: str, tag: str = "F"):
        """
        对单个货号执行完整管线。
        返回 (状态, 匹配原始SKU, 可用库存, 说明)
        状态: 匹配成功->"OK" | 多候选->"多候选" | 未匹配->"FAIL"
        """
        hl = norm_basic(h)
        if not hl or hl == "nan":
            return "FAIL", None, None, "货号为空"

        # L1 规范化精准
        r, extra = self._lookup(hl)
        if r:
            return "OK", r[0], r[1], f"{tag}L1规范化精准命中"

        # L2 去前缀英文
        h2 = norm_basic(strip_prefix_en(hl))
        if h2 and h2 != hl:
            r, extra = self._lookup(h2)
            if r:
                return "OK", r[0], r[1], f"{tag}L2去前缀英文: {hl!r} -> {h2!r} -> 库存SKU {r[0]!r}"

        # L3 去1a前缀
        h3 = norm_basic(strip_1a(hl))
        if h3 and h3 != hl:
            r, extra = self._lookup(h3)
            if r:
                return "OK", r[0], r[1], f"{tag}L3去1a前缀: {hl!r} -> {h3!r} -> 库存SKU {r[0]!r}"

        # 真实组合 SKU 先拆分，避免 L4 删除数量词时截掉 + 后的部件。
        if "+" in hl and self._has_multiple_sku_parts(hl):
            r_split = self._try_split(hl, tag)
            if r_split:
                return r_split

        # L4 去乘数/数量词
        h4 = norm_basic(strip_qty(hl))
        if h4 and h4 != hl:
            r, extra = self._lookup(h4)
            if r:
                return "OK", r[0], r[1], f"{tag}L4去乘数/数量词: {hl!r} -> {h4!r} -> 库存SKU {r[0]!r}"

        # /roll-3PCS、/10PCS 等包装后缀：仅对含主 SKU 数字的货号尝试斜杠前部分。
        # 先查主 SKU 本身；只有斜杠后是纯数量包装时，才补查 /1PCS 别名。
        if "/" in h4:
            slash_base = h4.split("/", 1)[0].rstrip()
            if slash_base and slash_base != h4 and re.search(r"\d{6,}", slash_base):
                r, extra = self._lookup(slash_base)
                if r:
                    return "OK", r[0], r[1], f"{tag}L4斜杠包装后缀: {h4!r} -> {slash_base!r} -> 库存SKU {r[0]!r}"
                if re.fullmatch(r"/\s*\d+\s*(?:pcs|pc|pack|pairs?)\s*", h4[len(slash_base):]):
                    one_piece = f"{slash_base}/1pcs"
                    r, extra = self._lookup(one_piece)
                    if r:
                        return "OK", r[0], r[1], f"{tag}L4斜杠数量包装别名: {h4!r} -> {one_piece!r} -> 库存SKU {r[0]!r}"

        # L5 全量规范化
        h5 = clean_full(hl)
        if h5 and h5 != hl:
            cands = self.norm.get(h5, [])
            if len(cands) == 1:
                s, av = cands[0]
                return "OK", s, av, f"{tag}L5全量规范化: {hl!r} -> {h5!r} -> 库存SKU {s!r}"
            if len(cands) > 1:
                best = self._resolve_multi(cands, h)
                if best:
                    s, av = best[1], best[2]
                    return "OK", s, av, f"{tag}L5全量规范化多候选择优: {h5!r} 候选{len(cands)}个，按词元相似度选中 {s!r}（其余: " + " | ".join(f"{c[0]}(可用{c[1]})" for c in cands if c[0] != s) + "）"
                # 多候选且无法区分：若含+号，先尝试组合拆分
                if "+" in hl:
                    r_split = self._try_split(hl, tag)
                    if r_split:
                        return r_split
                return "多候选", None, None, f"{tag}L5全量规范化后 {h5!r} 命中 {len(cands)} 个候选且无法区分: " + " | ".join(f"{c[0]}(可用{c[1]})" for c in cands[:5])

        # L6 前缀兜底（需唯一 + 货号含6位以上数字序列，防误匹配）
        if USE_PREFIX_FALLBACK:
            for prefix_key in dict.fromkeys((hl, h4, h5)):
                r = self._lookup_unique_prefix(prefix_key)
                if r:
                    s, av = r
                    return "OK", s, av, f"{tag}L6前缀兜底: 清理后 {prefix_key!r} 是库存SKU {s!r} 的唯一前缀"

        # L7 +号组合拆分
        if "+" in hl:
            r_split = self._try_split(hl, tag)
            if r_split:
                return r_split

        return "FAIL", None, None, f"{tag}各级规则均未命中（规范化后 {hl!r}）"

    @staticmethod
    def _has_multiple_sku_parts(hl: str) -> bool:
        """仅识别至少两个有效货号的 + 组合，避免规格碎片抢占常规匹配。"""
        parts = [p.strip() for p in hl.split("+") if p.strip()]
        return sum(bool(re.search(r"\d{6,}", p)) for p in parts) >= 2

    def _try_split(self, hl: str, tag: str):
        """
        +号组合拆分：仅当部分含6位以上数字（像真实货号）才参与匹配，
        避免 'blue1'、'l'、'nozzle' 等规格碎片被误匹配；
        存在被忽略的规格碎片时标记为部分匹配，提示人工核对。
        """
        parts = [p.strip() for p in hl.split("+") if p.strip()]
        meaningful = [p for p in parts if re.search(r"\d{6,}", p)]
        fragments = [p for p in parts if p not in meaningful]
        if not meaningful:
            return None
        ok_parts, miss_parts, avs, raw_list = [], [], [], []
        for p in meaningful:
            st, s, av, desc = self.match_one(p, tag=f"{tag}拆分")
            if st == "OK":
                ok_parts.append(p); avs.append(av); raw_list.append(s)
            else:
                miss_parts.append((p, desc))
        if ok_parts and not miss_parts:
            agg = min(avs) if COMBINE_MODE == "min" else sum(avs)
            if fragments:
                return "部分匹配", " + ".join(raw_list), agg, f"{tag}L7+号拆分匹配: 命中{ok_parts}({raw_list})，规格碎片 {fragments} 未参与匹配(无货号数字)，聚合={COMBINE_MODE}({agg})"
            return "OK", " + ".join(raw_list), agg, f"{tag}L7+号拆分全命中: {parts} -> {raw_list}，聚合={COMBINE_MODE}({agg})"
        if ok_parts:
            agg = min(avs) if COMBINE_MODE == "min" else sum(avs)
            return "部分匹配", " + ".join(raw_list), agg, f"{tag}L7+号拆分部分命中: 命中{ok_parts}({raw_list})，未命中{miss_parts}，聚合={COMBINE_MODE}({agg})"
        return None


# ==================== 主流程 ====================

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 90)
    print("调库匹配工具 v1.0 | 销售资料 I列库存更新")
    print("=" * 90)

    # 1) 读取库存索引
    exact, norm = load_stock_index(STOCK_XLS)

    # 2) 读取销售数据
    rows = load_sales_rows(SALES_XLSX)

    # 3) 逐行匹配
    matcher = Matcher(exact, norm)
    detail = []
    stat = Counter()
    for rec in rows:
        f, e = rec["f"], rec["e"]

        # F列主线
        st, sku, av, desc = matcher.match_one(f, tag="F")

        # 含"无备货"标注复核标记
        no_stock_tag = "无备货" in f

        if st != "OK" and st != "部分匹配" and USE_E_FALLBACK and e and e.lower() != "nan":
            # L8 E列主商品货号兜底
            st2, sku2, av2, desc2 = matcher.match_one(e, tag="E")
            if st2 == "OK":
                st, sku, av, desc = "OK", sku2, av2, f"E列兜底: {desc2}（F列{desc}）"
            elif st2 == "部分匹配":
                st, sku, av, desc = "部分匹配", sku2, av2, f"E列兜底部分匹配: {desc2}（F列{desc}）"
            elif st2 == "多候选":
                st, sku, av, desc = "多候选", None, None, f"E列兜底: {desc2}（F列{desc}）"

        if st == "OK":
            new_i = av
            st_final = "已匹配"
            if no_stock_tag:
                st_final = "已匹配(含无备货标注)"
        elif st == "部分匹配":
            new_i = av
            st_final = "部分匹配-需人工核对"
        else:
            new_i = rec["i_old"]
            st_final = "未匹配" if st == "FAIL" else "多候选-未写入"

        stat[st_final] += 1
        rec.update({
            "st": st_final, "matched_sku": sku or "", "av": av if av is not None else "",
            "new_i": new_i, "desc": desc,
        })
        detail.append(rec)

    # 4) 汇总
    print("\n" + "=" * 90)
    print("匹配结果汇总（共 %d 行）" % len(rows))
    print("=" * 90)
    matched = stat.get("已匹配", 0) + stat.get("已匹配(含无备货标注)", 0) + stat.get("部分匹配-需人工核对", 0)
    for k, v in stat.most_common():
        print(f"  {k}: {v} 行")
    print(f"  -> 合计可写入: {matched} 行 | 未写入: {len(rows) - matched} 行")

    # 5) 写回 I列（先备份）
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak_dir = os.path.join(OUT_DIR, "backup")
    os.makedirs(bak_dir, exist_ok=True)
    bak_path = os.path.join(bak_dir, f"Shopee-PH09-销售资料-备份-{ts}.xlsx")
    shutil.copy2(SALES_XLSX, bak_path)
    print(f"\n[备份] 原文件已备份到: {bak_path}")

    wb = load_workbook(SALES_XLSX)
    ws = wb[SALES_SHEET]
    write_cnt = 0
    for rec in detail:
        if rec["st"] in ("已匹配", "已匹配(含无备货标注)", "部分匹配-需人工核对"):
            ws.cell(row=rec["row"], column=9, value=rec["new_i"])   # I列 = 第9列
            write_cnt += 1
    wb.save(SALES_XLSX)
    print(f"[写入] 已更新 {write_cnt} 行 I列(卖家库存) -> {SALES_XLSX}")

    # 6) 明细报告 CSV（utf-8-sig 便于Excel打开）
    report_path = os.path.join(OUT_DIR, REPORT_NAME)
    rep_rows = []
    for r in detail:
        rep_rows.append({
            "Excel行号": r["row"],
            "商品ID": r["cid"],
            "商品名称": r["name"][:80],
            "商品货号(F列)": r["f"],
            "主商品货号(E列)": r["e"],
            "匹配状态": r["st"],
            "匹配到的库存SKU": r["matched_sku"],
            "可用库存": r["av"],
            "写入卖家库存(I列)": r["new_i"],
            "原卖家库存": r["i_old"],
            "匹配规则说明": r["desc"],
        })
    pd.DataFrame(rep_rows).to_csv(report_path, index=False, encoding="utf-8-sig")
    print(f"[报告] 明细已生成: {report_path}")

    # 7) 未匹配/多候选清单
    fail = [r for r in detail if r["st"] in ("未匹配", "多候选-未写入", "部分匹配-需人工核对")]
    print(f"\n[待人工处理] {len(fail)} 行，详见报告。样本：")
    for r in fail[:15]:
        print(f"  行{r['row']}: 货号={r['f']!r} -> {r['st']} | {r['desc'][:100]}")


if __name__ == "__main__":
    sys.exit(main())
