import pytest

from organizer.classification import (
    add_chat_assignment,
    compute_assigned_chat_ids,
    compute_unassigned_chats,
    merge_categorization_results,
    normalize_groups_data,
    validate_reference_integrity,
)


def test_normalize_rejects_non_dict():
    with pytest.raises(ValueError):
        normalize_groups_data([])


def test_normalize_rejects_missing_categorized():
    with pytest.raises(ValueError):
        normalize_groups_data({})


def test_normalize_keeps_valid_entries_and_drops_garbage():
    raw = {
        "categorized": [
            {
                "folder_id": "10",
                "folder_title": "技术",
                "chats": [
                    {"chat_id": 111, "type": "GROUP", "reason": "ok", "confidence": "high"},
                    {"chat_id": "not-an-int"},
                    {"chat_id": 111, "type": "GROUP"},  # duplicate in same folder
                    "not-a-dict",
                ],
            },
            "not-a-folder-dict",
            {"folder_id": "bad"},
        ]
    }
    normalized = normalize_groups_data(raw)
    folders = normalized["categorized"]
    assert len(folders) == 1
    assert folders[0]["folder_id"] == 10
    assert [c["chat_id"] for c in folders[0]["chats"]] == [111]


def test_normalize_truncates_long_reason():
    raw = {
        "categorized": [
            {
                "folder_id": 1,
                "folder_title": "T",
                "chats": [{"chat_id": 1, "type": "GROUP", "reason": "x" * 500}],
            }
        ]
    }
    out = normalize_groups_data(raw)
    assert len(out["categorized"][0]["chats"][0]["reason"]) <= 203


def test_merge_dedupes_chats_across_results():
    a = {"categorized": [{"folder_id": 1, "folder_title": "A", "chats": [{"chat_id": 11, "type": "GROUP"}]}]}
    b = {
        "categorized": [
            {"folder_id": 1, "folder_title": "A", "chats": [{"chat_id": 11, "type": "GROUP"}, {"chat_id": 12, "type": "GROUP"}]},
            {"folder_id": 2, "folder_title": "B", "chats": [{"chat_id": 11, "type": "GROUP"}]},
        ]
    }
    merged = merge_categorization_results([a, b], {1: "A", 2: "B"})
    folder_a = next(f for f in merged["categorized"] if f["folder_id"] == 1)
    folder_b = next((f for f in merged["categorized"] if f["folder_id"] == 2), None)
    assert sorted(c["chat_id"] for c in folder_a["chats"]) == [11, 12]
    # folder B's chat 11 was already taken by folder A's earlier result
    assert folder_b is None or all(c["chat_id"] != 11 for c in folder_b["chats"])


def test_compute_unassigned_returns_chats_not_in_categorized():
    chats = [{"chat_id": 1}, {"chat_id": 2}, {"chat_id": 3}]
    data = {"categorized": [{"folder_id": 1, "folder_title": "A", "chats": [{"chat_id": 2}]}]}
    unassigned = compute_unassigned_chats(chats, data)
    assert [c["chat_id"] for c in unassigned] == [1, 3]


def test_compute_assigned_chat_ids_handles_bad_ids():
    data = {
        "categorized": [
            {"folder_id": 1, "folder_title": "A", "chats": [{"chat_id": 11}, {"chat_id": "bad"}, {"chat_id": 12}]}
        ]
    }
    assert compute_assigned_chat_ids(data) == {11, 12}


def test_validate_reference_integrity_flags_unknown_and_duplicates():
    data = {
        "categorized": [
            {"folder_id": 1, "folder_title": "A", "chats": [{"chat_id": 11}, {"chat_id": 99}]},
            {"folder_id": 9, "folder_title": "X", "chats": [{"chat_id": 11}]},
        ]
    }
    errors = validate_reference_integrity(data, valid_folder_ids={1}, valid_chat_ids={11})
    # folder 9 missing + chat 99 missing + chat 11 duplicate across folders
    assert any("folder_id=9" in e for e in errors)
    assert any("chat_id=99" in e for e in errors)
    assert any("chat_id=11" in e and "重复" in e for e in errors)


def test_add_chat_assignment_creates_folder_when_missing():
    data = {"categorized": []}
    add_chat_assignment(data, folder_id=5, folder_title="新", chat={"chat_id": 77, "type": "GROUP"}, reason="r")
    assert data["categorized"] == [
        {
            "folder_id": 5,
            "folder_title": "新",
            "chats": [{"chat_id": 77, "type": "GROUP", "confidence": "manual", "reason": "r"}],
        }
    ]


def test_add_chat_assignment_appends_to_existing_folder():
    data = {"categorized": [{"folder_id": 5, "folder_title": "新", "chats": []}]}
    add_chat_assignment(data, folder_id=5, folder_title="新", chat={"chat_id": 77}, reason="r")
    add_chat_assignment(data, folder_id=5, folder_title="新", chat={"chat_id": 78}, reason="r2")
    assert [c["chat_id"] for c in data["categorized"][0]["chats"]] == [77, 78]
