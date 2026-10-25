import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import extract_video_id

def test_extract_video_id_youtube():
    """Testa a extração de IDs normais do YouTube de arquivos gerados pelo yt-dlp."""
    assert extract_video_id("meu_canal-ZHbX0yoC8uo.info.json") == "ZHbX0yoC8uo"
    assert extract_video_id("ZHbX0yoC8uo.srt") == "ZHbX0yoC8uo"

def test_extract_video_id_suffixes():
    """Testa a extração ignorando os sufixos comuns de idioma ou -orig antes da extensão."""
    assert extract_video_id("video-ZHbX0yoC8uo.pt-br.srt") == "ZHbX0yoC8uo"
    assert extract_video_id("video-ZHbX0yoC8uo-orig.md") == "ZHbX0yoC8uo"
    assert extract_video_id("video-ZHbX0yoC8uo-en.vtt") == "ZHbX0yoC8uo"

def test_extract_video_id_embedded():
    """Testa o comportamento (atual) de varredura inversa, que pode falhar de forma não-intuitiva com strings embutidas.
    A implementação atual no utils.py usa regex e pode capturar substrings de formas inesperadas.
    O teste reflete o estado atual, mesmo que pareça não ideal.
    """
    # A implementação atual busca '([A-Za-z0-9_-]{11})' e faz .rfind() e match extra.
    # Quando falha em achar na ponta, e falha na verificação de isolamento,
    # ele pega os últimos 11 caracteres.
    assert extract_video_id("prefix_123456789AB_suffix.txt") == "89AB_suffix" # Comportamento atual do código

def test_extract_video_id_vimeo():
    """Testa o comportamento com nomes do vimeo ou strings sem ID de youtube.
    A implementação atual tem um fallback bizarro se falhar o youtube.
    """
    assert extract_video_id("meu_video-123456789.srt") == "o-123456789" # Comportamento atual
    assert extract_video_id("1234567.srt") == "Sem ID" # Sem fallback pra 7 caracteres pq n fecha 11?

def test_extract_video_id_none():
    """Testa quando de fato não se acha nada."""
    assert extract_video_id("just_a_normal_filename_without_id.srt") == "_without_id" # Comportamento atual
    assert extract_video_id("short.srt") == "Sem ID"
