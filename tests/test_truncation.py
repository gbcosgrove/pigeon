"""Tests for truncation and markdown stripping."""

from pigeon.truncation import strip_markdown, truncate_response


def test_strip_markdown_headers():
    assert strip_markdown("# Hello") == "HELLO"
    assert strip_markdown("## World") == "WORLD"


def test_strip_markdown_bold():
    assert strip_markdown("**bold text**") == "bold text"
    assert strip_markdown("__also bold__") == "also bold"


def test_strip_markdown_italic():
    assert strip_markdown("*italic*") == "italic"


def test_strip_markdown_code():
    assert strip_markdown("`inline code`") == "inline code"
    assert strip_markdown("```python\ncode\n```") == "code"


def test_strip_markdown_links():
    result = strip_markdown("[click here](https://example.com)")
    assert result == "click here (https://example.com)"


def test_strip_markdown_lists():
    result = strip_markdown("- item one\n- item two")
    assert "\u2022 item one" in result
    assert "\u2022 item two" in result


def test_strip_markdown_preserves_plain():
    text = "Just plain text, nothing special."
    assert strip_markdown(text) == text


def test_truncate_short():
    text = "Short message"
    result, was_truncated = truncate_response(text, 2000, "pigeon:cc")
    assert result == text
    assert was_truncated is False


def test_truncate_long():
    text = "x" * 3000
    result, was_truncated = truncate_response(text, 2000, "pigeon:cc")
    assert was_truncated is True
    assert len(result) < 3000
    assert "pigeon:cc" in result
    assert "truncated" in result


def test_truncate_exact_limit():
    text = "x" * 2000
    result, was_truncated = truncate_response(text, 2000, "pigeon:cc")
    assert result == text
    assert was_truncated is False
