# -*- coding: utf-8 -*-
"""candidates.py —— 为人工复核生成候选SKU列表（打分排序）"""
import re
from collections import defaultdict

from match_stock import norm_basic, clean_full

STOP_TOKENS = {"pcs", "pc", "pack", "set", "1", "pairs", "pair", "bag", "roll"}


def tokens_of(s: str) -> frozenset:
    """把 SKU/货号 拆成词元集合（小写，过滤数量词）"""
    toks = set(re.findall(r"[a-z0-9]+", str(s).lower()))
    toks -= STOP_TOKENS
    return frozenset(toks)


def digit_runs(s: str) -> set:
    """提取字符串中所有 6 位以上数字串（货号基础号）"""
    return set(re.findall(r"\d{6,}", str(s)))


def build_run_index(exact: dict) -> dict:
    """预建 数字串 -> [库存SKU小写key] 索引，加速候选查找"""
    idx = defaultdict(list)
    for k in exact:
        for run in digit_runs(k):
            idx[run].append(k)
    return idx


def build_pool(exact: dict):
    """预建候选池：[(小写key, 原始SKU, 可用库存, 词元, clean_key)] 一次算好复用"""
    pool = []
    for k, (raw, av) in exact.items():
        pool.append((k, raw, av, tokens_of(raw), clean_full(raw)))
    return pool


def build_candidates(f: str, e: str, exact: dict, norm: dict, matcher,
                     pool=None, run_index=None, top_n: int = 6,
                     auto_match=None):
    """
    为单个货号生成候选列表。
    返回 [(原始SKU, 可用库存, score, tag), ...] 按 score 降序，最多 top_n 条。
    auto_match: (st, sku, av, desc) 自动匹配结果，避免重复计算。
    """
    hl = norm_basic(f)
    clean_f = clean_full(f)
    orig_toks = tokens_of(f + " " + (e or ""))
    orig_runs = digit_runs(f) | digit_runs(e or "")

    scored = {}   # 原始SKU -> (av, score, tag)

    def add(sku, av, score, tag):
        old = scored.get(sku)
        if old is None or score > old[1]:
            scored[sku] = (av, score, tag)

    # 1) 自动匹配结果（若有）作为强候选
    if auto_match:
        st, sku, av, desc = auto_match
        if st == "OK":
            add(sku, av, 3.0, "自动命中")
        elif st == "部分匹配":
            add(sku, av, 2.5, "组合")
        elif st == "组合表":
            add(sku, av, 2.8, "组合表")
    else:
        try:
            st, sku, av, desc = matcher.match_one(f)
            if st == "OK":
                add(sku, av, 3.0, "自动命中")
            elif st == "部分匹配":
                add(sku, av, 2.5, "组合")
        except Exception:
            pass

    # 2) 定位候选池
    if pool is not None and run_index is not None and orig_runs:
        keys = set()
        for r in orig_runs:
            keys.update(run_index.get(r, ()))
        sub = [(k, r, a, t, ck) for (k, r, a, t, ck) in pool if k in keys]
    elif pool is not None:
        sub = pool
    else:
        sub = [(k, raw, av, tokens_of(raw), clean_full(raw)) for k, (raw, av) in exact.items()]

    # 3) 打分（用预计算的词元与clean键）
    for k, raw, av, toks, ck in sub:
        if not toks:
            continue
        inter = len(orig_toks & toks)
        if inter == 0 and ck != clean_f:
            continue
        score = inter / max(1, len(orig_toks))
        tag = "相似"
        if ck == clean_f:
            score += 1.0
            tag = "规范化同键"
        if k == hl:
            score += 2.0
            tag = "精准"
        add(raw, av, score, tag)

    result = sorted(scored.items(), key=lambda kv: (-kv[1][1], kv[1][0]))
    return [(sku, av, round(score, 3), tag) for sku, (av, score, tag) in result[:top_n]]
