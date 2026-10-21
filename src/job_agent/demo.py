"""Демо-режим: полный прогон агента без интернета и без API-ключей.

Вместо hh.ru — подставные (вымышленные) вакансии, вместо LLM — «сценарий»,
который вызывает инструменты так же, как это делает настоящая модель.
Нужен, чтобы любой мог за 10 секунд увидеть, как работает агентный цикл.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from .net import HTTPError

DEMO_VACANCIES = [
    {
        "id": "100000001",
        "name": "Junior LLM Engineer",
        "employer": {"name": "Демо-компания «Альфа» (вымышленная)"},
        "area": {"name": "Москва"},
        "salary": {"from": 120000, "to": 180000, "currency": "RUR", "gross": False},
        "alternate_url": "https://example.com/demo-vacancy/1",
        "published_at": "2026-10-20T10:00:00+0300",
        "experience": {"name": "От 1 года до 3 лет"},
        "schedule": {"name": "Удаленная работа"},
        "snippet": {
            "requirement": "Python, опыт работы с <highlighttext>LLM</highlighttext> API, понимание RAG и агентов.",
            "responsibility": "Разработка AI-ассистентов для внутренних процессов.",
        },
        "description": (
            "<p>Ищем junior-разработчика в команду AI-ассистентов.</p>"
            "<p><strong>Задачи:</strong></p><ul><li>интеграция LLM через API</li>"
            "<li>разработка инструментов для агентов (function calling)</li>"
            "<li>обработка и сопоставление данных</li></ul>"
            "<p><strong>Требования:</strong></p><ul><li>Python</li><li>Git</li>"
            "<li>базовый SQL</li><li>английский для чтения документации</li></ul>"
        ),
        "key_skills": [{"name": "Python"}, {"name": "LLM"}, {"name": "SQL"}, {"name": "Git"}],
    },
    {
        "id": "100000002",
        "name": "Разработчик AI-агентов (стажёр)",
        "employer": {"name": "Демо-компания «Бета» (вымышленная)"},
        "area": {"name": "Санкт-Петербург"},
        "salary": {"from": 70000, "to": None, "currency": "RUR", "gross": True},
        "alternate_url": "https://example.com/demo-vacancy/2",
        "published_at": "2026-10-19T15:30:00+0300",
        "experience": {"name": "Нет опыта"},
        "schedule": {"name": "Гибкий график"},
        "snippet": {
            "requirement": "Python, интерес к <highlighttext>AI</highlighttext>-агентам, пет-проекты.",
            "responsibility": "Автоматизация обработки заявок с помощью LLM.",
        },
        "description": (
            "<p>Стажировка с возможностью перехода в штат.</p>"
            "<ul><li>Python на базовом уровне</li><li>пет-проекты с LLM — большой плюс</li>"
            "<li>Docker — будет плюсом</li></ul>"
        ),
        "key_skills": [{"name": "Python"}, {"name": "Docker"}, {"name": "LLM"}],
    },
    {
        "id": "100000003",
        "name": "Senior ML Engineer (Computer Vision)",
        "employer": {"name": "Демо-компания «Гамма» (вымышленная)"},
        "area": {"name": "Москва"},
        "salary": None,
        "alternate_url": "https://example.com/demo-vacancy/3",
        "published_at": "2026-10-18T09:00:00+0300",
        "experience": {"name": "Более 6 лет"},
        "schedule": {"name": "Полный день"},
        "snippet": {
            "requirement": "6+ лет в ML, PyTorch, CUDA, продакшн CV-моделей.",
            "responsibility": "Руководство командой CV.",
        },
        "description": "<p>Нужен опыт 6+ лет в компьютерном зрении, PyTorch, CUDA, MLOps.</p>",
        "key_skills": [{"name": "PyTorch"}, {"name": "CUDA"}, {"name": "Computer Vision"}],
    },
]

DEMO_RESUME = """\
Илья Минаков — начинающий разработчик LLM-приложений и AI-агентов.
Опыт: кодировщик данных в GfK Русь (с 10.2024) — сопоставление данных продавцов с базой данных.
Проекты: job-agent (Python, LLM tool calling, REST API, SQLite, Docker).
Английский: B2.
"""


def demo_hh_transport(method: str, url: str, headers: dict, body=None, timeout: float = 30):
    """Подменяет HTTP-запросы к hh.ru ответами из DEMO_VACANCIES."""
    parsed = urlparse(url)
    if parsed.path == "/vacancies":
        text = parse_qs(parsed.query).get("text", [""])[0].lower()
        items = list(DEMO_VACANCIES) if text else []
        return {"items": items, "found": len(items), "page": 0, "pages": 1}
    vacancy_id = parsed.path.rsplit("/", 1)[-1]
    for vacancy in DEMO_VACANCIES:
        if vacancy["id"] == vacancy_id:
            return vacancy
    raise HTTPError(404, "vacancy not found")


def _call(call_id: str, name: str, **arguments) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


class ScriptedLLM:
    """Имитация LLM: по очереди возвращает заранее заданные ответы."""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        self.calls.append([dict(m) for m in messages])
        if not self.replies:
            return {"role": "assistant", "content": "Сценарий закончился."}
        return self.replies.pop(0)


def demo_script() -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": "Ищу вакансии по профилю LLM/AI-агенты.",
            "tool_calls": [_call("c1", "search_vacancies", text="LLM разработчик")],
        },
        {
            "role": "assistant",
            "content": "Senior CV требует 6+ лет — пропускаю. Смотрю две подходящие.",
            "tool_calls": [
                _call("c2", "get_vacancy_details", vacancy_id="100000001"),
                _call("c3", "get_vacancy_details", vacancy_id="100000002"),
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                _call(
                    "c4",
                    "save_match",
                    vacancy_id="100000002",
                    score=82,
                    verdict="apply",
                    reasons=[
                        "Стажировка без требований к опыту — подходит начинающему кандидату",
                        "Пет-проект job-agent напрямую про автоматизацию с LLM",
                        "Docker есть в проекте кандидата",
                    ],
                    missing_skills=[],
                    cover_letter=(
                        "Здравствуйте! Меня заинтересовала стажировка по разработке AI-агентов. "
                        "Я сделал job-agent — агента на Python, который сам ищет вакансии через открытые API, "
                        "оценивает их с помощью LLM через tool calling и хранит результаты в SQLite; "
                        "проект упакован в Docker и покрыт тестами. В GfK Русь я с 2024 года сопоставляю "
                        "данные продавцов с базой данных — это близко к задачам автоматизации обработки заявок. "
                        "Буду рад обсудить, чем могу быть полезен."
                    ),
                ),
                _call(
                    "c5",
                    "save_match",
                    vacancy_id="100000001",
                    score=64,
                    verdict="maybe",
                    reasons=[
                        "Стек совпадает: Python, LLM API, function calling",
                        "Требуется опыт от 1 года в разработке — у кандидата его пока нет",
                    ],
                    missing_skills=["RAG", "коммерческий опыт разработки"],
                ),
                _call(
                    "c6",
                    "save_match",
                    vacancy_id="100000003",
                    score=5,
                    verdict="skip",
                    reasons=["Senior-позиция в Computer Vision с опытом 6+ лет"],
                    missing_skills=["PyTorch", "CUDA", "Computer Vision"],
                ),
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                _call(
                    "c7",
                    "finish",
                    summary=(
                        "Оценено 3 вакансии. Лучшая — стажировка по AI-агентам (82/100), письмо готово. "
                        "Чаще всего не хватает RAG и коммерческого опыта: стоит добавить в портфолио RAG-проект."
                    ),
                )
            ],
        },
    ]
