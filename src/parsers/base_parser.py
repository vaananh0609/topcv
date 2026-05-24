"""Parser tách biệt Spider — trang danh sách lấy job_id + url."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, TypedDict


class ListItem(TypedDict):
    job_id: str
    url: str


class BaseParser(ABC):
    source: str = ""

    @abstractmethod
    def parse_list(self, html: str, list_page_url: str) -> List[ListItem]:
        """Trích job_id + url từ HTML trang danh sách."""

    @abstractmethod
    def parse_detail(self, html: str, url: str) -> dict[str, Any]:
        """Trích các trường từ HTML trang chi tiết job."""
