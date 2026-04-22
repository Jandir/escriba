import re
import functools
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable, Pattern

# Caminho absoluto para o diretório do script (constante de módulo)
_SCRIPT_DIR_PATH: Path = Path(__file__).parent.resolve()


@functools.lru_cache(None)
def _parse_rules_file(path_obj: Path, rules_dict: Dict[str, str]) -> None:
    """
    Lê um arquivo de texto e extrai regras de 'troca de palavras'.
    
    Explicação para Juniores:
    O '@functools.lru_cache' é um 'memorizador'. Se chamarmos esta função 
    duas vezes com o mesmo arquivo, o Python não vai ler o disco de novo, 
    ele apenas entrega o resultado que já está na memória (cache).
    """
    if not path_obj.exists():
        return
    try:
        with open(path_obj, "r", encoding="utf-8") as file_descriptor:
            for raw_line in file_descriptor:
                _process_rule_line(raw_line, rules_dict)
    except Exception as error_obj:
        print(f"Erro ao ler regras em {path_obj.name}: {error_obj}")


def _process_rule_line(raw_line: str, rules_dict: Dict[str, str]) -> None:
    """
    Transforma uma linha de texto como 'antigo,novo' em um item do dicionário.
    """
    clean_line: str = raw_line.strip()
    # Ignora linhas vazias ou comentários (que começam com #)
    if not clean_line or clean_line.startswith("#"):
        return

    # Aceitamos tanto vírgula quanto sinal de igual como separador
    separator_str: str = "," if "," in clean_line else "="
    if separator_str in clean_line:
        original_term, new_term = clean_line.split(separator_str, 1)
        # .strip() remove espaços extras: " palavra " vira "palavra"
        rules_dict[original_term.strip()] = new_term.strip()


@functools.lru_cache(None)
def _load_ekklezia_rules() -> List[Tuple[str, str]]:
    """Carrega as regras de substituição do arquivo rules.txt."""
    all_rules_dict: Dict[str, str] = {}
    _parse_rules_file(_SCRIPT_DIR_PATH / "rules.txt", all_rules_dict)
    _parse_rules_file(Path.cwd() / "rules.txt", all_rules_dict)
    return list(all_rules_dict.items())


@functools.lru_cache(None)
def _get_ekklezia_regex() -> Tuple[Optional[Pattern], Dict[str, str]]:
    """
    Compila todas as regras em uma única 'Super Expressão Regular'.
    
    Por que fazer isso?
    Em vez de procurar 100 palavras uma por uma (o que seria lento), o Regex
    consegue procurar todas de uma vez só em uma única passada pelo texto.
    """
    rules_list: List[Tuple[str, str]] = _load_ekklezia_rules()
    if not rules_list:
        return None, {}

    # Ordenamos pelas palavras mais longas primeiro. 
    # Isso evita que "São Paulo" seja trocado errado por "São" se as duas 
    # forem regras.
    sorted_rules_list: List[Tuple[str, str]] = sorted(rules_list, key=lambda x: len(x[0]), reverse=True)
    
    # re.escape garante que caracteres especiais (como pontos ou parênteses) 
    # nas palavras sejam tratados como texto comum, não como comandos de regex.
    regex_pattern_str: str = "|".join(re.escape(orig) for orig, _ in sorted_rules_list)
    lookup_dict: Dict[str, str] = {orig: novo for orig, novo in sorted_rules_list}

    return re.compile(regex_pattern_str), lookup_dict


def clean_ekklezia_terms(text_str: str) -> str:
    """Aplica as regras de substituição de termos usando regex otimizado."""
    if not text_str:
        return text_str

    regex_pattern, lookup_dict = _get_ekklezia_regex()
    if not regex_pattern:
        return text_str

    def _replace_callback(match_obj: re.Match) -> str:
        return lookup_dict[match_obj.group(0)]

    return regex_pattern.sub(_replace_callback, text_str)

