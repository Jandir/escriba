import re
import functools
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable, Pattern

_script_dir = Path(__file__).parent.resolve()

@functools.lru_cache(None)
def _load_ekklezia_rules() -> List[Tuple[str, str]]:
    """
    Carrega as regras de substituição do arquivo rules.txt.
    """
    rules_dict: Dict[str, str] = {}
    
    global_rules_path: Path = _script_dir / "rules.txt"
    local_rules_path: Path = Path.cwd() / "rules.txt"
    
    for path in [global_rules_path, local_rules_path]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        
                        sep = "," if "," in line else "="
                        if sep in line:
                            orig, novo = line.split(sep, 1)
                            rules_dict[orig.strip()] = novo.strip()
            except Exception as e:
                # Truncamento de aviso; importará utils se necessário
                print(f"Erro ao ler regras em {path.name}: {e}")
    
    return list(rules_dict.items())


@functools.lru_cache(None)
def _get_ekklezia_regex() -> Tuple[Optional[Pattern], Dict[str, str]]:
    """
    Compila as regras de substituição em uma única expressão regular.
    """
    rules: List[Tuple[str, str]] = _load_ekklezia_rules()
    if not rules:
        return None, {}
    
    sorted_rules: List[Tuple[str, str]] = sorted(rules, key=lambda x: len(x[0]), reverse=True)
    pattern: str = "|".join(re.escape(orig) for orig, _ in sorted_rules)
    lookup: Dict[str, str] = {orig: novo for orig, novo in sorted_rules}
    
    return re.compile(pattern), lookup


def clean_ekklezia_terms(text: str) -> str:
    """
    Aplica as regras de substituição de termos usando regex otimizado.
    """
    if not text:
        return text
        
    regex, lookup = _get_ekklezia_regex()
    if not regex:
        return text
        
    def _replace_callback(m: re.Match) -> str:
        return lookup[m.group(0)]

    return regex.sub(_replace_callback, text)
