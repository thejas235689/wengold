"""A local server behind the IDE page: edit, save, build.

The page was a snapshot — everything embedded at build time, no backend. That made
it safe (a static file cannot damage anything) and useless for editing. This module
adds the backend, and the whole design is about making one narrow capability safe:

    the page may write **only** files that already exist **inside the project root**

That is deliberately stricter than "an editor":

  * **bind to loopback only.** No wildcard address, no LAN exposure. A file-writing
    HTTP endpoint reachable from the network is a remote code execution surface.
  * **root-confined.** Every path is resolved and must sit under the project root
    after `resolve()`, so a parent-relative path and a symlink pointing out both
    fail the same check.
  * **existing files only.** Save cannot create a new file. Creation needs a name
    the user chose in a shell, not one a request supplied.
  * **source extensions only.** The same set the indexer reads. Save cannot write a
    `.sh` or a `.py` that something later executes.
  * **a per-run token.** Every mutating request carries it, so another page open in
    the same browser cannot drive this one (CSRF).
  * **no build command from the request.** `build` runs the checks this module
    chooses; the client cannot name a command to run.

Anything refused is refused with a reason and a status code. Nothing is silently
dropped, and a failed save never reports success.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

__all__ = ["save_file", "run_build", "suggest", "serve", "SOURCE_SUFFIXES"]

# The same extensions the indexer reads. Writing outside this set would let a
# request drop an executable or a config file next to the design.
SOURCE_SUFFIXES = {".sv", ".svh", ".v", ".vh", ".vhd", ".vhdl"}

MAX_BODY = 4 * 1024 * 1024          # 4 MB: larger than any hand-written source


class Refused(Exception):
    """A request this server will not perform, with the reason it will not."""

    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def _confine(root: Path, rel: str) -> Path:
    """Resolve `rel` under `root`, or refuse.

    Both the lexical check and the resolved check are needed: the first catches
    `..` in the request, the second catches a symlink inside the project that
    points outside it.
    """
    if not rel or "\x00" in rel:
        raise Refused("empty or invalid path")
    p = Path(rel)
    if p.is_absolute():
        raise Refused("absolute paths are not accepted; send a path relative to the project")

    root_r = root.resolve()
    target = (root_r / p).resolve()

    # resolved target must be inside the resolved root
    try:
        target.relative_to(root_r)
    except ValueError:
        raise Refused(f"{rel!r} resolves outside the project root") from None

    return target


def save_file(root: Path, rel: str, content: str) -> dict:
    """Write `content` to an existing source file inside the project.

    Returns what was written. Raises `Refused` for anything this server will not
    do — a refusal is a result, never a silent no-op.
    """
    if not isinstance(content, str):
        raise Refused("content must be a string")
    if len(content.encode("utf-8", "replace")) > MAX_BODY:
        raise Refused(f"content larger than {MAX_BODY // 1024 // 1024} MB")

    target = _confine(Path(root), rel)

    if target.suffix.lower() not in SOURCE_SUFFIXES:
        raise Refused(
            f"{target.suffix or '(no extension)'} is not a source file; "
            f"this server writes only {sorted(SOURCE_SUFFIXES)}")

    if not target.exists():
        raise Refused(f"{rel!r} does not exist; this server does not create files",
                      status=404)
    if not target.is_file():
        raise Refused(f"{rel!r} is not a regular file")

    before = target.read_text(encoding="utf-8", errors="replace")
    if before == content:
        return {"path": rel, "changed": False, "bytes": len(before),
                "note": "identical to what was on disk; nothing written"}

    target.write_text(content, encoding="utf-8")
    after = target.read_text(encoding="utf-8", errors="replace")
    if after != content:
        # A write that did not round-trip is not a save.
        raise Refused(f"{rel!r} did not read back as written", status=500)

    return {"path": rel, "changed": True, "bytes": len(after),
            "before_bytes": len(before)}


def run_build(root: Path, backend: str = "auto") -> dict:
    """Re-index the project and report what the kernel now sees.

    The client cannot choose the command: this is the check. A build that cannot
    run reports the reason rather than an empty success.
    """
    from .graph.builder import GraphBuilder
    from .graph.slang_backend import available as slang_available

    root = Path(root)
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES:
            try:
                files[str(p)] = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return {"ok": False, "error": f"could not read {p.name}: {exc}"}

    if not files:
        return {"ok": False, "error": "no source files found", "files": 0}

    try:
        g = GraphBuilder().build_from_files(files, backend=backend)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"index failed: {exc}"}

    return {
        "ok": True,
        "files": len(files),
        "blocks": sum(1 for n in g.nodes.values()
                      if str(getattr(n, "kind", "")).endswith("MODULE")),
        "nodes": len(g.nodes),
        "edges": len(g.edges),
        "notes": list(g.notes),
        "slang": slang_available(),
        "backend": backend,
    }


MAX_CONTEXT = 6000          # characters of source handed to the model


def _kernel_facts(root: Path, backend: str = "auto") -> str:
    """The facts the suggestion is grounded in, as text the model can read.

    A model asked "how do I improve this file" with no facts produces generic
    advice. Given the graph's actual complaints it can be specific — and the same
    facts are shown to the user, so the suggestion can be checked against them.
    """
    b = run_build(root, backend)
    if not b.get("ok"):
        return f"the project could not be indexed: {b.get('error')}"
    lines = [f"files {b['files']}, blocks {b['blocks']}, nodes {b['nodes']}, "
             f"edges {b['edges']}"]
    for n in b.get("notes") or []:
        lines.append(f"note: {n}")
    if not b.get("slang"):
        lines.append("the real SystemVerilog parser (pyslang) is not installed, "
                     "so the block count is an under-estimate")
    return "\n".join(lines)


def suggest(root: Path, rel: str = "", backend: str = "auto") -> dict:
    """Ask the configured local model for a suggestion about this project.

    Three states, and they are different:
      * no model configured  -> ok=False, kind="note"  (nothing is wrong)
      * the model failed     -> ok=False, kind="error"
      * a suggestion         -> ok=True, with `facts` alongside it

    The facts are always returned, model or no model — the same rule the app's
    `explain` command follows. A suggestion without the facts it rests on cannot
    be checked, and a suggestion is never written to a file.
    """
    from .agent.llm import LLMUnavailable, from_env

    facts = _kernel_facts(root, backend)
    model = from_env()
    if model is None:
        return {"ok": False, "kind": "note", "facts": facts,
                "error": "no local model configured",
                "hint": ("set WENGOLD_LLM_MODEL and run a local server; "
                         "`wengold doctor --presets` lists the models this "
                         "project knows. Everything else works without one.")}

    source = ""
    if rel:
        try:
            target = _confine(Path(root), rel)
            source = target.read_text(encoding="utf-8", errors="replace")[:MAX_CONTEXT]
        except (Refused, OSError) as exc:
            return {"ok": False, "kind": "error", "facts": facts,
                    "error": f"could not read {rel!r}: {exc}"}

    prompt = (
        "You are reviewing a hardware design for a silicon verification tool.\n"
        "Answer in at most 6 short lines. Be concrete: name the signal or the line.\n"
        "If you cannot tell from what you are given, say so instead of guessing.\n\n"
        f"What the tool established (these are facts, not your opinion):\n{facts}\n\n"
        + (f"File under review: {rel}\n```systemverilog\n{source}\n```\n\n"
           if source else "")
        + "What should the engineer look at first, and why?"
    )
    try:
        answer = model.ask(prompt)
    except LLMUnavailable as exc:
        return {"ok": False, "kind": "error", "facts": facts,
                "error": f"model unavailable: {exc}"}

    return {"ok": True, "facts": facts, "suggestion": answer,
            "model": model.model,
            "note": "a suggestion from a local model, not a check. It was not "
                    "verified against the design and nothing was written."}


def _handler(root: Path, token: str, render):
    """Build the request handler. `render()` returns the current page HTML."""

    class H(BaseHTTPRequestHandler):
        server_version = "wengold-ide"

        def log_message(self, *a):        # quiet: the page reports its own errors
            pass

        # -- helpers -------------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _auth(self):
            """A mutating request must carry this run's token."""
            got = self.headers.get("X-Wengold-Token", "")
            if not secrets.compare_digest(got, token):
                raise Refused("missing or wrong token for a mutating request",
                              status=403)

        # -- routes --------------------------------------------------------
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, render().encode(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._json(200, {"token": token, "root": str(Path(root).resolve())})
            else:
                self._json(404, {"error": "no such path"})

        def do_POST(self):
            try:
                self._auth()
                n = int(self.headers.get("Content-Length", 0))
                if n > MAX_BODY:
                    raise Refused("request body too large", status=413)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise Refused("body is not JSON") from None
                if not isinstance(body, dict):
                    raise Refused("body must be a JSON object")

                if self.path == "/api/save":
                    res = save_file(Path(root), body.get("path", ""),
                                    body.get("content", ""))
                    self._json(200, res)
                elif self.path == "/api/suggest":
                    res = suggest(Path(root), body.get("path", ""),
                                  body.get("backend", "auto"))
                    self._json(200 if res.get("ok") else 422, res)
                elif self.path == "/api/build":
                    res = run_build(Path(root), body.get("backend", "auto"))
                    self._json(200 if res.get("ok") else 500, res)
                else:
                    self._json(404, {"error": "no such path"})
            except Refused as e:
                self._json(e.status, {"error": e.reason, "refused": True})
            except Exception as exc:                             # noqa: BLE001
                # An unexpected failure is reported, never a 200 with no work done.
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    return H


def serve(root: Path, render, port: int = 0, open_browser: bool = True) -> int:
    """Serve the IDE on 127.0.0.1. Returns the port it bound to."""
    root = Path(root).resolve()
    token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(root, token, render))
    bound = httpd.server_address[1]
    url = f"http://127.0.0.1:{bound}/"

    if open_browser:
        import webbrowser
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()

    # flush: a server runs until interrupted, and a block-buffered stdout means a
    # piped user sees the URL never. The line that tells you where it is must
    # appear immediately.
    print(f"  WENGOLD IDE  {url}", flush=True)
    print(f"  root  {root}", flush=True)
    print("  writes are confined to this root; loopback only; interrupt to stop",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()
    return bound
