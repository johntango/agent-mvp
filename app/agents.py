from typing import Dict, Any
from pydantic import BaseModel
from agents import Agent, Runner

class Design(BaseModel):
    design_summary: str
    files_touched: list[str]

class ImplResult(BaseModel):
    diff_summary: str
    code_snippets: list[str]

class TestResult(BaseModel):
    tests_added: int
    passed: int
    failed: int

class ReviewResult(BaseModel):
    approved: bool
    comments: list[str]

def make_architect_agent():
    return Agent(
        name="Architect",
        instructions=(
            "You are a software architect. Produce a succinct design plan for the task. "
            "List key files/modules to touch. Output only the structured fields."
        ),
        output_type=Design,
    )

def make_implementer_agent():
    return Agent(
        name="Implementer",
        instructions=(
            "You implement the design into code. Provide a short textual diff summary and "
            "include minimal code snippets (not full files). Output only the structured fields."
        ),
        output_type=ImplResult,
    )

def make_tester_agent():
    return Agent(
        name="Tester",
        instructions=(
            "You generate tests that verify the change and run them conceptually. "
            "Report counts: tests_added, passed, failed. Output only the structured fields."
        ),
        output_type=TestResult,
    )

def make_reviewer_agent():
    return Agent(
        name="Reviewer",
        instructions=(
            "You perform code review on the change. "
            "Set approved true only if no blockers remain; include brief comments."
        ),
        output_type=ReviewResult,
    )

def make_triage_agent():
    arch = make_architect_agent()
    impl = make_implementer_agent()
    test = make_tester_agent()
    rev = make_reviewer_agent()

    return Agent(
        name="Triage",
        instructions=(
            "You receive a software task description. "
            "Route work to Architect -> Implementer -> Tester -> Reviewer in that order. "
            "Return a compact human-readable summary of the overall outcome."
        ),
        handoffs=[arch, impl, test, rev],
    )

async def run_pipeline(task_text: str, context=None) -> Dict[str, Any]:
    triage = make_triage_agent()
    result = await Runner.run(triage, task_text, context=context)
    return {"final_output": result.final_output}
