import json
import unittest

from job_agent.agent import JobAgent
from job_agent.demo import DEMO_RESUME, ScriptedLLM, demo_hh_transport, demo_script
from job_agent.hh_client import HHClient
from job_agent.storage import Storage
from job_agent.tools import RunContext, build_toolbox


def make_agent(replies, max_steps=10):
    storage = Storage(":memory:")
    ctx = RunContext(run_id=storage.start_run("goal"))
    toolbox = build_toolbox(HHClient("ua", transport=demo_hh_transport), storage, ctx)
    llm = ScriptedLLM(replies)
    return JobAgent(llm, toolbox, ctx, max_steps=max_steps), llm, storage, ctx


def tool_call(call_id, name, **args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class AgentLoopTest(unittest.TestCase):
    def test_full_demo_scenario(self):
        agent, llm, storage, ctx = make_agent(demo_script())
        result = agent.run(DEMO_RESUME, "Junior LLM")

        self.assertEqual(result.steps, 4)
        self.assertFalse(result.stopped_by_limit)
        self.assertEqual([m.score for m in result.matches], [82, 64, 5])  # отсортировано по оценке
        self.assertIn("Оценено 3 вакансии", result.summary)
        self.assertEqual(len(storage.matches_for_run(ctx.run_id)), 3)
        self.assertEqual(result.tool_calls.count("save_match"), 3)

    def test_tool_results_are_sent_back_to_model(self):
        agent, llm, _, _ = make_agent(demo_script())
        agent.run(DEMO_RESUME, "Junior LLM")

        second_request = llm.calls[1]
        self.assertEqual(second_request[0]["role"], "system")
        self.assertIn("Резюме кандидата", second_request[1]["content"])
        self.assertEqual(second_request[2]["tool_calls"][0]["function"]["name"], "search_vacancies")
        tool_message = second_request[3]
        self.assertEqual(tool_message["role"], "tool")
        self.assertEqual(tool_message["tool_call_id"], "c1")
        self.assertEqual(json.loads(tool_message["content"])["found"], 3)

    def test_text_answer_ends_the_run(self):
        agent, _, _, _ = make_agent([{"role": "assistant", "content": "Ничего не нашёл."}])
        result = agent.run("резюме", "цель")
        self.assertEqual(result.summary, "Ничего не нашёл.")
        self.assertEqual(result.steps, 1)

    def test_model_can_recover_after_tool_error(self):
        replies = [
            {"role": "assistant", "content": "", "tool_calls": [tool_call("a", "get_vacancy_details", vacancy_id="abc")]},
            {"role": "assistant", "content": "", "tool_calls": [tool_call("b", "finish", summary="ok")]},
        ]
        agent, llm, _, _ = make_agent(replies)
        result = agent.run("резюме", "цель")
        error_message = llm.calls[1][-1]
        self.assertIn("error", json.loads(error_message["content"]))
        self.assertEqual(result.summary, "ok")

    def test_step_limit_stops_endless_loop(self):
        endless = [
            {"role": "assistant", "content": "", "tool_calls": [tool_call(str(i), "search_vacancies", text="LLM")]}
            for i in range(10)
        ]
        agent, _, _, _ = make_agent(endless, max_steps=3)
        result = agent.run("резюме", "цель")
        self.assertTrue(result.stopped_by_limit)
        self.assertEqual(result.steps, 3)


if __name__ == "__main__":
    unittest.main()
