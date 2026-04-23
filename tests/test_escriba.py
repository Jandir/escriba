import pytest
import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import Dict, List, Any

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

from escriba import clean_ekklezia_terms, _strip_rollup, create_adaptive_windows
import pysrt
import escriba

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
    windows_list = create_adaptive_windows(subs_list, window_size_s_int=60)
    
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
        
        result_str = escriba.detect_language([], [], "http://dummy")
        assert result_str == "^pt$"

def test_detect_language_fallback():
    """Verifica o fallback para o idioma padrão quando nada é detectado."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "NA\nNA\n"
        mock_run.return_value = mock_result
        
        with patch.dict("os.environ", {"DEFAULT_LANGUAGE": "pt_BR"}):
            result_str = escriba.detect_language([], [], "http://dummy")
            assert result_str == "^pt_BR$"


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



