from organizer.classification import (
    active_folder_rules_map,
    build_folder_rules_summary_lines,
    filter_classification_folders,
    sync_folder_rules,
)


def _folders():
    return [
        {"id": 1, "title": "技术"},
        {"id": 2, "title": "资讯"},
    ]


def test_sync_creates_defaults_for_new_folders():
    out = sync_folder_rules(_folders(), existing_rules=None)
    assert out["version"] == 1
    assert {f["folder_id"] for f in out["folders"]} == {1, 2}
    for f in out["folders"]:
        assert f["auto_classify"] is True
        assert f["missing_from_telegram"] is False
        assert f["description"] == ""


def test_sync_preserves_existing_descriptions_and_flags():
    existing = {
        "version": 1,
        "folders": [
            {
                "folder_id": 1,
                "folder_title": "技术",
                "auto_classify": False,
                "description": "编程",
                "include_keywords": ["python", "  "],  # whitespace filtered
                "exclude_keywords": ["广告"],
                "notes": "n",
            }
        ],
    }
    out = sync_folder_rules(_folders(), existing_rules=existing)
    rule_1 = next(f for f in out["folders"] if f["folder_id"] == 1)
    assert rule_1["auto_classify"] is False
    assert rule_1["description"] == "编程"
    assert rule_1["include_keywords"] == ["python"]
    assert rule_1["exclude_keywords"] == ["广告"]
    assert rule_1["notes"] == "n"


def test_sync_marks_orphan_rules_missing():
    existing = {
        "version": 1,
        "folders": [{"folder_id": 999, "folder_title": "已删", "description": "old"}],
    }
    out = sync_folder_rules(_folders(), existing_rules=existing)
    orphan = next(f for f in out["folders"] if f["folder_id"] == 999)
    assert orphan["missing_from_telegram"] is True
    assert orphan["description"] == "old"


def test_active_folder_rules_map_skips_missing():
    rules = {
        "folders": [
            {"folder_id": 1, "folder_title": "T", "description": "d"},
            {"folder_id": 2, "folder_title": "X", "missing_from_telegram": True},
        ]
    }
    active = active_folder_rules_map(rules)
    assert set(active) == {1}


def test_filter_classification_folders_drops_auto_classify_false():
    rules = {
        "folders": [
            {"folder_id": 1, "folder_title": "技术", "auto_classify": True},
            {"folder_id": 2, "folder_title": "资讯", "auto_classify": False},
        ]
    }
    filtered = filter_classification_folders(_folders(), rules)
    assert [f["id"] for f in filtered] == [1]


def test_summary_lines_count_missing_descriptions_for_active_only():
    rules = {
        "folders": [
            {"folder_id": 1, "folder_title": "技术", "auto_classify": True, "description": ""},
            {"folder_id": 2, "folder_title": "资讯", "auto_classify": False, "description": ""},
        ]
    }
    _lines, missing = build_folder_rules_summary_lines(rules, _folders())
    assert missing == 1
