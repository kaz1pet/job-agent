"""Агентный цикл: модель думает → вызывает инструменты → получает результаты → повторяет.

Схема одного шага:
    1. Отправляем LLM историю сообщений и список инструментов.
    2. Если LLM вернула tool_calls — выполняем каждый вызов и добавляем
       результаты в историю как сообщения с ролью "tool".
    3. Если LLM ответила текстом без вызовов или вызвала finish — завершаем.
    4. Если шаги закончились (max_steps) — останавливаемся принудительно.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

from .models import Match
from .tools import RunContext, Toolbox

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Ты — агент, который помогает кандидату найти подходящую работу.
Источник вакансий: {source}.

Как работать:
1. Изучи резюме и цель кандидата. Придумай 2–4 разных поисковых запроса
   (синонимы должности, ключевые технологии, русские и английские названия).
   Если источник — папка с вакансиями, один вызов search_vacancies вернёт их все.
2. Ищи вакансии через search_vacancies. Пропускай already_evaluated=true
   и явно нерелевантные вакансии (другая профессия, требуется 6+ лет опыта и т.п.).
3. Для перспективных вакансий вызывай get_vacancy_details и оценивай их через save_match.
   Оцени от {min_matches} до {max_matches} вакансий (или все, если их меньше).
4. Оценивай честно: сравнивай требования вакансии с тем, что реально есть в резюме.
   Не приписывай кандидату навыки и опыт, которых нет в резюме.
5. Для verdict="apply" напиши сопроводительное письмо: конкретное, без шаблонных фраз,
   со ссылкой на проекты кандидата и требования вакансии.
6. В конце вызови finish с коротким итогом: сколько нашлось, какие лучшие,
   каких навыков чаще всего не хватает.

Отвечай и пиши итоги на русском языке.
"""


class ChatModel(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


@dataclass
class AgentResult:
    summary: str
    matches: list[Match]
    steps: int
    stopped_by_limit: bool = False
    tool_calls: list[str] = field(default_factory=list)


class JobAgent:
    def __init__(
        self,
        llm: ChatModel,
        toolbox: Toolbox,
        ctx: RunContext,
        max_steps: int = 25,
        min_matches: int = 5,
        max_matches: int = 10,
        source_description: str = "сайт вакансий",
    ):
        self.llm = llm
        self.toolbox = toolbox
        self.ctx = ctx
        self.max_steps = max_steps
        self.system_prompt = SYSTEM_PROMPT.format(
            min_matches=min_matches, max_matches=max_matches, source=source_description
        )

    def run(self, resume: str, goal: str) -> AgentResult:
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"Цель поиска: {goal}\n\nРезюме кандидата:\n{resume.strip()}",
            },
        ]
        tools = self.toolbox.schemas()
        called: list[str] = []

        for step in range(1, self.max_steps + 1):
            reply = self.llm.chat(messages, tools=tools)
            tool_calls = reply.get("tool_calls") or []
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.get("content") or "",
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                }
            )

            if not tool_calls:
                # Модель ответила текстом — считаем это финальным итогом.
                summary = (reply.get("content") or "").strip()
                log.info("Шаг %d: модель завершила работу текстовым ответом", step)
                return self._result(summary, step, called)

            for call in tool_calls:
                name = call.get("function", {}).get("name", "")
                arguments = call.get("function", {}).get("arguments", "{}")
                log.info("Шаг %d → %s(%s)", step, name, _short(arguments))
                result = self.toolbox.call(name, arguments)
                called.append(name)
                if result.startswith('{"error"'):
                    log.info("   ✗ %s", _short(result, 200))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "name": name,
                        "content": result,
                    }
                )

            if self.ctx.finished:
                return self._result(self.ctx.summary, step, called)

        log.warning("Агент остановлен: достигнут лимит в %d шагов", self.max_steps)
        return self._result(
            f"Остановлено по лимиту шагов ({self.max_steps}). Оценено вакансий: {len(self.ctx.matches)}.",
            self.max_steps,
            called,
            stopped_by_limit=True,
        )

    def _result(
        self, summary: str, steps: int, called: list[str], stopped_by_limit: bool = False
    ) -> AgentResult:
        matches = sorted(self.ctx.matches, key=lambda m: m.score, reverse=True)
        return AgentResult(
            summary=summary,
            matches=matches,
            steps=steps,
            stopped_by_limit=stopped_by_limit,
            tool_calls=called,
        )


def _short(value: str | dict, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
