"""Local, manifest-scoped retrieval for hardware engineering drafts."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .graph.regmap import parse_ipxact, parse_rdl

SV = {".sv", ".svh", ".v", ".vh"}
SUFFIXES = {
    "rtl": SV, "sva": SV, "spec": {".md", ".rst", ".txt", ".pdf"},
    "registers": {".json", ".rdl", ".xml"}, "diagram": {".json"},
}
MAX_FILE = 512 * 1024
MAX_PDF = 12 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_CHUNK = 2400
MAX_CHUNKS = 5000
TOKEN = re.compile(r"0x[0-9a-f]+|[a-z_$][a-z0-9_$]*|[0-9]+", re.I | re.ASCII)
IDENT = r"[a-zA-Z_][\w$]*"
SV_TEXT = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"', re.S)
UNIT = re.compile(
    rf"\b(module|interface|package|program|checker|class)\s+({IDENT})\b"
    rf".*?\bend\1\b(?:\s*:\s*{IDENT})?", re.S)
SV_INCLUDES = re.compile(r'`include\s+"([^"\n]+)"')
KINDS = {"ModuleDeclaration", "InterfaceDeclaration", "PackageDeclaration",
         "ProgramDeclaration", "CheckerDeclaration", "ClassDeclaration"}
REFS = re.compile(rf"\b({IDENT})::")
TERM_EXPANSIONS = {
    "timing": "cycle latency clock edge handshake ready valid",
    "reset": "reset rst rst_n reset_n clear initialization",
    "register": "register csr address offset field bits mask access reset-value",
    "assertion": "assert property assume cover sva vacuity",
    "interface": "interface port modport package parameter",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{path.name} exceeds the {limit}-byte limit")
    return data


def _file(root: Path, rel: str, suffixes: set[str]) -> Path:
    if not isinstance(rel, str) or not rel or len(rel) > 512 or "\\" in rel:
        raise ValueError("expected a project-relative file path")
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"invalid project-relative path: {rel}")
    target = (root / p).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"missing file or path outside project: {rel}")
    if target.suffix.lower() not in suffixes:
        raise ValueError(f"unsupported file for its Multi-RAG role: {rel}")
    return target


def _tokens(text: str) -> Counter:
    terms = TOKEN.findall(text.lower())
    return Counter(terms + [p for t in terms if "_" in t
                            for p in t.split("_") if p])


def _vector(terms: Counter) -> dict[int, float]:
    """A local character n-gram feature-hash vector, not a neural embedding."""
    vec: dict[int, float] = defaultdict(float)
    for term in terms:
        s = "^" + term + "$"
        for i in range(max(len(s) - 2, 1)):
            h = int.from_bytes(hashlib.blake2s(s[i:i + 3].encode(), digest_size=2).digest(),
                               "little")
            vec[h % 256] += 1 if h & 256 else -1
    norm = math.sqrt(sum(x * x for x in vec.values())) or 1
    return {k: v / norm for k, v in vec.items() if v}


def _mask(text: str) -> str:
    return SV_TEXT.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)


def _tree(text: str, name: str, sm=None):
    import pyslang as slang
    from pyslang import parsing, syntax

    sm = slang.SourceManager() if sm is None else sm
    opts = parsing.PreprocessorOptions()
    # Never open an arbitrary include path from indexed or generated code.
    opts.maxIncludeDepth = 0
    bag = slang.Bag()
    bag.preprocessorOptions = opts
    return syntax.SyntaxTree.fromText(text, sm, name, "", bag)


def _units(text: str, name: str) -> tuple[list, str]:
    """Return source spans with design-unit names and dependency symbols."""
    masked = _mask(text)
    include_names = {m[1] for m in SV_INCLUDES.finditer(text)
                     if masked[m.start():m.start() + 8] == "`include"}
    try:
        tree = _tree(text, name)
    except ImportError:
        tree = None
    units = []
    backend = "slang_syntax" if tree is not None else "bounded_text"
    if tree is not None:
        root = tree.root
        members = root.members if str(root.kind).endswith(".CompilationUnit") else [root]
        raw = text.encode()
        for node in members:
            if str(node.kind).split(".")[-1] not in KINDS:
                continue
            header = getattr(node, "header", node)
            symbol = getattr(getattr(header, "name", None), "valueText", "")
            start, end = node.sourceRange.start.offset, node.sourceRange.end.offset
            if not symbol or not (0 <= start < end <= len(raw)):
                continue
            deps = set(include_names)

            def visit(item):
                kind = str(item.kind)
                if kind.endswith(".HierarchyInstantiation"):
                    deps.add(item.type.valueText)
                elif kind.endswith(".PackageImportItem"):
                    deps.add(item.package.valueText)

            node.visit(visit)
            body = raw[start:end].decode(errors="replace")
            deps.update(REFS.findall(_mask(body)))
            units.append((raw[:start].count(b"\n") + 1, body, symbol, deps))
    if not units:
        backend = "bounded_text"
        units = [(text.count("\n", 0, m.start()) + 1, text[m.start():m.end()], m[2],
                  set(REFS.findall(m[0])) | include_names)
                 for m in UNIT.finditer(masked)]
    if not units:
        units = [(1, text, Path(name).name, set(REFS.findall(masked)) | include_names)]
    return units, backend


def _blocks(text: str, size=MAX_CHUNK):
    """Yield bounded, non-overlapping excerpts with source line ranges."""
    start = 0
    line = 1
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary != -1:
                end = boundary + 1
        block = text[start:end]
        newlines = block.count("\n")
        if block.strip():
            yield line, line + newlines - int(block.endswith("\n")), block
        start, line = end, line + newlines


@dataclass(frozen=True)
class Entry:
    kind: str
    path: str
    location: str
    text: str
    sha256: str
    symbol: str = ""
    refs: tuple[str, ...] = ()
    facts: dict = field(default_factory=dict)
    asset: str | None = None
    asset_sha256: str | None = None

    def citation(self) -> dict:
        result = {key: getattr(self, key) for key in
                  ("kind", "path", "location", "symbol", "sha256")}
        if self.asset is not None:
            result.update(asset=self.asset, asset_sha256=self.asset_sha256)
        return result


def _rows(data, key: str) -> list:
    rows = data.get(key) if isinstance(data, dict) else None
    # All structured records on this path must be objects, no implicit schemas.
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        raise ValueError(f"expected a nonempty '{key}' array of objects")
    return rows


def _structured_fields(row: dict) -> dict:
    fields = {}
    items = row.get("fields", [])
    if not isinstance(items, list):
        raise ValueError("fields must be an array")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("fields require a name")
        name = item["name"].lower()
        if name in fields:
            raise ValueError(f"duplicate field: {name}")
        fields[name] = {k: v for k, v in item.items() if k != "name"}
    return fields


def _number(value):
    if isinstance(value, str):
        try:
            return int(value, 16 if value.lower().startswith("0x") else 10)
        except ValueError:
            pass
    return value


def _facts(scope: str, row: dict) -> dict:
    keys = ("address", "width", "access", "sw", "hw", "reset", "msb", "lsb")
    numeric = {"address", "width", "reset", "msb", "lsb"}
    fields = _structured_fields(row)
    named = [(scope, row)] + [(f"{scope}.{name}", values) for name, values in fields.items()]
    return {f"{name}.{('sw' if key == 'access' else key)}":
            _number(values[key]) if key in numeric else str(values[key]).lower()
            for name, values in named for key in keys if values.get(key) is not None}


def _pdf_pages(raw: bytes):
    exe = shutil.which("pdftotext")
    if not exe:
        raise ValueError("pdftotext is required for PDF text ingestion")
    with tempfile.TemporaryFile() as output:
        run = subprocess.run([exe, "-f", "1", "-l", "20", "-layout", "-", "-"],
                             input=raw, stdout=output, stderr=subprocess.DEVNULL,
                             timeout=10, check=False)
        if run.returncode:
            raise ValueError("PDF text extraction failed")
        output.seek(0)
        extracted = output.read(MAX_FILE + 1)
    if len(extracted) > MAX_FILE:
        raise ValueError("extracted PDF text exceeds the Multi-RAG limit")
    pages = extracted.decode("utf-8", errors="replace").split("\f")
    return [(n, page) for n, page in enumerate(pages, 1) if page.strip()]


@dataclass
class MultiRAG:
    entries: list[Entry]
    notes: list[str]
    compile_files: dict[str, str]
    _terms: list[Counter] = field(init=False, repr=False)
    _vectors: list[dict] = field(init=False, repr=False)
    _df: Counter = field(init=False, repr=False)
    _avg: float = field(init=False, repr=False)
    _symbols: dict = field(init=False, repr=False)
    _facts: dict = field(init=False, repr=False)

    def __post_init__(self):
        self._terms = [_tokens(f"{e.symbol} {e.path} {e.text}") for e in self.entries]
        self._vectors = [_vector(t) for t in self._terms]
        self._df = Counter(k for t in self._terms for k in t)
        self._avg = sum(map(sum, (t.values() for t in self._terms))) / max(len(self.entries), 1)
        self._symbols = defaultdict(list)
        self._facts = defaultdict(list)
        for i, e in enumerate(self.entries):
            for s in {e.symbol, Path(e.path).name} - {""}:
                self._symbols[s.lower()].append(i)
            for key, value in e.facts.items():
                self._facts[key].append((i, value))

    @classmethod
    def load(cls, root: str | Path, manifest: str = "multi-rag.json") -> MultiRAG:
        root = Path(root).resolve()
        mp = _file(root, manifest, {".json"})
        config = json.loads(_read(mp, MAX_FILE))
        items = _rows(config, "sources")
        if len(items) > 160:
            raise ValueError("Multi-RAG manifest may name at most 160 sources")
        scanned = set()
        entries: list[Entry] = []
        notes = []
        sv_files = {}
        total_bytes = 0
        for item in items:
            kind, rel = item.get("kind"), item.get("path")
            if not isinstance(kind, str) or kind not in SUFFIXES:
                raise ValueError(f"unknown Multi-RAG source kind: {kind}")
            path = _file(root, rel, SUFFIXES[kind])
            rel = Path(rel).as_posix()
            if path == mp or path in scanned:
                raise ValueError(f"duplicate source or manifest used as source: {rel}")
            scanned.add(path)
            raw = _read(path, MAX_PDF if path.suffix.lower() == ".pdf" else MAX_FILE)
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL:
                raise ValueError("Multi-RAG source set exceeds the total byte limit")
            digest = _sha(raw)
            text = "" if path.suffix.lower() == ".pdf" else raw.decode("utf-8")
            if kind in {"rtl", "sva"}:
                sv_files[rel] = text
                units, backend = _units(text, rel)
                if backend != "slang_syntax":
                    notes.append(f"{rel}: bounded text units; install pyslang for syntax indexing")
                for line, body, symbol, deps in units:
                    for a, b, chunk in _blocks(body):
                        entries.append(Entry(kind, rel, f"L{line+a-1}-L{line+b-1}",
                                             chunk, digest, symbol, tuple(sorted(deps))))
            elif kind == "registers":
                if path.suffix.lower() == ".json":
                    data = json.loads(text)
                else:
                    parsed = (parse_rdl if path.suffix.lower() == ".rdl" else parse_ipxact)(text)
                    data = parsed.as_dict()
                    notes.extend(f"{rel}: {issue}" for issue in parsed.check())
                scope = item.get("scope", data.get("name") if isinstance(data, dict) else None)
                if not isinstance(scope, str) or not scope.strip():
                    raise ValueError(f"{rel}: register map needs a name or manifest scope")
                for n, row in enumerate(_rows(data, "registers")):
                    symbol = row.get("name")
                    if not isinstance(symbol, str) or not symbol.strip():
                        raise ValueError(f"{rel}: each register needs a name")
                    scoped = f"{scope}.{symbol}"
                    serialized = json.dumps(row, ensure_ascii=False, sort_keys=True)
                    if len(serialized) > MAX_CHUNK:
                        raise ValueError(f"{rel}: register {symbol} exceeds the entry limit")
                    entries.append(Entry(kind, rel, f"/registers/{n}", serialized, digest,
                                         scoped, facts=_facts(scoped.lower(), row)))
            elif kind == "diagram":
                for n, row in enumerate(_rows(json.loads(text), "captions")):
                    caption = row.get("text")
                    if not isinstance(caption, str) or not caption.strip() or len(caption) > MAX_CHUNK:
                        raise ValueError(f"{rel}: diagram caption needs bounded text")
                    asset = row.get("asset")
                    ref = _file(root, asset, {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".webp"})
                    # Index the supplied caption only. Bind it to the exact local image revision.
                    asset_bytes = _read(ref, MAX_PDF)
                    total_bytes += len(asset_bytes)
                    if total_bytes > MAX_TOTAL:
                        raise ValueError("Multi-RAG source set exceeds the total byte limit")
                    entries.append(Entry(kind, rel, f"/captions/{n}", caption, digest,
                                         Path(asset).stem, asset=asset,
                                         asset_sha256=_sha(asset_bytes)))
            else:
                pdf = path.suffix.lower() == ".pdf"
                pages = _pdf_pages(raw) if pdf else [(None, text)]
                if pdf:
                    notes.append(f"{rel}: text extraction only, pages 1–20; no OCR or diagram reading")
                    if not pages:
                        notes.append(f"{rel}: no extractable PDF text, supply reviewed captions")
                for page, body in pages:
                    for a, b, chunk in _blocks(body):
                        loc = f"L{a}-L{b}" if page is None else f"page {page}, text L{a}-L{b}"
                        entries.append(Entry(kind, rel, loc, chunk, digest))
            if len(entries) > MAX_CHUNKS:
                raise ValueError("Multi-RAG index exceeds the excerpt limit")
        compile_names = config.get("compile_files", [])
        if (not isinstance(compile_names, list) or
                not all(isinstance(n, str) and n in sv_files for n in compile_names) or
                len(compile_names) != len(set(compile_names))):
            raise ValueError("compile_files must contain distinct paths from RTL/SVA sources")
        if not entries:
            raise ValueError("Multi-RAG manifest produced no indexable excerpts")
        return cls(entries, notes, {n: sv_files[n] for n in compile_names})

    def _rank(self, query: str, candidates: list[int]) -> list[list[int]]:
        q = _tokens(query)
        v = _vector(q)
        results = []
        for dense in (False, True):
            scores = []
            for i in candidates:
                terms = self._terms[i]
                if dense:
                    score = sum(weight * self._vectors[i].get(k, 0) for k, weight in v.items())
                else:
                    length = sum(terms.values()) / (self._avg or 1)
                    score = sum(math.log1p((len(self.entries) - self._df[t] + .5) /
                                           (self._df[t] + .5)) *
                                (2.5 * terms[t] / (terms[t] + .375 + 1.125 * length))
                                for t in q if t in terms)
                if score > (.18 if dense else 0):
                    scores.append((-score, i))
            results.append([i for _, i in sorted(scores)[:16]])
        return results

    def retrieve(self, query: str, *, symbols: tuple[str, ...] = (), limit: int = 8) -> dict:
        if not query.strip() or len(query) > 15000 or not 1 <= limit <= 12:
            raise ValueError("Multi-RAG needs a query up to 15000 characters and limit 1..12")
        # Route subqueries by requirement facet. Search across all indices for the
        # original task, and specialise only when its vocabulary supports it.
        facets = {"rtl": ("module", "rtl", "port", "interface", "parameter", "package"),
                  "spec": ("timing", "clock", "latency", "handshake", "reset", "protocol"),
                  "registers": ("register", "csr", "ral", "field", "address", "offset"),
                  "sva": ("assertion", "assert", "property", "sva", "cover", "formal"),
                  "diagram": ("diagram", "waveform", "timing", "clock", "handshake")}
        q_terms = _tokens(query)
        rrf: dict[int, float] = defaultdict(float)

        def fuse(q, pool, weight):
            for hits in self._rank(q, pool):
                for rank, i in enumerate(hits, 1):
                    rrf[i] += weight / (60 + rank)

        fuse(query, list(range(len(self.entries))), 1)
        for kind, triggers in facets.items():
            if set(triggers) & q_terms.keys():
                expansion = " ".join(TERM_EXPANSIONS.get(t, t) for t in triggers)
                fuse(query + " " + expansion, [i for i, e in enumerate(self.entries)
                                               if e.kind == kind], .7)
        # Choose one representative per exact symbol source before expansion.
        exact = []
        for term in sorted({s.lower() for s in symbols}):
            matches = list(self._symbols.get(term, ()))
            if "/" in term:
                matches = [i for i, e in enumerate(self.entries) if e.path.lower() == term]
            elif not matches:
                matches = list(self._symbols.get(Path(term).name, ()))
            by_source = {}
            for i in sorted(matches, key=lambda i: (-rrf.get(i, 0), i)):
                e = self.entries[i]
                by_source.setdefault((e.path, e.symbol), i)
            exact.extend(by_source.values())
        ranked = sorted(rrf, key=lambda i: (-rrf[i], i))
        chosen = list(dict.fromkeys(exact))[:limit]
        # Reserve a small dependency budget for actual syntax-derived edges.
        seeds = list(dict.fromkeys(chosen + ranked[:3]))
        reserve = max(0, min(2, limit - len(chosen) - 1))
        dependencies = []
        for i in seeds:
            for name in self.entries[i].refs:
                matches = self._symbols.get(Path(name).name.lower(), ())
                if any(j in seeds or j in dependencies for j in matches):
                    continue
                if matches:
                    dependencies.append(matches[0])
        for i in ranked:
            if len(chosen) >= limit - min(reserve, len(dependencies)):
                break
            if i not in chosen:
                chosen.append(i)
        for i in dependencies:
            if len(chosen) >= limit:
                break
            if i not in chosen:
                chosen.append(i)
        conflicts = {}
        for i in chosen:
            for key in self.entries[i].facts:
                rows = self._facts[key]
                if len({json.dumps(value, sort_keys=True) for _, value in rows}) > 1:
                    conflicts[key] = [{"source": self.entries[j].citation(), "value": value}
                                      for j, value in rows]
        return {"sources": [{**self.entries[i].citation(),
                             "text": self.entries[i].text}
                            for i in chosen], "conflicts": conflicts, "notes": self.notes}


def compiler_probe(text: str, compile_files: dict[str, str]) -> dict:
    """Compile declared source context with slang. No simulation, proof or I/O includes."""
    try:
        from pyslang import ast, SourceManager, DiagnosticEngine
    except ImportError:
        return {"status": "unavailable", "errors": [], "symbols": []}
    if len(text) > 150000 or not _mask(text).strip():
        note = "draft too large" if len(text) > 150000 else "no SystemVerilog code in draft"
        return {"status": "not_run", "errors": [], "symbols": [], "note": note}
    sm = SourceManager()
    compilation = ast.Compilation()
    for name, source in compile_files.items():
        compilation.addSyntaxTree(_tree(source, name, sm))
    compilation.addSyntaxTree(_tree(text, "<generated-draft>", sm))
    diagnostics = [d for d in compilation.getAllDiagnostics() if d.isError()]
    symbols = {"DiagCode(UnknownPackage)", "DiagCode(UnknownModule)",
               "DiagCode(UnknownClassOrPackage)", "DiagCode(UndeclaredIdentifier)"}
    missing = set()
    lines = text.splitlines()
    for diag in diagnostics:
        if str(sm.getFileName(diag.location)) != "<generated-draft>":
            continue
        if str(diag.code) in symbols and diag.args:
            missing.add(str(diag.args[0]))
        elif str(diag.code) == "DiagCode(ExceededMaxIncludeDepth)":
            line = sm.getLineNumber(diag.location) - 1
            if 0 <= line < len(lines) and (match := SV_INCLUDES.search(lines[line])):
                missing.add(match[1])
    # Render compiler facts separately from retrieved passages and generated prose.
    return {"status": "errors" if diagnostics else "clean", "count": len(diagnostics),
            "errors": DiagnosticEngine.reportAll(sm, diagnostics[:20])[:5000],
            "symbols": sorted(missing), "compile_files": list(compile_files)}


def context_payload(result: dict) -> dict:
    """Serialize bounded source data. Do not silently shorten a source excerpt."""
    max_chars = 16000
    context = {"sources": [], "conflicts": {}, "notes": [n[:300] for n in result["notes"][:8]]}

    def encoded():
        return json.dumps(context, ensure_ascii=False, sort_keys=True)

    # Surface conflicts before adding passages. Even when there are many conflicting
    # values, don't send one side of a conflict as though it were authoritative.
    for key, alternatives in sorted(result["conflicts"].items()):
        context["conflicts"][key] = alternatives[:4]
        if len(alternatives) > 4 or len(encoded()) > max_chars // 2:
            context["conflicts"][key] = {"status": "unresolved; see retrieval preview"}
        if len(encoded()) > max_chars // 2:
            del context["conflicts"][key]
            context["conflicts_omitted"] = True
            break
    for source in result["sources"]:
        context["sources"].append(source)
        if len(encoded()) > max_chars - 100:
            context["sources"].pop()
            context["sources_omitted"] = True
    return context


def prompt_context(context: dict) -> str:
    return ("\n\nRetrieved project data (JSON; reference only):\n" +
            json.dumps(context, ensure_ascii=False, sort_keys=True))
