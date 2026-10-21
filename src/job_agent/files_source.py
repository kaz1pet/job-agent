"""Источник вакансий из папки: каждый .txt или .md файл — одна вакансия.

Удобно, когда вакансии с сайта нельзя получить по API: копируете текст
понравившихся вакансий в файлы, а агент их оценивает и пишет письма.

Формат файла свободный. Агент понимает:
- первая непустая строка — название вакансии;
- строка «Компания: ...» — работодатель;
- строка «Зарплата: ...» — зарплата;
- первая ссылка http(s)://... — адрес вакансии.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Vacancy, VacancyDetails

ID_PREFIX = "file-"
_URL_RE = re.compile(r"https?://\S+")
_FIELD_RE = {
    "employer": re.compile(r"^\s*(компания|работодатель|company)\s*[:—-]\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    "salary": re.compile(r"^\s*(зарплата|доход|salary)\s*[:—-]\s*(.+)$", re.IGNORECASE | re.MULTILINE),
}


def _slug(path: Path) -> str:
    return ID_PREFIX + re.sub(r"[^\w-]+", "-", path.stem.lower()).strip("-")


def parse_vacancy_file(path: Path, max_chars: int = 3500) -> VacancyDetails:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = lines[0].lstrip("#").strip() if lines else path.stem

    def field(key: str) -> str:
        match = _FIELD_RE[key].search(text)
        return match.group(2).strip() if match else ""

    url_match = _URL_RE.search(text)
    description = text if len(text) <= max_chars else text[:max_chars].rstrip() + " …"
    return VacancyDetails(
        id=_slug(path),
        name=name,
        employer=field("employer") or "не указана",
        area="",
        salary=field("salary") or "не указана",
        url=url_match.group(0) if url_match else str(path),
        published_at="",
        requirement=description[:300],
        description=description,
    )


class FilesSource:
    name = "files"
    description = "папка с вакансиями, которые кандидат сохранил сам"

    def __init__(self, directory: str | Path = "vacancies"):
        self.directory = Path(directory)
        self._cache: dict[str, VacancyDetails] = {}

    def _load(self) -> list[VacancyDetails]:
        if not self.directory.is_dir():
            raise ValueError(f"Папка с вакансиями не найдена: {self.directory}")
        files = sorted(
            p for p in self.directory.iterdir() if p.suffix.lower() in {".txt", ".md"} and p.is_file()
        )
        vacancies = [parse_vacancy_file(p) for p in files]
        self._cache = {v.id: v for v in vacancies}
        return vacancies

    def search(
        self,
        text: str = "",
        experience: str | None = None,
        schedule: str | None = None,
        area: str | None = None,
        page: int = 0,
        limit: int = 20,
    ) -> list[Vacancy]:
        """Возвращает все сохранённые вакансии: их отобрал сам кандидат."""
        vacancies = self._load()
        start = max(0, page) * limit
        return list(vacancies[start : start + limit])

    def get(self, vacancy_id: str) -> VacancyDetails:
        if not self._cache:
            self._load()
        details = self._cache.get(str(vacancy_id))
        if details is None:
            raise ValueError(f"Нет вакансии с id {vacancy_id}")
        return details
