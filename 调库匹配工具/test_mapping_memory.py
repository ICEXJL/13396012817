# -*- coding: utf-8 -*-
"""历史人工 SKU 映射测试。"""

from mapping_memory import (
    load_mapping_memory,
    remember_mapping,
    resolve_remembered_mapping,
)


def test_manual_mapping_roundtrips_and_can_be_resolved_again(tmp_path):
    path = tmp_path / "sku_mapping_memory.json"
    mappings = {}

    remember_mapping(mappings, "  74700736-White  70m/roll-3PCS ", "SKU-747", path)

    loaded = load_mapping_memory(path)
    assert loaded["74700736-white 70m/roll-3pcs"]["stock_sku"] == "SKU-747"
    assert resolve_remembered_mapping(
        "74700736-white 70m/roll-3PCS",
        loaded,
        {"sku-747": ("SKU-747", 23)},
        {},
    ) == ("SKU-747", 23)


def test_missing_remembered_sku_falls_back_to_normal_matching():
    assert resolve_remembered_mapping(
        "missing-sales-sku",
        {
            "missing-sales-sku": {
                "sales_f": "missing-sales-sku",
                "stock_sku": "SKU-NOT-IN-STOCK",
            }
        },
        {},
        {},
    ) is None
