import pytest
from rules import fix_sentence_capitalization, restore_punctuation_heuristics

def test_fix_sentence_capitalization():
    text = "olá mundo. este é um teste. como você vai?"
    expected = "Olá mundo. Este é um teste. Como você vai?"
    assert fix_sentence_capitalization(text) == expected

def test_restore_punctuation_long_pause():
    text = "nós estamos aprendendo python"
    # Long pause (>= 1.0s) should add period and capitalize
    res = restore_punctuation_heuristics(text, pause_after_seconds=1.2, is_last_segment=False)
    assert res == "Nós estamos aprendendo python."

def test_restore_punctuation_medium_pause():
    text = "primeiro passo"
    # Medium pause (0.15s to 0.4s) should add comma
    res = restore_punctuation_heuristics(text, pause_after_seconds=0.25, is_last_segment=False)
    assert res == "Primeiro passo,"

def test_restore_punctuation_question_trigger():
    text = "como podemos resolver este problema"
    # Question trigger + long pause -> should add question mark '?'
    res = restore_punctuation_heuristics(text, pause_after_seconds=1.5, is_last_segment=False)
    assert res == "Como podemos resolver este problema?"

def test_restore_punctuation_already_punctuated():
    text = "este texto já tem ponto final."
    res = restore_punctuation_heuristics(text, pause_after_seconds=2.0, is_last_segment=False)
    assert res == "Este texto já tem ponto final."
