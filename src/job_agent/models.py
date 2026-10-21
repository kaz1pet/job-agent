"""Структуры данных: вакансии и результаты их оценки агентом."""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field

_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"[ \t\r\f\v]+")
_NEWLINES_RE = re.compile(r"\n{3,}")


def html_to_text(raw: str | None) -> str:
    """Превращает HTML-описание вакансии в читаемый текст."""
    if not raw:
        return ""
    text = re.sub(r"<\s*(br|/p|/ul|/ol|/h\d)\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<\s*li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _SPACES_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return _NEWLINES_RE.sub("\n\n", "\n".join(lines)).strip()


def format_salary(salary: dict | None) -> str:
    """{'from': 100000, 'to': 150000, 'currency': 'RUR', 'gross': True} -> текст."""
    if not salary:
        return "не указана"
    low, high = salary.get("from"), salary.get("to")
    currency = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€"}.get(
        salary.get("currency") or "", salary.get("currency") or ""
    )

    def num(value: int) -> str:
        return f"{value:,}".replace(",", " ")

    if low and high:
        text = f"{num(low)}–{num(high)} {currency}"
    elif low:
        text = f"от {num(low)} {currency}"
    elif high:
        text = f"до {num(high)} {currency}"
    else:
        return "не указана"
    if salary.get("gross") is True:
        text += " до вычета налогов"
    elif salary.get("gross") is False:
        text += " на руки"
    return text.strip()


def _name(obj: dict | None) -> str:
    return (obj or {}).get("name") or ""


@dataclass
class Vacancy:
    """Краткая карточка вакансии из поиска."""

    id: str
    name: str
    employer: str
    area: str
    salary: str
    url: str
    published_at: str
    requirement: str = ""
    responsibility: str = ""
    experience: str = ""
    schedule: str = ""

    @classmethod
    def from_api(cls, item: dict) -> Vacancy:
        snippet = item.get("snippet") or {}
        return cls(
            id=str(item["id"]),
            name=item.get("name", ""),
            employer=_name(item.get("employer")),
            area=_name(item.get("area")),
            salary=format_salary(item.get("salary") or item.get("salary_range")),
            url=item.get("alternate_url", ""),
            published_at=item.get("published_at", ""),
            requirement=html_to_text(snippet.get("requirement")),
            responsibility=html_to_text(snippet.get("responsibility")),
            experience=_name(item.get("experience")),
            schedule=_name(item.get("schedule")),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VacancyDetails(Vacancy):
    """Полная вакансия: описание и ключевые навыки."""

    description: str = ""
    key_skills: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, item: dict, max_description_chars: int = 3500) -> VacancyDetails:
        short = Vacancy.from_api(item)
        description = html_to_text(item.get("description"))
        if len(description) > max_description_chars:
            description = description[:max_description_chars].rstrip() + " …"
        return cls(
            **asdict(short),
            description=description,
            key_skills=[s.get("name", "") for s in item.get("key_skills") or []],
        )


VERDICTS = ("apply", "maybe", "skip")
VERDICT_LABELS = {"apply": "Откликаться", "maybe": "Подумать", "skip": "Пропустить"}


@dataclass
class Match:
    """Оценка вакансии агентом."""

    vacancy_id: str
    name: str
    employer: str
    url: str
    salary: str
    score: int
    verdict: str
    reasons: list[str]
    missing_skills: list[str] = field(default_factory=list)
    cover_letter: str | None = None
