import ast
from pathlib import Path

def check_function_lengths(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except Exception as e:
        return [f"Error parsing {file_path}: {e}"]

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_line = node.lineno
            end_line = getattr(node, "end_lineno", start_line)
            length = end_line - start_line + 1
            if length > 20:
                violations.append((node.name, length, start_line, end_line))
    
    return violations

if __name__ == "__main__":
    files = [
        "utils.py",
        "rules.py",
        "history.py",
        "youtube.py",
        "lexis.py"
    ]
    base_path = Path("/Users/jandirp/scripts/escriba")
    for filename in files:
        p = base_path / filename
        violations = check_function_lengths(p)
        print(f"\nChecking {filename}:")
        if not violations:
            print("  No functions exceed 20 lines.")
        else:
            print(f"  Found {len(violations)} violations:")
            for v in sorted(violations, key=lambda x: x[2] if isinstance(x, tuple) else 0):
                if isinstance(v, str):
                    print(f"  {v}")
                else:
                    name, length, start, end = v
                    print(f"  - {name}: {length} lines (L{start}-{end})")
