# app/pipeline/materialize_impl.py
from __future__ import annotations
import json, re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Any
from app.config import load_config

_BLOCK_HDR = re.compile(r"^\s*<path:\s*(.+?)\s*>\s*$")

def _safe_under_src(rel: str) -> Path:
    p = Path(rel.strip())
    if p.is_absolute():
        p = Path(*p.parts[1:])
    # force into src/
    if not p.parts or p.parts[0] != "src":
        p = Path("src") / p
    # normalize + forbid traversal
    q = Path("src") / Path(*[part for part in p.parts[1:] if part not in (".", "..")])
    if q.suffix == "":
        q = q.with_suffix(".py")
    return q

def _parse_blocks_strict(raw: str) -> List[Tuple[str, str]]:
    """
    Parse blocks in the strict format:
      <path: src/foo.py>
      ...code...
      ---
      <path: src/bar/baz.py>
      ...code...
    Returns list of (relpath, code).
    """
    out: List[Tuple[str, str]] = []
    cur_path: str | None = None
    buf: List[str] = []
    def flush():
        nonlocal cur_path, buf
        if cur_path is not None:
            code = "\n".join(buf).rstrip()
            if code:
                out.append((cur_path, code))
        cur_path, buf = None, []
    for line in raw.splitlines():
        m = _BLOCK_HDR.match(line)
        if m:
            flush()
            cur_path = m.group(1).strip()
            continue
        if line.strip() == "---":
            flush()
            continue
        buf.append(line)
    flush()
    return out

def _extract_files_from_impl(impl: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    Heuristics to support common impl shapes:
      1) {"files":[{"path":"src/x.py","content":"..."}]}
      2) {"artifacts":{"src/x.py":"...","src/y.py":"..."}}
      3) {"code_blocks":"<path: src/x.py>...---<path: src/y.py>..."}
      4) {"path":"src/x.py","code":"..."} or {"code":"..."} → default src/impl_generated.py
    """
    files: List[Tuple[str, str]] = []

    # 1) files[]
    files_arr = impl.get("files")
    if isinstance(files_arr, list):
        for it in files_arr:
            if isinstance(it, dict):
                path = it.get("path") or it.get("name")
                content = it.get("content") or it.get("code") or it.get("text")
                if path and isinstance(content, str):
                    files.append((path, content))

    # 2) artifacts {path: code}
    if not files and isinstance(impl.get("artifacts"), dict):
        for path, content in impl["artifacts"].items():
            if isinstance(path, str) and isinstance(content, str):
                files.append((path, content))

    # 3) strict code blocks
    if not files and isinstance(impl.get("code_blocks"), str):
        files.extend(_parse_blocks_strict(impl["code_blocks"]))

    # 4) single file
    if not files:
        path = impl.get("path") or impl.get("filename") or "src/impl_generated.py"
        content = impl.get("code") or impl.get("content") or impl.get("text") or ""
        if isinstance(content, str) and content.strip():
            files.append((path, content))

    return files

def materialize_impl_to_staging(task_id: str, impl: Dict[str, Any] | None = None) -> List[Path]:
    """
    Writes implementation files under generated/<taskId>/src based on 'impl' JSON.
    Returns list of written paths. No-ops cleanly if nothing to write.
    """
    cfg = load_config()
    generated_root = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    src_root = generated_root / "src"
    src_root.mkdir(parents=True, exist_ok=True)

    # Load impl JSON from APP_DATA_DIR if not provided
    if impl is None:
        app_dir = Path(cfg["APP_DATA_DIR"]) / task_id
        impl_path = app_dir / "implement@v1.json"
        if not impl_path.exists():
            return []  # nothing to do
        impl = json.loads(impl_path.read_text(encoding="utf-8"))

    files = _extract_files_from_impl(impl or {})
    written: List[Path] = []
    for rel, code in files:
        safe_rel = _safe_under_src(rel)
        dest = src_root.parent / safe_rel  # ensure under generated/<tid>/src
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(code, encoding="utf-8")
        written.append(dest)
    return written
