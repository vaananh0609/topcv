# TopCV Crawler

Crawl tin IT từ TopCV (list + chi tiết) và lưu MongoDB.

## Chạy bằng GitHub Actions (khuyên dùng: self-hosted runner)

IP server GitHub (`ubuntu-latest`) thường bị TopCV chặn. Workflow dùng **runner trên laptop Windows** của bạn — vẫn bấm Run trên tab Actions, nhưng job chạy bằng mạng nhà (không cần proxy).

### Bước 1: Cài runner trên laptop (một lần)

1. Repo → **Settings** → **Actions** → **Runners** → **New self-hosted runner**
2. Chọn **Windows** → **x64**
3. Tạo thư mục, ví dụ `C:\actions-runner`, chạy lần lượt lệnh GitHub hiển thị:

```powershell
mkdir C:\actions-runner
cd C:\actions-runner
# tải + giải nén theo hướng dẫn trên GitHub
.\config.cmd --url https://github.com/vaananh0609/topcv --token <TOKEN>
.\run.cmd
```

4. Giữ cửa sổ `.\run.cmd` **mở** khi muốn crawl (hoặc cài runner dạng Windows Service — xem docs GitHub).

Trên trang Runners phải thấy trạng thái **Idle** (màu xanh).

### Bước 2: Secrets

**Settings → Secrets and variables → Actions**:

| Secret | Bắt buộc |
|--------|----------|
| `MONGODB_URI` | Có |
| `MONGODB_DB` | Có |
| `TOPCV_PROXY_URL` | Không (chỉ khi vẫn bị block) |

**MongoDB Atlas:** Network Access → `0.0.0.0/0` (hoặc IP mạng nhà bạn).

### Bước 3: Chạy workflow

**Actions** → **TopCV Crawl** → **Run workflow**

| Ô | Gợi ý test | Crawl đầy đủ |
|---|------------|----------------|
| max_pages | `1` | `0` |
| limit_jobs | `5` | `0` |
| no_detail | bỏ tick | bỏ tick |

Lệnh thực tế: `python topcv-new.py --max-pages 0 --limit-jobs 0`

## Chạy local (không qua Actions)

```powershell
pip install -r requirements.txt
python -m playwright install chromium

# .env: MONGODB_URI, MONGODB_DB
python topcv-new.py --max-pages 1 --limit-jobs 5
```

## Lưu ý

- ~50 job/trang list; crawl detail ~15–20 giây/job.
- Laptop + runner phải bật khi chạy theo lịch (cron ~01:00 VN).
