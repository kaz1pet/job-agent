import json
import unittest

from job_agent.demo import demo_hh_transport
from job_agent.hh_client import HHClient
from job_agent.storage import Storage
from job_agent.tools import RunContext, build_toolbox


def make_toolbox():
    storage = Storage(":memory:")
    ctx = RunContext(run_id=storage.start_run("test"))
    hh = HHClient("ua", transport=demo_hh_transport)
    return build_toolbox(hh, storage, ctx), storage, ctx


class ToolboxTest(unittest.TestCase):
    def test_schemas_follow_openai_format(self):
        box, _, _ = make_toolbox()
        names = [s["function"]["name"] for s in box.schemas()]
        self.assertEqual(names, ["search_vacancies", "get_vacancy_details", "save_match", "finish"])
        for schema in box.schemas():
            self.assertEqual(schema["type"], "function")
            self.assertEqual(schema["function"]["parameters"]["type"], "object")

    def test_errors_are_returned_to_model_instead_of_raising(self):
        box, _, _ = make_toolbox()
        self.assertIn("Неизвестный инструмент", json.loads(box.call("delete_everything", "{}"))["error"])
        self.assertIn("Некорректные аргументы", json.loads(box.call("finish", "{not json"))["error"])
        self.assertIn("Неверные параметры", json.loads(box.call("finish", {"wrong": 1}))["error"])

    def test_save_match_requires_known_vacancy(self):
        box, _, _ = make_toolbox()
        result = json.loads(box.call("save_match", {
            "vacancy_id": "100000001", "score": 50, "verdict": "maybe", "reasons": ["x"],
        }))
        self.assertIn("сначала вызови search_vacancies", result["error"])

    def test_save_match_validates_and_stores(self):
        box, storage, ctx = make_toolbox()
        search = json.loads(box.call("search_vacancies", {"text": "LLM"}))
        self.assertEqual(search["found"], 3)

        bad_score = json.loads(box.call("save_match", {
            "vacancy_id": "100000001", "score": 150, "verdict": "maybe", "reasons": ["x"],
        }))
        self.assertIn("error", bad_score)

        no_letter = json.loads(box.call("save_match", {
            "vacancy_id": "100000001", "score": 90, "verdict": "apply", "reasons": ["x"],
        }))
        self.assertIn("cover_letter", no_letter["error"])

        ok = json.loads(box.call("save_match", {
            "vacancy_id": "100000001", "score": 90, "verdict": "apply",
            "reasons": ["стек совпадает"], "cover_letter": "Здравствуйте!",
        }))
        self.assertTrue(ok["saved"])
        stored = storage.matches_for_run(ctx.run_id)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].name, "Junior LLM Engineer")  # название берётся из hh, а не от модели

    def test_already_evaluated_flag_on_next_search(self):
        box, _, _ = make_toolbox()
        box.call("search_vacancies", {"text": "LLM"})
        box.call("save_match", {"vacancy_id": "100000003", "score": 5, "verdict": "skip", "reasons": ["senior"]})
        again = json.loads(box.call("search_vacancies", {"text": "LLM"}))
        flags = {v["id"]: v["already_evaluated"] for v in again["vacancies"]}
        self.assertTrue(flags["100000003"])
        self.assertFalse(flags["100000001"])

    def test_finish_marks_context(self):
        box, _, ctx = make_toolbox()
        box.call("finish", {"summary": "  готово  "})
        self.assertTrue(ctx.finished)
        self.assertEqual(ctx.summary, "готово")


if __name__ == "__main__":
    unittest.main()
