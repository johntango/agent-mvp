from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from agents import Agent, Runner

# ---------- Structured outputs per agent ----------

class Design(BaseModel):
    design_summary: str
    files_touched: List[str]

class ImplResult(BaseModel):
    diff_summary: str
    code_snippets: List[str]  # short snippets, not full files

class TestResult(BaseModel):
    tests_added: int
    passed: int
    failed: int

class ReviewResult(BaseModel):
    approved: bool
    comments: List[str]

# ---------- Factory functions (no classes) ----------

def make_architect_agent() -> Agent:
    return Agent(
        name="Architect",
        instructions=(
            "You are a software architect. Given the task prompt, produce a succinct design plan. "
            "Concisely list which files/modules to modify (files_touched). "
            "Output must populate the Pydantic fields exactly."
        ),
        output_type=Design,
    )

def make_implementer_agent() -> Agent:
    return Agent(
        name="Implementer",
        instructions=(
            "Implement the design with minimal, focused changes. "
            "Return a brief diff_summary and a few short code_snippets."
        ),
        output_type=ImplResult,
    )

def make_tester_agent() -> Agent:
    return Agent(
        name="Tester",
        instructions=(
            "Write tests that verify the change and conceptually execute them. "
            "Return counts (tests_added, passed, failed)."
        ),
        output_type=TestResult,
    )

def make_reviewer_agent() -> Agent:
    return Agent(
        name="Reviewer",
        instructions=(
            "Perform a code review of the change and tests. "
            "Set approved=true only if no blockers remain; include brief comments."
        ),
        output_type=ReviewResult,
    )

# Optional helper if you want to run everything in one call elsewhere.
async def run_pipeline(task_text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    triage_ctx = context or {}
    arch = make_architect_agent()
    impl = make_implementer_agent()
    test = make_tester_agent()
    rev  = make_reviewer_agent()

    # Architect
    r_arch = await Runner.run(arch, task_text, context=triage_ctx)
    arch_out = r_arch.final_output

    # Implementer
    r_impl = await Runner.run(impl, task_text, context={**triage_ctx, "design": arch_out})
    impl_out = r_impl.final_output

    # Tester
    r_test = await Runner.run(test, task_text, context={**triage_ctx, "design": arch_out, "impl": impl_out})
    test_out = r_test.final_output

    # Reviewer
    r_rev  = await Runner.run(rev,  task_text, context={**triage_ctx, "design": arch_out, "impl": impl_out, "tests": test_out})
    rev_out = r_rev.final_output

    return {
        "design": arch_out,
        "implementation": impl_out,
        "tests": test_out,
        "review": rev_out,
    }
