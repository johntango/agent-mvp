# app/plan_models.py
from __future__ import annotations
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, ValidationError

# Step identifiers are constrained to a catalog for safety.
STEP_CATALOG = {
    "design@v1",
    "implement@v1",
    "test@v1",
    "review@v1",
    # You can extend later, e.g.: "lint@v1", "codegen@v1", "testgen@v1", "unittest@v1"
}

class StepSpec(BaseModel):
    id: str = Field(..., description="Step type from STEP_CATALOG, e.g., design@v1")
    depends_on: List[str] = Field(default_factory=list)
    inputs: Dict[str, object] = Field(default_factory=dict)
    success_criteria: List[str] = Field(default_factory=list)

class Plan(BaseModel):
    task_id: str
    title: str
    assumptions: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    steps: List[StepSpec]
    constraints: Dict[str, object] = Field(default_factory=dict)

def validate_plan(plan: Plan) -> Plan:
    # Unique step ids
    ids = [s.id for s in plan.steps]
    if len(ids) != len(set(ids)):
        raise ValidationError([{"loc": ("steps",), "msg": "Duplicate step ids in plan", "type": "value_error"}], Plan)

    # All ids must be in the catalog
    unknown = [s.id for s in plan.steps if s.id not in STEP_CATALOG]
    if unknown:
        raise ValidationError([{"loc": ("steps",), "msg": f"Unknown step ids: {unknown}", "type": "value_error"}], Plan)

    # Dependencies must reference existing ids
    valid_ids = set(ids)
    bad_deps: List[str] = []
    for s in plan.steps:
        for d in s.depends_on:
            if d not in valid_ids:
                bad_deps.append(f"{s.id}->{d}")
    if bad_deps:
        raise ValidationError([{"loc": ("steps",), "msg": f"Bad dependencies: {bad_deps}", "type": "value_error"}], Plan)

    # Acyclic check via Kahn
    indeg = {sid: 0 for sid in ids}
    adj = {sid: [] for sid in ids}
    for s in plan.steps:
        for d in s.depends_on:
            indeg[s.id] += 1
            adj[d].append(s.id)
    q = [sid for sid, v in indeg.items() if v == 0]
    visited = 0
    while q:
        u = q.pop()
        visited += 1
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    if visited != len(ids):
        raise ValidationError([{"loc": ("steps",), "msg": "Plan contains a cycle", "type": "value_error"}], Plan)

    return plan
