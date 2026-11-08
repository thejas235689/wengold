#!/usr/bin/env python3
"""Run WENGOLD's model client against a *real* model, over real HTTP.

The client was tested against a mock for three releases because the machine it was
written on had 2 CPUs and 2 GB of RAM. A mock proves the request shape and the
failure paths; it cannot prove the client survives real tokenization, real
generation latency, or the shape a real model actually returns. This script does.

    python3 tools/verify-real-model.py                       # 135M, ~260 MB
    python3 tools/verify-real-model.py --model <hf-id>       # anything that fits
    python3 tools/verify-real-model.py --model sarvamai/sarvam-1 --tokens 64

It loads the model with transformers, serves it on an OpenAI-compatible endpoint,
and drives `wengold.agent.llm` at it: probe, ask, explain_failure, draft_rtl. It
prints what came back and whether it was fenced, which is how the markdown-fence
defect was found on the first run.

Needs: `pip install torch transformers` and enough RAM for the model. A 135M model
needs ~1 GB; Sarvam-1 (2B) needs ~5 GB; Sarvam-M (24B) needs ~16 GB at Q4 and cannot
be loaded this way at all — serve it with vLLM and point `WENGOLD_LLM_URL` at it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEFAULT = "HuggingFaceTB/SmolLM2-135M-Instruct"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT)
    ap.add_argument("--tokens", type=int, default=48)
    ap.add_argument("--cache", default=str(Path.home() / ".cache" / "wengold-hf"))
    args = ap.parse_args()

    os.environ.setdefault("HF_HOME", args.cache)
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print("  needs: pip install torch transformers", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from wengold.agent.llm import LocalModel, probe

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float16)
    model.eval()
    n = sum(p.numel() for p in model.parameters()) / 1e6
    print(f"  loaded {args.model} — {n:.0f}M params in {time.time() - t0:.1f}s")

    def generate(messages: list[dict]) -> str:
        text = tok.apply_chat_template(messages, tokenize=False,
                                       add_generation_prompt=True)
        ids = tok(text, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=args.tokens, do_sample=False,
                                 temperature=None, top_p=None,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, obj: dict) -> None:
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._send(200, {"data": [{"id": args.model}]})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            msgs = body.get("messages") or [{"role": "user",
                                             "content": body.get("prompt", "")}]
            started = time.time()
            try:
                text = generate(msgs)
            except Exception as e:                                # noqa: BLE001
                self._send(500, {"error": f"{type(e).__name__}: {e}"})
                return
            print(f"    [{time.time() - started:5.1f}s] {text.strip()[:70]!r}")
            self._send(200, {"choices": [{"message": {"content": text},
                                          "finish_reason": "stop"}]})

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"

    print("\n  1. probe")
    print("    ", probe(url, "openai", timeout=10).render().strip())

    m = LocalModel(args.model, url, "openai", timeout=300)

    print("\n  2. ask")
    print("    ", m.ask("In one sentence, what does a two-flop synchroniser do?")[:160])

    print("\n  3. explain_failure")
    print("    ", m.explain_failure("timer_sim: INVALIDATED — depends on "
                                    "changed node ['timer']")[:160])

    print("\n  4. draft_rtl")
    d = m.draft_rtl("a 4-bit counter with an enable")
    print("     fenced:", d.startswith(("```", "~~~")),
          "| first line:", repr(d.splitlines()[0] if d.splitlines() else ""))

    srv.shutdown()
    print(f"\n  {m.calls} real call(s) completed — the client works against a real "
          f"model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
