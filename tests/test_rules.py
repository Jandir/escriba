import pytest
import os
import sys
from pathlib import Path

# Adiciona diretório pai no path para facilitar import local de rules
sys.path.insert(0, str(Path(__file__).parent.parent))

from rules import clean_ekklezia_terms, _parse_rules_file, fix_sentence_capitalization

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

def test_fix_sentence_capitalization_edge_cases():
    """Verifica se lida corretamente com strings vazias e em branco."""
    assert fix_sentence_capitalization("") == ""
    assert fix_sentence_capitalization(None) == None
    assert fix_sentence_capitalization("   ") == "   "

def test_fix_sentence_capitalization_basic():
    """Verifica a capitalização básica da primeira letra."""
    assert fix_sentence_capitalization("hello world") == "Hello world"
    assert fix_sentence_capitalization("Hello world") == "Hello world"

def test_fix_sentence_capitalization_after_punctuation():
    """Verifica a capitalização de palavras após pontuações finais."""
    assert fix_sentence_capitalization("olá. tudo bem?") == "Olá. Tudo bem?"
    assert fix_sentence_capitalization("sim! muito bom.") == "Sim! Muito bom."
    assert fix_sentence_capitalization("onde? aqui.") == "Onde? Aqui."
    # Sem espaço após o ponto
    assert fix_sentence_capitalization("sem espaco.não capitaliza") == "Sem espaco.não capitaliza"

def test_fix_sentence_capitalization_questions():
    """Verifica a conversão de afirmações em perguntas baseada em palavras-chave."""
    assert fix_sentence_capitalization("como fazer isso.") == "Como fazer isso?"
    assert fix_sentence_capitalization("Por que você fez isso.") == "Por que você fez isso?"
    # não começa com a palavra, não converte
    assert fix_sentence_capitalization("ele perguntou onde fica.") == "Ele perguntou onde fica."
    assert fix_sentence_capitalization("qual a sua idade.") == "Qual a sua idade?"
    assert fix_sentence_capitalization("quantos anos você tem.") == "Quantos anos você tem?"
