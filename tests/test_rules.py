import pytest
import os
import sys
from pathlib import Path

# Adiciona diretório pai no path para facilitar import local de rules
sys.path.insert(0, str(Path(__file__).parent.parent))

from rules import clean_ekklezia_terms, _parse_rules_file

# EXPLICAÇÃO PARA JUNIORES:
# Testes de substituição de texto (Regex) garantem que nossas regras de "limpeza"
# não estraguem o texto original e que as substituições aconteçam exatamente
# como planejado no arquivo rules.txt.

def test_clean_terms_empty():
    """Verifica se a limpeza de termos lida corretamente com strings vazias ou nulas."""
    assert clean_ekklezia_terms("") == ""
    assert clean_ekklezia_terms(None) == None

def test_clean_terms_no_rules_match():
    """Verifica se o texto original é mantido quando não há regras correspondentes."""
    # Isso simula o comportamento se o rules.txt não existir
    assert clean_ekklezia_terms("Hello World") == "Hello World"

def test_parse_rules_file_with_dict(tmp_path: Path):
    """Verifica o parsing de um arquivo de regras para um dicionário."""
    rules_file_path: Path = tmp_path / "rules.txt"
    rules_content_str: str = "A = B\nC = D"
    rules_file_path.write_text(rules_content_str, encoding="utf-8")
    
    rules_dict: dict[str, str] = {}
    _parse_rules_file(rules_file_path, rules_dict)
    
    assert rules_dict == {"A": "B", "C": "D"}
