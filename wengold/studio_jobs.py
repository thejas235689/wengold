"""Bounded, auditable local studio jobs.

Tasks execute in one serialized worker, never in a request handler. The only
supported operations are formal checks, syntax analysis, and graph inspection.
Nothing performs automatic signoff or applies an RTL repair.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .ide_server import Refused
from .ledger.store import Ledger
from .studio_workspace import source, project_file, SOURCE_SUFFIXES


def syntax_diagnostics(text: str, filename: str = "source.sv") -> dict:
    try:
        from pyslang import syntax
    except ImportError:
        return {"status": "unavailable", "tool": "pyslang",
                "diagnostics": [], "note": "Install pyslang for actual syntax diagnostics."}
    try:
        tree = syntax.SyntaxTree.fromText(text, name=filename)
        rows = []
        for d in list(tree.diagnostics)[:150]:
            loc = getattr(d, "location", None)
            rows.append({"message": str(d), "offset": getattr(loc, "offset", None)})
        return {"status": "errors" if rows else "clean", "tool": "pyslang",
                "diagnostics": rows, "count": len(tree.diagnostics)}
    except Exception as exc:
        return {"status": "error", "tool": "pyslang",
                "diagnostics": [], "note": f"{type(exc).__name__}: {exc}"}


class StudioJobs:
    def __init__(self, project: str | Path):
        self.root = Path(project).resolve()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wengold-studio")
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._ledger = Ledger(self.root / ".wengold-studio-ledger.jsonl")

    def _record(self, kind: str, payload: dict) -> dict:
        return self._ledger.append(kind, payload)

    def submit(self, kind: str, rel: str, *, expr: str = "",
               engine: str = "explicit", depth: int = 12) -> dict:
        if kind not in ("syntax", "formal"):
            raise Refused("only syntax and formal jobs are supported", 400)
        if not isinstance(rel, str) or not rel:
            raise Refused("source path required", 400)
        if engine not in ("explicit", "z3"):
            raise Refused("unsupported proof engine", 400)
        if not isinstance(depth, int) or not 1 <= depth <= 20:
            raise Refused("proof depth must be 1..20", 400)
        if kind == "formal" and (not isinstance(expr, str) or not 1 <= len(expr) <= 240):
            raise Refused("a bounded safety expression is required", 400)
        if not project_file(self.root, rel, SOURCE_SUFFIXES):
            raise Refused("source not found", 404)
        snapshot = source(self.root, rel)
        with self._lock:
            if len(self._jobs) >= 128:
                raise Refused("job history at capacity; restart desktop", 429)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "kind": kind, "file": rel, "status": "queued",
                   "source_sha256": snapshot["sha256"], "result": None,
                   "ledger_seq": None}
            self._jobs[job_id] = job
            self._record("studio_job_queued", {
                "id": job_id, "kind": kind, "file": rel,
                "source_sha256": snapshot["sha256"], "engine": engine,
                "depth": depth, "expr": expr})
            self._pool.submit(self._execute, job_id, snapshot, expr, engine, depth)
            return dict(job)

    def _execute(self, job_id: str, snapshot: dict, expr: str, engine: str, depth: int):
        with self._lock:
            self._jobs[job_id]["status"] = "running"
        try:
            if self._jobs[job_id]["kind"] == "syntax":
                result = syntax_diagnostics(snapshot["content"], snapshot["file"])
            else:
                from .formal import Property, prove
                from .formal.rtl_model import UnsupportedConstruct
                # Never auto-repair or mutate source during proof.
                try:
                    outcome = prove(snapshot["content"], [
                        Property.safety("studio_property", expr, source="studio-user")
                    ], engine=engine, depth=depth, budget=1,
                        repair=lambda *_: None, max_states=5000)
                    result = {"engine": engine, "depth": depth,
                              "results": [r.as_dict() for r in outcome["results"]],
                              "repaired": False}
                except (UnsupportedConstruct, ValueError, SyntaxError) as exc:
                    result = {"engine": engine, "depth": depth, "results": [{
                        "property": "studio_property", "status": "unknown",
                        "detail": str(exc)}]}
            state = "completed"
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
            state = "failed"
        try:
            current = source(self.root, snapshot["file"])["sha256"]
        except (Refused, OSError):
            current = None
        stale = current != snapshot["sha256"]
        with self._lock:
            evidence_digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
            record = self._record("studio_job_finished", {
                "id": job_id, "status": state, "result": result,
                "stale": stale, "source_sha256": snapshot["sha256"],
                "result_sha256": evidence_digest})
            self._jobs[job_id].update(status=state, result=result, stale=stale,
                                       result_sha256=evidence_digest,
                                       ledger_seq=record["seq"])

    def get(self, job_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise Refused("unknown job", 404)
            job = dict(self._jobs[job_id])
        if job["status"] == "completed":
            try:
                job["stale"] = source(self.root, job["file"])["sha256"] != job["source_sha256"]
            except (Refused, OSError):
                job["stale"] = True
        return job

    def list_jobs(self) -> dict:
        with self._lock:
            ids = list(self._jobs)[-50:]
        return {"jobs": [self.get(i) for i in ids]}

    def signoff(self, job_id: str, reviewer: str, decision: str) -> dict:
        if not isinstance(reviewer, str) or not 2 <= len(reviewer.strip()) <= 100:
            raise Refused("reviewer identity is required", 400)
        if decision not in ("accept", "reject"):
            raise Refused("decision must be accept or reject", 400)
        job = self.get(job_id)
        if job["status"] != "completed" or job.get("stale"):
            raise Refused("only completed, current evidence can be reviewed", 409)
        if not self._ledger.audit().ok:
            raise Refused("ledger audit failed", 409)
        if decision == "accept":
            if job["kind"] != "formal" or not job["result"].get("results") or not all(
                r.get("status") == "proof" for r in job["result"]["results"]
            ):
                raise Refused("acceptance requires a current formal proof, not a bounded check", 409)
        with self._lock:
            if self._jobs[job_id].get("review"):
                raise Refused("already reviewed; decisions are immutable", 409)
            record = self._record("studio_signoff_decision", {
                "job_id": job_id, "reviewer": reviewer.strip(), "decision": decision,
                "result_sha256": job["result_sha256"], "source_sha256": job["source_sha256"]})
            self._jobs[job_id]["review"] = {"decision": decision,
                                            "reviewer": reviewer.strip(), "ledger_seq": record["seq"]}
            return dict(self._jobs[job_id])

    def audit(self) -> dict:
        return self._ledger.audit().as_dict()

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


def crossprobe(root: str | Path, indexed_files: list[str], signal: str) -> dict:
    """Find precise whole-token signal references in indexed RTL source lines.

    A lexical cross-probe, not a resolved hierarchy/symbol table. No guess about
    which declaration a waveform signal refers to is made.
    """
    import re
    if not isinstance(signal, str) or not 1 <= len(signal) <= 256:
        raise Refused("signal must be 1..256 characters", 400)
    leaf = signal.rsplit(".", 1)[-1]
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9$]*", leaf):
        raise Refused("signal is not a valid HDL identifier", 400)
    pattern = re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(leaf) + r"(?![A-Za-z0-9_$])")
    results = []
    for rel in indexed_files[:200]:
        try:
            doc = source(root, rel)
        except (Refused, OSError):
            continue
        for number, line in enumerate(doc["content"].splitlines(), 1):
            if pattern.search(line):
                results.append({"file": rel, "line": number, "text": line[:240]})
                if len(results) >= 100:
                    break
        if len(results) >= 100:
            break
    return {"signal": signal, "leaf": leaf, "matches": results,
            "resolution": "lexical only; hierarchy and symbol ownership not proved"}
