import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from job_agent.config import Settings
from job_agent.files_source import FilesSource
from job_agent.sources import make_source
from job_agent.storage import Storage
from job_agent.tools import RunContext, build_toolbox
from job_agent.trudvsem import TrudvsemClient

# Сокращённый реальный ответ opendata.trudvsem.ru (октябрь 2026)
TRUDVSEM_ITEM = {
    "vacancy": {
        "id": "c50d9cd8-bbe3-11f1-9a11-2f8460579df4",
        "region": {"region_code": "6300000000000", "name": "Самарская область"},
        "company": {"name": "ООО \"ПРИМЕР\""},
        "creation-date": "2026-09-29",
        "salary": "от 90000",
        "salary_min": 90000,
        "salary_max": 100000,
        "job-name": "Разработчик Python",
        "vac_url": "https://trudvsem.ru/vacancy/card/1/c50d9cd8",
        "schedule": "Полный рабочий день",
        "qualification": "Специалист",
        "requirements": "Опыт разработки на Python. Знание БД: PostgreSQL. Опыт написания тестов с использованием pytest.",
        "duty": "Разработка программного обеспечения на Python.",
        "requirement": {"education": "Среднее профессиональное образование", "experience": 1},
        "skills": [],
        "benefit": "Добровольное медицинское страхование",
        "currency": "«руб.»",
    }
}
SENIOR_ITEM = {
    "vacancy": {
        **TRUDVSEM_ITEM["vacancy"],
        "id": "senior-1",
        "job-name": "Ведущий разработчик",
        "requirement": {"experience": 6},
    }
}


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.urls = []

    def __call__(self, method, url, headers, body=None, timeout=30):
        self.urls.append(url)
        return self.response


class TrudvsemTest(unittest.TestCase):
    def test_parses_real_response(self):
        transport = FakeTransport({"status": "200", "results": {"vacancies": [TRUDVSEM_ITEM]}})
        client = TrudvsemClient(transport=transport)

        vacancies = client.search("python")

        query = parse_qs(urlparse(transport.urls[0]).query)
        self.assertEqual(query["text"], ["python"])
        v = vacancies[0]
        self.assertEqual(v.id, "tv-c50d9cd8-bbe3-11f1-9a11-2f8460579df4")
        self.assertEqual(v.name, "Разработчик Python")
        self.assertEqual(v.salary, "90 000–100 000 ₽")
        self.assertEqual(v.area, "Самарская область")
        self.assertEqual(v.experience, "от 1 года")
        self.assertIn("pytest", v.requirement)

        details = client.get(v.id)
        self.assertIn("Обязанности:", details.description)
        self.assertIn("Условия: Добровольное медицинское страхование", details.description)

    def test_region_goes_to_path(self):
        transport = FakeTransport({"results": {}})
        TrudvsemClient(transport=transport, region_code="7700000000000").search("python")
        self.assertIn("/vacancies/region/7700000000000?", transport.urls[0])

    def test_experience_filter_and_fallback(self):
        transport = FakeTransport({"results": {"vacancies": [TRUDVSEM_ITEM, SENIOR_ITEM]}})
        client = TrudvsemClient(transport=transport)
        names = [v.name for v in client.search("python", experience="noExperience")]
        self.assertEqual(names, ["Разработчик Python"])

        # если фильтр отсёк всё — возвращаем без фильтра, чтобы модели было что оценить
        transport.response = {"results": {"vacancies": [SENIOR_ITEM]}}
        self.assertEqual(len(client.search("python", experience="noExperience")), 1)

    def test_empty_results(self):
        self.assertEqual(TrudvsemClient(transport=FakeTransport({"results": {}})).search("llm"), [])

    def test_unknown_id(self):
        with self.assertRaises(ValueError):
            TrudvsemClient(transport=FakeTransport({})).get("tv-nope")


class FilesSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "gear games.txt").write_text(
            "Junior SDET (Quality & AI focus)\nКомпания: Gear Games\nЗарплата: не указана\n"
            "https://hh.ru/vacancy/123\n\nПисать автотесты на Python, анализировать логи.",
            encoding="utf-8",
        )
        (self.dir / "notes.pdf").write_bytes(b"ignored")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_fields_from_text(self):
        vacancies = FilesSource(self.dir).search("что угодно")
        self.assertEqual(len(vacancies), 1)
        v = vacancies[0]
        self.assertEqual(v.id, "file-gear-games")
        self.assertEqual(v.name, "Junior SDET (Quality & AI focus)")
        self.assertEqual(v.employer, "Gear Games")
        self.assertEqual(v.url, "https://hh.ru/vacancy/123")
        self.assertIn("анализировать логи", FilesSource(self.dir).get("file-gear-games").description)

    def test_missing_dir(self):
        with self.assertRaises(ValueError):
            FilesSource(self.dir / "nope").search("x")

    def test_works_inside_toolbox(self):
        storage = Storage(":memory:")
        ctx = RunContext(run_id=storage.start_run("g"))
        box = build_toolbox(FilesSource(self.dir), storage, ctx)
        found = json.loads(box.call("search_vacancies", {"text": "python"}))
        self.assertEqual(found["vacancies"][0]["employer"], "Gear Games")
        saved = json.loads(box.call("save_match", {
            "vacancy_id": "file-gear-games", "score": 70, "verdict": "maybe", "reasons": ["Python совпадает"],
        }))
        self.assertTrue(saved["saved"])


class MakeSourceTest(unittest.TestCase):
    def test_hh_requires_token(self):
        with self.assertRaisesRegex(ValueError, "HH_APP_TOKEN"):
            make_source("hh", Settings())
        self.assertEqual(make_source("hh", Settings(hh_app_token="t")).name, "hh")

    def test_known_and_unknown_sources(self):
        self.assertEqual(make_source("trudvsem", Settings()).name, "trudvsem")
        self.assertEqual(make_source("files", Settings()).name, "files")
        with self.assertRaises(ValueError):
            make_source("superjob", Settings())


if __name__ == "__main__":
    unittest.main()
