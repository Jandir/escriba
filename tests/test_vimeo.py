import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

from vimeo import download_video, filter_vimeo_cookies

def test_filter_vimeo_cookies_logic(tmp_path: Path):
    """Verifica se a filtragem de cookies do vimeo remove domínios não autorizados e mantém os válidos."""
    cookies_file_path: Path = tmp_path / "cookies.txt"
    content_str: str = (
        "# Netscape HTTP Cookie File\n"
        ".vimeo.com\tTRUE\t/\tFALSE\t0\tSID\tvalue1\n"
        ".akamaized.net\tTRUE\t/\tFALSE\t0\tGAIA\tvalue2\n"
        ".other.com\tTRUE\t/\tFALSE\t0\tID\tvalue3\n"
        ".evil.com\tTRUE\t/\tFALSE\t0\tID\tvimeo.com\n"
    )
    cookies_file_path.write_text(content_str, encoding="utf-8")

    filter_vimeo_cookies(cookies_file_path)

    result_str: str = cookies_file_path.read_text(encoding="utf-8")
    assert ".vimeo.com\tTRUE" in result_str
    assert ".akamaized.net\tTRUE" in result_str
    assert "other.com" not in result_str
    assert "evil.com" not in result_str
    assert "# Netscape" in result_str

def test_download_video_command_construction_vimeo():
    """Verifica se o comando yt-dlp é construído corretamente com e sem a flag download_video_only_hd no Vimeo."""
    import yt_dlp
    
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
            video_id_str="123456789",
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
            video_id_str="123456789",
            lang_filter_str="pt",
            folder_name_str="canal",
            download_video_only_hd=True
        )
        
        assert len(download_calls_params) == 2
        assert not download_calls_params[-1].get("skip_download")
        assert download_calls_params[-1].get("format") == "bestvideo[height<=1080]"
