import unittest
from datetime import datetime

from job_agent.llm import LLMClient, LLMError
from job_agent.models import Match
from job_agent.net import HTTPError
from job_agent.report import render_markdown, render_telegram, send_telegram, split_message
from job_agent.storage import Storage


def match(vacancy_id="1", score=70, verdict="maybe", letter=None):
    return Match(
        vacancy_id=vacancy_id, name=f"Вакансия {vacancy_id}", employer="Компания",
        url=f"https://example.com/{vacancy_id}", salary="не указана", score=score,
        verdict=verdict, reasons=["причина"], missing_skills=["RAG"], cover_letter=letter,
    )


class LLMClientTest(unittest.TestCase):
    def test_sends_tools_and_returns_message(self):
        sent = {}

        def transport(method, url, headers, body=None, timeout=30):
            sent.update(method=method, url=url, headers=headers, body=body)
            return {"choices": [{"message": {"content": "привет"}}]}

        client = LLMClient("http://localhost:11434/v1/", "key", "qwen2.5:7b", transport=transport)
        reply = client.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

        self.assertEqual(sent["url"], "http://localhost:11434/v1/chat/completions")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer key")
        self.assertEqual(sent["body"]["model"], "qwen2.5:7b")
        self.assertEqual(sent["body"]["tool_choice"], "auto")
        self.assertEqual(reply, {"content": "привет", "role": "assistant"})

    def test_retries_on_rate_limit(self):
        attempts = []

        def transport(method, url, headers, body=None, timeout=30):
            attempts.append(1)
            if len(attempts) < 3:
                raise HTTPError(429, "too many requests")
            return {"choices": [{"message": {"content": "ok"}}]}

        client = LLMClient("http://x/v1", "k", "m", transport=transport, retry_delay=0)
        self.assertEqual(client.chat([])["content"], "ok")
        self.assertEqual(len(attempts), 3)

    def test_raises_on_client_error_and_bad_response(self):
        def unauthorized(*args, **kwargs):
            raise HTTPError(401, "bad key")

        with self.assertRaises(LLMError):
            LLMClient("http://x/v1", "k", "m", transport=unauthorized).chat([])
        with self.assertRaises(LLMError):
            LLMClient("http://x/v1", "k", "m", transport=lambda *a, **k: {"oops": 1}).chat([])


class StorageTest(unittest.TestCase):
    def test_save_update_and_read(self):
        storage = Storage(":memory:")
        run_id = storage.start_run("goal")
        storage.save_match(run_id, match("1", 40))
        storage.save_match(run_id, match("2", 90, "apply", "письмо"))
        storage.save_match(run_id, match("1", 55))  # повторная оценка обновляет запись

        matches = storage.matches_for_run(run_id)
        self.assertEqual([(m.vacancy_id, m.score) for m in matches], [("2", 90), ("1", 55)])
        self.assertEqual(matches[0].missing_skills, ["RAG"])
        self.assertEqual(storage.seen_ids(["1", "2", "3"]), {"1", "2"})
        self.assertEqual(len(storage.recent_matches(min_score=60)), 1)


class ReportTest(unittest.TestCase):
    def test_markdown_is_sorted_and_contains_letter(self):
        md = render_markdown("Junior", "итог", [match("1", 30), match("2", 90, "apply", "Моё письмо")],
                             created=datetime(2026, 10, 21, 12, 0))
        self.assertIn("21.10.2026 12:00", md)
        self.assertLess(md.index("Вакансия 2"), md.index("Вакансия 1"))
        self.assertIn("Моё письмо", md)
        self.assertIn("**Чего не хватает:** RAG", md)

    def test_markdown_without_matches(self):
        self.assertIn("Подходящих вакансий не найдено", render_markdown("g", "s", []))

    def test_telegram_skips_bad_matches(self):
        text = render_telegram("итог", [match("1", 90, "apply", "x"), match("2", 10, "skip")])
        self.assertIn("Вакансия 1", text)
        self.assertNotIn("Вакансия 2", text)

    def test_split_message_respects_limit(self):
        parts = split_message("\n".join(["строка"] * 100), limit=50)
        self.assertTrue(all(len(p) <= 50 for p in parts))
        self.assertEqual("\n".join(parts).count("строка"), 100)

    def test_send_telegram_posts_every_part(self):
        calls = []
        sent = send_telegram("TOKEN", "42", "a" * 9000,
                             transport=lambda m, u, h, body=None, timeout=30: calls.append((u, body)))
        self.assertEqual(sent, 3)
        self.assertTrue(calls[0][0].endswith("/botTOKEN/sendMessage"))
        self.assertEqual(calls[0][1]["chat_id"], "42")


if __name__ == "__main__":
    unittest.main()
