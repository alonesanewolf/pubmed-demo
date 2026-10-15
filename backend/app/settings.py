"""应用配置。

设计原则：所有敏感信息（NCBI Key、DeepSeek Key）只从环境变量读取，
任何模块都不得把 key 拼进任何会返回给前端的字符串里。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/settings.py -> backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "pubmed-domain-analytics"
    version: str = "1.0.0"
    debug: bool = False

    # ---------- 数据源 ----------
    data_mode: str = "local"  # local | remote | hybrid

    # ---------- NCBI ----------
    ncbi_api_key: str = ""
    ncbi_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    ncbi_tool: str = "pubmed-domain-analytics"
    ncbi_email: str = ""
    ncbi_timeout: int = 30
    ncbi_min_interval: float = 0.12

    # ---------- 检索参数 ----------
    default_fetch_count: int = 1000
    max_fetch_count: int = 5000
    top_n_papers: int = 100
    recent_years: int = 5

    # ---------- LLM ----------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout: int = 90
    llm_max_retries: int = 2

    # ---------- 服务 ----------
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "*"

    # ---------- 路径 ----------
    presets_dir: Path = BACKEND_ROOT / "data" / "presets"
    journals_file: Path = BACKEND_ROOT / "data" / "journals.json"
    cache_db: Path = BACKEND_ROOT / "data" / "cache" / "app.db"

    # ---------- 派生属性 ----------
    @property
    def has_ncbi_key(self) -> bool:
        return bool(self.ncbi_api_key.strip())

    @property
    def has_llm_key(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def llm_provider_name(self) -> str:
        return "deepseek"

    @property
    def remote_enabled(self) -> bool:
        """remote/hybrid 模式下是否真的允许发起外网请求。"""
        return self.data_mode in ("remote", "hybrid")

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [x.strip() for x in raw.split(",") if x.strip()]

    def ensure_dirs(self) -> None:
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        self.cache_db.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
