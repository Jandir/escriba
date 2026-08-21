import pytest
import os
import sys
from pathlib import Path

# Adiciona diretório pai no path para facilitar import local de rules
sys.path.insert(0, str(Path(__file__).parent.parent))

from rules import clean_ekklezia_terms, _parse_rules_file, clean_asr_artifacts

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

def test_clean_asr_artifacts_empty():
    """Verifica comportamento com strings vazias e nulas."""
    assert clean_asr_artifacts("") == ""
    assert clean_asr_artifacts(None) == None

def test_clean_asr_artifacts_no_artifacts():
    """Verifica texto normal sem artefatos."""
    assert clean_asr_artifacts("Texto normal") == "Texto normal"

def test_clean_asr_artifacts_musical_notes():
    """Verifica remoção de notas musicais e caracteres hash."""
    assert clean_asr_artifacts("♪ Hello ♫") == "Hello"
    assert clean_asr_artifacts("# Music") == "Music"

def test_clean_asr_artifacts_brackets_case_insensitive():
    """Verifica remoção de marcadores comuns de ASR ignorando maiúsculas e minúsculas."""
    assert clean_asr_artifacts("[Música] Começa a tocar") == "Começa a tocar"
    assert clean_asr_artifacts("Apresentador entra [aplausos]") == "Apresentador entra"
    assert clean_asr_artifacts("[risos] Que engraçado") == "Que engraçado"
    assert clean_asr_artifacts("Fundo [música ao fundo]") == "Fundo"
    assert clean_asr_artifacts("[VINHETA]") == ""
    assert clean_asr_artifacts("[vinheta de abertura]") == ""
    assert clean_asr_artifacts("[LEGENDAS PELA COMUNIDADE]") == ""

def test_clean_asr_artifacts_unmatched_brackets():
    """Verifica que colchetes não listados não são removidos."""
    assert clean_asr_artifacts("Ação [Câmera] e [Luzes]") == "Ação [Câmera] e [Luzes]"

def test_clean_asr_artifacts_spacing():
    """Verifica se os espaços múltiplos e sobras são normalizados."""
    assert clean_asr_artifacts("  Muito    espaço  ") == "Muito espaço"
    assert clean_asr_artifacts("Texto ♪ com [Música] artefatos") == "Texto com artefatos"
