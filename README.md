# TopCV Crawler

Crawl tin IT từ TopCV (list + chi tiết) và lưu MongoDB.

## GitHub Secrets

Vào **Settings → Secrets and variables → Actions**, thêm:

| Secret | Mô tả |
|--------|--------|
| `MONGODB_URI` | Connection string MongoDB (Atlas) |
| `MONGODB_DB` | Tên database (vd. `salary_crawler`) |

**MongoDB Atlas:** Network Access → Allow access from anywhere (`0.0.0.0/0`) hoặc dùng IP cố định nếu có self-hosted runner.

## Chạy trên GitHub Actions

1. Tab **Actions** → workflow **TopCV Crawl** → **Run workflow**
2. Tuỳ chọn `max_pages`, `limit_jobs`, `no_detail`

Chạy theo lịch: mỗi ngày ~01:00 (giờ VN).

## Chạy local

```bash
pip install -r requirements.txt
python -m playwright install chromium

# Tạo file .env
# MONGODB_URI=mongodb+srv://...
# MONGODB_DB=salary_crawler

python topcv-new.py --max-pages 1 --limit-jobs 3
```

## Lưu ý tốc độ / block

- Mỗi trang list ~50 job.
- Crawl detail: ~15–20 giây/job (delay chống block).
- Có thể chỉnh env: `DELAY_TOPCV_MIN`, `DELAY_TOPCV_MAX`, `TOPCV_USE_CURL_CFFI_FIRST=true`.
