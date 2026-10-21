"""Источники вакансий: общий интерфейс и выбор источника по названию.

Агенту всё равно, откуда берутся вакансии: любой источник умеет
search(...) и get(id). Это позволило пережить закрытие публичного API
hh.ru — достаточно было добавить новые источники, не трогая агента.
"""

from __future__ import annotations

from typing import Protocol

from .config import Settings
from .files_source import FilesSource
from .hh_client import HHClient
from .models import Vacancy, VacancyDetails
from .trudvsem import TrudvsemClient

SOURCE_NAMES = ("trudvsem", "files", "hh")


class VacancySource(Protocol):
    name: str
    description: str

    def search(
        self,
        text: str,
        experience: str | None = None,
        schedule: str | None = None,
        area: str | None = None,
        page: int = 0,
    ) -> list[Vacancy]: ...

    def get(self, vacancy_id: str) -> VacancyDetails: ...


def make_source(name: str, settings: Settings) -> VacancySource:
    if name == "trudvsem":
        return TrudvsemClient(region_code=settings.trudvsem_region)
    if name == "files":
        return FilesSource(settings.vacancies_dir)
    if name == "hh":
        if not settings.hh_app_token:
            raise ValueError(
                "hh.ru с апреля 2026 года не отдаёт вакансии без авторизации. "
                "Укажите HH_APP_TOKEN (https://dev.hh.ru) или выберите --source trudvsem / files."
            )
        return HHClient(settings.hh_user_agent, settings.hh_app_token)
    raise ValueError(f"Неизвестный источник '{name}'. Доступны: {', '.join(SOURCE_NAMES)}")
