"""Developer tool: wraps user-facing messages in `_()` so they can be translated.

Rewrites, in place, the message argument of HTTPException / ValueError / BackupError calls (and the
"message" value of dict details): string literals become _("...") and f-strings become
_("template {name}", name=expr). Prints the expressions it could not convert (to do by hand).

    python tools/i18n_mark.py app/routers/*.py
"""
from __future__ import annotations

import ast
import re
import sys

TARGETS = {"HTTPException", "ValueError", "BackupError"}
APPEND_TO = {"unmet", "reasons", "errors", "problems", "out", "msgs", "notes"}  # lists of user-facing sentences
CALL_ARGS = {"_alert": (2, 3)}  # helper functions whose positional arguments are user-facing sentences
DICT_KEYS = {"notice", "action", "message", "title", "hint", "explanation", "recommendation", "name", "formula", "description"}


def _name(expr: ast.expr, used: dict[str, str], src: str) -> str:
    seg = ast.get_source_segment(src, expr)
    if isinstance(expr, ast.Name):
        base = expr.id
    elif isinstance(expr, ast.Attribute):
        base = expr.attr
    elif isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, str):
        base = expr.slice.value
    elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "len":
        base = "n"
    else:
        base = "v"
    base = re.sub(r"\W", "_", base).strip("_") or "v"
    if base[0].isdigit():
        base = "v" + base
    name, k = base, 2
    while name in used and used[name] != seg:
        name, k = f"{base}{k}", k + 1
    used[name] = seg
    return name


def convert(node: ast.expr, src: str) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return f"_({node.value!r})"
    if isinstance(node, ast.JoinedStr):
        parts, used = [], {}
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(v.value.replace("{", "{{").replace("}", "}}"))
            elif isinstance(v, ast.FormattedValue):
                if v.format_spec is not None and not all(isinstance(x, ast.Constant) for x in v.format_spec.values):
                    return None
                n = _name(v.value, used, src)
                conv = {115: "!s", 114: "!r", 97: "!a"}.get(v.conversion, "")
                spec = (":" + "".join(x.value for x in v.format_spec.values)) if v.format_spec else ""
                parts.append("{" + n + conv + spec + "}")
            else:
                return None
        tpl = "".join(parts)
        kws = ", ".join(f"{k}={seg}" for k, seg in used.items())
        return f"_({tpl!r}, {kws})" if kws else f"_({tpl!r})"
    return None


def process(path: str) -> list[str]:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln))
    pos = lambda ln, col: offs[ln - 1] + len(lines[ln - 1].encode("utf-8")[:col].decode("utf-8"))  # noqa: E731
    edits, todo = [], []

    def handle(msg: ast.expr):
        if isinstance(msg, ast.Call) and isinstance(msg.func, ast.Name) and msg.func.id == "_":
            return
        if isinstance(msg, ast.Dict):
            for k, v in zip(msg.keys, msg.values):
                if isinstance(k, ast.Constant) and k.value == "message":
                    handle(v)
            return
        new = convert(msg, src)
        if new is None:
            if not (isinstance(msg, ast.Name) or isinstance(msg, ast.Call)):
                todo.append(f"{path}:{msg.lineno}: {ast.get_source_segment(src, msg)[:100]}")
            return
        edits.append((pos(msg.lineno, msg.col_offset), pos(msg.end_lineno, msg.end_col_offset), new))

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name) and node.func.value.id in APPEND_TO and node.args
                and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))):
            handle(node.args[0])
        if DICT_MODE and isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in DICT_KEYS and isinstance(v, (ast.Constant, ast.JoinedStr)) \
                        and isinstance(getattr(v, "value", ""), str) and len(getattr(v, "value", "x") or "x") > 3:
                    handle(v)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CALL_ARGS:
            for i in CALL_ARGS[node.func.id]:
                if i < len(node.args):
                    handle(node.args[i])
        if REPORT_MODE and isinstance(node, ast.Call):
            report_call(node, handle)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in TARGETS:
            args = list(node.args)
            if node.func.id == "HTTPException":
                msg = args[1] if len(args) > 1 else next((k.value for k in node.keywords if k.arg == "detail"), None)
            else:
                msg = args[0] if args else None
            if msg is not None:
                handle(msg)
    if not edits:
        return todo
    for a, b, new in sorted(edits, reverse=True):
        src = src[:a] + new + src[b:]
    if "from ..i18n import _" not in src and "from .i18n import _" not in src and "from app.i18n import _" not in src:
        rel = "from ..i18n import _"
        m = list(re.finditer(r"^(from \S+ import [^\n(]+(\([^)]*\))?|import \S+)\n", src, re.M))
        at = m[-1].end() if m else 0
        src = src[:at] + rel + "\n" + src[at:]
    open(path, "w", encoding="utf-8").write(src)
    return todo


DICT_MODE = False
REPORT_MODE = False
STR = (ast.Constant, ast.JoinedStr)


def _is_text(e):
    return isinstance(e, ast.JoinedStr) or (isinstance(e, ast.Constant) and isinstance(e.value, str) and len(e.value) > 1)


def report_call(node: ast.Call, handle):
    """Report-builder calls whose text is user-facing (PDF content); CSV keys are left alone."""
    f = node.func
    attr = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
    a = node.args
    if attr in ("h2", "p", "set_title", "set_xlabel", "set_ylabel", "suptitle") and a and _is_text(a[0]):
        handle(a[0])
    elif attr == "Report":
        for x in a[:2]:
            if _is_text(x):
                handle(x)
    elif attr in ("bullets", "table") and a and isinstance(a[0], ast.List):
        for x in a[0].elts:
            if _is_text(x):
                handle(x)
    elif attr == "kv" and a and isinstance(a[0], ast.List):
        for t in a[0].elts:
            if isinstance(t, ast.Tuple) and t.elts and _is_text(t.elts[0]):
                handle(t.elts[0])
    for k in node.keywords:
        if k.arg in ("title", "label", "xlabel", "ylabel") and _is_text(k.value):
            handle(k.value)

if __name__ == "__main__":
    todo = []
    args = sys.argv[1:]
    if args and args[0] == "--dicts":
        DICT_MODE = True
        args = args[1:]
    if args and args[0] == "--reports":
        REPORT_MODE = True
        args = args[1:]
    for p in args:
        todo += process(p)
    print("\n".join(todo) or "all converted")
