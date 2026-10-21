"""Командная строка.

Примеры:
    python -m job_agent demo
    python -m job_agent run --resume my_resume.md --goal "Junior LLM-разработчик, удалёнка"
    python -m job_agent run --source files --vacancies-dir vacancies --resume my_resume.md --goal "..."
    python -m job_agent history --min-score 60
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .agent import AgentResult, JobAgent
from .config import Settings
from .demo import DEMO_RESUME, ScriptedLLM, demo_hh_transport, demo_script
from .hh_client import HHClient
from .llm import LLMClient, LLMError
from .models import VERDICT_LABELS
from .net import HTTPError
from .report import render_markdown, render_telegram, save_report, send_telegram
from .sources import SOURCE_NAMES, VacancySource, make_source
from .storage import Storage
from .tools import RunContext, build_toolbox


def _run_agent(
    llm,
    source: VacancySource,
    storage: Storage,
    resume: str,
    goal: str,
    max_steps: int,
    area: str | None,
) -> AgentResult:
    run_id = storage.start_run(goal)
    ctx = RunContext(run_id=run_id)
    toolbox = build_toolbox(source, storage, ctx, default_area=area)
    agent = JobAgent(llm, toolbox, ctx, max_steps=max_steps, source_description=source.description)
    result = agent.run(resume, goal)
    storage.finish_run(run_id, result.summary)
    return result


def _print_result(result: AgentResult, report_path: Path) -> None:
    print()
    print(f"Готово за {result.steps} шаг(ов). Вызовов инструментов: {len(result.tool_calls)}.")
    if result.stopped_by_limit:
        print("Внимание: агент остановлен по лимиту шагов.")
    print()
    for m in result.matches:
        print(f"  {m.score:>3}/100  {VERDICT_LABELS[m.verdict]:<12} {m.name} — {m.employer}")
    print()
    print("Итог:", result.summary)
    print("Отчёт:", report_path)


def cmd_demo(args: argparse.Namespace) -> int:
    hh = HHClient(user_agent="job-agent-demo", transport=demo_hh_transport)
    storage = Storage(":memory:")
    goal = "Junior LLM-разработчик / разработчик AI-агентов"
    result = _run_agent(ScriptedLLM(demo_script()), hh, storage, DEMO_RESUME, goal, 10, None)
    markdown = render_markdown(goal, result.summary, result.matches)
    path = save_report(markdown, args.report_dir)
    print("ДЕМО-РЕЖИМ: вакансии вымышленные, вместо LLM — заранее заданный сценарий.")
    _print_result(result, path)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    resume_path = Path(args.resume)
    if not resume_path.is_file():
        print(f"Файл резюме не найден: {resume_path}", file=sys.stderr)
        return 2
    resume = resume_path.read_text(encoding="utf-8")

    source_name = args.source or settings.vacancy_source
    if args.vacancies_dir:
        settings = replace(settings, vacancies_dir=args.vacancies_dir)
    try:
        source = make_source(source_name, settings)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    print(f"Источник вакансий: {source.description}. Модель: {settings.llm_model}")

    llm = LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    storage = Storage(settings.db_path)
    area = args.area or (settings.hh_area if source_name == "hh" else None)
    try:
        result = _run_agent(
            llm, source, storage, resume, args.goal,
            args.max_steps or settings.max_steps,
            area,
        )
    except (LLMError, HTTPError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        storage.close()

    markdown = render_markdown(args.goal, result.summary, result.matches)
    path = save_report(markdown, args.report_dir)
    _print_result(result, path)

    if args.telegram:
        if not settings.telegram_enabled:
            print("Telegram не настроен: задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID", file=sys.stderr)
        else:
            sent = send_telegram(
                settings.telegram_bot_token, settings.telegram_chat_id,
                render_telegram(result.summary, result.matches),
            )
            print(f"Отправлено в Telegram: {sent} сообщ.")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    storage = Storage(settings.db_path)
    matches = storage.recent_matches(limit=args.limit, min_score=args.min_score)
    storage.close()
    if not matches:
        print("История пуста.")
        return 0
    for m in matches:
        print(f"{m.score:>3}/100  {VERDICT_LABELS[m.verdict]:<12} {m.name} — {m.employer}\n         {m.url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-agent",
        description="AI-агент, который ищет вакансии и оценивает их под ваше резюме.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог шагов агента")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="прогон без интернета и API-ключей")
    demo.add_argument("--report-dir", default="reports")
    demo.set_defaults(func=cmd_demo)

    run = sub.add_parser("run", help="настоящий поиск вакансий")
    run.add_argument("--resume", required=True, help="путь к резюме (.md или .txt)")
    run.add_argument("--goal", required=True, help="что ищем, например 'Junior LLM-разработчик, удалёнка'")
    run.add_argument("--source", choices=SOURCE_NAMES, help="источник вакансий (по умолчанию из .env)")
    run.add_argument("--vacancies-dir", help="папка с вакансиями для --source files")
    run.add_argument("--area", help="регион: для hh — 113/1/2, для trudvsem — код вида 7700000000000")
    run.add_argument("--max-steps", type=int, help="лимит шагов агента")
    run.add_argument("--report-dir", default="reports")
    run.add_argument("--telegram", action="store_true", help="отправить подборку в Telegram")
    run.set_defaults(func=cmd_run)

    history = sub.add_parser("history", help="последние оценённые вакансии")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--min-score", type=int, default=0)
    history.set_defaults(func=cmd_history)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose or args.command != "history" else logging.WARNING,
        format="%(message)s",
    )
    return args.func(args)
