import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

from vimeo import (
    DownloadResult,
    _find_best_vimeo_subtitle,
    _is_allowed_vimeo_domain,
    _is_rate_limit_error,
    detect_language,
    download_video,
    filter_vimeo_cookies,
    generate_fast_list_json,
)


def test_download_video_command_construction_vimeo() -> None:
    """Verifica se o comando yt-dlp é construído corretamente com e sem a flag download_video_only_hd no Vimeo."""
    extract_calls_params_list = []
    download_calls_params_list = []

    def mock_extract(self, url_str: str, download: bool = False):
        extract_calls_params_list.append(dict(self.params))
        return {
            "subtitles": {"pt": [{"url": "http://example.com/pt.vtt", "ext": "vtt"}]},
            "automatic_captions": {},
        }

    def mock_process(self, info_dict: dict):
        download_calls_params_list.append(dict(self.params))
        return 0

    with patch.object(yt_dlp.YoutubeDL, "extract_info", mock_extract), \
         patch.object(yt_dlp.YoutubeDL, "process_info", mock_process):

        # Teste 1: download_video_only_hd = False (padrão)
        res_int = download_video(
            yt_dlp_cmd_list=["python", "-m", "yt_dlp"],
            cookie_args_list=["--cookies", "cookies.txt"],
            video_id_str="123456789",
            lang_filter_str="pt",
            folder_name_str="canal",
        )
        assert res_int == DownloadResult.SUCCESS
        assert len(download_calls_params_list) == 1
        assert download_calls_params_list[-1].get("skip_download") is True
        assert download_calls_params_list[-1].get("format") is None

        # Teste 2: download_video_only_hd = True
        res_int = download_video(
            yt_dlp_cmd_list=["python", "-m", "yt_dlp"],
            cookie_args_list=["--cookies", "cookies.txt"],
            video_id_str="123456789",
            lang_filter_str="pt",
            folder_name_str="canal",
            download_video_only_hd=True,
        )
        assert res_int == DownloadResult.SUCCESS
        assert len(download_calls_params_list) == 2
        assert not download_calls_params_list[-1].get("skip_download")
        assert download_calls_params_list[-1].get("format") == "bestvideo[height<=1080]"


def test_download_video_invalid_id_vimeo() -> None:
    """Verifica se IDs inválidos/truncados de Vimeo retornam código FAILED imediatamente."""
    res_int = download_video(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        video_id_str="12345",  # 5 caracteres (inválido, precisa ter entre 7 e 12 dígitos)
        lang_filter_str="pt",
        folder_name_str="canal",
    )
    assert res_int == DownloadResult.FAILED


def test_find_best_vimeo_subtitle_priority() -> None:
    """Verifica a prioridade de seleção de legenda (manual vs automática e idioma)."""
    # 1. Manual no idioma solicitado tem prioridade
    subs_dict = {"pt-BR": [{"ext": "vtt"}]}
    auto_dict = {"pt": [{"ext": "vtt"}]}
    lang_str, is_auto_bool = _find_best_vimeo_subtitle(subs_dict, auto_dict, "pt")
    assert lang_str == "pt-BR"
    assert is_auto_bool is False

    # 2. Automática no idioma solicitado quando manual não existe
    subs_dict = {"en": [{"ext": "vtt"}]}
    auto_dict = {"pt": [{"ext": "vtt"}]}
    lang_str, is_auto_bool = _find_best_vimeo_subtitle(subs_dict, auto_dict, "pt")
    assert lang_str == "pt"
    assert is_auto_bool is True

    # 3. Fallback para inglês quando idioma principal não existe
    subs_dict = {"en-US": [{"ext": "vtt"}]}
    auto_dict = {}
    lang_str, is_auto_bool = _find_best_vimeo_subtitle(subs_dict, auto_dict, "es")
    assert lang_str == "en-US"
    assert is_auto_bool is False

    # 4. Nenhuma legenda disponível
    lang_str, is_auto_bool = _find_best_vimeo_subtitle({}, {}, "pt")
    assert lang_str is None
    assert is_auto_bool is False


def test_detect_language_cached() -> None:
    """Verifica se detect_language retorna imediatamente quando há idioma em cache."""
    cached_str = "^pt.*"
    res_str = detect_language(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        channel_url_str="https://vimeo.com/channels/staffpicks",
        cached_lang_str=cached_str,
    )
    assert res_str == cached_str


@patch("subprocess.run")
def test_detect_language_sampling(mock_run: MagicMock) -> None:
    """Verifica se detect_language realiza amostragem dos 3 primeiros vídeos e encontra a língua mais comum."""
    # Mock do comando de listagem dos 3 primeiros vídeos
    proc_list = MagicMock()
    proc_list.returncode = 0
    proc_list.stdout = '{"id": "1111111"}\n{"id": "2222222"}\n'

    # Mock do comando de metadados de cada vídeo
    proc_meta1 = MagicMock()
    proc_meta1.returncode = 0
    proc_meta1.stdout = json.dumps({
        "subtitles": {"pt-BR": [{}]},
        "automatic_captions": {},
    })

    proc_meta2 = MagicMock()
    proc_meta2.returncode = 0
    proc_meta2.stdout = json.dumps({
        "subtitles": {"pt": [{}]},
        "automatic_captions": {},
    })

    mock_run.side_effect = [proc_list, proc_meta1, proc_meta2]

    lang_result_str = detect_language(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        channel_url_str="https://vimeo.com/channels/staffpicks",
    )
    assert lang_result_str == "^pt.*"


@patch("subprocess.run")
def test_detect_language_fallback(mock_run: MagicMock) -> None:
    """Verifica se detect_language usa fallback configurado quando nenhum idioma é detectado."""
    proc_err = MagicMock()
    proc_err.returncode = 1
    proc_err.stdout = ""
    mock_run.return_value = proc_err

    lang_result_str = detect_language(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        channel_url_str="https://vimeo.com/channels/staffpicks",
    )
    assert lang_result_str == "^pt.*"


@patch("subprocess.Popen")
def test_generate_fast_list_json(mock_popen: MagicMock) -> None:
    """Verifica a extração rápida de lista de vídeos do Vimeo."""
    proc_mock = MagicMock()
    proc_mock.stdout = [
        json.dumps({"id": "1234567", "title": "Vídeo 1", "upload_date": "20260101"}) + "\n",
        json.dumps({"id": "7654321", "title": "Vídeo 2", "date": "20260201"}) + "\n",
    ]
    proc_mock.returncode = 0
    proc_mock.wait.return_value = 0
    mock_popen.return_value.__enter__.return_value = proc_mock

    results_list = generate_fast_list_json(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        channel_url_str="https://vimeo.com/channels/staffpicks",
    )

    assert len(results_list) == 2
    assert results_list[0]["video_id"] == "1234567"
    assert results_list[0]["title"] == "Vídeo 1"
    assert results_list[0]["publish_date"] == "2026-01-01"
    assert results_list[1]["video_id"] == "7654321"


@patch("subprocess.Popen")
def test_generate_fast_list_json_smart_sync(mock_popen: MagicMock) -> None:
    """Verifica se o Smart Sync encerra a varredura ao atingir MAX_CONSECUTIVE_KNOWN."""
    proc_mock = MagicMock()
    # 12 vídeos conhecidos consecutivos
    lines = [json.dumps({"id": f"100000{i}"}) + "\n" for i in range(12)]
    proc_mock.stdout = lines
    proc_mock.returncode = 0
    proc_mock.wait.return_value = 0
    mock_popen.return_value.__enter__.return_value = proc_mock

    stop_ids_set = {f"100000{i}" for i in range(12)}
    results_list = generate_fast_list_json(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=[],
        channel_url_str="https://vimeo.com/channels/staffpicks",
        stop_at_ids=stop_ids_set,
    )

    assert proc_mock.terminate.called
    assert len(results_list) <= 10


def test_filter_vimeo_cookies(tmp_path: Path) -> None:
    """Verifica se a higienização de cookies preserva apenas domínios do Vimeo e Akamai."""
    cookies_file_path = tmp_path / "cookies.txt"
    sample_content = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.vimeo.com\tTRUE\t/\tTRUE\t0\tsession\tsecret1\n"
        ".google.com\tTRUE\t/\tTRUE\t0\tSID\tsecret2\n"
        "akamaized.net\tTRUE\t/\tFALSE\t0\takasid\tsecret3\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tYSC\tsecret4\n"
    )
    cookies_file_path.write_text(sample_content, encoding="utf-8")

    filter_vimeo_cookies(cookies_file_path)

    result_content = cookies_file_path.read_text(encoding="utf-8")
    assert "vimeo.com" in result_content
    assert "akamaized.net" in result_content
    assert "google.com" not in result_content
    assert "youtube.com" not in result_content


def test_is_allowed_vimeo_domain() -> None:
    """Verifica a função auxiliar de correspondência de domínios permitidos."""
    allowed = ["vimeo.com", "akamaized.net"]
    assert _is_allowed_vimeo_domain("vimeo.com", allowed) is True
    assert _is_allowed_vimeo_domain(".vimeo.com", allowed) is True
    assert _is_allowed_vimeo_domain("player.vimeo.com", allowed) is True
    assert _is_allowed_vimeo_domain("akamaized.net", allowed) is True
    assert _is_allowed_vimeo_domain("youtube.com", allowed) is False
    assert _is_allowed_vimeo_domain("notvimeo.com", allowed) is False


def test_is_rate_limit_error() -> None:
    """Verifica a identificação de erros de rate limit (HTTP 429)."""
    assert _is_rate_limit_error(Exception("HTTP Error 429: Too Many Requests")) is True
    assert _is_rate_limit_error(Exception("Generic connection error")) is False


@patch("vimeo._refresh_cookies_on_error")
@patch("vimeo._try_extract_and_download")
def test_download_video_auto_healing(
    mock_extract_and_download: MagicMock,
    mock_refresh: MagicMock
) -> None:
    """Verifica se download_video tenta renovar cookies após uma primeira falha."""
    mock_extract_and_download.side_effect = [
        RuntimeError("403 Forbidden"),  # Primeira tentativa falha
        None,  # Segunda tentativa após renovação sucede
    ]
    mock_refresh.return_value = ["--cookies", "new_cookies.txt"]

    res_int = download_video(
        yt_dlp_cmd_list=["yt-dlp"],
        cookie_args_list=["--cookies", "cookies.txt"],
        video_id_str="123456789",
        lang_filter_str="pt",
        folder_name_str="canal",
    )

    assert res_int == DownloadResult.SUCCESS
    assert mock_refresh.called
    assert mock_extract_and_download.call_count == 2
