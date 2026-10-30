"""Moves wording out of Python code into shared/messages/locales/messages.yaml.

Finds, with the Python parser (so positions are exact):
  - HTTPException(detail=...) and any call keyword named detail / message / description / title / subject / message_body
  - dict entries whose key is message / detail / error / description / title / text / label / hint / note / summary / body / subject / message_body
  - raise SomeError("sentence")
and replaces each with get_message("KEY", name=expr, ...). Log calls, pydantic Field(...) and route decorators are left alone.
Files that define Temporal workflows are not touched (the workflow sandbox restricts imports); they are listed.

Usage:  python scripts/i18n_convert_py.py [--write] [path-fragment ...]
"""
import ast
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / "shared/messages/locales/messages.yaml"
WRITE = "--write" in sys.argv
INCLUDE_WORKFLOWS = "--include-workflows" in sys.argv
LIST = "--list" in sys.argv                                        # print every piece of wording found     # workflow files need the sandbox pass-through import; check mode covers them anyway
FILTERS = [a for a in sys.argv[1:] if not a.startswith("--")]

CALL_KWARGS = {"detail", "message", "description", "title", "subject", "message_body"}
DICT_KEYS = {"message", "detail", "error", "description", "title", "text", "label", "hint", "note", "summary", "body",
             "subject", "message_body"}
LOG_NAMES = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "fatal"}
LOG_RECEIVERS = {"log", "logger", "logging", "structlog", "LOG", "_log"}
SKIP_CALLS = {"Field", "Query", "Path", "Body", "Header", "Depends", "APIRouter", "FastAPI", "Column", "field", "execute", "fetch", "fetchrow",
              "fetchval", "executemany", "text", "compile", "match", "search", "sub", "split", "startswith", "endswith", "join", "replace",
              "encode", "decode", "open", "getLogger", "get_logger", "print", "format", "start_workflow", "list_workflows", "count_workflows"}
# keywords that carry machine text (queries, prompts, protocol fields), never wording
TECH_KWARGS = {"sql", "query", "prompt", "system", "system_prompt", "content", "url", "path", "host", "key", "event", "event_type", "topic",
               "queue", "task_queue", "id", "workflow_id", "model", "regex", "pattern", "mode", "method", "media_type", "encoding", "name_prefix"}
SQLISH = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|ALTER|DROP|FROM|WHERE|AND|OR|ORDER)\b|\b(FROM|WHERE|JOIN|ILIKE)\b.*\$\d|WorkflowType\s*=|^You are |^Return only|^\s*\{|\n\n|^event:|^data:|^:\s|^(Bearer|Basic|attachment|inline)\b|^(application|text|multipart)/|^\s*<|^\s*[\[\(\d]")
SKIP_FILES = ("apps/api/dev_auth_server.py", "apps/api/routers/demo_cloud_extract.py", "modules/cts/demo/pipeline.py")
HAS_WORD = re.compile(r"[A-Za-z]{2,}")


def plausible(text: str) -> bool:
    t = text.strip()
    if not HAS_WORD.search(t):
        return False
    if re.fullmatch(r"[A-Z0-9_]+", t) and ("_" in t or len(t) <= 3):
        return False
    if " " not in t and re.fullmatch(r"[a-z0-9_:/\-\[\]\.#%@!]+", t):
        return False
    if re.match(r"(https?:|/|#|\./|mailto:)", t):
        return False
    return True


def name_of(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return name_of(node.func.value) if isinstance(node.func, ast.Attribute) else name_of(node.func)
    if isinstance(node, ast.Subscript):
        return name_of(node.value)
    return "value"


RESERVED = {"key", "locale", "self"}          # get_message(key, locale=..., **variables) already uses these names


def unique(base: str, used: set) -> str:
    base = base if re.fullmatch(r"[A-Za-z_]\w*", base) else "value"
    base = base.lstrip("_") or "value"                   # {_bank_id} is legal but reads as private; use the plain name
    if base in RESERVED:
        base = f"{base}_value"
    name, i = base, 2
    while name in used:
        name, i = f"{base}{i}", i + 1
    used.add(name)
    return name


def tracked_files():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    keep = []
    for f in out:
        if not f.startswith(("apps/", "modules/", "shared/")):
            continue
        if re.search(r"(^|/)(tests?|\.venv[^/]*|site-packages|indic_ocr|migrations)(/|$)", f) or f.startswith("shared/messages/"):
            continue
        if FILTERS and not any(x in f for x in FILTERS):
            continue
        keep.append(f)
    return keep


class Finder(ast.NodeVisitor):
    def __init__(self, src_bytes, src_lines):
        self.b, self.lines, self.sites = src_bytes, src_lines, []
        self.line_starts = [0]
        for ln in src_bytes.split(b"\n")[:-1]:
            self.line_starts.append(self.line_starts[-1] + len(ln) + 1)
        self.in_decorator = 0

    def off(self, lineno, col):
        return self.line_starts[lineno - 1] + col

    def text_of(self, node):
        """(text, [(name, source)]) for a str constant or f-string; None if not wording."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value, []
        if isinstance(node, ast.JoinedStr):
            used, parts, vars_ = set(), "", []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts += str(v.value)
                    for m in re.finditer(r"\{(\w+)\}", str(v.value)):          # f"...{{name}}..." is a literal {name} in the output
                        vars_.append((unique(m.group(1), used), repr("{" + m.group(1) + "}")))
                elif isinstance(v, ast.FormattedValue):
                    if v.format_spec is not None or v.conversion not in (-1,):
                        return None                                     # formatting we cannot express as a placeholder
                    n = unique(name_of(v.value), used)
                    src = self.b[self.off(v.value.lineno, v.value.col_offset):self.off(v.value.end_lineno, v.value.end_col_offset)].decode()
                    vars_.append((n, src)); parts += "{%s}" % n
            return parts, vars_
        return None

    def add(self, node, kind):
        got = self.text_of(node)
        if not got:
            return
        text, vars_ = got
        literal_part = re.sub(r"\{\w+\}", "", text) if vars_ else text
        if not plausible(literal_part if vars_ else text):
            return
        if not vars_ and re.search(r"[{}]", text):
            return                                                    # literal braces would be read as placeholders
        start, end = self.off(node.lineno, node.col_offset), self.off(node.end_lineno, node.end_col_offset)
        self.sites.append({"start": start, "end": end, "text": text, "vars": vars_, "kind": kind, "line": node.lineno})

    def visit_FunctionDef(self, node):
        for d in node.decorator_list:                                  # route decorators carry documentation text, not wording
            self.in_decorator += 1
            self.generic_visit(d)
            self.in_decorator -= 1
        for child in node.body + node.args.defaults:
            self.visit(child)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        func = node.func
        fname = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        recv = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else ""
        is_log = (fname in LOG_NAMES and (recv in LOG_RECEIVERS or recv.endswith("log") or recv.endswith("logger"))) or fname == "get_message"
        if any(kw.arg == "tags" for kw in node.keywords):             # tags=["Admin v1"] is API documentation metadata
            self.in_decorator += 1
            for child in ast.iter_child_nodes(node):
                self.visit(child)
            self.in_decorator -= 1
            return
        if not is_log and fname not in SKIP_CALLS and not self.in_decorator:
            for kw in node.keywords:
                if kw.arg in CALL_KWARGS:
                    self.add(kw.value, "kwarg")
                elif kw.arg and kw.arg not in TECH_KWARGS and isinstance(kw.value, (ast.Constant, ast.JoinedStr)) and self.phrase(kw.value):
                    self.add(kw.value, "kwarg")
        if is_log:
            return                                                     # log events are for developers
        self.generic_visit(node)

    def visit_Raise(self, node):
        exc = node.exc
        if isinstance(exc, ast.Call) and exc.args and not self.in_decorator:
            nm = exc.func.id if isinstance(exc.func, ast.Name) else exc.func.attr if isinstance(exc.func, ast.Attribute) else ""
            if nm not in ("NotImplementedError", "AssertionError", "StopIteration", "StopAsyncIteration", "KeyError", "SystemExit"):
                self.add(exc.args[0], "raise")
        self.generic_visit(node)

    def visit_Dict(self, node):
        if not self.in_decorator:
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in DICT_KEYS:
                    self.add(v, "dict")
                elif isinstance(v, (ast.Constant, ast.JoinedStr)) and self.phrase(v):
                    self.add(v, "dict")
        self.generic_visit(node)

    def phrase(self, node):
        """A multi-word sentence (not SQL, a prompt or a protocol line)."""
        t = self.text_of(node)
        if not t:
            return False
        text = t[0]
        return " " in text.strip() and not SQLISH.search(text) and len(text) < 400

    def visit_Return(self, node):
        if node.value is not None and not self.in_decorator:
            if isinstance(node.value, (ast.Constant, ast.JoinedStr)) and self.phrase(node.value):
                self.add(node.value, "return")
        self.generic_visit(node)

    def visit_IfExp(self, node):
        if not self.in_decorator:
            for b in (node.body, node.orelse):
                if isinstance(b, (ast.Constant, ast.JoinedStr)) and self.phrase(b):
                    self.add(b, "ifexp")
        self.generic_visit(node)

    def _seq(self, node):
        if not self.in_decorator:
            for e in node.elts:
                if isinstance(e, (ast.Constant, ast.JoinedStr)) and self.phrase(e):
                    self.add(e, "seq")
        self.generic_visit(node)

    visit_Tuple = visit_List = _seq


yaml_text = YAML.read_text(encoding="utf-8")
existing_keys = set(re.findall(r"^([A-Z][A-Z0-9_]+):\s*$", yaml_text, re.M))
by_text = {}
for m in re.finditer(r'^([A-Z][A-Z0-9_]+):\s*\n\s+severity:[^\n]*\n\s+surface:[^\n]*\n\s+variables: \[([^\]]*)\]\n\s+en: ("(?:[^"\\]|\\.)*")', yaml_text, re.M):
    try:
        text = json.loads(m.group(3))
    except Exception:
        continue
    sig = f"{text}|{','.join(s.strip() for s in m.group(2).split(',') if s.strip())}"
    by_text.setdefault(sig, m.group(1))


def domain(path: str) -> str:
    if path.startswith("apps/api/"):
        return "API"
    if path.startswith("modules/cts/"):
        return "CTS"
    if path.startswith("modules/msv/"):
        return "MSV"
    if path.startswith("shared/"):
        return "PLATFORM"
    m = re.match(r"apps/([a-z_]+)/", path)
    return (m.group(1).upper().replace("_SERVICE", "") if m else "PLATFORM")


def slug(text: str) -> str:
    words = re.sub(r"[^A-Za-z0-9]+", " ", re.sub(r"\{\w+\}", " ", text)).split()[:5]
    return re.sub(r"_+$", "", "_".join(words).upper()[:36]) or "TEXT"


def severity(text: str) -> str:
    return "ERROR" if re.search(r"fail|error|could not|cannot|unable|invalid|denied|refused|unavailable|not allowed|not found|required", text, re.I) else "WARN" if re.search(r"warn|overdue|expired|degraded|missing|late", text, re.I) else "INFO"


new_entries, new_keys = [], set()
report = Counter()
skipped_workflow, failed = [], []
for f in tracked_files():
    path = ROOT / f
    raw = path.read_bytes()
    src = raw.decode("utf-8", errors="replace")
    if f in SKIP_FILES:
        continue
    if "@workflow.defn" in src and not INCLUDE_WORKFLOWS:
        skipped_workflow.append(f)
        continue
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    finder = Finder(raw, src.splitlines())
    finder.visit(tree)
    if not finder.sites:
        continue
    if LIST:
        for x in sorted(finder.sites, key=lambda y: y["line"]):
            print(f"{f}:{x['line']} [{x['kind']}] {x['text'][:90]!r}")
    taken, used, edits = set(), {}, []
    for s in sorted({(x["start"], x["end"]): x for x in finder.sites}.values(), key=lambda x: x["start"]):
        sig = f"{s['text']}|{','.join(n for n, _ in s['vars'])}"
        key = used.get(sig) or by_text.get(sig)
        if key is None:
            base = f"{domain(f)}_{slug(s['text'])}"
            key, i = base, 2
            while key in existing_keys or key in new_keys or key in taken:
                key, i = f"{base}_{i}", i + 1
            taken.add(key)
            new_keys.add(key)
            new_entries.append((key, severity(s["text"]), s["text"], [n for n, _ in s["vars"]]))
            by_text[sig] = key
            report["created"] += 1
        else:
            report["reused"] += 1
        used[sig] = key
        args = "".join(f", {n}={code}" for n, code in s["vars"])
        edits.append((s["start"], s["end"], f'get_message("{key}"{args})'))
        report["sites"] += 1
    out = bytearray(raw)
    for st, en, rep in sorted(edits, reverse=True):
        out[st:en] = rep.encode()
    new_src = out.decode("utf-8")
    if "from shared.messages import get_message" not in new_src and not re.search(r"^\s*from shared\.messages import [^\n]*get_message", new_src, re.M):
        body = tree.body
        last_imp = [n for n in body if isinstance(n, (ast.Import, ast.ImportFrom))]
        if last_imp:
            line_no = last_imp[-1].end_lineno
        else:                                                            # after the module docstring
            line_no = body[0].end_lineno if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) else 0
        lines = new_src.split("\n")
        # edits can change line counts only on the edited lines, never above the last import
        if "@workflow.defn" in src:            # the Temporal sandbox restricts imports: pass the read-only message registry through
            lines[line_no:line_no] = ["with workflow.unsafe.imports_passed_through():", "    from shared.messages import get_message"]
        else:
            lines.insert(line_no, "from shared.messages import get_message")
        new_src = "\n".join(lines)
    try:
        compile(new_src, f, "exec")
    except SyntaxError as e:
        failed.append(f"{f}: {e}")
        continue
    report["files"] += 1
    if WRITE:
        path.write_bytes(new_src.encode("utf-8"))

if WRITE and new_entries:
    lines = ["", "# ══════════════════════════════════════════════════════════════════",
             "# API / SERVICE WORDING — generated from Python code by scripts/i18n_convert_py.py",
             "# ══════════════════════════════════════════════════════════════════", ""]
    for key, sev, text, vars_ in new_entries:
        lines += [f"{key}:", f"  severity: {sev}", "  surface: [UI]", f"  variables: [{', '.join(vars_)}]", f"  en: {json.dumps(text, ensure_ascii=False)}", '  hi: ""', ""]
    with YAML.open("a", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines))

print(json.dumps({"write": WRITE, **report, "workflow_files_skipped": len(skipped_workflow), "failed": len(failed)}))
for x in failed:
    print("FAILED", x)
for x in skipped_workflow:
    print("workflow (not touched):", x)
