"""Cấu hình tập trung: delay, user-agent, retry, URL nguồn."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "salary_crawler"
    mongodb_max_pool_size: int = Field(
        10,
        description="MongoClient singleton — maxPoolSize (Atlas / pool chung cho mọi task).",
    )
    mongodb_server_selection_timeout_ms: int = Field(
        30_000,
        description="Timeout chọn server Mongo (Atlas).",
    )

    usd_to_vnd_rate: float = Field(
        25_400.0,
        description="Tỷ giá USD→VND khi chuẩn hóa lương về VNĐ (Mincer / hồi quy).",
    )

    redis_url: str = "redis://localhost:6379/0"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "salary_db"
    postgres_user: str = "admin"
    postgres_password: str = "admin123"

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_timezone: str = Field(
        "Asia/Ho_Chi_Minh",
        description="Múi giờ dùng cho Celery Beat (crontab, v.v.).",
    )

    delay_topcv_min: float = Field(5.0, description="Giây — chống block TopCV")
    delay_topcv_max: float = 10.0
    delay_default_min: float = 2.0
    delay_default_max: float = 5.0

    http_proxy: str = ""
    https_proxy: str = ""
    proxy_list_file: str = Field(
        "",
        description="File proxy Webshare: mỗi dòng host:port:user:pass (ưu tiên hơn HTTP_PROXY)",
    )

    topcv_list_url: str = (
        "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
        "?sort=new&type_keyword=1&category_family=r257&saturday_status=0"
    )

    joboko_list_url: str = Field(
        "https://vn.joboko.com/jobs?ind=30&pr=1",
        description="URL danh sách JobOKO (phân trang thêm &p=N).",
    )
    joboko_list_url_matrix: str = Field(
        "",
        description=(
            "Danh sach seed URL JobOKO, cach nhau dau phay/; hoac xuong dong. "
            "Moi seed co the la URL day du hoac query fragment (vd: ind=30&pr=1&sal=10-15)."
        ),
    )
    joboko_matrix_spec: str = Field(
        "",
        description=(
            "Alias cu cho ma tran JobOKO (JOBOKO_MATRIX_SPEC), giu de tuong thich nguoc."
        ),
    )
    delay_joboko_min: float = Field(1.5, description="Giây — delay JobOKO (httpx).")
    delay_joboko_max: float = Field(3.5)
    joboko_http_timeout_sec: float = Field(
        45.0,
        description="Timeout (giây) cho một lần GET JobOKO bằng httpx.",
    )
    joboko_list_expand_sal_exp: bool = Field(
        True,
        description=(
            "Neu bat: moi seed JobOKO (JOBOKO_LIST_URL / matrix) nhan Cartesian product "
            "sal=[0-10..30-0,x] va exp=[1,3,5,6,100] trong query string."
        ),
    )

    enabled_crawl_sources: str = Field(
        "topcv",
        description="Nguồn quét list (topcv, joboko), cách nhau bằng dấu phẩy. VnWorks dùng scripts/crawl_vnworks_to_mongo.py.",
    )

    playwright_headless: bool = True
    playwright_timeout_ms: int = 60_000

    topcv_use_curl_cffi_first: bool = Field(
        True,
        description="TopCV: ưu tiên curl_cffi (TLS fingerprint giống Chrome) trước Playwright.",
    )
    topcv_curl_cffi_impersonate: str = Field(
        "chrome120",
        description="Profile TLS/browser dùng cho curl_cffi impersonate.",
    )
    topcv_curl_cffi_timeout_sec: int = Field(
        30,
        description="Timeout (giây) cho một lần GET TopCV bằng curl_cffi.",
    )

    crawl_max_retries: int = 3
    crawl_retry_backoff_sec: float = 2.0

    detail_ingest_write_mongo: bool = Field(
        True,
        description="Sau khi tai HTML: parse va ghi MongoDB — site TopCV -> collection topcv, JobOKO -> joboko.",
    )

    crawl_log_dir: str = Field(
        "logs",
        description="Thu muc ghi log thu thap (ten file: web_ngay_thang_nam_gio.log).",
    )

    cors_extra_origins: str = Field(
        "",
        description="Danh sách origin CORS thêm (cách nhau bởi dấu phẩy), VD: http://DESKTOP-ABC:5173",
    )

    admin_dashboard_live: bool = Field(
        True,
        description="/api/admin/dashboard: true = Mongo + artifacts; false = chỉ mock.",
    )
    admin_flower_url: str = Field("", description="URL Flower (quick link trên admin dashboard).")
    admin_pgadmin_url: str = Field("", description="URL pgAdmin.")
    admin_logs_url: str = Field("", description="URL xem log Celery / aggregator (tùy infra).")

    lasso_bundle_path: str = Field(
        "artifacts/mo_hinh_lasso.joblib",
        description="Bundle Lasso huấn luyện (joblib) — dùng cho POST /api/salary/predict.",
    )
    salary_predict_n_bootstrap: int = Field(
        400,
        ge=50,
        le=2000,
        description="Số mẫu bootstrap mỗi lần gọi API dự báo (cân nhắc latency).",
    )

    user_agents: list[str] = Field(
        default_factory=lambda: [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
