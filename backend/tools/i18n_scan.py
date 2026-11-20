"""Lists English sentences in the code that are not wrapped in _() / N_() (candidates to translate)."""
import ast
import sys

SKIP_CALLS = {"_", "N_", "translate", "info", "warning", "error", "exception", "debug", "getenv", "Field", "Query", "File", "Form",
              "execute", "text", "exec_driver_sql", "APIRouter", "FastAPI", "add_argument", "ArgumentParser", "add_parser", "print", "sub", "match",
              "fullmatch", "compile", "strftime", "strptime", "Path", "write_text", "mkdtemp", "Response", "set_main_option", "warn"}


def scan(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
            continue
        v = n.value.strip()
        if len(v.split()) < 3 or not v[:1].isalpha():
            continue
        p = parents.get(n)
        if isinstance(p, ast.Expr):  # docstring
            continue
        if isinstance(p, ast.JoinedStr):
            p = parents.get(p)
        anc, skip = p, False
        while anc is not None:
            if isinstance(anc, ast.Call):
                f = anc.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
                if name in SKIP_CALLS:
                    skip = True
                    break
            if isinstance(anc, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                break
            anc = parents.get(anc)
        if isinstance(p, ast.Dict) and n in p.keys:
            skip = True
        if not skip:
            out.append(f"{path}:{n.lineno}: {v[:110]}")
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        for line in scan(p):
            print(line)
