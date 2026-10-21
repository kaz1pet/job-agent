"""Настройки агента: читаются из переменных окружения и файла .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Минимальный парсер .env: строки вида KEY=VALUE, # — комментарий.

    Уже заданные переменные окружения не перезаписываются.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    # LLM: любой сервер с OpenAI-совместимым API (Ollama, OpenAI, OpenRouter и др.)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3.5:4b"

    # Источник вакансий: trudvsem (Работа России, без ключа), files (папка), hh (нужен токен)
    vacancy_source: str = "trudvsem"
    vacancies_dir: str = "vacancies"
    trudvsem_region: str | None = None  # код региона, например 7700000000000 — Москва

    # hh.ru: с апреля 2026 поиск вакансий требует токен приложения
    hh_user_agent: str = "job-agent/0.1 (github.com/your-name/job-agent)"
    hh_app_token: str | None = None
    hh_area: str | None = "113"  # 113 — вся Россия, 1 — Москва, 2 — Санкт-Петербург

    # Telegram (необязательно)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    db_path: str = "data/job_agent.sqlite3"
    max_steps: int = 25

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        defaults = cls()

        def get(name: str, default):
            value = os.environ.get(name)
            return value if value not in (None, "") else default

        return cls(
            llm_base_url=get("LLM_BASE_URL", defaults.llm_base_url).rstrip("/"),
            llm_api_key=get("LLM_API_KEY", defaults.llm_api_key),
            llm_model=get("LLM_MODEL", defaults.llm_model),
            vacancy_source=get("VACANCY_SOURCE", defaults.vacancy_source),
            vacancies_dir=get("VACANCIES_DIR", defaults.vacancies_dir),
            trudvsem_region=get("TRUDVSEM_REGION", None),
            hh_user_agent=get("HH_USER_AGENT", defaults.hh_user_agent),
            hh_app_token=get("HH_APP_TOKEN", None),
            hh_area=get("HH_AREA", defaults.hh_area),
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN", None),
            telegram_chat_id=get("TELEGRAM_CHAT_ID", None),
            db_path=get("DB_PATH", defaults.db_path),
            max_steps=int(get("MAX_STEPS", defaults.max_steps)),
        )

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)
