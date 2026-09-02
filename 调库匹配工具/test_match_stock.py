# -*- coding: utf-8 -*-
"""组合 SKU 核心匹配回归测试。"""

from match_stock import Matcher, clean_full


def _matcher_with_stock(entries):
    exact = {sku.lower(): (sku, stock) for sku, stock in entries}
    norm = {}
    for sku, stock in entries:
        norm.setdefault(clean_full(sku), []).append((sku, stock))
    return Matcher(exact, norm)


def test_multi_sku_is_split_before_quantity_cleanup():
    """防止 L4 清理 10pcs 时吞掉 + 后的第二个货号。"""
    matcher = _matcher_with_stock([
        ("74700593-10pcs", 7),
        ("51501252-blue", 2),
    ])

    status, sku, available, description = matcher.match_one(
        "74700593-10pcs + 51501252-blue"
    )

    assert status == "OK"
    assert sku == "74700593-10pcs + 51501252-blue"
    assert available == 2
    assert "L7+号拆分全命中" in description


def test_slash_roll_suffix_matches_sku_before_slash():
    """包装信息在斜杠后时，应使用斜杠前的主 SKU。"""
    matcher = _matcher_with_stock([
        ("74700736-white 70m", 296),
    ])

    status, sku, available, _ = matcher.match_one("74700736-white 70m/roll-3PCS")

    assert status == "OK"
    assert sku == "74700736-white 70m"
    assert available == 296


def test_slash_pack_quantity_falls_back_to_one_piece_alias():
    """/10PCS 库存不存在时，应尝试同主 SKU 的 /1PCS 形式。"""
    matcher = _matcher_with_stock([
        ("66600162-M/1PCS", 377),
    ])

    status, sku, available, _ = matcher.match_one("66600162-M/10PCS")

    assert status == "OK"
    assert sku == "66600162-M/1PCS"
    assert available == 377


def test_trailing_multiplier_matches_pack_sku():
    """尾部 *2 仅代表倍数，不应妨碍匹配原包装 SKU。"""
    matcher = _matcher_with_stock([
        ("337800429-100pcs", 48),
    ])

    status, sku, available, _ = matcher.match_one("337800429-100pcs*2")

    assert status == "OK"
    assert sku == "337800429-100pcs"
    assert available == 48


def test_embedded_pack_word_keeps_following_description():
    """中间的 -3pcs 应移除，但保留后面的颜色与规格用于匹配。"""
    matcher = _matcher_with_stock([
        ("35200908-Color Random 24*2.5cm", 181),
    ])

    status, sku, available, _ = matcher.match_one("35200908-3pcs Color Random zuhe")

    assert status == "OK"
    assert sku == "35200908-Color Random 24*2.5cm"
    assert available == 181


def test_cleaned_multiplier_prefix_uses_unique_stock_sku():
    """去掉 *100 后的主 SKU 可唯一前缀命中库存 SKU。"""
    matcher = _matcher_with_stock([
        ("74700034-L 100psc", 0),
        ("74700034-M 100psc", 1131),
    ])

    status, sku, available, _ = matcher.match_one("74700034-L*100")

    assert status == "OK"
    assert sku == "74700034-L 100psc"
    assert available == 0
