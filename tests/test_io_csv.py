import csv

from organizer.classification import (
    build_categorization_from_memory_csv,
    build_categorization_from_review_csv,
    compute_chat_signature,
    export_classification_memory_csv,
    export_classification_review_csv,
)


def _folders():
    return [{"id": 10, "title": "技术"}, {"id": 20, "title": "资讯"}]


def _chats():
    return [
        {"chat_id": 111, "title": "Py", "username": "py", "description": "python dev", "type": "SUPERGROUP"},
        {"chat_id": 222, "title": "News", "username": "news", "description": "news feed", "type": "CHANNEL"},
        {"chat_id": 333, "title": "Misc", "username": "", "description": "", "type": "GROUP"},
    ]


def _categorized():
    return {
        "categorized": [
            {
                "folder_id": 10,
                "folder_title": "技术",
                "chats": [{"chat_id": 111, "type": "SUPERGROUP", "confidence": "high", "reason": "title/Py"}],
            }
        ]
    }


def test_signature_is_stable_and_sensitive(tmp_path):
    chat = {"title": "X", "username": "x", "description": "d", "about": "a"}
    s1 = compute_chat_signature(chat)
    s2 = compute_chat_signature(dict(chat))
    assert s1 == s2
    s3 = compute_chat_signature({**chat, "description": "different"})
    assert s1 != s3


def test_review_csv_roundtrip(tmp_path):
    csv_path = tmp_path / "review.csv"
    export_classification_review_csv(csv_path, _categorized(), _chats())
    text = csv_path.read_text(encoding="utf-8-sig")
    # categorized row present and unassigned rows for the other two chats
    assert "categorized" in text and "111" in text
    assert "unassigned" in text and "222" in text and "333" in text

    rebuilt = build_categorization_from_review_csv(csv_path, _folders(), _chats())
    assert rebuilt["categorized"][0]["folder_id"] == 10
    assert rebuilt["categorized"][0]["chats"][0]["chat_id"] == 111


def test_review_csv_user_assigns_unassigned(tmp_path):
    csv_path = tmp_path / "review.csv"
    export_classification_review_csv(csv_path, _categorized(), _chats())

    # Simulate user editing the CSV: assign chat 222 to folder 20.
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    for row in rows:
        if row["chat_id"] == "222":
            row["folder_id"] = "20"
            row["folder_title"] = "资讯"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    rebuilt = build_categorization_from_review_csv(csv_path, _folders(), _chats())
    folder_ids = {f["folder_id"] for f in rebuilt["categorized"]}
    assert {10, 20}.issubset(folder_ids)


def test_review_csv_skip_status_removes_assignment(tmp_path):
    csv_path = tmp_path / "review.csv"
    export_classification_review_csv(csv_path, _categorized(), _chats())
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    for row in rows:
        if row["chat_id"] == "111":
            row["status"] = "ignore"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    rebuilt = build_categorization_from_review_csv(csv_path, _folders(), _chats())
    all_chat_ids = {c["chat_id"] for f in rebuilt["categorized"] for c in f["chats"]}
    assert 111 not in all_chat_ids


def test_memory_signature_hit_and_change(tmp_path):
    mem_path = tmp_path / "memory.csv"
    n = export_classification_memory_csv(mem_path, _categorized(), _chats())
    assert n == 1

    # Hit
    data, stats = build_categorization_from_memory_csv(mem_path, _folders(), _chats())
    assert stats["hit"] == 1 and stats["changed"] == 0
    assert data["categorized"][0]["chats"][0]["chat_id"] == 111

    # Changed: rewrite chat 111's description so the signature differs.
    chats_changed = [dict(c) for c in _chats()]
    chats_changed[0]["description"] = "completely different topic now"
    data2, stats2 = build_categorization_from_memory_csv(mem_path, _folders(), chats_changed)
    assert stats2["changed"] == 1 and stats2["hit"] == 0
    assert data2["categorized"] == []


def test_memory_missing_chat_counted(tmp_path):
    mem_path = tmp_path / "memory.csv"
    export_classification_memory_csv(mem_path, _categorized(), _chats())
    # Drop chat 111 from current chats.
    survivors = [c for c in _chats() if c["chat_id"] != 111]
    _data, stats = build_categorization_from_memory_csv(mem_path, _folders(), survivors)
    assert stats["missing_chat"] == 1


def test_memory_legacy_no_signature(tmp_path):
    # Write a memory CSV without the chat_signature column.
    legacy_path = tmp_path / "legacy.csv"
    with legacy_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["status", "folder_id", "folder_title", "chat_id", "chat_title", "chat_type", "reason"])
        writer.writerow(["categorized", "10", "技术", "111", "Py", "SUPERGROUP", "legacy"])

    data, stats = build_categorization_from_memory_csv(legacy_path, _folders(), _chats())
    assert stats["legacy_no_signature"] == 1
    assert data["categorized"][0]["chats"][0]["chat_id"] == 111
