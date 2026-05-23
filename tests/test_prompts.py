from organizer.classification import parse_ai_response_to_groups
import pytest


def test_parse_strips_markdown_fence():
    text = '```json\n{"categorized":[{"folder_id":1,"folder_title":"T","chats":[{"chat_id":11,"type":"GROUP"}]}]}\n```'
    out = parse_ai_response_to_groups(text)
    assert out["categorized"][0]["folder_id"] == 1
    assert out["categorized"][0]["chats"][0]["chat_id"] == 11


def test_parse_extracts_json_object_from_noisy_text():
    text = 'Here is the result:\n{"categorized":[]}\nDone.'
    out = parse_ai_response_to_groups(text)
    assert out == {"categorized": []}


def test_parse_rejects_no_json():
    with pytest.raises(ValueError):
        parse_ai_response_to_groups("no json here")


def test_parse_normalizes_string_folder_id():
    text = '{"categorized":[{"folder_id":"42","folder_title":"X","chats":[{"chat_id":"7","type":"GROUP"}]}]}'
    out = parse_ai_response_to_groups(text)
    assert out["categorized"][0]["folder_id"] == 42
    assert out["categorized"][0]["chats"][0]["chat_id"] == 7
