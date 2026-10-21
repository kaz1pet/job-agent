"""Инструменты, которые LLM может вызывать во время работы агента.

Каждый инструмент — это JSON-схема (её видит модель) и Python-функция
(её выполняет агент). Ошибки не роняют агента: они возвращаются модели
как {"error": "..."}, и она может исправить аргументы и попробовать снова.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .hh_client import EXPERIENCE_VALUES, SCHEDULE_VALUES
from .models import VERDICTS, Match, Vacancy
from .sources import VacancySource
from .storage import Storage

log = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class Toolbox:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def call(self, name: str, arguments: str | dict | None) -> str:
        """Выполняет инструмент и всегда возвращает JSON-строку для модели."""
        tool = self._tools.get(name)
        if tool is None:
            return _json({"error": f"Неизвестный инструмент '{name}'. Доступны: {self.names()}"})
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
            if not isinstance(args, dict):
                raise ValueError("аргументы должны быть JSON-объектом")
        except (json.JSONDecodeError, ValueError) as exc:
            return _json({"error": f"Некорректные аргументы: {exc}"})
        try:
            result = tool.handler(**args)
        except TypeError as exc:
            return _json({"error": f"Неверные параметры для {name}: {exc}"})
        except Exception as exc:  # noqa: BLE001 — модель должна узнать о любой ошибке
            log.warning("Инструмент %s завершился ошибкой: %s", name, exc)
            return _json({"error": str(exc)})
        return _json(result)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


@dataclass
class RunContext:
    """Состояние одного запуска агента."""

    run_id: int
    known: dict[str, Vacancy] = field(default_factory=dict)
    matches: list[Match] = field(default_factory=list)
    finished: bool = False
    summary: str = ""


def build_toolbox(
    source: VacancySource,
    storage: Storage,
    ctx: RunContext,
    default_area: str | None = None,
) -> Toolbox:
    box = Toolbox()

    def search_vacancies(
        text: str,
        experience: str | None = None,
        schedule: str | None = None,
        area: str | None = None,
        page: int = 0,
    ) -> dict:
        vacancies = source.search(
            text=text,
            area=area or default_area,
            experience=experience,
            schedule=schedule,
            page=page,
        )
        already = storage.seen_ids([v.id for v in vacancies])
        storage.mark_seen(vacancies)
        for v in vacancies:
            ctx.known[v.id] = v
        result: dict = {
            "found": len(vacancies),
            "vacancies": [
                {
                    "id": v.id,
                    "name": v.name,
                    "employer": v.employer,
                    "area": v.area,
                    "salary": v.salary,
                    "experience": v.experience,
                    "schedule": v.schedule,
                    "requirement": v.requirement[:300],
                    "already_evaluated": v.id in already,
                }
                for v in vacancies
            ],
        }
        if not vacancies:
            result["hint"] = "Ничего не найдено. Попробуй запрос короче или синоним, убери фильтры."
        return result

    def get_vacancy_details(vacancy_id: str) -> dict:
        details = source.get(str(vacancy_id))
        ctx.known[details.id] = details
        return {
            "id": details.id,
            "name": details.name,
            "employer": details.employer,
            "salary": details.salary,
            "experience": details.experience,
            "schedule": details.schedule,
            "key_skills": details.key_skills,
            "description": details.description,
        }

    def save_match(
        vacancy_id: str,
        score: int,
        verdict: str,
        reasons: list[str],
        missing_skills: list[str] | None = None,
        cover_letter: str | None = None,
    ) -> dict:
        vacancy_id = str(vacancy_id)
        vacancy = ctx.known.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Вакансия не найдена в этом запуске: сначала вызови search_vacancies")
        score = int(score)
        if not 0 <= score <= 100:
            raise ValueError("score должен быть от 0 до 100")
        if verdict not in VERDICTS:
            raise ValueError(f"verdict должен быть одним из {VERDICTS}")
        if not reasons:
            raise ValueError("укажи хотя бы одну причину оценки в reasons")
        if verdict == "apply" and not (cover_letter or "").strip():
            raise ValueError("для verdict='apply' нужно сопроводительное письмо cover_letter")
        match = Match(
            vacancy_id=vacancy_id,
            name=vacancy.name,
            employer=vacancy.employer,
            url=vacancy.url,
            salary=vacancy.salary,
            score=score,
            verdict=verdict,
            reasons=[str(r) for r in reasons],
            missing_skills=[str(s) for s in (missing_skills or [])],
            cover_letter=(cover_letter or "").strip() or None,
        )
        storage.save_match(ctx.run_id, match)
        ctx.matches = [m for m in ctx.matches if m.vacancy_id != vacancy_id] + [match]
        return {"saved": True, "evaluated_in_this_run": len(ctx.matches)}

    def finish(summary: str) -> dict:
        ctx.finished = True
        ctx.summary = summary.strip()
        return {"finished": True}

    box.register(
        Tool(
            name="search_vacancies",
            description=(
                f"Ищет вакансии (источник: {source.description}). Возвращает до 20 коротких карточек. "
                "already_evaluated=true значит, что вакансию уже оценивали раньше — её можно пропустить."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Поисковый запрос, например 'LLM разработчик'"},
                    "experience": {"type": "string", "enum": list(EXPERIENCE_VALUES)},
                    "schedule": {"type": "string", "enum": list(SCHEDULE_VALUES)},
                    "area": {"type": "string", "description": "Регион (необязательно, лучше не указывать)"},
                    "page": {"type": "integer", "minimum": 0, "description": "Номер страницы, с 0"},
                },
                "required": ["text"],
            },
            handler=search_vacancies,
        )
    )
    box.register(
        Tool(
            name="get_vacancy_details",
            description="Возвращает полное описание вакансии и ключевые навыки. Вызывай перед оценкой.",
            parameters={
                "type": "object",
                "properties": {"vacancy_id": {"type": "string"}},
                "required": ["vacancy_id"],
            },
            handler=get_vacancy_details,
        )
    )
    box.register(
        Tool(
            name="save_match",
            description=(
                "Сохраняет оценку вакансии. score — от 0 до 100, насколько кандидат подходит. "
                "verdict: apply (стоит откликнуться), maybe (подумать), skip (не подходит). "
                "Для apply обязательно напиши сопроводительное письмо на языке вакансии."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "vacancy_id": {"type": "string"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2–4 конкретные причины оценки со ссылкой на резюме и вакансию",
                    },
                    "missing_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Навыки из вакансии, которых нет в резюме",
                    },
                    "cover_letter": {
                        "type": "string",
                        "description": "Сопроводительное письмо, 600–1200 символов, без выдуманных фактов",
                    },
                },
                "required": ["vacancy_id", "score", "verdict", "reasons"],
            },
            handler=save_match,
        )
    )
    box.register(
        Tool(
            name="finish",
            description="Завершает работу. Вызывай, когда оценил достаточно вакансий.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Короткий итог для кандидата: что нашлось и что подтянуть"}
                },
                "required": ["summary"],
            },
            handler=finish,
        )
    )
    return box
