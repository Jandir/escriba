import pytest
import os
import sys
from pathlib import Path

# Adiciona diretório pai no path para facilitar import local de rules
sys.path.insert(0, str(Path(__file__).parent.parent))

from rules import clean_ekklezia_terms

def test_clean_terms_empty():
    assert clean_ekklezia_terms("") == ""
    assert clean_ekklezia_terms(None) == None

def test_clean_terms_no_rules_match():
    # Isso simula o comportamento se o rules.txt não existir
    assert clean_ekklezia_terms("Hello World") == "Hello World"
