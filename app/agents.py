# app/agents.py
from typing import List
from pydantic import BaseModel
from agents import Agent, Runner

class Design(BaseModel):
    design_summary: str
    files_touched: List[str]

class ImplResult(BaseModel):
    diff_summary: str
    code_snippets: List[str]

class TestResult(BaseModel):
    tests_added: int
    passed: int
    failed: int

class ReviewResult(BaseModel):
    approved: bool
    comments: List[str]

def make_architect_agent() -> Agent:
    return Agent(
        name="Architect",
        instructions=(
            "Given a software task, produce a succinct design plan and list files_touched."
        ),
        output_type=Design,
    )

def make_implementer_agent() -> Agent:
    return Agent(
        name="Implementer",
        instructions=(
            "Apply the design with minimal diffs. Return a short diff_summary and a few code_snippets."
        ),
        output_type=ImplResult,
    )

def make_tester_agent() -> Agent:
    return Agent(
        name="Tester",
        instructions=(
            "Generate tests that verify the change and conceptually run them. "
            "Report tests_added, passed, failed."
        ),
        output_type=TestResult,
    )

def make_reviewer_agent() -> Agent:
    return Agent(
        name="Reviewer",
        instructions=(
            "Review the change. Approve only if no blockers remain; include brief comments."
        ),
        output_type=ReviewResult,
    )
