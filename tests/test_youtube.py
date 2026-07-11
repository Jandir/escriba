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


def test_download_video_command_construction():
    """Verifica se o comando yt-dlp é construído corretamente com e sem a flag download_video_only_hd."""
    from unittest.mock import patch
    import yt_dlp
    from youtube import download_video
    
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
        download_video(
            yt_dlp_cmd_list=["yt-dlp"],
            cookie_args_list=["--cookies", "cookies.txt"],
            video_id_str="jNQXAC9IVRw",
            lang_filter_str="pt",
            folder_name_str="canal"
        )
        
        assert len(download_calls_params) == 1
        assert download_calls_params[-1].get("skip_download") is True
        assert download_calls_params[-1].get("format") is None
        
        # Teste 2: download_video_only_hd = True
        download_video(
            yt_dlp_cmd_list=["yt-dlp"],
            cookie_args_list=["--cookies", "cookies.txt"],
            video_id_str="jNQXAC9IVRw",
            lang_filter_str="pt",
            folder_name_str="canal",
            download_video_only_hd=True
        )
        
        assert len(download_calls_params) == 2
        assert not download_calls_params[-1].get("skip_download")
        assert download_calls_params[-1].get("format") == "bestvideo[height<=1080]"


def test_download_video_invalid_id_youtube():
    """Verifica se IDs inválidos/truncados de YouTube retornam código 2 imediatamente."""
    from youtube import download_video
    
    res = download_video(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        video_id_str="kThAk18lk",  # 9 caracteres (inválido)
        lang_filter_str="pt",
        folder_name_str="canal"
    )
    assert res == 2

