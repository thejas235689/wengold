"""Durable multi-process studio job queue with leased claims.

SQLite transactions arbitrate multiple worker processes on *one shared filesystem*.
Workers never shell out and never auto-apply patches. This is not a cross-host
distributed broker: use a proper service/DB before spanning machines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from .studio_workspace import source
from .ide_server import Refused


class DurableQueue:
    def __init__(self, project: str | Path):
        self.root = Path(project).resolve()
        self.db = self.root / ".wengold-jobs.sqlite3"
        if not self.root.is_dir():
            raise Refused("project directory not found", 404)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL,
                spec TEXT NOT NULL, source TEXT NOT NULL, sha256 TEXT NOT NULL,
                status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                owner TEXT, lease_until REAL, result TEXT, result_sha256 TEXT,
                submitted REAL NOT NULL, updated REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(status,lease_until,submitted)")

    def connect(self):
        db = sqlite3.connect(str(self.db), timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def submit(self, kind: str, rel: str, expr: str = "", depth: int = 12) -> dict:
        if kind not in ("syntax", "formal", "pipeline"):
            raise Refused("unsupported job type")
        if not isinstance(depth, int) or not 1 <= depth <= 20:
            raise Refused("depth must be between 1 and 20")
        if kind != "syntax" and (not isinstance(expr, str) or not 1 <= len(expr) <= 240):
            raise Refused("bounded formal expression required")
        snap = source(self.root, rel)
        if len(snap["content"].encode()) > 2_000_000:
            raise Refused("RTL file too large")
        job_id = uuid.uuid4().hex
        now = time.time()
        spec = json.dumps({"expr": expr, "depth": depth}, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO jobs(id,kind,path,spec,source,sha256,status,submitted,updated)
                       VALUES(?,?,?,?,?,?,'queued',?,?)""",
                       (job_id, kind, rel, spec, snap["content"], snap["sha256"], now, now))
            db.commit()
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise Refused("unknown job", 404)
        result = {k: row[k] for k in ("id", "kind", "path", "status", "attempt", "owner",
                                      "lease_until", "sha256", "result_sha256")}
        result["result"] = json.loads(row["result"]) if row["result"] else None
        try:
            result["stale"] = source(self.root, row["path"])["sha256"] != row["sha256"]
        except (Refused, OSError):
            result["stale"] = True
        return result

    def list_jobs(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            ids = [r[0] for r in db.execute(
                "SELECT id FROM jobs ORDER BY submitted DESC LIMIT ?", (max(1, min(limit, 200)),))]
        return [self.get(i) for i in ids]

    def claim(self, worker: str, lease_seconds: int = 120, max_attempts: int = 3) -> dict | None:
        if not worker or len(worker) > 100:
            raise Refused("worker identity invalid")
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # At-least-once execution. Expired work is requeued unless attempts are exhausted.
            db.execute("""UPDATE jobs SET status='failed', updated=?, result=?
                       WHERE status='running' AND lease_until<? AND attempt>=?""",
                       (now, json.dumps({"error": "worker lease expired; retry limit reached"}), now, max_attempts))
            db.execute("""UPDATE jobs SET status='queued',owner=NULL,lease_until=NULL,updated=?
                       WHERE status='running' AND lease_until<? AND attempt<?""",
                       (now, now, max_attempts))
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY submitted,id LIMIT 1").fetchone()
            if row is None:
                db.commit()
                return None
            db.execute("""UPDATE jobs SET status='running',owner=?,lease_until=?,
                       attempt=attempt+1,updated=? WHERE id=? AND status='queued'""",
                       (worker, now + lease_seconds, now, row["id"]))
            db.commit()
            return {"id": row["id"], "kind": row["kind"], "path": row["path"],
                    "spec": json.loads(row["spec"]), "source": row["source"],
                    "sha256": row["sha256"], "attempt": row["attempt"]+1}

    def renew(self, job_id: str, worker: str, attempt: int, seconds: int = 120) -> bool:
        with self.connect() as db:
            cur = db.execute("""UPDATE jobs SET lease_until=?,updated=?
                            WHERE id=? AND owner=? AND attempt=? AND status='running'""",
                             (time.time()+seconds, time.time(), job_id, worker, attempt))
            return cur.rowcount == 1

    def finish(self, claim: dict, worker: str, result: dict) -> bool:
        # Fencing by owner AND attempt prevents a crashed worker overwriting
        # evidence produced by a worker holding a later lease.
        encoded = json.dumps(result, sort_keys=True, default=str)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connect() as db:
            cur = db.execute("""UPDATE jobs SET status='completed',result=?,result_sha256=?,
                updated=?,lease_until=NULL WHERE id=? AND owner=? AND attempt=?
                AND status='running' AND lease_until>=?""",
                (encoded, digest, time.time(), claim["id"], worker, claim["attempt"], time.time()))
            return cur.rowcount == 1

    @staticmethod
    def execute(claim: dict) -> dict:
        from .studio_jobs import syntax_diagnostics
        spec = claim["spec"]
        kind = claim["kind"]
        stages = []
        if kind in ("syntax", "pipeline"):
            diag = syntax_diagnostics(claim["source"], claim["path"])
            stages.append({"stage": "syntax", "result": diag})
            if kind == "syntax":
                return {"stages": stages, "status": diag["status"]}
            if diag["status"] != "clean":
                return {"stages": stages, "status": "unknown",
                        "detail": "formal not run because syntax did not pass"}
        from .formal import Property, prove
        try:
            proof = prove(claim["source"],
                          [Property.safety("studio_property", spec["expr"], source="studio-user")],
                          engine="explicit", depth=spec["depth"], budget=1,
                          repair=lambda *_: None, max_states=5000)
            result = [x.as_dict() for x in proof["results"]]
        except Exception as exc:
            result = [{"status": "unknown", "detail": f"{type(exc).__name__}: {exc}"}]
        stages.append({"stage": "formal", "results": result})
        return {"stages": stages, "results": result, "status": "completed"}

    def work_once(self, worker: str | None = None) -> dict | None:
        worker = worker or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        claim = self.claim(worker, lease_seconds=600)
        if claim is None:
            return None
        try:
            result = self.execute(claim)
        except BaseException as exc:
            # Retry is intentionally not automatic on caught runtime errors;
            # unknown is conservative, and crash recovery uses lease expiry.
            result = {"status": "unknown", "error": f"{type(exc).__name__}: {exc}"}
        accepted = self.finish(claim, worker, result)
        return {"job_id": claim["id"], "committed": accepted, "result": result}


def main():
    parser = argparse.ArgumentParser(description="WENGOLD durable local multi-worker queue")
    parser.add_argument("project")
    parser.add_argument("--worker", action="store_true", help="poll this project's queue")
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()
    queue = DurableQueue(args.project)
    if not args.worker:
        parser.error("specify --worker")
    while True:
        out = queue.work_once()
        if out is not None:
            print(json.dumps(out, default=str), flush=True)
        if args.once:
            return
        time.sleep(max(.1, min(30, args.sleep)))


if __name__ == "__main__":
    main()
