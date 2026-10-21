import unittest
from urllib.parse import parse_qs, urlparse

from job_agent.demo import DEMO_VACANCIES
from job_agent.hh_client import HHClient
from job_agent.models import format_salary, html_to_text


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def __call__(self, method, url, headers, body=None, timeout=30):
        self.requests.append((method, url, headers))
        return self.response


class HHClientTest(unittest.TestCase):
    def test_search_builds_query_and_parses_items(self):
        transport = FakeTransport({"items": DEMO_VACANCIES})
        client = HHClient("test-agent/1.0", transport=transport)

        vacancies = client.search_vacancies("LLM разработчик", area="1", experience="noExperience")

        method, url, headers = transport.requests[0]
        query = parse_qs(urlparse(url).query)
        self.assertEqual(method, "GET")
        self.assertEqual(urlparse(url).path, "/vacancies")
        self.assertEqual(query["text"], ["LLM разработчик"])
        self.assertEqual(query["area"], ["1"])
        self.assertEqual(query["experience"], ["noExperience"])
        self.assertNotIn("schedule", query)  # пустые параметры не отправляются
        self.assertEqual(headers["HH-User-Agent"], "test-agent/1.0")

        self.assertEqual(len(vacancies), 3)
        first = vacancies[0]
        self.assertEqual(first.id, "100000001")
        self.assertEqual(first.area, "Москва")
        self.assertEqual(first.salary, "120 000–180 000 ₽ на руки")
        self.assertNotIn("<highlighttext>", first.requirement)

    def test_app_token_is_sent_as_bearer(self):
        transport = FakeTransport({"items": []})
        HHClient("ua", app_token="secret", transport=transport).search_vacancies("python")
        self.assertEqual(transport.requests[0][2]["Authorization"], "Bearer secret")

    def test_get_vacancy_returns_plain_text_description_and_skills(self):
        transport = FakeTransport(DEMO_VACANCIES[0])
        details = HHClient("ua", transport=transport).get_vacancy("100000001")
        self.assertIn("интеграция LLM через API", details.description)
        self.assertNotIn("<li>", details.description)
        self.assertEqual(details.key_skills, ["Python", "LLM", "SQL", "Git"])

    def test_invalid_arguments_are_rejected(self):
        client = HHClient("ua", transport=FakeTransport({"items": []}))
        with self.assertRaises(ValueError):
            client.search_vacancies("   ")
        with self.assertRaises(ValueError):
            client.search_vacancies("python", experience="10 years")
        with self.assertRaises(ValueError):
            client.get_vacancy("../../me")


class FormattingTest(unittest.TestCase):
    def test_salary_variants(self):
        self.assertEqual(format_salary(None), "не указана")
        self.assertEqual(format_salary({"from": 70000, "currency": "RUR", "gross": True}), "от 70 000 ₽ до вычета налогов")
        self.assertEqual(format_salary({"to": 3000, "currency": "USD"}), "до 3 000 $")
        self.assertEqual(format_salary({"from": None, "to": None}), "не указана")

    def test_html_to_text(self):
        text = html_to_text("<p>Задачи:</p><ul><li>один</li><li>два &amp; три</li></ul>")
        self.assertEqual(text, "Задачи:\n\n- один\n- два & три")


if __name__ == "__main__":
    unittest.main()
