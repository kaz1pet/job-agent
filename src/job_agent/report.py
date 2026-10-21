"""Отчёт по результатам: Markdown-файл и (по желанию) сообщение в Telegram."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import VERDICT_LABELS, Match
from .net import Transport, urllib_transport

TELEGRAM_LIMIT = 4000  # у Telegram лимит 4096 символов, оставляем запас


def render_markdown(goal: str, summary: str, matches: list[Match], created: datetime | None = None) -> str:
    created = created or datetime.now()
    lines = [
        "# Подборка вакансий",
        "",
        f"**Цель поиска:** {goal}  ",
        f"**Дата:** {created:%d.%m.%Y %H:%M}  ",
        f"**Оценено вакансий:** {len(matches)}",
        "",
        "## Итог агента",
        "",
        summary or "—",
        "",
    ]
    if not matches:
        return "\n".join(lines + ["Подходящих вакансий не найдено."]) + "\n"

    lines += ["## Рейтинг", "", "| # | Вакансия | Компания | Зарплата | Оценка | Решение |", "|---|---|---|---|---|---|"]
    ordered = sorted(matches, key=lambda m: m.score, reverse=True)
    for i, m in enumerate(ordered, 1):
        name = m.name.replace("|", "/")
        lines.append(
            f"| {i} | [{name}]({m.url}) | {m.employer} | {m.salary} | {m.score}/100 | {VERDICT_LABELS[m.verdict]} |"
        )
    lines.append("")

    for i, m in enumerate(ordered, 1):
        lines += [f"## {i}. {m.name} — {m.employer}", "", f"[Открыть вакансию]({m.url}) · {m.salary} · **{m.score}/100**", ""]
        lines += ["**Почему такая оценка:**", ""] + [f"- {r}" for r in m.reasons] + [""]
        if m.missing_skills:
            lines += [f"**Чего не хватает:** {', '.join(m.missing_skills)}", ""]
        if m.cover_letter:
            lines += ["<details><summary>Сопроводительное письмо</summary>", "", m.cover_letter, "", "</details>", ""]
    return "\n".join(lines)


def save_report(markdown: str, report_dir: str | Path = "reports") -> Path:
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"report_{datetime.now():%Y-%m-%d_%H-%M-%S}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def render_telegram(summary: str, matches: list[Match], top: int = 5) -> str:
    best = [m for m in sorted(matches, key=lambda m: m.score, reverse=True) if m.verdict != "skip"][:top]
    lines = ["Подборка вакансий от job-agent", "", summary, ""]
    if not best:
        lines.append("Подходящих вакансий пока нет.")
    for i, m in enumerate(best, 1):
        lines += [f"{i}. {m.name} — {m.employer}", f"   {m.score}/100 · {m.salary}", f"   {m.url}", ""]
    return "\n".join(lines).strip()


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Делит длинный текст на части по границам строк."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # очень длинная строка
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def send_telegram(
    token: str,
    chat_id: str,
    text: str,
    transport: Transport = urllib_transport,
) -> int:
    """Отправляет текст в Telegram. Возвращает число отправленных сообщений."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    parts = split_message(text)
    for part in parts:
        transport("POST", url, {}, {"chat_id": chat_id, "text": part, "disable_web_page_preview": True})
    return len(parts)
