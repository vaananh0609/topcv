#!/usr/bin/env python3
"""
TopCV crawler: list + chi tiết job.

Trang list: job_id, title, child_name, url
Trang chi tiết: salary, city, exp, education, company_name, company_size, description

Chạy local:
    python topcv-new.py

Chạy thử (1 trang, 3 job):
    python topcv-new.py --max-pages 1 --limit-jobs 3

Chỉ list (nhanh, không vào trang chi tiết):
    python topcv-new.py --no-detail
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.parsers.topcv_parser import TopcvParser, topcv_list_html_seems_blocked_or_empty  # noqa: E402
from src.spiders.topcv_spider import TopcvSpider  # noqa: E402
from src.utils.bs4_parser import get_bs4_parser  # noqa: E402


SOURCE_URL = (
    "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
    "?type_keyword=1&sba=1&category_family=r257&saturday_status=0"
)
COLLECTION_NAME = "topcv-new"
DEFAULT_MAX_PAGES = 0  # 0 = chạy tới khi không còn trang mới

CHILD_NAMES = [
    "Software Engineer",
    "Backend Developer",
    "Frontend Developer",
    "Mobile Developer",
    "Fullstack Developer",
    "Blockchain Engineer",
    "Software Tester (Automation & Manual)",
    "Automation Tester",
    "Manual Tester",
    "Game Tester",
    "QA Engineer",
    "Process Quality Assurance (PQA)",
    "AI Engineer",
    "AI Researcher",
    "Data Labeling (Gán nhãn dữ liệu)",
    "Data Analyst",
    "Data Engineer",
    "Data Scientist",
    "IT Helpdesk/IT support",
    "DevOps Engineer",
    "Network Engineer",
    "System Engineer",
    "System Administrator",
    "Database Administrator (DBA)",
    "Cloud Engineer",
    "Kỹ thuật IT",
    "Chuyên viên Cyber Security",
    "Chuyên viên IT Security",
    "Chiến lược và phân tích bảo mật",
    "Quản trị và vận hành bảo mật",
    "Tuân thủ và kiểm toán bảo mật",
    "Phòng chống lừa đảo và an ninh mạng",
    "Bảo mật ứng dụng và phát triển",
    "Mã hóa và bảo mật dữ liệu",
    "Kiểm thử và đánh giá bảo mật",
    "Kỹ sư IoT (IoT Engineer)",
    "Embedded Engineer/Lập trình nhúng",
    "IT Project Manager",
    "Scrum Master",
    "Kỹ sư cầu nối BrSE",
    "IT Comtor",
    "Software Architect",
    "System Architect",
    "Solution Architect",
    "Technical Leader",
    "Technical Manager",
    "Head of Engineering",
    "Technical Director",
    "Chief Technology Officer (CTO)",
    "Chief Information Officer (CIO)",
    "UI/UX Design",
    "Thiết kế đồ họa (Graphic Design)",
    "Illustration",
    "Animation Design",
    "Interaction Designer",
    "3D Modeler",
    "Product Owner/Product Manager",
    "Business Analyst (Phân tích nghiệp vụ)",
    "Product Analyst/Research",
    "Game Developer",
    "Concept Artist",
    "Game Design",
    "AR/VR Developer",
    "Vị trí Game Development khác",
    "Kinh doanh phần mềm",
    "Kinh doanh Domain/Hosting/Server",
    "Sales IT Phần mềm khác",
    "IT Consultant",
    "GIS Engineer",
    "Bán hàng kỹ thuật IT",
    "Chuyên môn Công nghệ thông tin khác",
]

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def page_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query))
    if page <= 1:
        query.pop("page", None)
    else:
        query["page"] = str(page)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment)
    )


def mongo_collection() -> Collection:
    load_dotenv(ROOT / ".env", override=False)
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("Missing MONGODB_URI in .env")

    db_name = os.getenv("MONGODB_DB", "salary_crawler")
    client = MongoClient(uri, serverSelectionTimeoutMS=30_000)
    client.admin.command("ping")

    collection = client[db_name][COLLECTION_NAME]
    collection.drop_indexes()
    collection.create_index([("job_id", ASCENDING)], unique=True)
    collection.create_index([("child_name", ASCENDING)])
    return collection


def child_aliases(name: str) -> list[str]:
    aliases = {name}
    no_parens = re.sub(r"\([^)]*\)", "", name).strip()
    if no_parens:
        aliases.add(no_parens)
    for part in re.split(r"[/|]", no_parens or name):
        part = part.strip()
        if len(part) >= 3:
            aliases.add(part)
    return sorted(aliases, key=len, reverse=True)


CHILD_ALIASES = sorted(
    [(alias.casefold(), name) for name in CHILD_NAMES for alias in child_aliases(name)],
    key=lambda x: len(x[0]),
    reverse=True,
)


def extract_child_name(card_text: str) -> str:
    text = clean_text(card_text).casefold()
    for alias, child_name in CHILD_ALIASES:
        if alias in text:
            return child_name
    return ""


def extract_job_id(url: str) -> str:
    for pattern in (r"-j(\d+)\.html", r"/(\d{5,})\.html", r"-p(\d+)\.html"):
        match = re.search(pattern, url, flags=re.I)
        if match:
            return match.group(1)
    return ""


def extract_title_and_url_from_card(card, base_url: str) -> tuple[str, str, str]:
    for anchor in card.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "/viec-lam/" not in href and "/brand/" not in href:
            continue

        full_url = urljoin(base_url, href).split("?")[0].split("#")[0]
        job_id = extract_job_id(full_url)
        title = clean_text(anchor.get_text(" ", strip=True))
        if job_id and title and title.lower() not in {"ứng tuyển", "xem chi tiết", "lưu tin"}:
            return job_id, title, full_url
    return "", "", ""


def parse_jobs_from_list(html: str, list_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, get_bs4_parser())
    base_url = f"{urlparse(list_url).scheme}://{urlparse(list_url).netloc}"
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for card in soup.select(".job-item-search-result"):
        job_id, title, url = extract_title_and_url_from_card(card, base_url)
        if not job_id or job_id in seen:
            continue

        rows.append(
            {
                "job_id": job_id,
                "title": title,
                "url": url,
                "child_name": extract_child_name(card.get_text(" ", strip=True)),
            }
        )
        seen.add(job_id)

    return rows


def cities_from_locations(locations: list[dict[str, str]] | None) -> str:
    if not locations:
        return ""
    seen: list[str] = []
    for loc in locations:
        city = clean_text(loc.get("city"))
        if city and city not in seen:
            seen.append(city)
    return ", ".join(seen)


def detail_to_flat_fields(parsed: dict[str, Any]) -> dict[str, str]:
    """Map output TopcvParser sang field ngắn gọn cho collection topcv-new."""
    out: dict[str, str] = {}
    salary = parsed.get("salary_raw")
    if salary:
        out["salary"] = str(salary)
    city = cities_from_locations(parsed.get("locations"))
    if city:
        out["city"] = city
    exp = parsed.get("experience")
    if exp:
        out["exp"] = str(exp)
    education = parsed.get("education")
    if education:
        out["education"] = str(education)
    company = parsed.get("company")
    if company:
        out["company_name"] = str(company)
    size = parsed.get("company_size")
    if size:
        out["company_size"] = str(size)
    desc = parsed.get("information_detail")
    if desc:
        out["description"] = str(desc)
    return out


def fetch_and_parse_detail(
    spider: TopcvSpider,
    parser: TopcvParser,
    url: str,
) -> dict[str, str] | None:
    if not url:
        return None
    html = spider.fetch_html(url)
    if len(html) < 5000 and "job-detail" not in html.lower():
        return None
    parsed = parser.parse_detail(html, url)
    return detail_to_flat_fields(parsed)


def upsert_job(collection: Collection, job: dict[str, str]) -> str:
    result = collection.update_one(
        {"job_id": job["job_id"]},
        {"$set": job},
        upsert=True,
    )
    if result.upserted_id:
        return "inserted"
    if result.modified_count:
        return "updated"
    return "unchanged"


def crawl(
    max_pages: int,
    start_page: int,
    limit_jobs: int,
    delay: float,
    fetch_detail: bool,
) -> None:
    collection = mongo_collection()
    spider = TopcvSpider()
    parser = TopcvParser()
    total_seen = 0
    total_written = 0
    total_errors = 0
    total_detail_ok = 0
    total_detail_fail = 0
    previous_ids: tuple[str, ...] | None = None
    t0 = time.perf_counter()

    page = start_page
    while max_pages <= 0 or page <= max_pages:
        url = page_url(SOURCE_URL, page)
        print(f"Trang {page}: {url}", flush=True)

        try:
            html = spider.fetch_html(url)
            if topcv_list_html_seems_blocked_or_empty(html):
                print("  HTML list bị block/rỗng, dừng crawl.", flush=True)
                total_errors += 1
                break
            jobs = parse_jobs_from_list(html, url)
        except Exception as exc:  # noqa: BLE001
            total_errors += 1
            print(f"  Lỗi list page={page}: {exc}", flush=True)
            break

        current_ids = tuple(sorted(job["job_id"] for job in jobs))
        if not jobs or current_ids == previous_ids:
            print("  Không còn job mới / trang bị lặp, dừng crawl.", flush=True)
            break
        previous_ids = current_ids

        print(f"  Tìm thấy {len(jobs)} job", flush=True)
        for job in jobs:
            if limit_jobs and total_seen >= limit_jobs:
                print_summary(
                    total_seen,
                    total_written,
                    total_errors,
                    total_detail_ok,
                    total_detail_fail,
                    fetch_detail,
                    t0,
                )
                return

            total_seen += 1
            record = dict(job)

            if fetch_detail and job.get("url"):
                try:
                    detail_fields = fetch_and_parse_detail(spider, parser, job["url"])
                    if detail_fields:
                        record.update(detail_fields)
                        total_detail_ok += 1
                    else:
                        total_detail_fail += 1
                        print(f"    DETAIL_FAIL {job['job_id']}: HTML/detail rỗng", flush=True)
                except Exception as exc:  # noqa: BLE001
                    total_detail_fail += 1
                    total_errors += 1
                    print(f"    DETAIL_ERR {job['job_id']}: {exc}", flush=True)

            status = upsert_job(collection, record)
            if status in {"inserted", "updated"}:
                total_written += 1

            extra = ""
            if fetch_detail:
                extra = (
                    f" | {record.get('salary', '-')}"
                    f" | {record.get('city', '-')}"
                    f" | {record.get('company_name', '-')}"
                )
            print(
                f"    {status.upper()} {job['job_id']}: {job['title']} | {job['child_name']}{extra}",
                flush=True,
            )

        time.sleep(delay)
        page += 1

    print_summary(
        total_seen,
        total_written,
        total_errors,
        total_detail_ok,
        total_detail_fail,
        fetch_detail,
        t0,
    )


def print_summary(
    total_seen: int,
    total_written: int,
    total_errors: int,
    total_detail_ok: int,
    total_detail_fail: int,
    fetch_detail: bool,
    t0: float,
) -> None:
    elapsed = time.perf_counter() - t0
    per_job = elapsed / total_seen if total_seen else 0.0
    detail_line = ""
    if fetch_detail:
        detail_line = f" detail_ok={total_detail_ok} detail_fail={total_detail_fail}"
    print(
        f"\nXong topcv-new: seen={total_seen} written={total_written} "
        f"errors={total_errors}{detail_line} "
        f"elapsed={elapsed:.1f}s (~{per_job:.1f}s/job) collection={COLLECTION_NAME}",
        flush=True,
    )
    if fetch_detail:
        print(
            "  Gợi ý tốc độ: bật TOPCV_USE_CURL_CFFI_FIRST=true và giảm DELAY_TOPCV_MIN/MAX trong .env",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TopCV: list + chi tiết (salary, city, exp, education, company, description)."
    )
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Giới hạn số trang. Mặc định 0 = chạy tới khi không còn trang mới.",
    )
    parser.add_argument("--limit-jobs", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.0, help="Nghỉ giữa các trang list (giây).")
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Chỉ crawl trang list (nhanh hơn nhiều).",
    )
    args = parser.parse_args()
    crawl(args.max_pages, args.start_page, args.limit_jobs, args.delay, not args.no_detail)


if __name__ == "__main__":
    main()
