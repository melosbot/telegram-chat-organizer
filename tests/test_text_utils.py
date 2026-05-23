from organizer.utils.text import (
    dedupe_message_samples,
    flatten_message_text,
    message_identity_text,
    messages_are_duplicate,
)


def test_flatten_collapses_whitespace():
    assert flatten_message_text("hello   world\n\tnext") == "hello world next"


def test_identity_strips_timestamp_and_normalizes_case():
    assert message_identity_text("11-12 13:14  Hello WORLD") == "hello world"


def test_duplicate_detects_exact_after_timestamp_strip():
    assert messages_are_duplicate("11-12 13:14 hello world", "hello world")


def test_duplicate_detects_substring_when_shorter_long_enough():
    assert messages_are_duplicate("abcdefghijklm", "abcdefghijklmxxxxxx")


def test_duplicate_rejects_short_substring():
    assert not messages_are_duplicate("abc", "abcdefghij")


def test_duplicate_rejects_empty():
    assert not messages_are_duplicate("", "anything")
    assert not messages_are_duplicate("anything", "")


def test_dedupe_drops_empty_and_duplicates_against_last_message():
    samples = ["a", "", "a", "b", "11-12 13:14 b"]
    assert dedupe_message_samples(samples, last_message="a") == ["b"]


def test_dedupe_preserves_first_occurrence_order():
    samples = ["x", "y", "x", "z"]
    assert dedupe_message_samples(samples, last_message="") == ["x", "y", "z"]
