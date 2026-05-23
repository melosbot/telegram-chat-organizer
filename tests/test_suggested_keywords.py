from app.classification import (
    derive_suggested_keywords,
    sync_folder_rules,
)


def _folders():
    return [{"id": 1, "title": "技术"}, {"id": 2, "title": "资讯"}]


def _categorized():
    return {
        "categorized": [
            {
                "folder_id": 1,
                "folder_title": "技术",
                "chats": [
                    {"chat_id": 101, "type": "GROUP"},
                    {"chat_id": 102, "type": "GROUP"},
                    {"chat_id": 103, "type": "GROUP"},
                ],
            },
            {
                "folder_id": 2,
                "folder_title": "资讯",
                "chats": [{"chat_id": 201, "type": "CHANNEL"}],
            },
        ]
    }


def _chats():
    return [
        {"chat_id": 101, "title": "Python 学习"},
        {"chat_id": 102, "title": "Python 后端 开发"},
        {"chat_id": 103, "title": "Python 招聘"},
        {"chat_id": 201, "title": "每日要闻 News"},
    ]


def test_derive_collects_top_tokens_per_folder():
    rules = sync_folder_rules(_folders())
    out = derive_suggested_keywords(rules, _categorized(), _chats(), min_count=2, max_per_folder=5)
    folder_1 = next(r for r in out["folders"] if r["folder_id"] == 1)
    # "python" appears 3 times in folder 1 -> top suggestion
    assert "python" in folder_1["suggested_keywords"]


def test_derive_skips_tokens_already_in_include_keywords():
    rules = sync_folder_rules(
        _folders(),
        existing_rules={"folders": [{"folder_id": 1, "folder_title": "技术", "include_keywords": ["python"]}]},
    )
    out = derive_suggested_keywords(rules, _categorized(), _chats(), min_count=2, max_per_folder=5)
    folder_1 = next(r for r in out["folders"] if r["folder_id"] == 1)
    assert "python" not in folder_1.get("suggested_keywords", [])


def test_derive_drops_low_count_tokens():
    rules = sync_folder_rules(_folders())
    out = derive_suggested_keywords(rules, _categorized(), _chats(), min_count=2)
    folder_2 = next(r for r in out["folders"] if r["folder_id"] == 2)
    # folder 2 has only one chat, so its tokens all appear once -> no suggestions
    assert folder_2.get("suggested_keywords", []) == [] or "suggested_keywords" not in folder_2


def test_derive_skips_pure_digits_and_stopwords():
    rules = sync_folder_rules(_folders())
    chats = [
        {"chat_id": 1, "title": "channel 2024 news"},
        {"chat_id": 2, "title": "channel 2024 news"},
    ]
    categorized = {
        "categorized": [
            {"folder_id": 1, "folder_title": "技术", "chats": [{"chat_id": 1}, {"chat_id": 2}]}
        ]
    }
    out = derive_suggested_keywords(rules, categorized, chats, min_count=2)
    folder_1 = next(r for r in out["folders"] if r["folder_id"] == 1)
    suggestions = folder_1.get("suggested_keywords", [])
    assert "channel" not in suggestions  # stopword
    assert "news" not in suggestions  # stopword
    assert "2024" not in suggestions  # pure digit


def test_sync_preserves_suggested_keywords_round_trip():
    existing = {
        "folders": [{"folder_id": 1, "folder_title": "技术", "suggested_keywords": ["python", "ai"]}]
    }
    out = sync_folder_rules(_folders(), existing_rules=existing)
    folder_1 = next(r for r in out["folders"] if r["folder_id"] == 1)
    assert folder_1["suggested_keywords"] == ["python", "ai"]
