import pytest
import sys
import os
from pathlib import Path

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

from youtube import filter_youtube_cookies

# EXPLICAÇÃO PARA JUNIORES:
# Testar interações com o sistema de arquivos ou rede (como cookies do YouTube)
# exige cautela. Usamos o `tmp_path` do pytest para criar um ambiente isolado
# onde podemos criar arquivos fictícios sem sujar o computador real do usuário.

def test_filter_youtube_cookies_logic(tmp_path: Path):
    """Verifica se a filtragem de cookies remove domínios não autorizados e mantém os do YouTube/Google."""
    cookies_file_path: Path = tmp_path / "cookies.txt"
    content_str: str = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tvalue1\n"
        ".google.com\tTRUE\t/\tFALSE\t0\tGAIA\tvalue2\n"
        ".other.com\tTRUE\t/\tFALSE\t0\tID\tvalue3\n"
    )
    cookies_file_path.write_text(content_str, encoding="utf-8")
    
    filter_youtube_cookies(cookies_file_path)
    
    result_str: str = cookies_file_path.read_text(encoding="utf-8")
    assert "youtube.com" in result_str
    assert "google.com" in result_str
    assert "other.com" not in result_str
    assert "# Netscape" in result_str

def test_filter_youtube_cookies_missing_file():
    """Verifica se a função lida graciosamente com a ausência do arquivo de cookies."""
    # Não deve levantar erro
    filter_youtube_cookies(Path("non_existent_cookies_file.txt"))


from unittest.mock import patch, MagicMock
import os

def test_detect_language_ignores_invalid_tags():
    """Verifica se tags 'NA' ou 'none' são ignoradas na detecção de idioma."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "NA\nnone\nNA\npt\n"
        mock_run.return_value = mock_result

        import youtube
        result_str = youtube.detect_language([], [], "http://dummy")
        assert result_str == "^pt.*"

def test_detect_language_fallback():
    """Verifica o fallback para o idioma padrão quando nada é detectado."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "NA\nNA\n"
        mock_run.return_value = mock_result

        with patch.dict("os.environ", {"DEFAULT_LANGUAGE": "pt_BR"}):
            import youtube
            result_str = youtube.detect_language([], [], "http://dummy")
            assert result_str == "^pt_BR.*"
