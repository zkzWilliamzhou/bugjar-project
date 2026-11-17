"""Static source audit: stubs, forbidden calls, unused imports, source size."""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_CALLS = {"eval", "exec", "compile", "os.system", "pickle.loads",
                   "yaml.load", "marshal.loads"}
FORBIDDEN_MODULES = {"pickle", "yaml", "requests", "urllib.request", "socket",
                     "http.client", "ftplib", "telnetlib"}
STUB_MARKERS = ("TODO", "FIXME", "NotImplementedError", "pass  #")


def scan():
    findings = []
    stats = {"files": 0, "lines": 0, "defs": 0}
    for py in sorted((ROOT / "bugjar").glob("*.py")):
        text = py.read_text(encoding="utf-8")
        stats["files"] += 1
        stats["lines"] += len(text.splitlines())
        tree = ast.parse(text)
        stats["defs"] += sum(isinstance(n, (ast.FunctionDef, ast.ClassDef))
                             for n in ast.walk(tree))
        for i, line in enumerate(text.splitlines(), 1):
            for marker in STUB_MARKERS:
                if marker in line and not line.lstrip().startswith("#"):
                    findings.append("%s:%d stub marker %r" % (py.name, i, marker))
        # A bare `...` expression is a real stub. A string containing "..." is not.
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and node.value.value is Ellipsis:
                findings.append("%s:%d bare Ellipsis stub" % (py.name, node.lineno))
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) \
                    and getattr(node.exc.func, "id", None) == "NotImplementedError":
                findings.append("%s:%d NotImplementedError" % (py.name, node.lineno))
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported[a.asname or a.name.split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                for a in node.names:
                    imported[a.asname or a.name] = node.lineno
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "shell":
                        findings.append("%s:%d shell= keyword" % (py.name, node.lineno))
                f = node.func
                name = None
                if isinstance(f, ast.Name):
                    name = f.id
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    name = f.value.id + "." + f.attr
                if name in FORBIDDEN_MODULES or name in FORBIDDEN_CALLS:
                    findings.append("%s:%d forbidden call %s" % (py.name, node.lineno, name))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""])
                for m in mods:
                    if m.split(".")[0] in FORBIDDEN_MODULES:
                        findings.append("%s:%d forbidden module %s" % (py.name, node.lineno, m))
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for alias, lineno in imported.items():
            if alias not in used and alias != "annotations":
                findings.append("%s:%d unused import %s" % (py.name, lineno, alias))
    return {"stats": stats, "findings": findings}


if __name__ == "__main__":
    report = scan()
    print(json.dumps(report, indent=2, sort_keys=True))
    sys.exit(1 if report["findings"] else 0)
