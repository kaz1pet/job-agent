"""Хранилище на SQLite: запуски агента, просмотренные вакансии и оценки.

Благодаря ему агент не оценивает одну и ту же вакансию повторно
при следующих запусках.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Match, Vacancy

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    goal        TEXT NOT NULL,
    summary     TEXT
);
CREATE TABLE IF NOT EXISTS seen_vacancies (
    vacancy_id     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    employer       TEXT,
    url            TEXT,
    first_seen_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    vacancy_id      TEXT PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    name            TEXT NOT NULL,
    employer        TEXT,
    url             TEXT,
    salary          TEXT,
    score           INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    verdict         TEXT NOT NULL CHECK (verdict IN ('apply', 'maybe', 'skip')),
    reasons         TEXT NOT NULL,
    missing_skills  TEXT NOT NULL,
    cover_letter    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matches_run ON matches(run_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- запуски ---------------------------------------------------------
    def start_run(self, goal: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs (started_at, goal) VALUES (?, ?)", (_now(), goal)
            )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, summary: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE runs SET summary = ? WHERE id = ?", (summary, run_id))

    # --- просмотренные вакансии ----------------------------------------
    def seen_ids(self, vacancy_ids: list[str]) -> set[str]:
        if not vacancy_ids:
            return set()
        placeholders = ",".join("?" * len(vacancy_ids))
        rows = self.conn.execute(
            f"SELECT vacancy_id FROM matches WHERE vacancy_id IN ({placeholders})",
            vacancy_ids,
        ).fetchall()
        return {row["vacancy_id"] for row in rows}

    def mark_seen(self, vacancies: list[Vacancy]) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO seen_vacancies VALUES (?, ?, ?, ?, ?)",
                [(v.id, v.name, v.employer, v.url, _now()) for v in vacancies],
            )

    # --- оценки ----------------------------------------------------------
    def save_match(self, run_id: int, match: Match) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vacancy_id) DO UPDATE SET
                    run_id = excluded.run_id, score = excluded.score,
                    verdict = excluded.verdict, reasons = excluded.reasons,
                    missing_skills = excluded.missing_skills,
                    cover_letter = excluded.cover_letter, created_at = excluded.created_at
                """,
                (
                    match.vacancy_id,
                    run_id,
                    match.name,
                    match.employer,
                    match.url,
                    match.salary,
                    match.score,
                    match.verdict,
                    json.dumps(match.reasons, ensure_ascii=False),
                    json.dumps(match.missing_skills, ensure_ascii=False),
                    match.cover_letter,
                    _now(),
                ),
            )

    def matches_for_run(self, run_id: int) -> list[Match]:
        rows = self.conn.execute(
            "SELECT * FROM matches WHERE run_id = ? ORDER BY score DESC", (run_id,)
        ).fetchall()
        return [self._row_to_match(row) for row in rows]

    def recent_matches(self, limit: int = 20, min_score: int = 0) -> list[Match]:
        rows = self.conn.execute(
            "SELECT * FROM matches WHERE score >= ? ORDER BY created_at DESC, score DESC LIMIT ?",
            (min_score, limit),
        ).fetchall()
        return [self._row_to_match(row) for row in rows]

    @staticmethod
    def _row_to_match(row: sqlite3.Row) -> Match:
        return Match(
            vacancy_id=row["vacancy_id"],
            name=row["name"],
            employer=row["employer"],
            url=row["url"],
            salary=row["salary"],
            score=row["score"],
            verdict=row["verdict"],
            reasons=json.loads(row["reasons"]),
            missing_skills=json.loads(row["missing_skills"]),
            cover_letter=row["cover_letter"],
        )
