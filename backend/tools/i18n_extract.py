"""Collects every translatable template: first literal argument of _(), N_(), S_() in app/ (excluding seed)."""
import ast
import pathlib
import re

FUNCS = {"_", "N_", "S_"}


def templates(root: str = "app") -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(pathlib.Path(root).rglob("*.py")):
        if "seed" in path.parts or "locales" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and n.args \
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                found.setdefault(n.args[0].value, []).append(f"{path}:{n.lineno}")
    return found


def fields(t: str) -> set[str]:
    return {m.split(":")[0].split("!")[0] for m in re.findall(r"(?<!\{)\{([^{}]*)\}(?!\})", t)}


if __name__ == "__main__":
    import sys

    from app.locales.fr import FR

    tpl = templates()
    missing = [t for t in tpl if t not in FR]
    print(f"{len(tpl)} templates, {len(missing)} without French")
    if "--missing" in sys.argv:
        for t in missing:
            print(repr(t))
