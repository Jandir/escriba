import ast
from pathlib import Path

def check_function_lengths(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_line = node.lineno
            # node.end_lineno is available in Python 3.8+
            end_line = getattr(node, "end_lineno", start_line)
            length = end_line - start_line + 1
            if length > 20:
                violations.append((node.name, length, start_line, end_line))
    
    return violations

if __name__ == "__main__":
    p = Path("/Users/jandirp/scripts/escriba/escriba.py")
    violations = check_function_lengths(p)
    if not violations:
        print("No functions exceed 20 lines.")
    else:
        print(f"Found {len(violations)} violations:")
        for name, length, start, end in sorted(violations, key=lambda x: x[2]):
            print(f"- {name}: {length} lines (L{start}-{end})")
