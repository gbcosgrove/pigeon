"""Tests for chat.db text extraction."""

from pigeon.chatdb import extract_text


def test_extract_text_from_text_column():
    assert extract_text("hello world", None) == "hello world"


def test_extract_text_strips_whitespace():
    assert extract_text("  hello  ", None) == "hello"


def test_extract_text_none_both():
    assert extract_text(None, None) is None


def test_extract_text_empty_string():
    assert extract_text("", None) is None


def test_extract_text_prefers_text_column():
    assert extract_text("from text", b"from body") == "from text"


def test_extract_text_bad_blob():
    # Random bytes that don't contain NSString marker
    assert extract_text(None, b"\x00\x01\x02\x03") is None
