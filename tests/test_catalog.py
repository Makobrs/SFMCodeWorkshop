import json
from pathlib import Path

from sfm_workshop.core.catalog import (
    catalog_path,
    import_items,
    load_catalog,
    parse_items_payload,
    search_catalog,
    search_entries,
)


def test_tooltip_name_pinyin_and_initials():
    rows = parse_items_payload(
        [
            {
                "id": "minecraft:iron_ingot",
                "tags": ["forge:ingots"],
                "tooltip": "铁锭\nminecraft:iron_ingot\nMinecraft",
            }
        ]
    )
    entry = rows[0]
    assert entry.name == "铁锭"
    assert entry.pinyin == "tieding"
    assert entry.initials == "td"
    assert entry.tags == ("forge:ingots",)
    for query in ("铁锭", "tie ding", "tieding", "td", "minecraft:iron_ingot"):
        assert any(e.id == "minecraft:iron_ingot" for e in search_entries(rows, query)), query



def test_parse_items_list_and_dict():
    payload = [
        {"id": "minecraft:iron_ingot", "display_name": "铁锭"},
        {"resource": "minecraft:gold_ingot", "translation": "金锭"},
        "minecraft:coal",
    ]
    rows = parse_items_payload(payload)
    ids = {e.id for e in rows}
    assert ids == {"minecraft:iron_ingot", "minecraft:gold_ingot", "minecraft:coal"}
    assert any(e.name == "铁锭" for e in rows)


def test_parse_wrapped_and_keyed():
    payload = {"items": {"minecraft:iron_ingot": "Iron Ingot", "minecraft:water": {"display_name": "Water"}}}
    rows = parse_items_payload(payload)
    ids = {e.id for e in rows}
    assert "minecraft:iron_ingot" in ids
    assert "minecraft:water" in ids


def test_import_and_search(tmp_path, monkeypatch):
    # isolate the profile data dir
    import sfm_workshop.core.catalog as catalog

    monkeypatch.setattr(catalog, "user_root", lambda: tmp_path)
    src = tmp_path / "items.json"
    src.write_text(json.dumps([{"id": "minecraft:iron_ingot", "name": "铁锭"}]), encoding="utf-8")
    rows = import_items(src, "test-profile")
    assert len(rows) == 1
    assert catalog_path("test-profile").exists()
    loaded = load_catalog("test-profile")
    assert loaded[0].id == "minecraft:iron_ingot"
    assert search_catalog("test-profile", "iron")[0].name == "铁锭"
    assert search_catalog("test-profile", "not-found") == []
