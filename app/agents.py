import json
from pathlib import Path
from agents import Agent, Runner

LOGFILE = Path("data/reports.jsonl")
LOGFILE.parent.mkdir(parents=True, exist_ok=True)

def make_architect_agent():
    return Agent(name='Architect', instructions='Design the solution.', output_type="design")

def make_implementer_agent():
    return Agent(name='Implementer', instructions='Write the implementation code.', output_type="code")

def make_tester_agent():
    return Agent(name='Tester', instructions='Write tests and run them.', output_type="test_results")

def make_reviewer_agent():
    return Agent(name='Reviewer', instructions='Review code and test results.', output_type="review")

def run_pipeline(task_id: str, prompt: str):
    runner = Runner()
    agents = [
        make_architect_agent(),
        make_implementer_agent(),
        make_tester_agent(),
        make_reviewer_agent()
    ]

    current_input = prompt
    for agent in agents:
        result = runner.run(agent, current_input)
        persist_stage(task_id, agent.name, result)
        current_input = result  # Pass output to next stage

    persist_final(task_id)

def persist_stage(task_id: str, stage: str, content):
    entry = {"task_id": task_id, "stage": stage, "output": content}
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def persist_final(task_id: str):
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"task_id": task_id, "status": "done"}) + "\n")
