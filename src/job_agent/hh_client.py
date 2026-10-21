"""Клиент API hh.ru.

Важно: с апреля 2026 года hh.ru закрыл поиск вакансий для запросов без
авторизации (ответ 403 forbidden). Источник работает только с токеном
приложения (HH_APP_TOKEN), который выдаётся на https://dev.hh.ru.

Документация: https://api.hh.ru/openapi/redoc
"""

from __future__ import annotations

from urllib.parse import urlencode

from .models import Vacancy, VacancyDetails
from .net import Transport, urllib_transport

EXPERIENCE_VALUES = ("noExperience", "between1And3", "between3And6", "moreThan6")
SCHEDULE_VALUES = ("fullDay", "shift", "flexible", "remote", "flyInFlyOut")


class HHClient:
    BASE_URL = "https://api.hh.ru"

    def __init__(
        self,
        user_agent: str,
        app_token: str | None = None,
        transport: Transport = urllib_transport,
        timeout: float = 20,
    ):
        self.headers = {"HH-User-Agent": user_agent, "User-Agent": user_agent}
        if app_token:
            self.headers["Authorization"] = f"Bearer {app_token}"
        self.transport = transport
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        url = f"{self.BASE_URL}{path}"
        if query:
            url += "?" + urlencode(query)
        return self.transport("GET", url, self.headers, None, self.timeout)

    def search_vacancies(
        self,
        text: str,
        area: str | None = None,
        experience: str | None = None,
        schedule: str | None = None,
        salary: int | None = None,
        period_days: int | None = 14,
        per_page: int = 20,
        page: int = 0,
    ) -> list[Vacancy]:
        if not text.strip():
            raise ValueError("поисковый запрос не может быть пустым")
        if experience and experience not in EXPERIENCE_VALUES:
            raise ValueError(f"experience должен быть одним из {EXPERIENCE_VALUES}")
        if schedule and schedule not in SCHEDULE_VALUES:
            raise ValueError(f"schedule должен быть одним из {SCHEDULE_VALUES}")
        data = self._get(
            "/vacancies",
            {
                "text": text,
                "area": area,
                "experience": experience,
                "schedule": schedule,
                "salary": salary,
                "period": period_days,
                "per_page": max(1, min(per_page, 100)),
                "page": max(0, page),
                "order_by": "publication_time",
            },
        )
        return [Vacancy.from_api(item) for item in data.get("items", [])]

    def get_vacancy(self, vacancy_id: str) -> VacancyDetails:
        if not str(vacancy_id).isdigit():
            raise ValueError("id вакансии должен состоять из цифр")
        return VacancyDetails.from_api(self._get(f"/vacancies/{vacancy_id}"))

    # --- общий интерфейс источника вакансий (см. sources.py) ---------------
    name = "hh"
    description = "hh.ru"

    def search(
        self,
        text: str,
        experience: str | None = None,
        schedule: str | None = None,
        area: str | None = None,
        page: int = 0,
    ) -> list[Vacancy]:
        return self.search_vacancies(text, area=area, experience=experience, schedule=schedule, page=page)

    def get(self, vacancy_id: str) -> VacancyDetails:
        return self.get_vacancy(vacancy_id)
