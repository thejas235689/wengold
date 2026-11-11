"""Local Silicon Studio workspace: guarded RTL editing and evidence inspection.

All paths are confined to the chosen project. No shell execution is exposed.
Formal reports are *viewed*, never synthesized or invented by this dashboard.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .ide_server import Refused, SOURCE_SUFFIXES, MAX_BODY
from .wave import from_vcd

MAX_VCD_BYTES = 8 * 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024


def project_file(root: str | Path, rel: str, suffixes: set[str]) -> Path:
    base = Path(root).resolve()
    if not rel or "\x00" in rel or Path(rel).is_absolute():
        raise Refused("invalid project-relative path")
    path = (base / rel).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise Refused("path escapes project root", 403) from None
    if path.suffix.lower() not in suffixes or not path.is_file():
        raise Refused("unsupported or missing project file", 404)
    return path


def source(root: str | Path, rel: str) -> dict:
    path = project_file(root, rel, SOURCE_SUFFIXES)
    if path.stat().st_size > MAX_BODY:
        raise Refused("source file exceeds editor limit", 413)
    data = path.read_bytes()
    return {"file": rel, "content": data.decode("utf-8", "replace"),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def save_source(root: str | Path, rel: str, content: str, expected_sha256: str) -> dict:
    path = project_file(root, rel, SOURCE_SUFFIXES)
    if not isinstance(content, str) or not isinstance(expected_sha256, str):
        raise Refused("content and expected_sha256 are required")
    raw = content.encode("utf-8")
    if len(raw) > MAX_BODY:
        raise Refused("source file exceeds editor limit", 413)
    current = path.read_bytes()
    if hashlib.sha256(current).hexdigest() != expected_sha256:
        raise Refused("file changed on disk; reopen before saving", 409)
    changed = current != raw
    if changed:
        path.write_bytes(raw)
    return {"ok": True, "changed": changed, "file": rel,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "note": "Re-index the project to refresh validity verdicts." if changed else "No changes"}


def list_evidence(root: str | Path) -> dict:
    base = Path(root).resolve()
    vcd, formal = [], []
    # Search only conventional evidence directories; do not crawl huge checkout trees.
    dirs = [base / n for n in ("waveforms", "waves", "sim", "results", "formal-results", "reports")]
    for folder in dirs:
        if not folder.is_dir() or not folder.resolve().is_relative_to(base):
            continue
        for path in sorted(folder.glob("**/*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                rel = str(path.relative_to(base))
                size = path.stat().st_size
            except OSError:
                continue
            if path.suffix.lower() == ".vcd" and size <= MAX_VCD_BYTES:
                vcd.append(rel)
            elif path.suffix.lower() == ".json" and size <= MAX_REPORT_BYTES:
                formal.append(rel)
            if len(vcd) + len(formal) >= 200:
                break
    return {"waveforms": vcd[:100], "formal_reports": formal[:100]}


def waveform(root: str | Path, rel: str) -> dict:
    path = project_file(root, rel, {".vcd"})
    if path.stat().st_size > MAX_VCD_BYTES:
        raise Refused("VCD exceeds 8 MB viewer limit", 413)
    result = from_vcd(path)
    result["source"] = rel
    # Cap payload size without inventing any samples. Full-resolution source remains on disk.
    result["signals"] = result["signals"][:256]
    for sig in result["signals"]:
        sig["values"] = sig["values"][:1200]
    result["times"] = result.get("times", [])[:1200]
    result["cycles"] = min(result["cycles"], 1200)
    return result


def formal_report(root: str | Path, rel: str) -> dict:
    path = project_file(root, rel, {".json"})
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise Refused("formal report exceeds 2 MB viewer limit", 413)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise Refused(f"invalid JSON report: {exc}") from exc
    if not isinstance(payload, (dict, list)):
        raise Refused("formal report must contain an object or array")
    # Return source data unmodified: status remains the producer's claim.
    return {"file": rel, "report": payload, "note":
            "Unverified imported report; inspect tool, property, assumptions and run provenance."}
