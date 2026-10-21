"""Источник вакансий «Работа России» (trudvsem.ru): открытый API без ключа.

Документация открытых данных: https://trudvsem.ru/opendata/api
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from .models import Vacancy, VacancyDetails, format_salary, html_to_text
from .net import Transport, urllib_transport

ID_PREFIX = "tv-"


def _parse(item: dict) -> VacancyDetails:
    v = item.get("vacancy", item)
    requirement = v.get("requirement") or {}
    if not isinstance(requirement, dict):
        requirement = {"qualification": str(requirement)}

    experience_years = requirement.get("experience")
    experience = ""
    if isinstance(experience_years, (int, float)):
        years = int(experience_years)
        experience = "Без опыта" if years == 0 else f"от {years} {'года' if years == 1 else 'лет'}"

    salary = format_salary(
        {"from": v.get("salary_min") or None, "to": v.get("salary_max") or None, "currency": "RUR"}
    )
    if salary == "не указана" and v.get("salary"):
        salary = str(v["salary"])

    duty = html_to_text(v.get("duty"))
    # Текст требований лежит в поле "requirements", а "requirement" — это словарь
    # с образованием и стажем в годах.
    qualification = html_to_text(v.get("requirements") or requirement.get("qualification"))
    benefit = html_to_text(v.get("benefit"))
    skills = [s if isinstance(s, str) else str((s or {}).get("name", "")) for s in v.get("skills") or []]
    parts = [
        f"Обязанности:\n{duty}" if duty else "",
        f"Требования:\n{qualification}" if qualification else "",
        f"Образование: {requirement['education']}" if requirement.get("education") else "",
        f"Опыт: {experience}" if experience else "",
        f"График: {v['schedule']}" if v.get("schedule") else "",
        f"Условия: {benefit}" if benefit else "",
    ]
    description = "\n\n".join(p for p in parts if p)
    if len(description) > 3500:
        description = description[:3500].rstrip() + " …"

    return VacancyDetails(
        id=ID_PREFIX + str(v.get("id", "")),
        name=v.get("job-name") or v.get("job_name") or "",
        employer=(v.get("company") or {}).get("name", ""),
        area=(v.get("region") or {}).get("name", ""),
        salary=salary,
        url=v.get("vac_url", ""),
        published_at=v.get("creation-date", ""),
        requirement=qualification[:300],
        responsibility=duty[:300],
        experience=experience,
        schedule=v.get("schedule", ""),
        description=description,
        key_skills=[s for s in skills if s],
    )


def _matches_filters(v: VacancyDetails, raw: dict, experience: str | None, schedule: str | None) -> bool:
    """API «Работы России» не умеет фильтровать по опыту и графику — делаем это сами."""
    text = (v.schedule + " " + v.description).lower()
    if schedule == "remote" and "удал" not in text and "дистанц" not in text:
        return False
    years = ((raw.get("vacancy", raw).get("requirement") or {}) or {}).get("experience")
    if experience and isinstance(years, (int, float)):
        limits = {"noExperience": 1, "between1And3": 3, "between3And6": 6}
        if experience in limits and years > limits[experience]:
            return False
    return True


class TrudvsemClient:
    name = "trudvsem"
    description = "портал «Работа России» (trudvsem.ru)"
    BASE_URL = "https://opendata.trudvsem.ru/api/v1/vacancies"

    def __init__(self, transport: Transport = urllib_transport, region_code: str | None = None, timeout: float = 30):
        self.transport = transport
        self.region_code = region_code  # например 7700000000000 — Москва
        self.timeout = timeout
        self._cache: dict[str, VacancyDetails] = {}

    def search(
        self,
        text: str,
        experience: str | None = None,
        schedule: str | None = None,
        area: str | None = None,
        page: int = 0,
        limit: int = 20,
    ) -> list[Vacancy]:
        if not text.strip():
            raise ValueError("поисковый запрос не может быть пустым")
        region = area if area and len(str(area)) > 5 else self.region_code
        url = self.BASE_URL + (f"/region/{quote(str(region))}" if region else "")
        # Берём с запасом, потому что часть отсеется фильтрами
        url += "?" + urlencode({"text": text, "offset": max(0, page), "limit": 100})
        data = self.transport("GET", url, {"User-Agent": "job-agent/0.1"}, None, self.timeout) or {}
        results = data.get("results") or {}
        items = results.get("vacancies") or [] if isinstance(results, dict) else []

        parsed = [(item, _parse(item)) for item in items]
        parsed = [(item, d) for item, d in parsed if d.id != ID_PREFIX]
        found = [d for item, d in parsed if _matches_filters(d, item, experience, schedule)]
        if not found:
            # Фильтры по опыту и графику часто отсекают всё: на «Работе России»
            # их редко заполняют. Лучше показать модели вакансии без фильтров.
            found = [d for _, d in parsed]
        found = found[:limit]
        for details in found:
            self._cache[details.id] = details
        return list(found)

    def get(self, vacancy_id: str) -> VacancyDetails:
        details = self._cache.get(str(vacancy_id))
        if details is None:
            raise ValueError("Вакансия не найдена: сначала вызови search_vacancies")
        return details
