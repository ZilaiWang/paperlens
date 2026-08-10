"""Configuration with conservative defaults and no embedded secrets."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = ""
    openai_base_url: str = "http://127.0.0.1:1234/v1"
    paperlens_model: str = "qwen2.5-7b-instruct"
    paperlens_temperature: float = Field(default=0.1, ge=0, le=1)
    paperlens_max_output_tokens: int = Field(default=1800, ge=128, le=8192)
    paperlens_disable_thinking: bool = False
    paperlens_data_dir: Path = Path(".paperlens")
    paperlens_max_pdf_mb: int = Field(default=80, ge=1, le=500)
    paperlens_top_k: int = Field(default=8, ge=1, le=30)
    # V4.0-4：PDF 解析后端。
    # hybrid = PyMuPDF 几何提取优先，失败自动回退 pdfplumber；
    # pymupdf / pdfplumber = 强制指定。GROBID/Docling 属 V4.2 规划。
    paperlens_pdf_parser: str = "hybrid"

    contact_email: str = ""

    @property
    def database_path(self) -> Path:
        return self.paperlens_data_dir / "paperlens.db"

    @property
    def uploads_dir(self) -> Path:
        return self.paperlens_data_dir / "uploads"

    @property
    def llm_configured(self) -> bool:
        # Local OpenAI-compatible servers commonly accept any non-empty placeholder key.
        return bool(self.openai_api_key or self.openai_base_url.startswith("http://127.0.0.1"))

    def ensure_dirs(self) -> None:
        self.paperlens_data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
