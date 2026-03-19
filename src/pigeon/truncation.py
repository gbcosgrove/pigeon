"""Response truncation and markdown stripping for iMessage display."""

import re


def strip_markdown(text: str) -> str:
    """Strip markdown formatting for clean iMessage display."""
    # Headers → UPPERCASE
    text = re.sub(r'^#{1,6}\s+(.+)$', lambda m: m.group(1).upper(), text, flags=re.MULTILINE)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
    # Strikethrough
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # Code blocks (must come before inline code)
    text = re.sub(r'```[\w]*\n(.*?)\n```', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'```[\w]*\n?', '', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # List items → bullet
    text = re.sub(r'^[\s]*[-*]\s+', '  \u2022 ', text, flags=re.MULTILINE)
    # Links → text (url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    # Horizontal rules
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def truncate_response(text: str, limit: int, expand_keyword: str) -> tuple[str, bool]:
    """Truncate text if it exceeds the limit.

    Returns (possibly_truncated_text, was_truncated).
    """
    if len(text) <= limit:
        return text, False

    truncated = text[:limit] + f"\n\n[truncated — reply {expand_keyword} for full]"
    return truncated, True
