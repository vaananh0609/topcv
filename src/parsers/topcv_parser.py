"""
TopCV — parse list (job_id + url) và parse chi tiết (selector theo layout TopCV).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, List
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from src.parsers.base_parser import BaseParser, ListItem
from src.utils.blocked_html import html_is_waf_blocked
from src.utils.bs4_parser import get_bs4_parser


class TopcvListPageBlockedError(RuntimeError):
    """Trang danh sách không hợp lệ (WAF / thiếu link)."""


def topcv_list_html_seems_blocked_or_empty(html: str) -> bool:
    if html_is_waf_blocked(html):
        return True
    low = html.lower()
    if len(html) >= 18_000:
        return False
    signals = low.count("viec-lam") + low.count("tuyen-dung")
    return signals < 3


def topcv_list_url_with_page(list_url: str, page: int) -> str:
    u = urlparse(list_url)
    q = dict(parse_qsl(u.query))
    if page <= 1:
        q.pop("page", None)
    else:
        q["page"] = str(page)
    query = urlencode(q)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, query, u.fragment))


def topcv_list_page_state(
    items: list[ListItem],
    prev_fp: tuple[str, ...] | None,
) -> tuple[bool, tuple[str, ...] | None]:
    if not items:
        return True, None
    fp = tuple(sorted({str(i["job_id"]) for i in items}))
    if prev_fp is not None and fp == prev_fp:
        return True, fp
    return False, fp


def _strip_js_title(s: str) -> str:
    t = s.strip().replace("\\'", "'")
    for _ in range(4):
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
            t = t[1:-1].strip()
            continue
        break
    return t.replace('\\"', '"').strip()


def _extract_window_topcv_job(html: str) -> dict[str, Any]:
    m = re.search(r"window\.topcvJob\s*=\s*\{", html)
    if not m:
        return {}
    block = html[m.start() : m.start() + 12000]
    out: dict[str, Any] = {}
    jm = re.search(r"jobId:\s*(\d+)", block)
    if jm:
        out["source_job_id"] = jm.group(1)
    tm = re.search(r'title:\s*"((?:\\.|[^"\\])*)"', block)
    if not tm:
        tm = re.search(r'title:\s*""(.*?)""\s*,', block, re.DOTALL)
    if tm:
        raw = tm.group(1).replace("\\\\", "\\").replace('\\"', '"')
        out["title"] = _strip_js_title(raw)
    lm = re.search(r'linkType:\s*"([^"]*)"', block)
    if not lm:
        lm = re.search(r"linkType:\s*(\w+)\s*,", block)
    if lm:
        out["link_type"] = lm.group(1).strip()
    return out


def _iter_ld_json_objects(html: str):
    soup = BeautifulSoup(html, get_bs4_parser())
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            for x in data:
                if isinstance(x, dict):
                    yield x
        elif isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                for x in data["@graph"]:
                    if isinstance(x, dict):
                        yield x
            else:
                yield data


def _is_jobposting(obj: dict[str, Any]) -> bool:
    t = obj.get("@type")
    if t == "JobPosting":
        return True
    if isinstance(t, list):
        return "JobPosting" in t
    return False


def _extract_jsonld_jobposting(html: str) -> dict[str, Any]:
    """baseSalary, datePosted, validThrough, industry từ JobPosting."""
    out: dict[str, Any] = {
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "posted_date": None,
        "deadline_at": None,
        "industry": None,
    }
    for obj in _iter_ld_json_objects(html):
        if not _is_jobposting(obj):
            continue
        base = obj.get("baseSalary")
        if isinstance(base, dict):
            out["salary_currency"] = base.get("currency")
            val = base.get("value")
            if isinstance(val, dict):
                lo = val.get("minValue")
                hi = val.get("maxValue")
                if isinstance(lo, (int, float)):
                    out["salary_min"] = float(lo)
                if isinstance(hi, (int, float)):
                    out["salary_max"] = float(hi)
        if obj.get("datePosted"):
            out["posted_date"] = str(obj["datePosted"]).strip()
        if obj.get("validThrough"):
            out["deadline_at"] = str(obj["validThrough"]).strip()
        ind = obj.get("industry")
        if isinstance(ind, str) and ind.strip():
            out["industry"] = ind.strip()
        elif isinstance(ind, dict) and isinstance(ind.get("name"), str):
            out["industry"] = ind["name"].strip()
        if not out.get("industry"):
            occ = obj.get("occupationalCategory")
            if isinstance(occ, str) and occ.strip():
                out["industry"] = occ.strip()
            elif isinstance(occ, dict) and isinstance(occ.get("name"), str):
                out["industry"] = occ["name"].strip()
        break
    return out


def _normalize_text(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip())


def _extract_labeled_info_sections(soup: BeautifulSoup) -> dict[str, str]:
    """job-detail__info--section-content: title (Mức lương, Kinh nghiệm, …) → value."""
    found: dict[str, str] = {}
    for div in soup.find_all("div", class_=re.compile(r"job-detail__info--section-content")):
        title_el = div.find("div", class_=re.compile(r"job-detail__info--section-content-title"))
        value_el = div.find("div", class_=re.compile(r"job-detail__info--section-content-value"))
        if not title_el or not value_el:
            continue
        key = _normalize_text(title_el.get_text())
        val = _normalize_text(value_el.get_text())
        if key:
            found[key.lower()] = val
    return found


def _extract_basic_information_map(soup: BeautifulSoup) -> dict[str, str]:
    """Pro TH2: .basic-information-item__data (label / value)."""
    out: dict[str, str] = {}
    for block in soup.select("div.basic-information-item__data"):
        lab = block.select_one(".basic-information-item__data--label")
        val = block.select_one(".basic-information-item__data--value")
        if lab and val:
            k = _normalize_text(lab.get_text()).lower()
            out[k] = _normalize_text(val.get_text())
    return out


def _extract_general_information_map(soup: BeautifulSoup) -> dict[str, str]:
    """Pro TH2: .general-information-data."""
    out: dict[str, str] = {}
    for block in soup.select("div.general-information-data"):
        lab = block.select_one(".general-information-data__label")
        val = block.select_one(".general-information-data__value")
        if lab and val:
            k = _normalize_text(lab.get_text()).lower()
            out[k] = _normalize_text(val.get_text())
    return out


def _extract_strong_span_map(soup: BeautifulSoup) -> dict[str, str]:
    """
    Pro TH3: <div><strong>Học vấn </strong><br><span>...</span></div> (và Kinh nghiệm, Thu nhập, …).
    """
    out: dict[str, str] = {}
    for strong in soup.find_all("strong"):
        raw_lab = _normalize_text(strong.get_text()).replace("\xa0", " ").strip().rstrip(":")
        if not raw_lab:
            continue
        key = raw_lab.lower()
        parent = strong.parent
        if not isinstance(parent, Tag) or parent.name != "div":
            continue
        span: Tag | None = None
        for sib in strong.next_siblings:
            name = getattr(sib, "name", None)
            if name == "br":
                continue
            if name == "span":
                span = sib  # type: ignore[assignment]
                break
            if name and name != "br":
                break
        if span is not None:
            val = _normalize_text(span.get_text())
            if val:
                out[key] = val
    return out


def _pick_from_label_maps(maps: list[dict[str, str]], *needles: str) -> str | None:
    """Tìm value: key chứa bất kỳ needle (đã lower)."""
    needles_l = tuple(n.lower() for n in needles if n)
    for m in maps:
        for key, val in m.items():
            kl = key.lower()
            if any(n in kl for n in needles_l):
                if val:
                    return val
    return None


def _extract_salary_raw_unified(
    soup: BeautifulSoup,
    sections: dict[str, str],
    basic: dict[str, str],
    general: dict[str, str],
    strong_map: dict[str, str],
) -> str | None:
    v = _pick_from_label_maps([sections, basic, general], "mức lương", "muc luong")
    if v:
        return v
    for k, val in strong_map.items():
        if "thu nhập" in k or "thu nhap" in k:
            if val:
                return val
    return None


def _extract_company_name_unified(soup: BeautifulSoup) -> str | None:
    a = soup.select_one(".job-detail__company--link a[title]")
    if a:
        t = a.get("title")
        if isinstance(t, str) and t.strip():
            return t.strip()
    a2 = soup.select_one(".job-detail__company--link a")
    if a2:
        t2 = _normalize_text(a2.get_text())
        if t2:
            return t2
    h1_brand = soup.select_one("h1.company-content__title--name")
    if h1_brand:
        t3 = _normalize_text(h1_brand.get_text())
        if t3:
            return t3
    foot = soup.select_one(".footer-info-company-name, .footer-info-content.footer-info-company-name")
    if foot:
        t4 = _normalize_text(foot.get_text())
        if t4:
            return t4
    return None


def _extract_company_size_unified(soup: BeautifulSoup) -> str | None:
    """Job thường + pro (value-block / box-information)."""
    for item in soup.select(".job-detail__company--information-item"):
        title_el = item.select_one(".company-title")
        val_el = item.select_one(".company-value")
        if not title_el or not val_el:
            continue
        title = _normalize_text(title_el.get_text()).lower()
        if "quy mô" in title or "quy mo" in title:
            return _normalize_text(val_el.get_text()) or None
    for cv in soup.select(".company-value"):
        t = _normalize_text(cv.get_text())
        if "nhân viên" in t.lower() or re.search(r"\d+\s*-\s*\d+", t):
            return t
    for tb in soup.select("div.title-block"):
        if "quy mô" not in _normalize_text(tb.get_text()).lower():
            continue
        parent = tb.parent
        if isinstance(parent, Tag):
            vb = parent.select_one(".value-block")
            if vb:
                s = _normalize_text(vb.get_text())
                if s:
                    return s
    cap = soup.select_one(".box-information__caption")
    if cap:
        lab = cap.select_one(".box-information__label")
        if lab and "quy mô" in _normalize_text(lab.get_text()).lower():
            tot = cap.select_one(".box-information__total")
            if tot:
                s2 = _normalize_text(tot.get_text())
                if s2:
                    return s2
    return None


def _extract_industry_unified(soup: BeautifulSoup) -> str | None:
    for item in soup.select(".job-detail__company--information-item.company-field"):
        val_el = item.select_one(".company-value")
        if val_el:
            return _normalize_text(val_el.get_text()) or None
    for item in soup.select(".job-detail__company--information-item"):
        title_el = item.select_one(".company-title")
        val_el = item.select_one(".company-value")
        if not title_el or not val_el:
            continue
        title = _normalize_text(title_el.get_text()).lower()
        if "lĩnh vực" in title or "linh vuc" in title:
            return _normalize_text(val_el.get_text()) or None
    return None


def _find_content_block(soup: BeautifulSoup, *labels: str) -> Tag | None:
    """Job thường (h3 + job-description__item) | premium (h2 + box) | box-info (h2.title)."""
    labels_l = tuple(_normalize_text(x).lower() for x in labels if x)
    for h3 in soup.find_all("h3"):
        ht = _normalize_text(h3.get_text()).lower()
        if any(l in ht for l in labels_l):
            parent = h3.find_parent("div", class_=re.compile(r"job-description__item"))
            if parent:
                return parent
    for h2 in soup.select("h2.premium-job-description__box--title"):
        ht = _normalize_text(h2.get_text()).lower()
        if any(l in ht for l in labels_l):
            parent = h2.find_parent("div", class_=re.compile(r"premium-job-description__box"))
            if parent:
                return parent
    for box in soup.select("div.box-info"):
        h2 = box.select_one("h2.title")
        if not h2:
            continue
        ht = _normalize_text(h2.get_text()).lower()
        if any(l in ht for l in labels_l):
            return box
    return None


def _collect_li_or_p(content: Tag) -> list[str]:
    items: list[str] = []
    for li in content.find_all("li"):
        t = _normalize_text(li.get_text())
        if t:
            items.append(t)
    if items:
        return items
    for p in content.find_all("p"):
        t = _normalize_text(p.get_text())
        if t:
            items.append(t)
    return items


def _lines_from_flexible_block(container: Tag | None) -> list[str]:
    if not container:
        return []
    for sel in (
        ".job-description__item--content",
        ".premium-job-description__box--content",
        ".content-tab",
    ):
        el = container.select_one(sel)
        if el:
            return _collect_li_or_p(el)
    return _collect_li_or_p(container)


def _extract_information_detail_description(soup: BeautifulSoup) -> str:
    """
    Toàn bộ nội dung mô tả trong #box-job-information-detail
    (ưu tiên .job-description bên trong .job-detail__information-detail--content).
    """
    box = soup.select_one("#box-job-information-detail") or soup.select_one(
        "div.job-detail__information-detail"
    )
    if not box:
        return ""
    content = box.select_one(".job-detail__information-detail--content") or box
    target = content.select_one(".job-description") or content
    clone = BeautifulSoup(str(target), get_bs4_parser())
    for tag in clone.find_all(["script", "style", "button"]):
        tag.decompose()
    parts: list[str] = []
    for item in clone.select(".job-description__item"):
        title_el = item.find("h3")
        body_el = item.select_one(".job-description__item--content")
        if title_el and body_el:
            title = _normalize_text(title_el.get_text())
            body = _normalize_text(body_el.get_text(" ", strip=True))
            if title and body:
                parts.append(f"{title}\n{body}")
                continue
        t = _normalize_text(item.get_text(" ", strip=True))
        if t:
            parts.append(t)
    if parts:
        return "\n\n".join(parts)
    return _normalize_text(clone.get_text("\n", strip=True))


def _extract_description_lines(soup: BeautifulSoup) -> list[str]:
    block = _find_content_block(soup, "mô tả công việc", "mo ta cong viec")
    return _lines_from_flexible_block(block)


def _extract_requirements_lines(soup: BeautifulSoup) -> list[str]:
    block = _find_content_block(soup, "yêu cầu ứng viên", "yeu cau ung vien")
    if block is None:
        for box in soup.select("div.box-info.job-detail-section.requirement"):
            block = box
            break
    if block is None:
        for box in soup.select("div.premium-job-description__box.job-detail-section.requirement"):
            block = box
            break
    return _lines_from_flexible_block(block)


def _extract_benefits_unified(soup: BeautifulSoup) -> list[str]:
    """Quyền lợi: job thường / premium / box-info benefit; cuối cùng tag trong nhóm Quyền lợi."""
    for labels in (
        ("quyền lợi được hưởng", "quyen loi duoc huong"),
        ("quyền lợi", "quyen loi"),
    ):
        block = _find_content_block(soup, *labels)
        if block:
            lines = _lines_from_flexible_block(block)
            if lines:
                return lines
    for box in soup.select("div.box-info.job-detail-section.benefit"):
        lines = _lines_from_flexible_block(box)
        if lines:
            return lines
    sec = _find_description_section(soup, "Quyền lợi")
    if sec:
        lines = _lines_from_job_description_block(sec)
        if lines:
            return lines
    for h3 in soup.find_all("h3"):
        ht = _normalize_text(h3.get_text()).lower()
        if "quyền lợi" not in ht and "quyen loi" not in ht:
            continue
        parent = h3.find_parent("div", class_=re.compile(r"job-description__item"))
        if parent:
            lines = _lines_from_job_description_block(parent)
            if lines:
                return lines
    out: list[str] = []
    for name in soup.select(".job-tags__group-name"):
        if "quyền lợi" not in _normalize_text(name.get_text()).lower():
            continue
        wrap = name.find_parent("div")
        if wrap:
            for a in wrap.select(".job-tags__group-list-tag a.item"):
                t = _normalize_text(a.get_text())
                if t:
                    out.append(t)
        break
    return out


def _extract_skills_unified(soup: BeautifulSoup) -> list[str]:
    """
    Job thường: .box-title 'Kỹ năng cần có' + .box-category-tag.
    Brand/pro: mỗi khối .premium-job-related-tags__section có h2 chứa 'Kỹ năng' — gồm
    'Kỹ năng cần có' và 'Kỹ năng nên có' (điểm cộng, ví dụ ecommerce); gom tất cả .tag-item.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(txt: str) -> None:
        t = _normalize_text(txt)
        if not t:
            return
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)

    for title_el in soup.select(".box-title"):
        t = _normalize_text(title_el.get_text()).lower()
        if "kỹ năng cần có" not in t and "ky nang can co" not in t:
            continue
        tags_el = title_el.find_next_sibling("div", class_=re.compile(r"box-category-tags"))
        if not tags_el:
            wrap = title_el.find_parent("div", class_=re.compile(r"box"))
            if wrap:
                tags_el = wrap.select_one(".box-category-tags")
        if tags_el:
            for sp in tags_el.select(".box-category-tag"):
                _add(sp.get_text())
            return out
        break

    for sec in soup.select("div.premium-job-related-tags__section"):
        h2 = sec.select_one("h2.premium-job-box__title")
        if not h2:
            continue
        ht = _normalize_text(h2.get_text()).lower()
        if "kỹ năng" not in ht and "ky nang" not in ht:
            continue
        for sp in sec.select(".tag-item"):
            _add(sp.get_text())
    return out


def _parse_deadline_div(soup: BeautifulSoup) -> datetime | None:
    el = soup.select_one(".job-detail__info--deadline-date")
    if not el:
        return None
    text = _normalize_text(el.get_text())
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d, 23, 59, 59, tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_iso_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_posted_date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return None


def _extract_locations_from_html(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Div có margin-bottom + <strong>Thành phố:</strong> địa chỉ chi tiết."""
    out: list[dict[str, str]] = []
    for div in soup.find_all("div", attrs={"style": True}):
        st = div.get("style", "")
        if "margin-bottom" not in st.lower():
            continue
        strong = div.find("strong")
        if not strong:
            continue
        city = _normalize_text(strong.get_text()).rstrip(":")
        full = _normalize_text(div.get_text(" ", strip=True))
        full = re.sub(r"^-\s*", "", full)
        prefix = f"{city}:"
        if full.lower().startswith(prefix.lower()):
            detail = full[len(prefix) :].strip()
        else:
            detail = full
        if city:
            out.append({"city": city, "detail": detail})
    return out


def _extract_box_general(soup: BeautifulSoup) -> dict[str, str]:
    """Học vấn, Cấp bậc, Hình thức làm việc, Số lượng tuyển."""
    out: dict[str, str] = {}
    for box in soup.select(".box-general-group-info"):
        t_el = box.select_one(".box-general-group-info-title")
        v_el = box.select_one(".box-general-group-info-value")
        if not t_el or not v_el:
            continue
        key = _normalize_text(t_el.get_text()).lower()
        val = _normalize_text(v_el.get_text())
        out[key] = val
    return out


def _find_description_section(soup: BeautifulSoup, label: str) -> Tag | None:
    label_l = label.lower().strip()
    for h3 in soup.find_all("h3"):
        if label_l in _normalize_text(h3.get_text()).lower():
            parent = h3.find_parent("div", class_=re.compile(r"job-description__item"))
            if parent:
                return parent
    return None


def _lines_from_job_description_block(container: Tag | None) -> list[str]:
    """
    Ưu tiên từng <li>; không có thì từng <p> (Quyền lợi thường là đoạn, không phải tag a rác).
    """
    if not container:
        return []
    content = container.select_one(".job-description__item--content")
    if not content:
        content = container
    items: list[str] = []
    for li in content.find_all("li"):
        t = _normalize_text(li.get_text())
        if t:
            items.append(t)
    if items:
        return items
    for p in content.find_all("p"):
        t = _normalize_text(p.get_text())
        if t:
            items.append(t)
    return items


def _canonical_url(soup: BeautifulSoup) -> str | None:
    link = soup.find("link", rel=lambda x: x and "canonical" in str(x).lower())
    if isinstance(link, Tag) and link.get("href"):
        return str(link["href"]).strip()
    return None


class TopcvParser(BaseParser):
    source = "topcv"

    _LIST_VIEC = re.compile(r"/viec-lam/", re.I)
    _LIST_BRAND = re.compile(r"/brand/[^/]+/tuyen-dung/", re.I)
    _ID_HTML = re.compile(r"/(\d{5,})\.html", re.I)
    _ID_J = re.compile(r"-j(\d+)\.html", re.I)
    _ID_P = re.compile(r"-p(\d+)\.html", re.I)

    def parse_list(self, html: str, list_page_url: str) -> List[ListItem]:
        soup = BeautifulSoup(html, get_bs4_parser())
        base = f"{urlparse(list_page_url).scheme}://{urlparse(list_page_url).netloc}"
        seen: set[str] = set()
        out: List[ListItem] = []

        def push(href: str) -> None:
            full = urljoin(base, href).split("?")[0].split("#")[0]
            jid: str | None = None
            jm = self._ID_J.search(full)
            if jm:
                jid = jm.group(1)
            if not jid:
                hm = self._ID_HTML.search(full)
                if hm:
                    jid = hm.group(1)
            if not jid:
                pm = self._ID_P.search(full)
                if pm:
                    jid = pm.group(1)
            if not jid or jid in seen:
                return
            if not (self._LIST_VIEC.search(full) or self._LIST_BRAND.search(full)):
                return
            seen.add(jid)
            out.append({"job_id": jid, "url": full})

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not (self._LIST_VIEC.search(href) or self._LIST_BRAND.search(href)):
                continue
            push(href)

        if not out:
            for m in re.finditer(
                r"https?://www\.topcv\.vn/(?:viec-lam/[^\"'\\\s]+|brand/[^\"'\\\s]+/tuyen-dung/[^\"'\\\s]+)",
                html,
                re.I,
            ):
                push(m.group(0).rstrip(".,)"))

        return out

    def parse_detail(self, html: str, url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, get_bs4_parser())
        meta_js = _extract_window_topcv_job(html)
        jld = _extract_jsonld_jobposting(html)
        sections = _extract_labeled_info_sections(soup)
        basic_map = _extract_basic_information_map(soup)
        general_map = _extract_general_information_map(soup)
        strong_map = _extract_strong_span_map(soup)
        all_maps = [sections, basic_map, general_map, strong_map]

        salary_raw = _extract_salary_raw_unified(soup, sections, basic_map, general_map, strong_map)

        experience = _pick_from_label_maps(all_maps, "kinh nghiệm", "kinh nghiem")

        title = meta_js.get("title")
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = _normalize_text(h1.get_text())

        canonical = _canonical_url(soup)
        locations = _extract_locations_from_html(soup)
        company = _extract_company_name_unified(soup)
        company_size = _extract_company_size_unified(soup)
        industry_html = _extract_industry_unified(soup)
        industry = industry_html if industry_html else jld.get("industry")

        box = _extract_box_general(soup)
        education = _pick_from_label_maps(all_maps, "học vấn", "hoc van") or (
            box.get("học vấn") or box.get("hoc van")
        )
        position_level = _pick_from_label_maps(all_maps, "cấp bậc", "cap bac") or (
            box.get("cấp bậc") or box.get("cap bac")
        )
        employment_type = _pick_from_label_maps(all_maps, "hình thức làm việc", "hinh thuc lam viec") or (
            box.get("hình thức làm việc") or box.get("hinh thuc lam viec")
        )
        headcount = _pick_from_label_maps(all_maps, "số lượng tuyển", "so luong tuyen") or (
            box.get("số lượng tuyển") or box.get("so luong tuyen")
        )

        description_items = _extract_description_lines(soup)
        information_detail = _extract_information_detail_description(soup)
        requirements_items = _extract_requirements_lines(soup)
        benefits_items = _extract_benefits_unified(soup)
        skills = _extract_skills_unified(soup)

        posted = _parse_posted_date(jld.get("posted_date"))
        deadline_at = _parse_deadline_div(soup)
        if deadline_at is None:
            deadline_at = _parse_iso_datetime(jld.get("deadline_at"))

        smin = jld.get("salary_min")
        smax = jld.get("salary_max")

        return {
            "canonical_url": canonical,
            "source_job_id": meta_js.get("source_job_id"),
            "link_type": meta_js.get("link_type"),
            "title": title,
            "salary_raw": salary_raw,
            "salary_min": smin,
            "salary_max": smax,
            "salary_currency": jld.get("salary_currency"),
            "locations": locations,
            "experience": experience,
            "posted_date": posted,
            "deadline_at": deadline_at,
            "company": company,
            "company_size": company_size,
            "industry": industry,
            "education": education,
            "position_level": position_level,
            "employment_type": employment_type,
            "headcount": headcount,
            "description_items": description_items,
            "information_detail": information_detail or None,
            "requirements_items": requirements_items,
            "benefits_items": benefits_items,
            "skills": skills,
        }
