import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

from youtube import (
    filter_youtube_cookies, 
    configure_cookies, 
    _normalize_lang_pattern, 
    _is_rate_limit_error,
    DownloadResult,
    download_video
)
import yt_dlp
from yt_dlp.utils import DownloadError

# EXPLICAÇÃO PARA JUNIORES:
# Testar interações com o sistema de arquivos ou rede (como cookies do YouTube)
# exige cautela. Usamos o `tmp_path` do pytest para criar um ambiente isolado
# onde podemos criar arquivos fictícios sem sujar o computador real do usuário.

def test_filter_youtube_cookies_logic(tmp_path: Path):
    """Verifica se a filtragem de cookies remove domínios não autorizados e mantém os do YouTube/Google de forma segura."""
    cookies_file_path: Path = tmp_path / "cookies.txt"
    content_str: str = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tvalue1\n"
        ".google.com\tTRUE\t/\tFALSE\t0\tGAIA\tvalue2\n"
        ".other.com\tTRUE\t/\tFALSE\t0\tID\tvalue3\n"
        "#HttpOnly_.youtube.com\tTRUE\t/\tFALSE\t0\tHSID\tvalue4\n"
        ".evilyoutube.com\tTRUE\t/\tFALSE\t0\tEVIL\tvalue5\n"
        "#HttpOnly_.other.com\tTRUE\t/\tFALSE\t0\tID\tvalue6\n"
    )
    cookies_file_path.write_text(content_str, encoding="utf-8")
    
    filter_youtube_cookies(cookies_file_path)
    
    result_str: str = cookies_file_path.read_text(encoding="utf-8")
    assert "value1" in result_str  # youtube.com normal
    assert "value2" in result_str  # google.com normal
    assert "value3" not in result_str  # other.com drop
    assert "value4" in result_str  # youtube.com httponly
    assert "value5" not in result_str  # evilyoutube.com evasion drop
    assert "value6" not in result_str  # other.com httponly drop
    assert "# Netscape" in result_str


def test_filter_youtube_cookies_missing_file():
    """Verifica se a função lida graciosamente com a ausência do arquivo de cookies."""
    # Não deve levantar erro
    filter_youtube_cookies(Path("non_existent_cookies_file.txt"))


def test_configure_cookies_pure_and_explicit(tmp_path: Path):
    """Garante que configure_cookies retorna os parâmetros esperados e não depende de estado global."""
    script_dir = tmp_path / "script"
    script_dir.mkdir()
    
    # Sem cookies.txt existente: deve retornar argumentos do navegador especificado
    args_chrome = configure_cookies(tmp_path, script_dir, force_refresh_bool=False, browser_str="chrome")
    assert args_chrome == ["--cookies-from-browser", "chrome", "--cookies", str(tmp_path / "cookies.txt")]
    
    # Com cookies.txt válido existente
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tSID\tv\n", encoding="utf-8")
    args_cached = configure_cookies(tmp_path, script_dir, force_refresh_bool=False, browser_str="firefox")
    assert args_cached == ["--cookies", str(cookies_file)]
    
    # Com force_refresh_bool: deve expurgar e voltar a pedir do navegador
    args_refreshed = configure_cookies(tmp_path, script_dir, force_refresh_bool=True, browser_str="brave")
    assert not cookies_file.exists()
    assert args_refreshed == ["--cookies-from-browser", "brave", "--cookies", str(cookies_file)]


def test_normalize_lang_pattern():
    """Verifica se o helper de normalização de regex do idioma funciona nos diversos formatos."""
    assert _normalize_lang_pattern("pt") == "^pt.*"
    assert _normalize_lang_pattern("^en.*") == "^en.*"
    assert _normalize_lang_pattern("pt|en") == "pt|en"
    assert _normalize_lang_pattern("N/A") == "N/A"
    assert _normalize_lang_pattern("") == ""


def test_is_rate_limit_error():
    """Verifica a identificação precisa de erros HTTP 429 / Rate Limit."""
    err_429 = DownloadError("HTTP Error 429: Too Many Requests")
    assert _is_rate_limit_error(err_429) is True

    err_generic_429 = Exception("Error code: 429")
    assert _is_rate_limit_error(err_generic_429) is True

    err_other = DownloadError("HTTP Error 404: Not Found")
    assert _is_rate_limit_error(err_other) is False


def test_download_result_enum():
    """Verifica a integridade e compatibilidade com inteiros do enum DownloadResult."""
    assert DownloadResult.SUCCESS == 0
    assert DownloadResult.SKIPPED == 1
    assert DownloadResult.FAILED == 2


def test_download_video_command_construction():
    """Verifica se o comando yt-dlp é construído corretamente com e sem a flag download_video_only_hd."""
    extract_calls_params = []
    download_calls_params = []
    
    def mock_extract(self, url, download=False):
        extract_calls_params.append(dict(self.params))
        return {
            'subtitles': {'pt': [{'url': 'http://example.com/pt.vtt', 'ext': 'vtt'}]},
            'automatic_captions': {}
        }
        
    def mock_process(self, info):
        download_calls_params.append(dict(self.params))
        return 0
        
    with patch.object(yt_dlp.YoutubeDL, "extract_info", mock_extract), \
         patch.object(yt_dlp.YoutubeDL, "process_info", mock_process):
         
        # Teste 1: download_video_only_hd = False (padrão)
        res1 = download_video(
            yt_dlp_cmd_list=["yt-dlp"],
            cookie_args_list=["--cookies", "cookies.txt"],
            video_id_str="jNQXAC9IVRw",
            lang_filter_str="pt",
            folder_name_str="canal"
        )
        assert res1 == DownloadResult.SUCCESS
        assert len(download_calls_params) == 1
        assert download_calls_params[-1].get("skip_download") is True
        assert download_calls_params[-1].get("format") is None
        
        # Teste 2: download_video_only_hd = True
        res2 = download_video(
            yt_dlp_cmd_list=["yt-dlp"],
            cookie_args_list=["--cookies", "cookies.txt"],
            video_id_str="jNQXAC9IVRw",
            lang_filter_str="pt",
            folder_name_str="canal",
            download_video_only_hd=True
        )
        assert res2 == DownloadResult.SUCCESS
        assert len(download_calls_params) == 2
        assert not download_calls_params[-1].get("skip_download")
        assert download_calls_params[-1].get("format") == "bestvideo[height<=1080]"


def test_download_video_invalid_id_youtube():
    """Verifica se IDs inválidos/truncados de YouTube retornam código FAILED (2) imediatamente."""
    res = download_video(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        video_id_str="kThAk18lk",  # 9 caracteres (inválido)
        lang_filter_str="pt",
        folder_name_str="canal"
    )
    assert res == DownloadResult.FAILED
    assert res == 2


def test_download_video_auto_healing_success(tmp_path: Path):
    """Garante que falhas normais disparam auto-healing de cookies e recuperam no retry."""
    attempts = [0]
    
    def mock_extract(self, url, download=False):
        attempts[0] += 1
        if attempts[0] == 1:
            raise DownloadError("HTTP Error 403: Forbidden")
        return {
            'subtitles': {'pt': [{'url': 'http://example.com/pt.vtt', 'ext': 'vtt'}]},
            'automatic_captions': {}
        }
        
    def mock_process(self, info):
        return 0

    with patch.object(yt_dlp.YoutubeDL, "extract_info", mock_extract), \
         patch.object(yt_dlp.YoutubeDL, "process_info", mock_process), \
         patch("youtube._refresh_cookies_on_error", return_value=["--cookies", "fresh_cookies.txt"]) as mock_refresh:
         
        res = download_video(
            yt_dlp_cmd_list=["yt-dlp"],
            cookie_args_list=["--cookies", "old_cookies.txt"],
            video_id_str="jNQXAC9IVRw",
            lang_filter_str="pt",
            folder_name_str="canal"
        )
        
        assert res == DownloadResult.SUCCESS
        assert attempts[0] == 2
        assert mock_refresh.called
