"""Chon parser BeautifulSoup: uu tien lxml, fallback html.parser (khi lxml chua cai)."""

from __future__ import annotations

_BS4_PARSER: str | None = None


def get_bs4_parser() -> str:
    global _BS4_PARSER
    if _BS4_PARSER is not None:
        return _BS4_PARSER
    try:
        import lxml  # noqa: F401

        from bs4 import BeautifulSoup

        BeautifulSoup("<html></html>", "lxml")
        _BS4_PARSER = "lxml"
    except Exception:
        _BS4_PARSER = "html.parser"
    return _BS4_PARSER
