import re
import functools
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Pattern
from utils import print_err

# Caminho absoluto para o diretório do script (constante de módulo)
_SCRIPT_DIR_PATH: Path = Path(__file__).parent.resolve()

"""
MÓDULO RULES: O Tradutor de Termos
----------------------------------
Este módulo é responsável por garantir que termos específicos sejam escritos 
corretamente nas transcrições (ex: nomes próprios, siglas ou termos técnicos).
Ele funciona como um sistema de "Localizar e Substituir" inteligente.
"""


def _parse_rules_file(path_obj: Path, rules_dict: Dict[str, str]) -> None:
    """
    Lê um arquivo de texto e extrai regras de 'troca de palavras'.
    
    Explicação para Juniores:
    Cada linha do arquivo 'rules.txt' deve seguir o padrão: antigo,novo.
    Exemplo: 'eklesia,Ekklezia'.
    """
    if not path_obj.exists():
        return
    try:
        with open(path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            for raw_line_str in file_descriptor_obj:
                _process_rule_line(raw_line_str, rules_dict)
    except Exception as error_obj:
        print_err(f"Erro ao ler regras em {path_obj.name}: {error_obj}")


def _process_rule_line(raw_line_str: str, rules_dict: Dict[str, str]) -> None:
    """
    Transforma uma linha de texto como 'antigo,novo' em um item do dicionário.
    """
    clean_line_str: str = raw_line_str.strip()
    # Ignora linhas vazias ou comentários (que começam com #)
    if not clean_line_str or clean_line_str.startswith("#"):
        return

    # Aceitamos tanto vírgula quanto sinal de igual como separador
    separator_str: str = "," if "," in clean_line_str else "="
    if separator_str in clean_line_str:
        original_term_str, new_term_str = clean_line_str.split(separator_str, 1)
        # .strip() remove espaços extras: " palavra " vira "palavra"
        rules_dict[original_term_str.strip()] = new_term_str.strip()


@functools.lru_cache(None)
def _load_ekklezia_rules() -> List[Tuple[str, str]]:
    """
    Carrega as regras de substituição do arquivo rules.txt.
    
    Explicação para Juniores:
    O '@functools.lru_cache' é um 'memorizador'. Se chamarmos esta função 
    duas vezes, o Python não vai ler o disco de novo, ele apenas entrega o 
    resultado que já está na memória (cache).
    """
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
    sorted_rules_list: List[Tuple[str, str]] = sorted(rules_list, key=lambda x_tuple: len(x_tuple[0]), reverse=True)
    
    # re.escape garante que caracteres especiais (como pontos ou parênteses) 
    # nas palavras sejam tratados como texto comum, não como comandos de regex.
    # O '|'.join() une todas as palavras com uma barra vertical, que significa "OU".
    regex_pattern_str: str = "|".join(re.escape(original_str) for original_str, _ in sorted_rules_list)
    lookup_dict: Dict[str, str] = {original_str: new_str for original_str, new_str in sorted_rules_list}

    return re.compile(regex_pattern_str), lookup_dict


def clean_ekklezia_terms(text_str: str) -> str:
    """Aplica as regras de substituição de termos usando regex otimizado."""
    if not text_str:
        return text_str

    regex_pattern_obj, lookup_dict = _get_ekklezia_regex()
    if not regex_pattern_obj:
        return text_str

    def _replace_callback(match_obj: re.Match) -> str:
        """
        Função interna que decide qual termo novo usar para o que foi encontrado.
        
        Explicação para Juniores:
        O 'match_obj.group(0)' contém a palavra exata que o Regex encontrou no texto.
        Usamos essa palavra como chave no 'lookup_dict' para pegar a versão corrigida.
        """
        return lookup_dict[match_obj.group(0)]

    return regex_pattern_obj.sub(_replace_callback, text_str)

