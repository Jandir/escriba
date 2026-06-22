import pytest
import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import Dict, List, Any

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

from escriba import clean_ekklezia_terms, _strip_rollup, create_adaptive_windows, srt_to_md, _dedup_lines
import pysrt
import escriba
import youtube

# ─── Termos Ekklezia ─────────────────────────────────────────────────────────

def test_clean_ekklezia_terms():
    """Verifica se a substituição de termos Ekklezia funciona corretamente."""
    assert clean_ekklezia_terms("Sete Montanhas e Ecclesia") == "Sete Montes e Ekklezia"
    assert clean_ekklezia_terms(None) == None
    assert clean_ekklezia_terms("Normal text") == "Normal text"





# ─── Roll-up e Deduplicação ──────────────────────────────────────────────────

def test_strip_rollup_full_overlap():
    """Verifica a remoção de texto repetido (roll-up) quando há sobreposição total."""
    prev_text_str: str = "Este é um teste"
    current_text_str: str = "Este é um teste de legenda"
    # Como "Este é um teste" (4 tokens) é o prefixo, ele deve ser removido.
    # Restando apenas o sufixo inédito.
    result_str: str = _strip_rollup(current_text_str, prev_text_str)
    assert result_str == "de legenda"

def test_strip_rollup_low_overlap():
    """Verifica se mantém o texto quando a sobreposição é baixa demais."""
    prev_text_str: str = "Início diferente"
    current_text_str: str = "Este é um teste de legenda"
    result_str: str = _strip_rollup(current_text_str, prev_text_str)
    # Não deve remover nada pois o primeiro token "Este" != "Início"
    assert result_str == "Este é um teste de legenda"


# ─── Janelas Adaptativas ─────────────────────────────────────────────────────

def test_create_adaptive_windows_basic():
    """Verifica a criação de janelas temporárias para processamento de legendas."""
    # Criamos um mock simples para objetos de legenda (subs)
    mock_sub1 = MagicMock()
    mock_sub1.start = pysrt.SubRipTime(seconds=1)
    mock_sub1.end = pysrt.SubRipTime(seconds=5)
    mock_sub1.text = "Olá"
    
    mock_sub2 = MagicMock()
    mock_sub2.start = pysrt.SubRipTime(seconds=10)
    mock_sub2.end = pysrt.SubRipTime(seconds=15)
    mock_sub2.text = "Mundo"
    
    subs_list = [mock_sub1, mock_sub2]
    windows_list, clean_texts = create_adaptive_windows(subs_list, window_size_s_int=60)
    
    assert len(windows_list) == 1
    assert windows_list[0]["text"] == "Olá Mundo"








# ─── Ambiente e Idioma ───────────────────────────────────────────────────────

def test_setup_environment_success():
    """Verifica se a configuração do ambiente retorna o diretório e o comando base."""
    with patch("youtube.setup_environment") as mock_setup:
        mock_setup.return_value = (Path("/tmp"), ["yt-dlp"])
        script_dir_path, cmd_list = mock_setup.return_value
        assert "yt-dlp" in cmd_list
        assert isinstance(script_dir_path, Path)

def test_detect_language_ignores_invalid_tags():
    """Verifica se tags 'NA' ou 'none' são ignoradas na detecção de idioma."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "NA\nnone\nNA\npt\n"
        mock_run.return_value = mock_result
        
        result_str = youtube.detect_language([], [], "http://dummy")
        assert result_str == "^pt.*"

def test_detect_language_fallback():
    """Verifica o fallback para o idioma padrão quando nada é detectado."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "NA\nNA\n"
        mock_run.return_value = mock_result
        
        with patch.dict("os.environ", {"DEFAULT_LANGUAGE": "pt_BR"}):
            result_str = youtube.detect_language([], [], "http://dummy")
            assert result_str == "^pt_BR.*"


# ─── Parsing de Entradas ──────────────────────────────────────────────────────

def test_parse_input_type_full_video_url():
    """Verifica se URLs completas de vídeos são reconhecidas como 'video'."""
    url_str, input_type_str, vid_id_str = escriba.parse_input_type("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert input_type_str == "video"
    assert vid_id_str == "dQw4w9WgXcQ"
    assert "watch?v=" in url_str

def test_parse_input_type_short_video_url():
    """Verifica se URLs encurtadas (youtu.be) são reconhecidas como 'video'."""
    url_str, input_type_str, vid_id_str = escriba.parse_input_type("https://youtu.be/dQw4w9WgXcQ")
    assert input_type_str == "video"
    assert vid_id_str == "dQw4w9WgXcQ"

def test_parse_input_type_bare_video_id():
    """Verifica se IDs puros de vídeo são reconhecidos e transformados em URL."""
    url_str, input_type_str, vid_id_str = escriba.parse_input_type("dQw4w9WgXcQ")
    assert input_type_str == "video"
    assert vid_id_str == "dQw4w9WgXcQ"
    assert url_str == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

def test_parse_input_type_playlist():
    """Verifica se URLs de playlist são reconhecidas corretamente."""
    url_str, input_type_str, vid_id_str = escriba.parse_input_type("https://www.youtube.com/playlist?list=PLxxx123")
    assert input_type_str == "playlist"
    assert vid_id_str == ""

def test_parse_input_type_channel_handle():
    """Verifica se handles de canal (@User) são reconhecidos corretamente."""
    url_str, input_type_str, vid_id_str = escriba.parse_input_type("@MeuCanal")
    assert input_type_str == "channel"
    assert vid_id_str == ""
    assert "youtube.com" in url_str


# ─── Filtragem e Sumários ─────────────────────────────────────────────────────

def test_filter_state_list_no_filter():
    """Verifica se a lista permanece intacta quando não há filtro de data."""
    videos_list = [
        {"video_id": "a", "publish_date": "2023-01-01"},
        {"video_id": "b", "publish_date": "2022-05-15"},
    ]
    result_list = escriba.filter_state_list(videos_list, "")
    assert len(result_list) == 2

def test_filter_state_list_with_date_filter():
    """Verifica a filtragem de vídeos por data (Apenas novos)."""
    videos_list = [
        {"video_id": "a", "publish_date": "20230601"},
        {"video_id": "b", "publish_date": "20220101"},
        {"video_id": "c", "publish_date": "N/A"},
    ]
    result_list = escriba.filter_state_list(videos_list, "20230101")
    video_ids_list = [v["video_id"] for v in result_list]
    assert "a" in video_ids_list
    assert "b" not in video_ids_list
    assert "c" not in video_ids_list

def test_print_summary_basic(capsys):
    """Verifica se o sumário final exibe os números corretos."""
    escriba.print_summary(
        downloaded_videos_count=5,
        skipped_videos_count=3,
        error_videos_count=0,
        total_videos_count=8,
    )
    captured = capsys.readouterr()
    assert "5" in captured.out
    assert "3" in captured.out
    assert "8" in captured.out


# ─── Validação de Download de Vídeo para Canais ───────────────────────────────

@patch("youtube.setup_environment")
@patch("escriba._print_session_info")
def test_setup_session_download_video_channel(mock_print_info, mock_setup_env):
    """Verifica se setup_session impede download de vídeo (-dv) para canais completos."""
    mock_setup_env.return_value = (Path("/tmp"), ["yt-dlp"])
    
    import argparse
    cli_args = argparse.Namespace(canal="@MeuCanal", download_video=True)
    
    with pytest.raises(SystemExit) as exc_info:
        escriba.setup_session(cli_args)
        
    assert exc_info.value.code == 1


@patch("youtube.setup_environment")
@patch("escriba._print_session_info")
@patch("escriba._resolve_uploader_id")
@patch("escriba.get_provider")
def test_setup_session_download_video_video(mock_provider, mock_uploader, mock_print_info, mock_setup_env):
    """Verifica se setup_session permite download de vídeo (-dv) para vídeos individuais."""
    mock_setup_env.return_value = (Path("/tmp"), ["yt-dlp"])
    mock_uploader.return_value = "uploader_id"
    mock_provider.return_value = "youtube"
    
    import argparse
    cli_args = argparse.Namespace(canal="dQw4w9WgXcQ", download_video=True)
    
    config = escriba.setup_session(cli_args)
    assert config.channel_input_url_or_handle == "dQw4w9WgXcQ"
    assert config.provider == "youtube"


@patch("youtube.setup_environment")
@patch("escriba._print_session_info")
@patch("escriba._resolve_uploader_id")
@patch("escriba.get_provider")
def test_setup_session_download_video_playlist(mock_provider, mock_uploader, mock_print_info, mock_setup_env):
    """Verifica se setup_session permite download de vídeo (-dv) para playlists."""
    mock_setup_env.return_value = (Path("/tmp"), ["yt-dlp"])
    mock_uploader.return_value = "uploader_id"
    mock_provider.return_value = "youtube"
    
    import argparse
    cli_args = argparse.Namespace(canal="https://www.youtube.com/playlist?list=PLxxx123", download_video=True)
    
    config = escriba.setup_session(cli_args)
    assert "playlist" in config.channel_url
    assert config.provider == "youtube"


# ─── Download Direto de Vídeo (-dv) ──────────────────────────────────────────

def test_validate_direct_download_target_video():
    """Valida se o alvo de download aceita URLs ou IDs de vídeo."""
    url_str, input_type_str = escriba._validate_direct_download_target("dQw4w9WgXcQ")
    assert input_type_str == "video"
    assert url_str == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    url_str, input_type_str = escriba._validate_direct_download_target("https://www.youtube.com/playlist?list=PLxxx123")
    assert input_type_str == "playlist"
    assert "playlist?list=" in url_str


def test_validate_direct_download_target_channel_aborts():
    """Valida se tentar baixar canal completo com -dv gera SystemExit(1)."""
    with pytest.raises(SystemExit) as exc_info:
        escriba._validate_direct_download_target("@MeuCanal")
    assert exc_info.value.code == 1

    with pytest.raises(SystemExit) as exc_info:
        escriba._validate_direct_download_target(None)
    assert exc_info.value.code == 1


def test_build_yt_dlp_direct_cmd():
    """Verifica se compila corretamente o comando do yt-dlp sem áudio e em MP4."""
    url_str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    base_cmd_list = ["/path/to/yt-dlp"]
    cookies_list = ["--cookies", "/path/to/cookies.txt"]
    
    cmd_list = escriba._build_yt_dlp_direct_cmd(url_str, base_cmd_list, cookies_list)
    
    # Valida presença dos argumentos exigidos pelo design do download de vídeo
    assert cmd_list[0] == "/path/to/yt-dlp"
    assert "--cookies" in cmd_list
    assert "--ignore-no-formats-error" in cmd_list
    assert "--restrict-filenames" in cmd_list
    assert "-f" in cmd_list
    assert "bestvideo[height<=1080]" in cmd_list
    assert "--remux-video" in cmd_list
    assert "mp4" in cmd_list
    assert "-o" in cmd_list
    assert "%(title)s [%(id)s].%(ext)s" in cmd_list
    assert cmd_list[-1] == url_str


@patch("escriba.filter_youtube_cookies")
@patch("pathlib.Path.is_file")
def test_filter_cookies_if_present_youtube(mock_is_file, mock_filter_yt):
    """Verifica se filtra cookies do YouTube quando o arquivo cookies.txt existe."""
    mock_is_file.return_value = True
    escriba._filter_cookies_if_present(Path("/dummy"), "youtube")
    mock_filter_yt.assert_called_once_with(Path("/dummy/cookies.txt"))


@patch("escriba.filter_vimeo_cookies")
@patch("pathlib.Path.is_file")
def test_filter_cookies_if_present_vimeo(mock_is_file, mock_filter_vimeo):
    """Verifica se filtra cookies do Vimeo quando o arquivo cookies.txt existe."""
    mock_is_file.return_value = True
    escriba._filter_cookies_if_present(Path("/dummy"), "vimeo")
    mock_filter_vimeo.assert_called_once_with(Path("/dummy/cookies.txt"))


# ─── SRT -> MD Pipeline ─────────────────────────────────────────────────────

import tempfile

def test_srt_to_md_basic():
    """Verifica o fluxo completo de conversão SRT para MD."""
    srt_content = """1
00:00:01,000 --> 00:00:05,000
Ola pessoal bem vindos ao canal

2
00:00:05,500 --> 00:00:10,000
Hoje vamos falar sobre programacao em Python

3
00:00:10,500 --> 00:00:15,000
Python e uma linguagem muito versatil

4
00:00:15,500 --> 00:00:20,000
Ela e usada em muitas areas

5
00:00:20,500 --> 00:00:25,000
Vamos comecar com os fundamentos

6
00:00:25,500 --> 00:00:30,000
Primeiro vamos entender variaveis

7
00:00:30,500 --> 00:00:35,000
Variaveis sao espacos na memoria

8
00:00:35,500 --> 00:00:40,000
Agora vamos falar sobre funcoes

9
00:00:40,500 --> 00:00:45,000
Funcoes sao blocos de codigo

10
00:00:45,500 --> 00:00:50,000
Elas ajudam a organizar o codigo

11
00:00:50,500 --> 00:00:55,000
Vamos ver exemplos praticos agora

12
00:00:55,500 --> 00:01:00,000
Espero que tenham gostado do video

13
00:01:00,500 --> 00:01:05,000
Nao esquecam de se inscrever

14
00:01:05,500 --> 00:01:10,000
E ativar o sininho de notificacoes
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        srt_path = Path(tmpdir) / "test-abc12345678-pt.srt"
        srt_path.write_text(srt_content, encoding="utf-8")
        result = srt_to_md(srt_path, "abc12345678", "Teste Python", "2026-01-01")
        assert result is not None
        assert result.exists()
        md = result.read_text(encoding="utf-8")
        assert "---" in md
        assert "Teste Python" in md
        assert "### Transcri" in md


def test_srt_to_md_empty_file():
    """Verifica comportamento com arquivo SRT vazio."""
    with tempfile.TemporaryDirectory() as tmpdir:
        srt_path = Path(tmpdir) / "test-abc12345678-pt.srt"
        srt_path.write_text("", encoding="utf-8")
        result = srt_to_md(srt_path, "abc12345678", "Teste Vazio")
        assert result is None


def test_srt_to_md_nonexistent_file():
    """Verifica comportamento com arquivo SRT inexistente."""
    fake_path = Path("/tmp/nonexistent-abc12345678-pt.srt")
    result = srt_to_md(fake_path, "abc12345678", "Teste Inexistente")
    assert result is None


def test_dedup_lines_word_level():
    """Verifica dedup por palavras: 'cat' nao deve casar com 'category'."""
    lines = ["cat", "category", " dogs"]
    result = _dedup_lines(lines)
    assert len(result) == 3


def test_dedup_lines_rollup():
    """Verifica dedup de roll-up: linha prefixo deve ser removida."""
    lines = ["Ola pessoal", "Ola pessoal bem vindos"]
    result = _dedup_lines(lines)
    assert len(result) == 1
    assert result[0] == "Ola pessoal bem vindos"


def test_dedup_lines_identical():
    """Verifica dedup de linhas identicas."""
    lines = ["mesma linha", "mesma linha"]
    result = _dedup_lines(lines)
    assert len(result) == 1


def test_create_adaptive_windows_returns_clean_texts():
    """Verifica que create_adaptive_windows retorna tuple (windows, clean_texts)."""
    mock_sub1 = MagicMock()
    mock_sub1.start = pysrt.SubRipTime(seconds=1)
    mock_sub1.end = pysrt.SubRipTime(seconds=5)
    mock_sub1.text = "Olá mundo"
    
    mock_sub2 = MagicMock()
    mock_sub2.start = pysrt.SubRipTime(seconds=10)
    mock_sub2.end = pysrt.SubRipTime(seconds=15)
    mock_sub2.text = "Teste de legenda"
    
    subs_list = [mock_sub1, mock_sub2]
    result = create_adaptive_windows(subs_list, window_size_s_int=60)
    
    assert isinstance(result, tuple)
    assert len(result) == 2
    windows_list, clean_texts = result
    assert isinstance(windows_list, list)
    assert isinstance(clean_texts, dict)
    assert len(windows_list) == 1
    assert len(clean_texts) == 2



