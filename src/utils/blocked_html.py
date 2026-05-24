"""Phát hiện HTML là trang WAF / Cloudflare block — dùng chung mọi nguồn crawl."""

from __future__ import annotations


class BlockedHtmlError(RuntimeError):
    """Trang trả về block/challenge thay vì nội dung job — nên retry sau."""


# Chuỗi đặc trưng (kiểm tra không phân biệt hoa thường trừ khi ghi chú)
_BLOCK_MARKERS_LOWER = (
    "sorry, you have been blocked",
    "you have been blocked",
    "cf-browser-verification",
    "cf-challenge",
    "cf-error-details",
    "cf-error-footer",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
    "just a moment",
    "attention required! | cloudflare",
    "access denied",
    "error code 1020",
)

# Giữ nguyên case (một số site nhúng đúng chữ hoa)
_BLOCK_MARKERS_RAW = (
    "Sorry, you have been blocked",
    "Enable JavaScript and cookies to continue",
    "Access denied",
)


def html_is_waf_blocked(html: str) -> bool:
    """True nếu HTML là trang chặn / challenge, không phải trang job."""
    if not html:
        return False
    for s in _BLOCK_MARKERS_RAW:
        if s in html:
            return True
    h = html.lower()
    for s in _BLOCK_MARKERS_LOWER:
        if s in h:
            return True
    return False
