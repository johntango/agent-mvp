# app/agents.py
from typing import List
from pydantic import BaseModel
from agents import Agent, Runner


# ----- Structured file outputs -----
class FileChange(BaseModel):
    path: str
    content: str

class Design(BaseModel):
    design_summary: str
    files_touched: List[str]

class ImplResult(BaseModel):
    diff_summary: str
    code_snippets: List[str] = []
    files: List[FileChange] = []       # NEW: concrete code files to write

class TestResult(BaseModel):
    tests_added: int
    passed: int
    failed: int
    test_files: List[FileChange] = []  # NEW: concrete test files to write


class ReviewResult(BaseModel):
    approved: bool
    comments: List[str]


# ----- Factories -----
def make_architect_agent() -> Agent:
    return Agent(
        name="Architect",
        instructions=(
            "Given the task prompt, produce a succinct design plan and list files_touched."
        ),
        output_type=Design,
    )

def make_implementer_agent() -> Agent:
    return Agent(
        name="Implementer",
        instructions=(
            "Implement the design with focused edits.\n"
            "Return diff_summary and populate files[] with concrete file edits "
            "e.g. [{path:'src/module.py', content:'...'}]. Keep code_snippets as brief excerpts."
        ),
        output_type=ImplResult,
    )

def make_tester_agent() -> Agent:
    return Agent(
        name="Tester",
        instructions=(
            "Write runnable tests for the change and conceptually execute them. "
            "Populate test_files[] with concrete test files (e.g., tests/test_module.py) "
            "and report tests_added, passed, failed."
        ),
        output_type=TestResult,
    )

def make_reviewer_agent() -> Agent:
    return Agent(
        name="Reviewer",
        instructions=(
            "Review the change and tests. Approve only if no blockers remain; include brief comments."
        ),
        output_type=ReviewResult,
    )



