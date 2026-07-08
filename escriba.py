#!/usr/bin/env python3
"""
=============================================================================
ESCRIBA: Orquestrador de Download de Legendas do YouTube/Vimeo
=============================================================================

SUMÁRIO DO SCRIPT:
Baixa legendas de todos os vídeos de um canal do YouTube ou Vimeo.
O objetivo original é utilizar estas legendas como fontes no NotebookLM,
para alavancar estudos sobre determinado autor ou assunto.

Principais Funcionalidades:
1. Sincronização Incremental: Mantém o registro de progresso primário em
   `escriba_*.json` (metadados e legendas), centralizando o estado da sessão.
2. Controle de Ausência: Registra status `has_no_subtitle` no JSON de estado
   para evitar novas tentativas de extração futuramente.
3. Tratamento de Formatação e Limpeza: Baixa `.srt` e gera `.md` estruturado por IA.
4. Interface Visual Rica (CLI): Fornece cores semânticas e contadores de tempo e status.

Este script segue as regras de Clean Code Naming para Ekklezia: variáveis
com nomes reveladores, sem aspas enigmáticas e com sufixos tipados
(`_list`, `_set`, `_dict`, `_path`, etc.) para máxima legibilidade.
=============================================================================
"""

import os
import sys
import signal

# Força codificação UTF-8 no console do Windows para evitar UnicodeEncodeError com emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys._escriba_interrupted = False

def setup_sigint_handler() -> None:
    """Registra um tratador de sinal customizado para CTRL+C para definir a flag global."""
    def handler(signum, frame):
        sys._escriba_interrupted = True
        raise KeyboardInterrupt
        
    signal.signal(signal.SIGINT, handler)

import subprocess
import warnings
from pathlib import Path

# ─── Gerenciamento de Ambiente Virtual ───────────────────────────────────────
# Quando rodamos o script diretamente (ex: python3 escriba.py), pode ser que o Python
# usado seja o do sistema, não o do ambiente virtual (.venv). Esse bloco detecta isso
# e reinicia o script usando o Python correto do venv, garantindo que todas as dependências
# (requests, urllib3, yt-dlp) sejam as do projeto e não asglobais do sistema.
_script_dir = Path(__file__).parent.resolve()
_venv_bin = _script_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin")
_venv_python = _venv_bin / ("python.exe" if os.name == "nt" else "python3")

if _venv_python.exists() and Path(sys.executable).resolve() != _venv_python.resolve():
    try:
        # EXPLICAÇÃO PARA JUNIORES:
        # Aqui, estamos trocando o "motor" do Python. Se o script começou com o Python
        # do sistema, nós o paramos e reiniciamos usando o Python que está dentro da
        # nossa pasta .venv, onde todas as ferramentas necessárias estão instaladas.
        os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)
    except Exception:
        pass # Fallback suave

# Suprime avisos chatos de dependências (urllib3ngt/requests)
# Isso evita que warnings do urllib3 poluam a saída do CLI.
# Aplicamos DEPOIS do re-execução do venv para garantir que funciona após restart.
import requests.packages.urllib3
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported")
warnings.filterwarnings("ignore", message=".*doesn't match a supported version")

import argparse
import glob
import json
import re
import random
import threading
try:
    import _interpreters
except ImportError:
    _interpreters = None
import shutil
import time
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import print_ok, print_err, print_warn, print_info, print_skip, print_dl, print_section, print_header, print_countdown, extract_video_id, format_date, BOLD, RESET, DIM, GREEN, RED, YELLOW, BLUE, WHITE, BCYAN, BWHITE, BRED, BGREEN, BYELLW, ICON_OK, ICON_ERR, ICON_WARN, ICON_SKIP, ICON_DL, ICON_WAIT, ICON_INFO
from rules import clean_ekklezia_terms
from history import get_latest_json_path, load_all_local_history, save_channel_state_json, auto_migrate_legacy_files, migrate_all_databases, filter_state_list, register_channel_in_json
import youtube
from youtube import configure_cookies, filter_youtube_cookies
import vimeo
from vimeo import filter_vimeo_cookies
from datetime import datetime
from dataclasses import dataclass
from lexis import consolidar_por_canal

from typing import Optional
from dotenv import load_dotenv
import requests

from collections import Counter

VERSION = "2.7.1"
DEFAULT_THRESHOLD = 0.3

_script_dir = Path(__file__).parent.resolve()

@dataclass
class SessionConfig:
    """Configuração de sessão montada durante o setup inicial."""
    cwd_path: Path
    channel_dir_name: str
    script_dir_path: Path
    yt_dlp_cmd_list: list[str]
    channel_input_url_or_handle: str
    channel_url: str
    discovered_uploader_id: Optional[str] = None
    provider: str = "youtube" # 'youtube' ou 'vimeo'
    disk_files_cache: dict[str, list[str]] = None  # Cache indexado por video_id: { "vid_id": ["file1.srt", "file1.md"] }
    browser_name: str = "firefox"


@dataclass
class DownloadConfig:
    """Configurações para download de um vídeo específico."""
    language: str  # Idioma das legendas
    output_dir: Path | None = None  # Diretório customizado
    keep_srt: bool = False  # Manter .srt após converter para .md

# Carrega variáveis do .env (localizado no diretório do script)
load_dotenv(Path(__file__).parent / ".env")

# Node.js path para o js-runtime do yt-dlp.
# Por que isso? O yt-dlp às vezes precisa de JavaScript para processar certain páginas.
# Prioridade: variável NODE_PATH do .env (se você definir) → node encontrado no PATH do sistema
NODE_PATH = os.getenv("NODE_PATH") or shutil.which("node") or ""

def _extract_video_meta_cli(url_str: str, cmd_list: list[str], cookie_args_list: list[str]) -> tuple[str | None, str | None]:
    """Executa comando yt-dlp para extrair metadados de vídeo único."""
    meta_cmd_list: list[str] = cmd_list + cookie_args_list + ["--dump-json", "--skip-download", url_str]
    try:
        proc_res_obj = subprocess.run(meta_cmd_list, capture_output=True, text=True, encoding="utf-8", timeout=15)
        if proc_res_obj.stdout:
            meta_dict: dict = json.loads(proc_res_obj.stdout)
            # Para o Vimeo, o uploader_id pode estar em outros campos, mas o yt-dlp costuma normalizar
            return meta_dict.get("uploader_id") or meta_dict.get("uploader"), meta_dict.get("channel_id")
    except Exception: pass
    return None, None


def _identify_video_source(url_str: str, history_dict: dict, cmd_list: list[str], cookie_args_list: list[str]) -> tuple[str | None, str, str | None, str | None]:
    """Extrai metadados quando a origem é um vídeo individual."""
    # YouTube match
    yt_match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url_str)
    # Vimeo match
    vimeo_match = re.search(r"vimeo\.com/(\d+)", url_str)
    
    if yt_match:
        vid_id_str = yt_match.group(1)
    elif vimeo_match:
        vid_id_str = vimeo_match.group(1)
    else:
        vid_id_str = "video"
    
    if vid_id_str in history_dict:
        ent_dict = history_dict[vid_id_str]
        up_id_str = ent_dict.get("uploader_id")
        if up_id_str:
            print_ok(f"Origem identificada (cache local): {BOLD}@{up_id_str.lstrip('@')}{RESET}")
            return up_id_str.lstrip("@"), vid_id_str, ent_dict.get("channel_id"), up_id_str

    print_info(f"Identificando canal de origem para o vídeo {BOLD}{vid_id_str}{RESET}...")
    up_id_str, chan_id_str = _extract_video_meta_cli(url_str, cmd_list, cookie_args_list)
    if up_id_str:
        print_ok(f"Origem identificada: {BOLD}@{up_id_str.lstrip('@')}{RESET}")
        return up_id_str.lstrip("@"), vid_id_str, chan_id_str, up_id_str
    
    return f"video_{vid_id_str}", vid_id_str, None, None


def _extract_playlist_meta_cli(url_str: str, cmd_list: list[str], cookie_args_list: list[str]) -> tuple[str | None, str | None, str | None]:
    """Executa comando yt-dlp para extrair metadados de playlist."""
    meta_cmd_list = cmd_list + cookie_args_list + ["--dump-json", "--flat-playlist", "--playlist-end", "1", "--ignore-errors", url_str]
    try:
        proc_res = subprocess.run(meta_cmd_list, capture_output=True, text=True, encoding="utf-8", timeout=15)
        if proc_res.stdout:
            meta_dict = json.loads(proc_res.stdout.splitlines()[0])
            return meta_dict.get("uploader_id") or meta_dict.get("uploader"), meta_dict.get("channel_id"), meta_dict.get("uploader")
    except Exception: pass
    return None, None, None


def _identify_playlist_source(url_str: str, history_dict: dict, cmd_list: list[str], cookie_args_list: list[str]) -> tuple[str | None, str, str | None, str | None]:
    """Extrai metadados quando a origem é uma playlist."""
    # YouTube
    yt_match = re.search(r"list=([A-Za-z0-9_-]+)", url_str)
    # Vimeo
    vimeo_match = re.search(r"showcase/(\d+)", url_str)
    
    if yt_match:
        list_id_str = yt_match.group(1)
    elif vimeo_match:
        list_id_str = vimeo_match.group(1)
    else:
        list_id_str = "playlist"
    
    for _, ent_dict in history_dict.items():
        if "playlists" in ent_dict and list_id_str in ent_dict["playlists"]:
            up_id_str: str = ent_dict.get("uploader_id", "")
            if up_id_str:
                print_ok(f"Origem identificada (cache local): {BOLD}@{up_id_str.lstrip('@')}{RESET}")
                return up_id_str.lstrip("@"), f"list={list_id_str}", ent_dict.get("channel_id"), up_id_str

    print_info(f"Identificando canal de origem para a lista {BOLD}{list_id_str}{RESET}...")
    up_id_str, chan_id_str, up_name_str = _extract_playlist_meta_cli(url_str, cmd_list, cookie_args_list)
    if up_id_str:
        print_ok(f"Origem identificada: {BOLD}@{up_id_str.lstrip('@')}{RESET}")
        return up_id_str.lstrip("@"), f"list={list_id_str}", chan_id_str, up_id_str
    
    return f"playlist_{list_id_str}", f"list={list_id_str}", None, None


def identify_source_type(url_str: str, cmd_list: list[str], cookie_args_list: list[str], history_dict: dict) -> tuple[str, str, str | None, str | None]:
    """Identifica o tipo de origem (vídeo, playlist ou canal) e retorna metadados básicos."""
    provider = get_provider(url_str)
    
    # Detecção de vídeo
    if "watch?v=" in url_str or "youtu.be/" in url_str or (provider == "vimeo" and re.search(r"vimeo\.com/\d+", url_str) and not any(x in url_str for x in ["/showcase/", "/channels/"])):
        return _identify_video_source(url_str, history_dict, cmd_list, cookie_args_list)
    
    # Detecção de playlist / showcase
    if "list=" in url_str or (provider == "vimeo" and "/showcase/" in url_str):
        return _identify_playlist_source(url_str, history_dict, cmd_list, cookie_args_list)
    
    # Detecção de canal
    if "@" in url_str:
        match = re.search(r"@([A-Za-z0-9_\-\.]+)", url_str)
        return (match.group(1) if match else "canal"), "", None, None
        
    if provider == "vimeo" and "/channels/" in url_str:
        match = re.search(r"channels/([A-Za-z0-9_\-\.]+)", url_str)
        return (match.group(1) if match else "canal"), "", None, None

    return "canal", "", None, None


def consolidar_dados_legados(cwd_path: Path, target_json_path: Path) -> None:
    """Migra automaticamente JSONs antigos para o novo formato de pasta consolidada."""
    legacy_list = list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json"))
    for lj_path in legacy_list:
        if lj_path.resolve() == target_json_path.resolve(): continue
        if not target_json_path.exists():
            print_info(f"Migrando base antiga: {BOLD}{lj_path.name}{RESET} -> {BOLD}{target_json_path.name}{RESET}")
            lj_path.rename(target_json_path)
        else:
            print_info(f"Consolidando base antiga (backup): {BOLD}{lj_path.name}{RESET} -> {BOLD}{target_json_path.name}{RESET}")
            lj_path.rename(lj_path.with_suffix(".bak"))


def _merge_yt_listing(state_dict: dict[str, dict], current_list: list[dict], playlist_str: str | None, tag_str: str | None) -> None:
    """Integra vídeos vindos da listagem atual do YouTube no estado local."""
    for entry_dict in current_list:
        vid_id_str = entry_dict["video_id"]
        if vid_id_str in state_dict:
            exist_dict = state_dict[vid_id_str]
            _update_existing_entry(exist_dict, entry_dict, playlist_str, tag_str)
        else:
            _add_new_entry(state_dict, vid_id_str, entry_dict, playlist_str, tag_str)


def _update_existing_entry(exist_dict: dict, entry_dict: dict, playlist_str: str | None, tag_str: str | None) -> None:
    """Atualiza campos de uma entrada existente com novos dados do YT."""
    if entry_dict.get("publish_date") != "N/A":
        exist_dict["publish_date"] = entry_dict.get("publish_date", exist_dict.get("publish_date"))
    if entry_dict.get("title") not in ("N/A", "", "Avulso"):
        exist_dict["title"] = entry_dict.get("title", exist_dict.get("title"))
    
    if playlist_str:
        exist_dict.setdefault("playlists", [])
        if playlist_str not in exist_dict["playlists"]:
            exist_dict["playlists"].append(playlist_str)
    
    if tag_str:
        old_tag = exist_dict.get("source_channel")
        # Se não tem tag, ou se a nova tag é uma versão mais completa da antiga (ex: @Goshen -> @Goshen.Official)
        if not old_tag or (tag_str.lower().startswith(old_tag.lower()) and tag_str.lower() != old_tag.lower()):
            exist_dict["source_channel"] = tag_str


def _add_new_entry(state_dict: dict, vid_id_str: str, entry_dict: dict, playlist_str: str | None, tag_str: str | None) -> None:
    """Adiciona uma nova entrada de vídeo ao estado local."""
    if playlist_str:
        entry_dict["playlists"] = [playlist_str]
    if tag_str:
        entry_dict["source_channel"] = tag_str
    state_dict[vid_id_str] = entry_dict


def _import_reverse_history(state_dict: dict[str, dict], history_dict: dict, chan_id_str: str | None, up_id_str: str | None, name_str: str | None, tag_str: str | None) -> int:
    """Importa vídeos do histórico global que pertencem ao canal atual mas sumiram do YT."""
    imp_count_int: int = 0
    for vid_id_str, hist_dict in history_dict.items():
        if vid_id_str in state_dict:
            continue
        
        is_same_bool: bool = (chan_id_str and hist_dict.get("channel_id") == chan_id_str) or \
                             (up_id_str and hist_dict.get("uploader_id") == up_id_str) or \
                             (name_str and name_str.lower() in str(hist_dict.get("uploader", "")).lower())
        
        if is_same_bool:
            new_entry_dict: dict = hist_dict.copy()
            if tag_str and not new_entry_dict.get("source_channel"):
                new_entry_dict["source_channel"] = tag_str
            state_dict[vid_id_str] = new_entry_dict
            imp_count_int += 1
    return imp_count_int


def sync_video_records(
    state_dict: dict[str, dict], current_list: list[dict], history_dict: dict, 
    playlist_str: str | None, tag_str: str | None, chan_id_str: str | None,
    up_id_str: str | None, name_str: str | None
) -> tuple[int, int]:
    """Mescla vídeos do YouTube com o histórico local."""
    old_size_int = len(state_dict)
    _merge_yt_listing(state_dict, current_list, playlist_str, tag_str)
    new_v_int = len(state_dict) - old_size_int
    imp_v_int = _import_reverse_history(state_dict, history_dict, chan_id_str, up_id_str, name_str, tag_str)
    return new_v_int, imp_v_int


def _read_persisted_lang(json_path: Path) -> str | None:
    """Tenta ler o idioma detectado salvo no JSON."""
    if not json_path.exists(): return None
    try:
        with open(json_path, "r", encoding="utf-8") as fd:
            data_dict = json.load(fd)
            return data_dict.get("detected_language") if isinstance(data_dict, dict) else None
    except Exception: return None


def _load_existing_state_map(json_path: Path) -> dict[str, dict]:
    """Carrega o mapa de vídeos do JSON existente."""
    state_dict = {}
    if not json_path.exists():
        return state_dict
    try:
        with open(json_path, "r", encoding="utf-8") as fd_obj:
            data_obj = json.load(fd_obj)
            v_list = data_obj["videos"] if isinstance(data_obj, dict) and "videos" in data_obj else data_obj
            for v_dict in (v_list if isinstance(v_list, list) else []):
                vid_id_str = v_dict.get("video_id") or v_dict.get("id")
                if vid_id_str:
                    state_dict[vid_id_str] = v_dict
    except Exception:
        pass
    return state_dict


def _load_initial_metadata(cwd_path: Path, url_str: str, cmd_list: list[str], cookies_list: list[str]) -> tuple:
    """Carrega metadados iniciais e identifica o tipo de origem."""
    hist_dict = load_all_local_history(cwd_path)
    res_tuple = identify_source_type(url_str, cmd_list, cookies_list, hist_dict)
    name_str, ident_str, chan_id_str, up_id_str = res_tuple
    
    json_path = cwd_path / f"escriba_{cwd_path.name}.json"
    consolidar_dados_legados(cwd_path, json_path)
    return json_path, hist_dict, name_str, ident_str, chan_id_str, up_id_str


def load_or_create_channel_state(
    cwd_path: Path, cmd_list: list[str], cookies_list: list[str], 
    url_str: str, only_peek_lang_bool: bool = False
) -> tuple[Path | None, list[dict], str | None, int]:
    """Carrega ou cria o banco de dados JSON do canal."""
    json_path, hist_dict, name_str, ident_str, chan_id_str, up_id_str = _load_initial_metadata(cwd_path, url_str, cmd_list, cookies_list)
    lang_cached_str = _read_persisted_lang(json_path)
    if only_peek_lang_bool: return json_path, [], lang_cached_str, 0

    state_dict = _load_existing_state_map(json_path)
    
    # SMART SYNC: Se não for um full scan, passamos os IDs conhecidos para parar cedo
    stop_ids = set(state_dict.keys()) if not getattr(sys, "_escriba_full_scan", False) else None
    
    provider_mod = _get_provider_module(url_str)
    yt_list = provider_mod.generate_fast_list_json(cmd_list, cookies_list, url_str, history_dict=hist_dict, stop_at_ids=stop_ids)
    if not yt_list and not state_dict: return None, [], lang_cached_str, 0

    tag_str = f"@{name_str}" if name_str and name_str != "canal" else url_str
    _perform_state_sync(state_dict, yt_list, ident_str, tag_str, chan_id_str, up_id_str, name_str, cwd_path, url_str)
    return json_path, list(state_dict.values()), lang_cached_str, len(state_dict)


def _perform_state_sync(state_dict: dict, yt_list: list, ident_str: str, tag_str: str, chan_id_str: str, up_id_str: str, name_str: str, cwd_path: Path, url_str: str):
    """Auxiliar para sincronizar e limpar o estado durante o carregamento."""
    history_dict = load_all_local_history(cwd_path)
    new_v_int, imp_v_int = sync_video_records(
        state_dict, yt_list, history_dict, (ident_str if "list=" in url_str else None), 
        tag_str, chan_id_str, up_id_str, name_str
    )
    ghosts_int = len([state_dict.pop(k) for k in list(state_dict.keys()) if k.startswith(f"{cwd_path.name}-")])
    if ghosts_int: print_ok(f"Limpeza Automática: Removidos {BOLD}{ghosts_int}{RESET} IDs fantasmas.")
    if new_v_int > 0: print_ok(f"Descobertos {BOLD}{new_v_int}{RESET} novos vídeos.")
    if imp_v_int > 0: print_ok(f"Importados {BOLD}{imp_v_int}{RESET} vídeos do histórico local.")


# ─── Marcadores de Discurso Oral (Complemento ao NLTK) ────────────────────────

ORAL_MARKERS_PT = {
    "então", "né", "aí", "tipo", "assim", "cara", "gente", "tá", "tô",
    "isso", "esse", "essa", "esses", "essas", "aqui", "ali", "lá",
    "muito", "mais", "mas", "também", "já", "ainda", "agora", "bem",
    "sim", "não", "nunca", "sempre", "talvez", "quando", "onde", "porque", "porquê",
    "pronto", "legal", "beleza", "entende", "sabe", "certo", "ok", "ah", "eh", "uh", "hum",
    "aí", "então"
}

ORAL_MARKERS_EN = {
    "like", "just", "so", "actually", "basically", "literally", "yeah", "yes", "no",
    "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just",
    "don", "now", "well", "right", "okay", "ok", "uh", "um", "ah", "know", "mean", "guess"
}

ORAL_MARKERS_ES = {
    "y", "o", "pero", "si", "no", "sí", "ya", "muy", "más", "también",
    "entonces", "pues", "bueno", "claro", "vale", "verdad", "así", "esto", "este", "esta",
    "ahora", "siempre", "nunca", "nada", "algo", "todo", "mucho", "poco", "bien", "mal",
    "eh", "ah", "uh", "mira", "venga", "oye"
}

# ─── Cache de dependências de ML ─────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _load_ml_deps():
    """
    Importa as dependências de Machine Learning (pysrt, sklearn, nltk) de forma preguiçosa (Lazy Loading).
    
    Explicação para Iniciantes:
    - Bibliotecas como scikit-learn e nltk demoram frações de segundo significativas para serem carregadas
      pelo interpretador do Python. Se importássemos esses módulos globalmente no topo de escriba.py,
      qualquer comando simples (ex: `escriba --version` ou `escriba --help`) sofreria um atraso chato para rodar.
    - Solução: Usamos o padrão 'Lazy Loading' (Importação Tardia). Só importamos essas ferramentas grandes
      no momento exato em que a conversão de SRT para MD é acionada.
    - O `@functools.lru_cache(maxsize=1)` faz com que, após a primeira importação (que lê do disco),
      os módulos permaneçam na memória RAM do processo. Nas chamadas seguintes, a função retorna a referência
      da memória de forma instantânea.
    """
    try:
        import pysrt
        import numpy as np
        import nltk
        from nltk.corpus import stopwords as nltk_stopwords
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        return pysrt, np, nltk, nltk_stopwords, TfidfVectorizer, cosine_similarity
    except ImportError:
        return None


def _get_lang_resources(lang_code_str: str) -> tuple[str, set]:
    """Mapeia o código de idioma para o nome NLTK e marcadores orais correspondentes."""
    lang_map = {
        "pt": ("portuguese", ORAL_MARKERS_PT),
        "en": ("english",    ORAL_MARKERS_EN),
        "es": ("spanish",    ORAL_MARKERS_ES)
    }
    prefix_str = lang_code_str[:2] if lang_code_str else "pt"
    return lang_map.get(prefix_str if prefix_str in lang_map else "pt")


@functools.lru_cache(maxsize=8)
def get_merged_stopwords(lang_code_str: str) -> frozenset:
    """Retorna o frozenset de stopwords (NLTK + marcadores orais) para o idioma."""
    deps = _load_ml_deps()
    if deps is None: return frozenset()
    _, _, nltk, nltk_stopwords, _, _ = deps

    nltk_lang_name_str, oral_markers_set = _get_lang_resources(lang_code_str)

    try:
        base_stops = set(nltk_stopwords.words(nltk_lang_name_str))
    except LookupError:
        nltk.download('stopwords', quiet=True)
        base_stops = set(nltk_stopwords.words(nltk_lang_name_str))

    return frozenset(base_stops | oral_markers_set)



def _strip_rollup(text_str: str, prev_text_str: str, overlap_ratio_float: float = 0.5) -> str:
    """Remove do início de 'text' a porção que já foi vista em 'prev_text'."""
    prev_tokens_list, cur_tokens_list = prev_text_str.split(), text_str.split()
    if not prev_tokens_list or not cur_tokens_list: return text_str
    overlap_int: int = 0
    for i_int, token_str in enumerate(cur_tokens_list):
        if i_int < len(prev_tokens_list) and token_str == prev_tokens_list[i_int]: overlap_int += 1
        else: break
    return " ".join(cur_tokens_list[overlap_int:])

def _calc_total_seconds(pysrt_time) -> int:
    """Converte tempo pysrt para segundos totais."""
    return pysrt_time.hours * 3600 + pysrt_time.minutes * 60 + pysrt_time.seconds


def _smart_ts(pysrt_time_obj) -> str:
    """HH:MM:SS só quando necessário (≥1h), senão MM:SS."""
    total_s_int = _calc_total_seconds(pysrt_time_obj)
    h_int, rem_int = divmod(total_s_int, 3600)
    m_int, s_int = divmod(rem_int, 60)
    return f"{h_int:02d}:{m_int:02d}:{s_int:02d}" if h_int else f"{m_int:02d}:{s_int:02d}"

def _seg_keywords(seg_wins_list: list, tfidf_vec_obj, tfidf_mat_obj, win_indices_list: list[int], oral_stopwords_set: frozenset, top_n_int: int = 3) -> str:
    """Extrai as top-N palavras-chave do segmento via TF-IDF."""
    import numpy as np
    feature_names_list = tfidf_vec_obj.get_feature_names_out()
    seg_vector_obj = np.asarray(tfidf_mat_obj[win_indices_list, :].sum(axis=0)).flatten()
    top_indices_list = seg_vector_obj.argsort()[::-1]
    keywords_list: list[str] = []
    for i_int in top_indices_list:
        word_str: str = feature_names_list[i_int]
        if len(word_str) > 2 and word_str.lower() not in oral_stopwords_set and word_str.isalpha():
            keywords_list.append(word_str.lower())
        if len(keywords_list) >= top_n_int: break
    return " · ".join(keywords_list) if keywords_list else ""

def create_adaptive_windows(subs_list, window_size_s_int: int) -> tuple[list[dict], dict]:
    """Agrupa legendas em janelas adaptativas. Retorna (windows, clean_texts)."""
    windows_list: list[dict] = []
    current_window_subs_list: list = []
    clean_texts: dict = {}
    start_time_obj = subs_list[0].start
    prev_sub_text_str: str = ""
    for sub_obj in subs_list:
        raw_text_str: str = re.sub(r"<[^>]+>", "", sub_obj.text.replace('\n', ' ')).strip()
        clean_text_str: str = _strip_rollup(raw_text_str, prev_sub_text_str)
        if clean_text_str:
            prev_sub_text_str = raw_text_str
            clean_texts[id(sub_obj)] = clean_text_str
            current_window_subs_list.append(sub_obj)
        if (sub_obj.end - start_time_obj).seconds > window_size_s_int and current_window_subs_list:
            w_text_str: str = " ".join(clean_texts.get(id(s), "") for s in current_window_subs_list)
            if w_text_str:
                windows_list.append({'text': w_text_str, 'timestamp': str(current_window_subs_list[0].start).split(',')[0], 'subs': current_window_subs_list})
            current_window_subs_list, start_time_obj = [], sub_obj.start
    if current_window_subs_list:
        w_text_str: str = " ".join(clean_texts.get(id(s), "") for s in current_window_subs_list)
        if w_text_str:
            windows_list.append({'text': w_text_str, 'timestamp': str(current_window_subs_list[0].start).split(',')[0], 'subs': current_window_subs_list})
    return windows_list, clean_texts

def get_adaptive_config(total_duration_s: int) -> tuple[int, float, int]:
    """Calcula parâmetros adaptativos baseados na duração do vídeo."""
    if total_duration_s < 1800:
        win_size = 30
        adapt_thresh = 0.25
        min_segs = 3
    elif total_duration_s < 3600:
        win_size = 60
        adapt_thresh = 0.35
        min_segs = 5
    else:
        win_size = 90
        adapt_thresh = 0.50
        min_segs = 10
    return win_size, adapt_thresh, min_segs

def detect_topic_breaks(tfidf_matrix, adapt_thresh: float, cosine_similarity_func) -> set[int]:
    """Identifica quebras de tópico baseadas na similaridade de cosseno entre janelas."""
    breaks = {0}
    num_windows = tfidf_matrix.shape[0]
    for i in range(1, num_windows):
        sim = cosine_similarity_func(tfidf_matrix[i], tfidf_matrix[i-1])[0][0]
        if sim < adapt_thresh:
            breaks.add(i)
    return breaks

def assemble_segments(windows_list: list[dict], topic_breaks_set: set[int]) -> list[tuple]:
    """Agrupa janelas em segmentos de tópicos."""
    segments_list: list[tuple] = []
    current_seg_wins_list: list[dict] = []
    for i_int, window_dict in enumerate(windows_list):
        if i_int in topic_breaks_set and current_seg_wins_list:
            segments_list.append((current_seg_wins_list[0]['timestamp'], len(segments_list) + 1, current_seg_wins_list))
            current_seg_wins_list = []
        current_seg_wins_list.append(window_dict)
    if current_seg_wins_list:
        segments_list.append((current_seg_wins_list[0]['timestamp'], len(segments_list) + 1, current_seg_wins_list))
    return segments_list

def get_provider(url: str) -> str:
    """Retorna 'vimeo' ou 'youtube' baseado na URL."""
    if not url: return "youtube"
    if "vimeo.com" in url or re.match(r"^\d+$", url):
        return "vimeo"
    return "youtube"

def yaml_safe(template) -> str:
    """
    Função de Tag (PEP 750) para renderizar cabeçalhos YAML com segurança.
    Escapa aspas duplas internas de valores que estão entre aspas duplas no template.
    """
    res = []
    for i, interp in enumerate(template.interpolations):
        prefix = template.strings[i]
        res.append(prefix)
        val = str(interp.value)
        if prefix.endswith('"') and template.strings[i+1].startswith('"'):
            val = val.replace('"', '\\"')
        res.append(val)
    res.append(template.strings[-1])
    return "".join(res)

def generate_md_header(video_title: str, video_id: str, video_date: str, duration_str: str, lang_code: str, version: str) -> list[str]:
    """Gera o cabeçalho YAML e título do arquivo Markdown usando t-strings."""
    provider = get_provider(video_id)
    if provider == "vimeo":
        url = f"https://vimeo.com/{video_id}"
    else:
        url = f"https://youtube.com/watch?v={video_id}"
        
    header_content = yaml_safe(t"""---
title: "{video_title}"
video_id: "{video_id}"
url: "{url}"
date: "{video_date}"
duration: "{duration_str}"
language: "{lang_code}"
source: "Escriba v{version}"
---

# {video_title}

> **Data:** {video_date} · **Duração:** {duration_str} · **Idioma:** {lang_code}  
> 🔗 [{url}]({url})

""")
    return [line + "\n" for line in header_content.splitlines()]

# BOLT OPTIMIZATION:
# Replaced regex-based whitespace normalization (e.g. `re.sub(r'\s+', ' ', text)`) with native string primitives
# like `text.split()` and `" ".join()`. `str.split()` without arguments natively and optimally handles contiguous whitespace.
# This yields a ~5x-6x speedup in hot paths that parse multiline blocks of text.
def _dedup_lines(lines: list[str]) -> list[str]:
    """Remove roll-up duplicatas: pula linha se uma é prefixo de palavras da outra."""
    out = []
    for line in lines:
        if out:
            prev_words = out[-1].lower().split()
            cur_words  = line.lower().split()
            min_len = min(len(prev_words), len(cur_words))
            overlap = min_len > 0 and all(prev_words[i] == cur_words[i] for i in range(min_len))
            if overlap:
                if len(cur_words) > len(prev_words):
                    out[-1] = line
                continue
        out.append(line)
    return out

def _flush_paragraph(lines: list[str], para_ts: str, out: list[str]) -> None:
    """Normaliza e emite um parágrafo capturado, com âncora de tempo."""
    if not lines:
        return
    text = " ".join(" ".join(lines).split())
    if text:
        text = re.sub(r'(^|[.!?]\s+)(\w)', lambda m: m.group(0)[:-1] + m.group(0)[-1].upper(), text)
        out.append(f"[{para_ts}] {clean_ekklezia_terms(text)}\n\n")

def _init_md_processing(srt_path: Path, indentation_prefix: str) -> tuple | None:
    """Carrega dependências e abre o arquivo SRT com validação."""
    if not srt_path.exists():
        print_warn(f"Arquivo SRT não encontrado: {srt_path.name}", indentation_prefix)
        return None
    if srt_path.stat().st_size == 0:
        print_warn(f"Arquivo SRT vazio: {srt_path.name}", indentation_prefix)
        return None
    deps = _load_ml_deps()
    if not deps:
        print_err("Faltam dependências de ML para MD.", indentation_prefix)
        return None
    pysrt, np, _, _, TfidfVectorizer, cosine_similarity = deps
    try:
        subs = pysrt.open(str(srt_path), encoding='utf-8')
    except Exception as e:
        print_warn(f"Erro ao abrir SRT (encoding ou formato inválido): {e}", indentation_prefix)
        return None
    if not subs or len(subs) == 0:
        print_warn(f"Arquivo SRT sem legendas: {srt_path.name}", indentation_prefix)
        return None
    valid_subs = [s for s in subs if s.text and s.text.strip()]
    if len(valid_subs) == 0:
        print_warn(f"Arquivo SRT sem texto válido: {srt_path.name}", indentation_prefix)
        return None
    return deps, subs


def _setup_vectorizer(srt_path_name: str, windows: list[dict]):
    """Configura o vetorizador TF-IDF com base no idioma."""
    lang_match = re.search(r"[\.\-]([a-z]{2}(?:-[a-z]{2,3})?)\.srt$", srt_path_name, re.IGNORECASE)
    lang_code_str = lang_match.group(1).lower() if lang_match else "pt"
    oral_stopwords = get_merged_stopwords(lang_code_str)

    deps = _load_ml_deps()
    _, _, _, _, TfidfVectorizer, _ = deps
    vectorizer = TfidfVectorizer(stop_words=list(oral_stopwords), min_df=1)
    tfidf_matrix = vectorizer.fit_transform([w['text'] for w in windows])
    return vectorizer, tfidf_matrix, lang_code_str, oral_stopwords


def _process_sub_into_para(sub, para_start_time, para_lines_list, md_lines, sentence_end_re, clean_texts=None):
    """Processa uma única legenda dentro de um parágrafo."""
    sub_text_str = (clean_texts or {}).get(id(sub)) or re.sub(r"<[^>]+>", "", sub.text.replace('\n', ' ')).strip()
    sub_text_str = " ".join(sub_text_str.split())
    if not sub_text_str: return para_start_time, para_lines_list
    if para_start_time is None: para_start_time = sub.start
    para_lines_list.append(sub_text_str)
    elapsed_int = (sub.end - para_start_time).seconds
    if (elapsed_int >= 60 and sentence_end_re.search(sub_text_str)) or elapsed_int >= 120:
        _flush_paragraph(_dedup_lines(para_lines_list), _smart_ts(para_start_time), md_lines)
        return None, []
    return para_start_time, para_lines_list


def _generate_transcription_structured(segments: list, topic_labels: list[str], md_lines: list[str], clean_texts: dict | None = None):
    """Gera a transcrição estruturada por tópicos."""
    sentence_end_re = re.compile(r'[.!?]["\']?\s*$')
    for (ts_str, _, seg_wins_list), label_str in zip(segments, topic_labels):
        md_lines.append(f"#### [{ts_str}] - Tópico: {label_str}\n")
        para_lines_list, para_start_time = [], None
        for window_dict in seg_wins_list:
            for sub_obj in window_dict['subs']:
                para_start_time, para_lines_list = _process_sub_into_para(
                    sub_obj, para_start_time, para_lines_list, md_lines, sentence_end_re, clean_texts
                )
        if para_lines_list:
            _flush_paragraph(_dedup_lines(para_lines_list), _smart_ts(para_start_time), md_lines)


def _generate_md_body_sections(md_lines, segs_list, vec, tfidf_mat, stops, clean_texts=None):
    """Gera as seções de segmentos e transcrição do MD."""
    md_lines.append("### Segmentos de Tópicos (Timestamps)\n")
    topic_labels_list, win_idx_int = [], 0
    for _, idx_int, s_wins in segs_list:
        indices_list = list(range(win_idx_int, win_idx_int + len(s_wins)))
        win_idx_int += len(s_wins)
        kw_str = _seg_keywords(s_wins, vec, tfidf_mat, indices_list, stops)
        label_str = "Introdução" if idx_int == 1 else (kw_str if kw_str else f"Tópico {idx_int}")
        topic_labels_list.append(label_str)
        md_lines.append(f"* `[{_smart_ts(s_wins[0]['subs'][0].start)}]` **{label_str}**\n")
    md_lines.append("\n### Transcrição Estruturada\n")
    _generate_transcription_structured(segs_list, topic_labels_list, md_lines, clean_texts)


def _generate_full_md_content(
    video_title_str: str, video_id_str: str, video_date_str: str, last_sub_end,
    lang_str: str, segs_list: list, vec, tfidf_mat, stops, clean_texts=None
) -> list[str]:
    """Combina cabeçalho e corpo para gerar o conteúdo total do MD."""
    duration_str = _smart_ts(last_sub_end)
    md_lines_list = generate_md_header(
        video_title_str, video_id_str, video_date_str, duration_str, lang_str, VERSION
    )
    _generate_md_body_sections(md_lines_list, segs_list, vec, tfidf_mat, stops, clean_texts)
    return md_lines_list


def _run_md_segmentation(subs_list, srt_path_name: str, cosine_sim_func):
    """Executa a segmentação por tópicos das janelas de legenda."""
    win_size_int, adapt_thresh_float, _ = get_adaptive_config(_calc_total_seconds(subs_list[-1].end))
    result = create_adaptive_windows(subs_list, win_size_int)
    if not result: return None, None, None, None, None, None
    windows_list, clean_texts = result
    if not windows_list: return None, None, None, None, None, None
    vec, tfidf_mat, lang_str, stops = _setup_vectorizer(srt_path_name, windows_list)
    breaks = detect_topic_breaks(tfidf_mat, adapt_thresh_float, cosine_sim_func)
    segs_list = assemble_segments(windows_list, breaks)
    return segs_list, vec, tfidf_mat, lang_str, stops, clean_texts


def srt_to_md(
    srt_path: Path, video_id_str: str, video_title_str: str,
    video_date_str: str = "Desconhecida", threshold_float: float = 0.3, indentation_prefix_str: str = "  "
) -> Path | None:
    """
    Converte legendas .srt em arquivos .md estruturados com segmentação semântica por tópicos (NLP/TF-IDF).
    
    Explicação para Iniciantes (O Processo de Segmentação de Tópicos):
    Q: Como o programa sabe onde um assunto termina e outro começa sem de fato compreender o português?
    A: Usamos algoritmos de Processamento de Linguagem Natural (NLP):
       1. Janelas Adaptativas: Agrupamos os blocos de legenda em janelas de tempo baseadas na duração total do vídeo.
       2. Vetorização TF-IDF (Term Frequency-Inverse Document Frequency): Convertemos cada janela em um vetor numérico
          que representa a importância das palavras. Termos muito comuns no idioma (stopwords como "que", "de")
          ou marcadores de fala ("né", "tipo") são ignorados. Termos raros e repetidos ganham peso alto.
       3. Similaridade de Cosseno: Calculamos o ângulo geométrico entre o vetor da janela atual e o da janela anterior.
          Se a similaridade de cosseno ficar abaixo de um limite (`threshold`), significa que o vocabulário mudou
          de forma abrupta (indicando transição de assunto e gerando uma quebra de capítulo).
       4. Indexação de Palavras-Chave: Usamos os termos de maior peso TF-IDF de cada capítulo para nomear
          os tópicos de forma automática (ex: "Introdução", "código · python · compilador").
    """
    init_res = _init_md_processing(srt_path, indentation_prefix_str)
    if not init_res: return None
    (pysrt, np, _, _, _, cosine_sim_func), subs_list = init_res

    segs, vec, tfidf, lang, stops, clean_texts = _run_md_segmentation(subs_list, srt_path.name, cosine_sim_func)
    if not segs: return None

    md_lines = _generate_full_md_content(
        video_title_str, video_id_str, video_date_str, subs_list[-1].end, 
        lang, segs, vec, tfidf, stops, clean_texts
    )
    md_file_path = srt_path.with_suffix(".md")
    try:
        md_file_path.write_text("".join(md_lines), encoding="utf-8-sig")
    except OSError as e:
        print_warn(f"Erro ao escrever MD: {e}", indentation_prefix_str)
        return None
    return md_file_path



def _cleanup_by_patterns(cwd_path: Path, patterns: list[str]) -> int:
    """Remove arquivos baseados em padrões de glob."""
    cleaned_int = 0
    for pattern_str in patterns:
        for temp_file_path in cwd_path.glob(pattern_str):
            try:
                temp_file_path.unlink()
                cleaned_int += 1
            except Exception: pass
    return cleaned_int


def cleanup_temp_files(cwd_path: Path, channel_dir_name: str) -> int:
    """Remove arquivos temporários deixados pelo yt-dlp."""
    cleaned_int = _cleanup_by_patterns(cwd_path, ["*.part", "*.ytdl", "*.temp", "*.tmp"])
    
    for info_file_path in cwd_path.glob(f"{channel_dir_name}-*.info.json"):
        try:
            info_file_path.unlink()
            cleaned_int += 1
        except Exception: pass
    
    if cleaned_int > 0:
        print_info(f"{DIM}Cleanup: {cleaned_int} arquivo(s) temporário(s) removido(s){RESET}")
    return cleaned_int


def _find_and_select_subtitle(cwd_path: Path, channel_dir_name: str, video_id: str, indent: str) -> Path | None:
    """Busca arquivos de legenda e resolve duplicatas."""
    pattern_str = str(cwd_path / f"{channel_dir_name}-{video_id}*.srt")
    matches_list = glob.glob(pattern_str)
    
    if not matches_list:
        # Fallback para o caso de o nome do canal conter pontos e ter sido truncado pelo yt-dlp
        prefix_base = channel_dir_name.split('.')[0]
        fallback_pattern = str(cwd_path / f"{prefix_base}*.srt")
        fallback_matches = glob.glob(fallback_pattern)
        # BOLT OPTIMIZATION: Usando os.path.basename em vez de Path().name para evitar overhead de instanciamento de objetos no loop.
        valid_fallbacks = [f for f in fallback_matches if "-" not in os.path.basename(f)]
        
        if valid_fallbacks:
            for f_str in valid_fallbacks:
                old_path = Path(f_str)
                # Extrai a extensão e sufixo de idioma, ex: "pt-orig.srt" de "andrea.pt-orig.srt"
                suffix = old_path.name[len(prefix_base):].lstrip('.')
                if not suffix:
                    suffix = "srt"
                
                if suffix.endswith(".srt"):
                    lang_part = suffix[:-4]
                    new_name = f"{channel_dir_name}-{video_id}-{lang_part}.srt" if lang_part else f"{channel_dir_name}-{video_id}.srt"
                else:
                    new_name = f"{channel_dir_name}-{video_id}.srt"
                
                new_path = old_path.parent / new_name
                try:
                    old_path.rename(new_path)
                    print_info(f"Legenda órfã recuperada e renomeada: {DIM}{old_path.name} → {new_name}{RESET}", indent)
                    matches_list.append(str(new_path))
                except Exception as e:
                    print_warn(f"Erro ao renomear legenda órfã {old_path.name}: {e}", indent)

    if not matches_list: return None

    if len(matches_list) > 1:
        print_warn(f"{len(matches_list)} variações de legenda detectadas — mantendo apenas uma.", indent)
        shortest_str = min(matches_list, key=len)
        for f_str in matches_list:
            if f_str != shortest_str: os.unlink(f_str)
        return Path(shortest_str)
    return Path(matches_list[0])


def convert_vtt_to_srt(vtt_path: Path) -> Path:
    """Converte um arquivo WebVTT (.vtt) para SubRip (.srt) de forma robusta e nativa."""
    srt_path = vtt_path.with_suffix(".srt")
    content = vtt_path.read_text(encoding="utf-8")
    
    # Normaliza quebras de linha
    content = content.replace("\r\n", "\n")
    
    # Remove o cabeçalho WEBVTT
    if content.startswith("WEBVTT"):
        content = re.sub(r"^WEBVTT.*?\n\n", "", content, flags=re.DOTALL)
    
    blocks = content.split("\n\n")
    srt_blocks = []
    block_index = 1
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
            
        lines = block.split("\n")
        
        # Localiza a linha do timestamp
        time_line_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                time_line_idx = i
                break
                
        if time_line_idx == -1:
            continue  # Não é um bloco de legenda válido
            
        time_line = lines[time_line_idx]
        text_lines = lines[time_line_idx + 1:]
        
        # Corrige o timestamp: troca pontos por vírgulas nos milissegundos e remove propriedades extras do VTT
        match = re.search(r"(\d{2}:\d{2}:\d{2})[.,](\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2})[.,](\d{3})", time_line)
        if not match:
            # Tenta sem horas (MM:SS.mmm)
            match = re.search(r"(\d{2}:\d{2})[.,](\d{3})\s*-->\s*(\d{2}:\d{2})[.,](\d{3})", time_line)
            if match:
                t1, m1, t2, m2 = match.groups()
                srt_time_line = f"00:{t1},{m1} --> 00:{t2},{m2}"
            else:
                continue
        else:
            t1, m1, t2, m2 = match.groups()
            srt_time_line = f"{t1},{m1} --> {t2},{m2}"
            
        srt_block = f"{block_index}\n{srt_time_line}\n" + "\n".join(text_lines)
        srt_blocks.append(srt_block)
        block_index += 1
        
    srt_path.write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8")
    return srt_path


def _auto_convert_vtt_to_srt(cwd_path: Path, channel_dir_name: str, video_id_str: str, indent_str: str) -> None:
    """Procura por arquivo .vtt correspondente e converte para .srt se encontrado."""
    pattern_str = str(cwd_path / f"{channel_dir_name}-{video_id_str}*.vtt")
    matches_list = glob.glob(pattern_str)
    
    if not matches_list:
        # Fallback para o caso de o nome do canal conter pontos e ter sido truncado pelo yt-dlp
        prefix_base = channel_dir_name.split('.')[0]
        fallback_pattern = str(cwd_path / f"{prefix_base}*.vtt")
        fallback_matches = glob.glob(fallback_pattern)
        # BOLT OPTIMIZATION: Usando os.path.basename em vez de Path().name para evitar overhead de instanciamento de objetos no loop.
        matches_list = [f for f in fallback_matches if "-" not in os.path.basename(f)]
        
    for vtt_path_str in matches_list:
        vtt_path = Path(vtt_path_str)
        try:
            srt_path = convert_vtt_to_srt(vtt_path)
            print_info(f"Convertido WebVTT para SRT: {DIM}{srt_path.name}{RESET}", indent_str)
            vtt_path.unlink()
        except Exception as e:
            print_warn(f"Falha ao converter {vtt_path.name} para SRT: {e}", indent_str)


def cleanup_subtitles(
    cwd_path: Path, channel_dir_name: str, video_id_str: str, video_title_str: str = "Vídeo Sem Título",
    convert_srt_to_md_bool: bool = False, keep_srt_bool: bool = False, indent_str: str = "  ",
) -> tuple[bool, Path | None]:
    """Limpa e organiza arquivos de legenda baixados."""
    _auto_convert_vtt_to_srt(cwd_path, channel_dir_name, video_id_str, indent_str)
    
    target_path = _find_and_select_subtitle(cwd_path, channel_dir_name, video_id_str, indent_str)
    if not target_path: return False, None

    target_path = _rename_to_standard_format(target_path, channel_dir_name, video_id_str)

    status_str = "SRT mantido temp" if convert_srt_to_md_bool else "Legenda salva"
    print_info(f"{status_str}: {DIM}{target_path.name}{RESET}", indent_str)
    return True, target_path


def _rename_to_standard_format(target_path: Path, channel_dir_name: str, video_id_str: str) -> Path:
    """Renomeia o arquivo de legenda para o formato padrão se necessário."""
    prefix_str = f"{channel_dir_name}-{video_id_str}"
    lang_suffix_str = target_path.name[len(prefix_str):]

    if _is_legacy_srt_format(target_path, lang_suffix_str):
        new_path = target_path.parent / f"{prefix_str}-{lang_suffix_str.lstrip('.')}"
        target_path.rename(new_path)
        return new_path
    return target_path


def _is_legacy_srt_format(target_path: Path, lang_suffix_str: str) -> bool:
    """Verifica se o arquivo segue o formato de nome legado."""
    return lang_suffix_str.startswith(".") and target_path.suffix == ".srt" and lang_suffix_str.count(".") >= 2


# ─── Download Individual ──────────────────────────────────────────────────────




def _extract_meta_to_dict(meta_dict: dict, video_dict: dict):
    """Mapeia campos do info.json para o dicionário do vídeo."""
    if not video_dict.get("title") or video_dict["title"] in ("N/A", "", "Avulso"):
        video_dict["title"] = meta_dict.get("title") or video_dict.get("title", "N/A")
    if not video_dict.get("publish_date") or video_dict["publish_date"] in ("N/A", "", "Desconhecida"):
        raw_date_any = meta_dict.get("upload_date") or meta_dict.get("publish_date") or meta_dict.get("date")
        video_dict["publish_date"] = format_date(raw_date_any)
    if not video_dict.get("duration_s"):
        video_dict["duration_s"] = meta_dict.get("duration")
    if not video_dict.get("channel"):
        video_dict["channel"] = meta_dict.get("channel") or meta_dict.get("uploader")
    if not video_dict.get("view_count"):
        video_dict["view_count"] = meta_dict.get("view_count")


def harvest_and_delete_info_json(cwd_path: Path, channel_dir_name: str, video_id: str, video_dict: dict) -> bool:
    """Colhe metadados do arquivo .info.json e o remove."""
    info_path = cwd_path / f"{channel_dir_name}-{video_id}.info.json"
    if not info_path.exists():
        # Fallback para o caso de o nome do canal conter pontos e ter sido truncado pelo yt-dlp
        prefix_base = channel_dir_name.split('.')[0]
        fallback_path = cwd_path / f"{prefix_base}.info.json"
        if fallback_path.exists():
            info_path = fallback_path
        else:
            return False
    
    harvested_flag = False
    try:
        with open(info_path, encoding="utf-8") as f:
            _extract_meta_to_dict(json.load(f), video_dict)
        harvested_flag = True
    except Exception as e:
        print_warn(f"Erro ao processar info.json de {video_id}: {e}")
    finally:
        try:
            if info_path.exists(): info_path.unlink()
        except Exception as e:
            print_warn(f"Erro ao remover arquivo temporário {info_path.name}: {e}")
    return harvested_flag


# ─── Argparse ─────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Configura e processa argumentos da linha de comando."""
    parser_obj = argparse.ArgumentParser(
        prog="escriba.py",
        description=_get_cli_description(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_core_args(parser_obj)
    _add_behavior_args(parser_obj)
    _add_utility_args(parser_obj)
    return parser_obj.parse_args()


def _get_cli_description() -> str:
    """Retorna a string de descrição longa da CLI."""
    return (
        "Baixa legendas de todos os vídeos de um canal ou playlist do YouTube/Vimeo.\n"
        f"Versão: {VERSION}\n\n"
        "Substituições: Aplica regras de limpeza de termos (Ekklezia) usando arquivos\n"
        "'rules.txt' na pasta raiz do script e/ou na pasta atual (CWD).\n"
        "Formato: 'Termo Original, Termo Novo' ou 'Original=Novo'.\n\n"
        "Padrão: [NOME_DA_PASTA]-[ID_VIDEO]-[LANG].srt\n"
        "Vídeos sem legenda são registrados no JSON de estado e ignorados automaticamente."
    )


def _add_core_args(parser_obj: argparse.ArgumentParser) -> None:
    """Adiciona argumentos principais (alvo, idioma, formato)."""
    parser_obj.add_argument("canal", nargs="*", default=None, help="Canal, playlist, vídeo ou URL (YouTube ou Vimeo)")
    parser_obj.add_argument("-l", "--lang", default="", metavar="LANG", help="Idioma das legendas (ex: pt, en). Padrão: idioma nativo do canal")
    parser_obj.add_argument("-m", "--md", action="store_true", default=True, help="Exporta legendas em .md segmentado por IA via TF-IDF (Padrão: Ativo)")
    parser_obj.add_argument("--no-md", action="store_false", dest="md", help="Desativa a exportação em .md")
    parser_obj.add_argument("--keep-srt", action="store_true", help="Mantém o arquivo .srt no disco após a conversão para .md")


def _add_behavior_args(parser_obj: argparse.ArgumentParser) -> None:
    """Adiciona argumentos de comportamento do processamento."""
    parser_obj.add_argument("-d", "--date", default="", metavar="DATA", help="Data limite (posterior a). Formato: YYYYMMDD (ex: 20260101)")
    parser_obj.add_argument("-f", "--fast", action="store_true", help="Modo rápido: pula o tempo de espera entre downloads")
    parser_obj.add_argument("-rc", "--refresh-cookies", action="store_true", help="Força a extração de novos cookies do navegador (apaga cookies.txt existente)")
    parser_obj.add_argument("-b", "--browser", default="firefox", choices=["chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari"], help="Navegador do qual extrair os cookies. Padrão: firefox")
    parser_obj.add_argument("--full-scan", action="store_true", help="Desativa o Smart Sync e força a listagem completa de todos os vídeos do canal")
    parser_obj.add_argument("--ignore-metadata", action="store_true", help="Pula a auto-recuperação de datas e títulos ausentes no histórico JSON")
    parser_obj.add_argument("--retry-nosub", action="store_true", help="Tenta baixar novamente as legendas de vídeos marcados como 'sem legenda'")
    parser_obj.add_argument("-dv", "--download-video", action="store_true", help="Baixa o vídeo no formato Full HD (1080p, sem áudio)")
    parser_obj.add_argument("--limit", type=int, default=None, metavar="LIMIT", help="Limita o número de novos vídeos a baixar nesta sessão")



def _add_utility_args(parser_obj: argparse.ArgumentParser) -> None:
    """Adiciona argumentos de utilidade e manutenção."""
    parser_obj.add_argument("--regen-md", action="store_true", help="Modo offline: regenera .md a partir de todos os .srt na pasta atual")
    parser_obj.add_argument("--force", action="store_true", help="Combinado com --regen-md: sobrescreve .md existentes")
    parser_obj.add_argument("--upgrade-md", action="store_true", help="Converte cabeçalho dos .md existentes para o novo formato (YAML)")
    parser_obj.add_argument("--consolidar", "-j", "--juntar", action="store_true", help="Gera ou atualiza os volumes unificados do NotebookLM (busca na pasta atual, 'archive' e 'archives'). Alias: -j / --juntar")
    parser_obj.add_argument("--lexis-reset", action="store_true", help="Apaga os volumes do NotebookLM do canal e reprocessa")
    parser_obj.add_argument("--migrate", action="store_true", help="Adapta bancos de dados JSON antigos para a nova versão")
    parser_obj.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, metavar="FLOAT",
                           help=f"Sensibilidade de deteccao de topicos (0.0-1.0). Padrao: {DEFAULT_THRESHOLD}")
    parser_obj.add_argument("--status", action="store_true", help="Exibe o status consolidado de todos os canais locais em formato JSON")
    parser_obj.add_argument("-v", "--version", action="version", version=f"Versão: {VERSION}")


# ─── Main ─────────────────────────────────────────────────────────────────────

# Regex para detectar YouTube video ID (exatamente 11 chars alfanuméricos + _ e -)
VIDEO_ID_REGEX_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIMEO_ID_REGEX_PATTERN = re.compile(r"^\d{7,12}$")


def _try_parse_video_input(input_str: str) -> tuple[str, str, str] | None:
    """Tenta parsear input como vídeo (URL ou ID)."""
    # YouTube
    yt_regex = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/|v/)([A-Za-z0-9_-]{11})")
    match = yt_regex.search(input_str)
    if match:
        vid_id = match.group(1)
        url = input_str if input_str.startswith("http") else f"https://www.youtube.com/watch?v={vid_id}"
        return url, "video", vid_id
    
    if VIDEO_ID_REGEX_PATTERN.match(input_str):
        return f"https://www.youtube.com/watch?v={input_str}", "video", input_str

    # Vimeo
    vimeo_regex = re.compile(r"vimeo\.com/(\d+)")
    match = vimeo_regex.search(input_str)
    if match:
        vid_id = match.group(1)
        return input_str, "video", vid_id
    
    if VIMEO_ID_REGEX_PATTERN.match(input_str):
        return f"https://vimeo.com/{input_str}", "video", input_str

    return None


def parse_input_type(channel_input_str: str) -> tuple[str, str, str]:
    """Detecta o tipo de entrada (vídeo, playlist ou canal)."""
    vid_res = _try_parse_video_input(channel_input_str)
    if vid_res: return vid_res

    # Vimeo detection
    if "vimeo.com" in channel_input_str:
        if "/showcase/" in channel_input_str or "/channels/" in channel_input_str:
            return channel_input_str, "playlist", ""
        return channel_input_str, "channel", ""

    if "list=" in channel_input_str or "/playlist/" in channel_input_str:
        url = channel_input_str if channel_input_str.startswith("http") else f"https://www.youtube.com/{channel_input_str.lstrip('/')}"
        return url, "playlist", ""

    url = channel_input_str if channel_input_str.startswith("http") else f"https://www.youtube.com/{channel_input_str}"
    return url, "channel", ""





def _get_provider_module(url_str: str):
    """Retorna o módulo (youtube ou vimeo) baseado na URL."""
    return vimeo if get_provider(url_str) == "vimeo" else youtube


def _infer_canal_from_json(json_data_dict: dict, json_name_str: str) -> str | None:
    """Tenta inferir o nome do canal de campos variados do JSON ou do nome do arquivo."""
    canal_str = json_data_dict.get("youtube_channels", [None])[0] or \
                json_data_dict.get("vimeo_channels", [None])[0] or \
                json_data_dict.get("youtube_channel") or \
                json_data_dict.get("vimeo_channel") or \
                json_data_dict.get("channel") or \
                json_data_dict.get("channel_context")
    if canal_str: return canal_str
    
    match = re.search(r"(?:escriba_|lista_)(.+)\.json", json_name_str)
    return f"@{match.group(1)}" if match else None


def _auto_detect_channel(cwd_path: Path, cli_args: argparse.Namespace) -> Path | None:
    """Tenta descobrir o canal alvo a partir do arquivo de estado local."""
    latest_json_path = get_latest_json_path(cwd_path)
    if not latest_json_path.exists():
        print_err("Parâmetro 'canal' não fornecido e nenhum banco de dados encontrado.")
        sys.exit(1)
        
    try:
        with open(latest_json_path, "r", encoding="utf-8") as fd:
            json_data = json.load(fd)
            cli_args.canal = _infer_canal_from_json(json_data if isinstance(json_data, dict) else {}, latest_json_path.name)
    except Exception as e:
        print_err(f"Erro na auto-detecção: {e}")
        sys.exit(1)
    
    if not cli_args.canal:
        print_err("Não foi possível inferir o canal.")
        sys.exit(1)
    return latest_json_path


def _resolve_uploader_id(input_str: str, url_str: str) -> str | None:
    """Extrai o ID do uploader (handle) da URL ou input."""
    if input_str.startswith("@"): return input_str
    if "/@" in url_str:
        match = re.search(r"/(@[A-Za-z0-9_\-\.]+)", url_str)
        if match: return match.group(1)
    return None


def _print_session_info(cli_args: argparse.Namespace, latest_json_path: Path | None):
    """Imprime metadados da sessão inicial."""
    md_label_str = "+MD" if cli_args.md else ""
    mode_label_str = f"Legendas/SRT{md_label_str} ({cli_args.lang or 'auto'})"
    if cli_args.date: mode_label_str += f"  ·  a partir de {cli_args.date}"
    if cli_args.fast: mode_label_str += "  ·  rápido"
    
    print_info(f"Canal alvo: {BOLD}{cli_args.canal}{RESET}")
    print_info(f"Modo: {mode_label_str}")
    if latest_json_path: print_info(f"Auto-detecção via {latest_json_path.name}")


def _recover_orphaned_files(cwd_path: Path, channel_dir_name: str) -> None:
    """Localiza arquivos .info.json órfãos (sem ID no nome), lê seu ID interno e renomeia
    todos os arquivos relacionados (.info.json, .srt, .vtt) para o formato padrão.
    """
    prefix_base = channel_dir_name.split('.')[0]
    
    # Procura por prefix_base.info.json
    orphaned_info_path = cwd_path / f"{prefix_base}.info.json"
    if not orphaned_info_path.exists():
        return
        
    try:
        with open(orphaned_info_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            video_id = data.get("id")
            
        if not video_id:
            return
            
        # Renomeia o .info.json
        new_info_name = f"{channel_dir_name}-{video_id}.info.json"
        new_info_path = cwd_path / new_info_name
        orphaned_info_path.rename(new_info_path)
        print_info(f"Metadados órfãos recuperados: {DIM}{orphaned_info_path.name} → {new_info_name}{RESET}")
        
        # Agora busca e renomeia os arquivos de legenda correspondentes (.srt ou .vtt)
        # Qualquer arquivo que comece com prefix_base + "." e termine com .srt ou .vtt
        # e que não contenha hífen no nome.
        for f in cwd_path.iterdir():
            if f.is_file() and f.name.startswith(f"{prefix_base}.") and f.suffix in (".srt", ".vtt"):
                if extract_video_id(f.name) == "Sem ID":
                    # Ex: andrea.pt-orig.srt -> pt-orig
                    suffix = f.name[len(prefix_base):].lstrip('.')
                    if suffix.endswith(".srt"):
                        lang_part = suffix[:-4]
                        ext = "srt"
                    else:
                        lang_part = suffix[:-4]
                        ext = "vtt"
                        
                    if lang_part:
                        new_sub_name = f"{channel_dir_name}-{video_id}-{lang_part}.{ext}"
                    else:
                        new_sub_name = f"{channel_dir_name}-{video_id}.{ext}"
                        
                    new_sub_path = cwd_path / new_sub_name
                    f.rename(new_sub_path)
                    print_info(f"Legenda órfã recuperada: {DIM}{f.name} → {new_sub_name}{RESET}")
    except Exception as e:
        print_warn(f"Erro ao recuperar arquivos órfãos para {channel_dir_name}: {e}")


def setup_session(cli_args: argparse.Namespace) -> SessionConfig:
    """Etapa 1: configura tudo que precisamos antes de começar."""
    cwd_path = Path.cwd()
    _recover_orphaned_files(cwd_path, cwd_path.name)
    script_dir_path, yt_dlp_cmd_list = youtube.setup_environment()
    
    latest_json_path = _auto_detect_channel(cwd_path, cli_args) if not cli_args.canal else None
    url_str, input_type, _ = parse_input_type(cli_args.canal)

    if getattr(cli_args, "download_video", False) and input_type == "channel":
        print_err("Download de vídeo original (-dv/--download-video) não é permitido para CANAL completo.")
        print_err("Por favor, execute o download de vídeo apenas para um vídeo individual ou playlist.")
        sys.exit(1)

    _print_session_info(cli_args, latest_json_path)

    return SessionConfig(
        cwd_path=cwd_path, channel_dir_name=cwd_path.name,
        script_dir_path=script_dir_path, yt_dlp_cmd_list=yt_dlp_cmd_list,
        channel_input_url_or_handle=cli_args.canal, channel_url=url_str,
        discovered_uploader_id=_resolve_uploader_id(cli_args.canal, url_str),
        provider=get_provider(url_str),
        browser_name=getattr(cli_args, "browser", "firefox")
    )

def _warm_up_cookies(session_config: SessionConfig, cookie_args_list: list[str]) -> list[str]:
    """Realiza warm-up para extrair cookies do navegador e os filtra."""
    cookies_txt_path = session_config.cwd_path / "cookies.txt"
    if not cookies_txt_path.is_file():
        print_warn(f"Executando warm-up para extrair cookies do {session_config.browser_name.capitalize()} silenciosamente...")
        subprocess.run(
            session_config.yt_dlp_cmd_list + cookie_args_list + ["--dump-json", "--playlist-items", "0", session_config.channel_url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    
    if cookies_txt_path.is_file():
        if session_config.provider == "vimeo":
            filter_vimeo_cookies(cookies_txt_path)
            print_info("Cookies filtrados limitados ao Vimeo.")
        else:
            filter_youtube_cookies(cookies_txt_path)
            print_info("Cookies filtrados limitados ao YouTube (trackers removidos).")
        return configure_cookies(session_config.cwd_path, session_config.script_dir_path, False, silent_bool=True, browser_str=session_config.browser_name)
    
    print_err(f"Falha na extração de cookies do navegador '{session_config.browser_name}'.")
    if sys.platform.startswith("win"):
        print_warn("Dicas para Windows:")
        print_warn("1. Certifique-se de que o navegador selecionado está totalmente fechado antes de iniciar.")
        print_warn("2. Se estiver usando o Chrome 127+ (ou Edge equivalente), a proteção 'Appbound Encryption'")
        print_warn("   do Windows pode impedir a extração automática. Soluções:")
        print_warn("   * Recomendada: Instale a extensão 'Get cookies.txt LOCALLY' no Chrome, exporte")
        print_warn("     os cookies em formato Netscape e salve como 'cookies.txt' na pasta deste canal.")
        print_warn("   * Alternativa: Use outro navegador (ex: Firefox) com 'escriba -b firefox @canal'.")
    return cookie_args_list


def init_auth_and_language(
    session_config: SessionConfig, language_arg_str: str, force_refresh_flag: bool
) -> tuple[list[str], str]:
    """Etapa 2: configura autenticação e idioma."""
    print_section("Autenticação")
    cookies_list = configure_cookies(session_config.cwd_path, session_config.script_dir_path, force_refresh_flag, browser_str=session_config.browser_name)

    print_section("Idioma")
    lang_str = _detect_and_report_language(session_config, cookies_list, language_arg_str)

    if "--cookies-from-browser" in cookies_list:
        cookies_list = _warm_up_cookies(session_config, cookies_list)

    return cookies_list, lang_str


def _ensure_global_cookies(session_config: SessionConfig, cli_args_ns: argparse.Namespace) -> list[str]:
    """
    Garante a existência e validade do arquivo cookies.txt antes do loop principal.
    Retorna a lista de argumentos de cookies para serem reutilizados.
    """
    cookies_path = session_config.cwd_path / "cookies.txt"
    
    # Se o arquivo existe e não foi solicitado refresh, apenas carregamos silenciosamente
    if cookies_path.is_file() and not cli_args_ns.refresh_cookies:
        return configure_cookies(session_config.cwd_path, session_config.script_dir_path, False, silent_bool=True, browser_str=session_config.browser_name)

    # Caso contrário, realiza a autenticação completa (que pode disparar extração do navegador)
    print_section("Autenticação Global")
    cookies_list, _ = init_auth_and_language(session_config, cli_args_ns.lang, cli_args_ns.refresh_cookies)
    
    # Após o setup inicial, desativamos o refresh para os itens subsequentes
    cli_args_ns.refresh_cookies = False
    return cookies_list


def _detect_and_report_language(session_config: SessionConfig, cookies_list: list, user_lang_str: str) -> str:
    """Detecta o idioma e imprime feedback se definido pelo usuário."""
    _, _, cached_lang_str, _ = load_or_create_channel_state(
        session_config.cwd_path, session_config.yt_dlp_cmd_list, cookies_list, session_config.channel_url,
        only_peek_lang_bool=True
    )
    provider_mod = _get_provider_module(session_config.channel_url)
    lang_str = user_lang_str or provider_mod.detect_language(
        session_config.yt_dlp_cmd_list, cookies_list, session_config.channel_url, cached_lang_str
    )
    if user_lang_str: 
        print_ok(f"Idioma definido pelo usuário: {BOLD}{lang_str}{RESET}")
    return lang_str


def _sync_initial_state(
    session_config: SessionConfig, 
    cookie_args_list: list[str], 
    language_opt_string: str
) -> tuple[Path, list[dict], str | None, int]:
    """Sincroniza o estado inicial com o JSON e persiste descobertas recentes."""
    json_path, state_list, lang_cached, total = load_or_create_channel_state(
        session_config.cwd_path, session_config.yt_dlp_cmd_list, cookie_args_list, session_config.channel_url
    )
    
    if json_path:
        # Persistência de metadados de canal/idioma detectados agora
        save_channel_state_json(
            json_path, state_list, 
            detected_language_str=lang_cached if lang_cached else language_opt_string,
            channel_url_str=session_config.channel_url,
            channel_handle_str=session_config.discovered_uploader_id
        )
    return json_path, state_list, lang_cached, total


def _filter_by_single_video(state_list: list[dict], video_id_str: str) -> list[dict]:
    """Filtra o estado para um único vídeo, criando entrada se necessário."""
    working_list = [v for v in state_list if v["video_id"] == video_id_str]
    if not working_list:
        new_video_dict = {
            "video_id": video_id_str, "publish_date": "N/A", "title": "Avulso", 
            "subtitle_downloaded": False, "info_downloaded": False, "has_no_subtitle": False
        }
        state_list.append(new_video_dict)
        working_list = [new_video_dict]
    print_info(f"Foco em vídeo único: {BOLD}{video_id_str}{RESET}")
    return working_list


def _resolve_filter_handle(filter_str: str) -> str:
    """Normaliza o handle do canal para filtragem."""
    handle_str = filter_str
    if "/@" in handle_str:
        match_obj = re.search(r'/@([A-Za-z0-9_\-\.]+)', handle_str)
        if match_obj: handle_str = f"@{match_obj.group(1)}"
    elif not handle_str.startswith("@") and not handle_str.startswith("http"):
        handle_str = f"@{handle_str}"
    return handle_str


def _filter_by_handle(working_list: list[dict], channel_filter_str: str, is_first: bool) -> list[dict]:
    """Filtra vídeos por handle de canal e inclui órfãos se for o primeiro canal."""
    handle_str = _resolve_filter_handle(channel_filter_str).lower()
    
    # Normalização para comparação flexível (ex: @goshen.official -> @goshen)
    def normalize(h): return str(h).lower().replace(".official", "").replace("-official", "")
    target_norm = normalize(handle_str)

    filtered_list = [
        v for v in working_list 
        if normalize(v.get("source_channel", "")) == target_norm
    ]
    
    if is_first:
        orphans_list = [v for v in working_list if not v.get("source_channel")]
        if orphans_list:
            print_info(f"Incluindo {BOLD}{len(orphans_list)}{RESET} vídeo(s) órfãos.")
            filtered_list.extend(orphans_list)
    
    print_info(f"Canal filtrado: {BOLD}{handle_str}{RESET} (base: {target_norm}) → {len(filtered_list)} vídeo(s).")
    return filtered_list


def _filter_working_videos(
    full_state_list: list[dict], input_type_str: str, single_video_id_str: str | None,
    channel_filter_str: str | None, is_first_channel_bool: bool, cli_args: argparse.Namespace
) -> list[dict]:
    """Aplica filtros de data, canal e modo single-video."""
    if input_type_str == "video" and single_video_id_str:
        return _filter_by_single_video(full_state_list, single_video_id_str)

    working_list = filter_state_list(full_state_list, cli_args.date)
    if not channel_filter_str: return working_list

    return _filter_by_handle(working_list, channel_filter_str, is_first_channel_bool)


def _check_disk_files(
    video_id_str: str, session_config: SessionConfig, video_dict: dict,
    cli_args: argparse.Namespace, pending_md_list: list, prefix_str: str,
    idx_int: int = 0, total_int: int = 0
) -> bool:
    """Verifica se arquivos SRT/MD já existem no disco."""
    # OTIMIZAÇÃO: Usa busca em dicionário O(1) em vez de iterar sobre todos os arquivos (O(N^2) corrigido)
    if session_config.disk_files_cache is not None:
        files_for_this_video = session_config.disk_files_cache.get(video_id_str, [])
        srt_list = [str(session_config.cwd_path / f) for f in files_for_this_video if f.endswith(".srt")]
        md_list = [str(session_config.cwd_path / f) for f in files_for_this_video if f.endswith(".md")]
    else:
        # Fallback para o método clássico lento
        base_name = f"{session_config.channel_dir_name}-{video_id_str}"
        srt_list = glob.glob(str(session_config.cwd_path / f"{base_name}*.srt"))
        md_list = glob.glob(str(session_config.cwd_path / f"{base_name}*.md"))

    if not srt_list and not md_list:
        return False
    
    _handle_found_disk_files(video_id_str, video_dict, srt_list, md_list, cli_args, pending_md_list, prefix_str, idx_int, total_int)
    video_dict.update({"info_downloaded": True, "subtitle_downloaded": True})
    return True


def _report_skip_progress(current_idx: int, total_count: int) -> None:
    """Atualiza um contador dinâmico na mesma linha para itens pulados."""
    # OTIMIZAÇÃO: Atualiza o console apenas a cada 20 itens para evitar lag de I/O em loops rápidos
    if current_idx % 20 != 0 and current_idx != total_count:
        return
        
    msg = f"\r  {ICON_WAIT}  {DIM}Verificando histórico: {BOLD}{current_idx}{RESET}{DIM}/{total_count} vídeos...{RESET}"
    sys.stdout.write(msg.ljust(100))
    sys.stdout.flush()


def _handle_found_disk_files(vid_id, v_dict, srt_list, md_list, args, pending, prefix, idx_int=0, total_int=0):
    """Trata arquivos encontrados no disco, agendando MD se necessário."""
    if srt_list and not md_list and args.md:
        if idx_int > 0: print() # Quebra a linha do contador dinâmico antes de imprimir o agendamento
        pending.append((
            Path(srt_list[0]), vid_id, 
            v_dict.get("title", "Sem Título"), v_dict.get("publish_date", "N/A")
        ))
        print_skip(f"{vid_id}  {DIM}.srt encontrado → agendado MD{RESET}", prefix)
    else:
        _report_skip_progress(idx_int, total_int)


def _check_video_skip(
    video_dict: dict,
    session_config: SessionConfig,
    cli_args: argparse.Namespace,
    prefix_str: str,
    pending_md_list: list,
    idx_int: int = 0,
    total_int: int = 0
) -> bool:
    """Verifica se o vídeo deve ser pulado por registro no JSON ou arquivos em disco."""
    video_id_str = video_dict["video_id"]
    if video_dict.get("subtitle_downloaded"):
        _report_skip_progress(idx_int, total_int)
        return True
    if video_dict.get("has_no_subtitle") and not getattr(cli_args, "retry_nosub", False):
        _report_skip_progress(idx_int, total_int)
        return True

    return _check_disk_files(video_id_str, session_config, video_dict, cli_args, pending_md_list, prefix_str, idx_int, total_int)


def _prepare_working_state(
    conf_obj: SessionConfig, cookies_list: list[str], lang_str: str, cli_args_ns: argparse.Namespace,
    channel_filter_str: str | None, is_first_channel_bool: bool
) -> tuple[Path, list[dict], list[dict], int]:
    """Sincroniza o estado e filtra os vídeos a serem processados."""
    _, itype, vid_id = parse_input_type(conf_obj.channel_input_url_or_handle)
    json_path, full_list, _, chan_tot = _sync_initial_state(conf_obj, cookies_list, lang_str)
    
    working_list = _filter_working_videos(
        full_list, itype, vid_id, channel_filter_str, is_first_channel_bool, cli_args_ns
    )
    
    if not working_list:
        _handle_empty_working_list(channel_filter_str)
        
    return json_path, full_list, working_list, chan_tot


def _handle_empty_working_list(channel_filter_str: str | None) -> None:
    """Trata o caso de não haver vídeos para processar."""
    if channel_filter_str:
        return
    print_err("Nenhum vídeo retornado pela listagem ou filtro.")
    sys.exit(1)


def _print_partition_summary(
    working_list: list[dict], to_download: list[dict], is_first_channel_bool: bool
) -> None:
    """Imprime o resultado do particionamento em uma única linha antes do loop de download."""
    if is_first_channel_bool:
        print_section("Processamento")
    n_total    = len(working_list)
    n_download = len(to_download)
    n_skip     = n_total - n_download
    no_sub_int = sum(1 for v in working_list if v.get("has_no_subtitle"))
    print_info(f"Verificando histórico: {BOLD}{n_skip}{RESET}/{n_total} já processados · {no_sub_int} sem legenda")
    if n_download > 0:
        print_section(f"Download  {DIM}(0/{n_download}){RESET}")
    else:
        print_ok("Nenhum vídeo novo para baixar.")


def process_videos(
    conf_obj: SessionConfig, cookies_list: list[str], lang_str: str, 
    cli_args_ns: argparse.Namespace, channel_filter_str: str | None = None, is_first_channel_bool: bool = True
) -> tuple:
    """Orquestra o download e processamento de vídeos."""
    try:
        # ── Cache de disco via os.scandir() ──────────────────────────────────
        # os.scandir() usa DirEntry que já carrega o tipo do arquivo sem syscall
        # stat() adicional. Regex pré-compilado fora do loop evita recompilação.
        if conf_obj.disk_files_cache is None:
            from collections import defaultdict
            prefix    = f"{conf_obj.channel_dir_name}-"
            prefix_re = re.compile(fr"^{re.escape(prefix)}([A-Za-z0-9_-]{{11}}|\d+)")
            cache: defaultdict[str, list[str]] = defaultdict(list)
            with os.scandir(conf_obj.cwd_path) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False) and entry.name.startswith(prefix):
                        m = prefix_re.match(entry.name)
                        if m:
                            cache[m.group(1)].append(entry.name)
            conf_obj.disk_files_cache = dict(cache)

        sys._escriba_full_scan = cli_args_ns.full_scan

        json_path, full_list, working_list, chan_tot_int = _prepare_working_state(
            conf_obj, cookies_list, lang_str, cli_args_ns, channel_filter_str, is_first_channel_bool
        )

        if not working_list:
            if is_first_channel_bool: print_ok("Nenhum vídeo novo para processar.")
            return 0, 0, 0, 0, chan_tot_int, False

        # ── Particionamento por conjuntos (Set Partition) ─────────────────────
        # Substitui o loop imperativo com _check_video_skip() por vídeo por
        # operações de conjuntos executadas em C interno do CPython — sem overhead
        # de chamada de função por item.
        retry_nosub = getattr(cli_args_ns, "retry_nosub", False)
        disk_cache  = conf_obj.disk_files_cache or {}

        # Set comprehensions: O(N) em C, sem chamada de função por item
        already_downloaded_ids = {v["video_id"] for v in working_list if v.get("subtitle_downloaded")}
        no_subtitle_ids        = {v["video_id"] for v in working_list
                                   if v.get("has_no_subtitle") and not retry_nosub}
        disk_ids               = set(disk_cache)   # dict → set: O(1) amortizado
        all_skip_ids           = already_downloaded_ids | no_subtitle_ids | disk_ids

        # Pré-agenda MD para arquivos .srt encontrados no disco sem .md correspondente
        pending_md_pre: list[tuple] = []
        for v in working_list:
            vid_id = v["video_id"]
            if vid_id in disk_ids and vid_id not in already_downloaded_ids:
                files   = disk_cache.get(vid_id, [])
                has_srt = any(f.endswith(".srt") for f in files)
                has_md  = any(f.endswith(".md")  for f in files)
                if has_srt and not has_md and cli_args_ns.md:
                    srt_f = next(f for f in files if f.endswith(".srt"))
                    pending_md_pre.append((
                        conf_obj.cwd_path / srt_f, vid_id,
                        v.get("title", "Sem Título"), v.get("publish_date", "N/A")
                    ))
                # Replica o que _check_disk_files fazia: marca como baixado em memória
                v.update({"info_downloaded": True, "subtitle_downloaded": True})

        # Partição final: apenas vídeos que realmente precisam ser baixados
        to_download = [v for v in working_list if v["video_id"] not in all_skip_ids]
        if getattr(cli_args_ns, "limit", None) is not None and cli_args_ns.limit > 0:
            to_download = to_download[:cli_args_ns.limit]
        n_total     = len(working_list)
        pre_skipped = n_total - len(to_download)

        _print_partition_summary(working_list, to_download, is_first_channel_bool)

        stats, interrupted, pending_dl = _run_video_download_loop(
            conf_obj, cookies_list, lang_str, cli_args_ns, json_path, full_list,
            to_download, pre_skip_count=pre_skipped, total_count=n_total
        )

        # Combina MD pré-agendados (disco) + gerados durante o download
        pending = pending_md_pre + pending_dl

        # Mesmo se o download foi interrompido, tenta converter o que já baixou
        interrupted_md = _run_deferred_md_conversion(pending, cli_args_ns)
        
        return (*stats, chan_tot_int, interrupted or interrupted_md)
    except KeyboardInterrupt:
        print()
        print_warn(f"Interrompido pelo usuário. {DIM}Pulando para as próximas etapas...{RESET}")
        cleanup_temp_files(conf_obj.cwd_path, conf_obj.channel_dir_name)
        return 0, 0, 0, 0, 0, True


def _run_video_download_loop(
    conf: SessionConfig, cookies: list[str], lang: str, args: argparse.Namespace,
    json_path: Path, full_list: list[dict], to_download_list: list[dict],
    pre_skip_count: int = 0, total_count: int = 0
) -> tuple[tuple[int, int, int, int], bool, list]:
    """Executa o loop de download sobre vídeos pré-filtrados pelo particionamento.
    
    Args:
        to_download_list: Apenas vídeos que precisam de download (sem skips).
        pre_skip_count:   Skips contabilizados antes do loop (particionamento).
        total_count:      Total real da sessão para estatísticas do resumo.
    """
    # Skip pré-inicializado com o resultado do particionamento
    stats_list = [0, pre_skip_count, 0]  # [dl, skip, err]
    pending_md, dirty, interrupted = [], [0], False
    n = len(to_download_list)
    real_total = total_count or n
    try:
        for idx_int, video_dict in enumerate(to_download_list, start=1):
            if getattr(sys, "_escriba_interrupted", False):
                raise KeyboardInterrupt
            res = _process_loop_item(idx_int, video_dict, conf, cookies, lang, args, pending_md, dirty, n)
            _update_loop_stats(res, stats_list)
            _check_auto_save(json_path, full_list, lang, conf, dirty)
    except KeyboardInterrupt:
        interrupted = True
        print()
        msg = "Pulando para geração de arquivos .md..." if args.md else "Pulando para as próximas etapas..."
        print_warn(f"Download interrompido. {DIM}{msg}{RESET}")
        cleanup_temp_files(conf.cwd_path, conf.channel_dir_name)

    _persist_state(json_path, full_list, lang, conf)

    return (*stats_list, real_total), interrupted, pending_md


def _update_loop_stats(res_tuple: tuple[int, bool], stats_list: list[int]) -> None:
    """Atualiza contadores de progresso do loop de download."""
    res_int, skip_bool = res_tuple
    if skip_bool: stats_list[1] += 1
    elif res_int == 1: stats_list[0] += 1
    elif res_int == -1: stats_list[2] += 1


def _check_auto_save(json_path: Path, full_list: list[dict], lang_str: str, session_config_obj: SessionConfig, dirty_list: list[int]) -> None:
    """Salva o estado automaticamente a cada 5 alterações."""
    if dirty_list[0] >= 5:
        _persist_state(json_path, full_list, lang_str, session_config_obj)
        dirty_list[0] = 0


def _process_loop_item(
    idx: int, video_dict: dict, session_config: SessionConfig,
    cookie_args_list: list[str], language_opt_str: str, cli_args: argparse.Namespace,
    pending_md_list: list, dirty_int: list[int], total: int
) -> tuple[int, bool]:
    """Processa um item individual do loop de download.
    
    Nota: A entrada já foi pré-filtrada pelo particionamento de conjuntos em
    process_videos() — todos os itens aqui requerem download efetivo.
    """
    prefix_str = f"  {BLUE}[{idx:>{len(str(total))}}/{total}]{RESET}"
    res = _download_and_process_single(
        video_dict, session_config, cookie_args_list, language_opt_str,
        cli_args, prefix_str, pending_md_list, dirty_int
    )
    return res, False


def _download_and_process_single(
    video_dict: dict, conf: SessionConfig, cookies: list[str], lang: str, 
    args: argparse.Namespace, prefix: str, pending: list, dirty: list[int]
) -> int:
    """Realiza o download e processamento pós-download de um vídeo único."""
    print_dl(f"{video_dict['video_id']}{RESET}  {DIM}legenda/{lang}{RESET}", prefix)
    provider_mod = _get_provider_module(conf.channel_url)
    exit_code = provider_mod.download_video(
        conf.yt_dlp_cmd_list, cookies, video_dict["video_id"], lang, conf.channel_dir_name,
        download_video_only_hd=getattr(args, "download_video", False)
    )
    
    if getattr(sys, "_escriba_interrupted", False):
        raise KeyboardInterrupt
        
    _update_metadata_from_json(conf, video_dict, dirty)

    if exit_code == 0:
        return _handle_post_download(conf, video_dict, args, pending, prefix, dirty, lambda: None)
    
    _handle_download_failure(exit_code, args, prefix)
    return -1


def _update_metadata_from_json(conf: SessionConfig, video_dict: dict, dirty_list: list[int]) -> None:
    """Extrai metadados do JSON de info se disponível e marca como sujo."""
    if harvest_and_delete_info_json(conf.cwd_path, conf.channel_dir_name, video_dict["video_id"], video_dict):
        video_dict["info_downloaded"] = True
        dirty_list[0] += 1


def _handle_post_download(
    session_config: SessionConfig, video_dict: dict, cli_args_ns: argparse.Namespace, 
    pending_md_list: list, prefix_str: str, dirty_list: list[int], flush_func: callable
) -> int:
    """Resolve a legenda após o download e registra o resultado."""
    ok_bool, srt_path = cleanup_subtitles(
        session_config.cwd_path, session_config.channel_dir_name, 
        video_dict["video_id"], video_dict.get("title", "Sem Título"),
        convert_srt_to_md_bool=cli_args_ns.md, keep_srt_bool=cli_args_ns.keep_srt, 
        indent_str=prefix_str
    )
    
    if ok_bool:
        _register_subtitle_success(video_dict, srt_path, cli_args_ns, pending_md_list, dirty_list, prefix_str, flush_func)
        return 1
    
    return _handle_missing_subtitle(video_dict, cli_args_ns, prefix_str, dirty_list, flush_func)


def _handle_download_failure(exit_code_int: int, cli_args_ns: argparse.Namespace, prefix_str: str) -> None:
    """Trata falha no download de vídeo."""
    if exit_code_int == 2:
        print_err("falha (2) — ID/URL inválido ou vídeo inacessível (permanente)", prefix_str)
        return
        
    print_err(f"falha ({exit_code_int}) — possível 429", prefix_str)
    if not cli_args_ns.fast:
        print_countdown(300, "Resfriamento", prefix_str)


def _persist_state(json_path: Path, full_list: list[dict], language_opt_str: str, session_config: SessionConfig) -> None:
    """Salva o estado atual no arquivo JSON."""
    _, input_type, _ = parse_input_type(session_config.channel_input_url_or_handle)
    url_to_save = session_config.channel_url if input_type != "video" else None

    save_channel_state_json(
        json_path, full_list, 
        detected_language_str=language_opt_str,
        channel_url_str=url_to_save,
        channel_handle_str=session_config.discovered_uploader_id
    )


def _register_subtitle_success(
    video_dict: dict, srt_path: Path | None, cli_args_ns: argparse.Namespace, 
    pending_md_list: list, dirty_list: list[int], prefix_str: str, flush_func: callable
) -> None:
    """Registra sucesso no download de legenda e agenda conversão."""
    if srt_path and cli_args_ns.md:
        pending_md_list.append((
            srt_path, video_dict["video_id"], 
            video_dict.get("title", "Sem Título"), video_dict.get("publish_date", "Desconhecida")
        ))
    
    video_dict["subtitle_downloaded"] = True
    video_dict["has_no_subtitle"] = False
    dirty_list[0] += 1
    flush_func()
    
    if not cli_args_ns.fast:
        print_countdown(random.randint(1, 5), "Aguardando", prefix_str)
    else:
        print_ok("ok", prefix_str)


def _handle_missing_subtitle(video_dict: dict, cli_args_ns: argparse.Namespace, prefix_str: str, dirty_list: list[int], flush_func: callable) -> int:
    """Trata ausência de legenda e decide se marca como definitiva."""
    print_warn("sem legenda — pulando", prefix_str)
    pub_date_str = video_dict.get("publish_date", "Desconhecida")
    if pub_date_str not in ("N/A", "Desconhecida", ""):
        try:
            days_int = (datetime.now() - datetime.strptime(pub_date_str, "%Y-%m-%d")).days
            if days_int > 7:
                video_dict["has_no_subtitle"] = True
                dirty_list[0] += 1
                flush_func()
            else:
                print_info(f"vídeo recente ({days_int}d) — não marcado", prefix_str)
        except ValueError:
            pass

    if not cli_args_ns.fast:
        print_countdown(1, "Aguardando", prefix_str)
    return 0


def _get_concurrency_config(total_int: int) -> tuple[bool, int]:
    """Retorna se deve usar paralelismo e o número de threads com base no estado do GIL no Python 3.14."""
    import sys
    import sysconfig
    
    # Detecção de GIL desativado (Free-threaded Python 3.14+)
    gil_disabled = False
    if hasattr(sys, "_is_gil_enabled"):
        gil_disabled = not sys._is_gil_enabled()
    else:
        try:
            gil_disabled = (sysconfig.get_config_var("Py_GIL_DISABLED") == 1)
        except Exception:
            pass
            
    if gil_disabled:
        # Sem GIL: podemos paralelizar mesmo lotes pequenos sem overhead do GIL.
        # max_workers usa todos os cores lógicos de CPU.
        use_parallel = total_int > 1
        max_workers = os.cpu_count() or 4
        return use_parallel, max_workers
    else:
        # Com GIL: manter a otimização conservadora tradicional
        use_parallel = total_int > 10
        max_workers = min(os.cpu_count() or 4, 8) if use_parallel else 1
        return use_parallel, max_workers


def _run_deferred_md_conversion(pending_list: list[tuple], cli_args_ns: argparse.Namespace) -> bool:
    """Executa a conversão para MD dos arquivos agendados. Retorna True se interrompido."""
    if not pending_list:
        return False
    
    total_int = len(pending_list)
    print()
    
    # Ativamos o pool de threads com base na configuração adaptativa do GIL
    use_parallel_bool, max_workers = _get_concurrency_config(total_int)
    
    mode_suffix_str = f" ({max_workers} threads)" if use_parallel_bool else ""
    print_info(f"Fase 4: Clusterização de IA (TF-IDF) — {BOLD}{total_int} arquivo(s){RESET}{mode_suffix_str}")

    def _convert_task(item: tuple) -> tuple[str, Path | None]:
        """Tarefa individual de conversão para o pool ou loop."""
        srt_path, vid_id_str, title_str, date_str = item
        if not srt_path.exists():
            return vid_id_str, None
        
        md_path = srt_to_md(
            srt_path, vid_id_str, title_str, 
            video_date_str=format_date(date_str), 
            threshold_float=getattr(cli_args_ns, 'threshold', DEFAULT_THRESHOLD),
            indentation_prefix_str="    "
        )
        
        if not cli_args_ns.keep_srt and srt_path.exists():
            try: srt_path.unlink()
            except Exception: pass
            
        return vid_id_str, md_path

    try:
        if use_parallel_bool:
            finished_count_int = 0
            # Explicação para Iniciantes (Concorrência com Threads):
            # Q: Por que usamos ThreadPoolExecutor em vez de um loop 'for' convencional?
            # A: O cálculo de TF-IDF e leitura/escrita de arquivos MD consome processamento e tempo.
            #    Se processarmos sequencialmente, o usuário teria que esperar cada arquivo acabar.
            #    Com o 'ThreadPoolExecutor', o Python cria uma piscina (pool) de trabalhadores (threads)
            #    executando tarefas de forma simultânea (concorrente).
            # - `executor.submit(_convert_task, item)` agenda a execução de uma tarefa e retorna um
            #   objeto do tipo `Future` (uma promessa de resultado futuro).
            # - `as_completed(futures_dict)` é um iterador que nos dá as tarefas conforme elas vão
            #   terminando, não importando a ordem em que foram iniciadas, otimizando o fluxo.
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures_dict = {executor.submit(_convert_task, item): item[1] for item in pending_list}
                for future_obj in as_completed(futures_dict):
                    finished_count_int += 1
                    vid_id, md_res_path = future_obj.result()
                    prefix_str = f"  {BLUE}[{finished_count_int:>{len(str(total_int))}}/{total_int}]{RESET}"
                    
                    if md_res_path:
                        print_ok(f"{vid_id} → {DIM}{md_res_path.name}{RESET}", prefix_str)
                    else:
                        print_warn(f"{vid_id} → falha na conversão", prefix_str)
        else:
            # Mantém o comportamento sequencial clássico para poucos arquivos
            for idx_int, item in enumerate(pending_list, start=1):
                srt_path, vid_id_str, _, _ = item
                prefix_str = f"  {BLUE}[{idx_int:>{len(str(total_int))}}/{total_int}]{RESET}"
                if not srt_path.exists(): continue
                print_dl(f"{vid_id_str}{RESET}  {DIM}gerando .md{RESET}", prefix_str)
                _, md_res_path = _convert_task(item)
                if md_res_path:
                    print_ok(f"{DIM}{md_res_path.name}{RESET}", prefix_str)
                else:
                    print_warn(f"falha na conversão", prefix_str)

    except KeyboardInterrupt:
        print()
        print_warn(f"Geração de MDs interrompida. {DIM}Pulando para a consolidação...{RESET}")
        return True
    except Exception as e_obj:
        print_err(f"Erro na fase de conversão: {e_obj}")

    return False


def _scan_srt_files(cwd_path: Path) -> list[tuple[Path, str]]:
    """Varre archive/, archives/ e cwd buscando arquivos .srt."""
    scan_dirs_list = []
    for arch_dir in ["archive", "archives"]:
        if (cwd_path / arch_dir).is_dir():
            scan_dirs_list.append((cwd_path / arch_dir, f"{arch_dir}/"))
    scan_dirs_list.append((cwd_path, "./"))
    
    srt_files_list = []
    for scan_dir_path, label_str in scan_dirs_list:
        for srt_path in sorted(scan_dir_path.glob("*.srt")):
            srt_files_list.append((srt_path, label_str))
    return srt_files_list


def _load_video_lookup(cwd_path: Path) -> dict:
    """Carrega o estado JSON e retorna um dicionário {video_id: {'title': title, 'date': date}}."""
    json_path = get_latest_json_path(cwd_path)
    state_map = _load_existing_state_map(json_path)
    return {
        vid: {
            "title": v.get("title", "Sem Título"),
            "date": format_date(v.get("publish_date") or v.get("upload_date") or v.get("date"))
        } 
        for vid, v in state_map.items()
    }


def regen_md_from_srt_files(force_bool: bool = False) -> None:
    """Modo offline: regenera .md a partir de arquivos .srt existentes."""
    cwd_path = Path.cwd()
    srt_list = _scan_srt_files(cwd_path)
    if not srt_list:
        print_err("Nenhum arquivo .srt encontrado.")
        sys.exit(1)

    lookup_dict = _load_video_lookup(cwd_path)
    _print_regen_header(cwd_path, len(srt_list))

    conv_int, skip_int = _run_regen_loop(srt_list, lookup_dict, force_bool)
    _print_regen_summary(conv_int, skip_int, len(srt_list))


def _run_regen_loop(srt_list: list, lookup_dict: dict, force_bool: bool) -> tuple[int, int]:
    """Executa o loop de regeneração de arquivos MD."""
    conv_int, skip_int = 0, 0
    total_int = len(srt_list)
    
    # Ativamos o pool de threads com base na configuração adaptativa do GIL
    use_parallel_bool, max_workers = _get_concurrency_config(total_int)
    
    if use_parallel_bool:
        print_info(f"Iniciando regeneração paralela ({max_workers} threads)...")
        
        def _regen_task(indexed_item: tuple) -> tuple[int, str]:
            idx, (srt_path, _) = indexed_item
            # O _process_srt_item já faz seus próprios prints internos
            res = _process_srt_item(srt_path, idx, total_int, lookup_dict, force_bool)
            return res, srt_path.name

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Mantemos o índice original para o prefixo correto [1/N]
                futures_list = [executor.submit(_regen_task, item) for item in enumerate(srt_list, start=1)]
                for future_obj in as_completed(futures_list):
                    res_int, _ = future_obj.result()
                    if res_int == 1:
                        conv_int += 1
                    elif res_int == 0:
                        skip_int += 1
        except KeyboardInterrupt:
            print()
            print_warn(f"Regeneração interrompida. {DIM}Saindo...{RESET}")
    else:
        # Mantém o comportamento sequencial clássico com agrupamento visual por pastas
        curr_label_str = ""
        for idx_int, (srt_path, label_str) in enumerate(srt_list, start=1):
            if label_str != curr_label_str:
                curr_label_str = label_str
                _print_srt_group_header(label_str, srt_list)
            
            res_int = _process_srt_item(srt_path, idx_int, total_int, lookup_dict, force_bool)
            if res_int == 1:
                conv_int += 1
            elif res_int == 0:
                skip_int += 1
                
    return conv_int, skip_int


def _print_regen_header(cwd_path: Path, total_int: int) -> None:
    """Imprime cabeçalho do modo de regeneração."""
    print_info(f"Canal alvo: {BOLD}{cwd_path.name}{RESET}")
    print_info(f"Modo: Regeneração MD offline ({total_int} arquivos)")


def _print_srt_group_header(label_str: str, srt_list: list) -> None:
    """Imprime o divisor de grupo para arquivos SRT."""
    count_int = sum(1 for _, l in srt_list if l == label_str)
    print_section(f"{label_str}  {DIM}({count_int} arquivos .srt){RESET}")


def _process_srt_item(srt_path: Path, idx_int: int, total_int: int, lookup_dict: dict, force_bool: bool) -> int:
    """Processa um único arquivo SRT para regeneração de MD."""
    prefix_str = f"  {BLUE}[{idx_int:>{len(str(total_int))}}/{total_int}]{RESET}"
    vid_id_str = _extract_video_id_from_srt(srt_path)
    meta = lookup_dict.get(vid_id_str, {"title": srt_path.stem, "date": "Desconhecida"})
    title_str = meta["title"]
    date_str = meta["date"]
    md_path = srt_path.with_suffix(".md")

    if md_path.exists() and not force_bool:
        _report_skip_progress(idx_int, total_int)
        return 0
    
    print() # Quebra a linha do contador antes de iniciar a regeneração real
    print_dl(f"{srt_path.name}{RESET}  {DIM}{'re-segmentando' if md_path.exists() else 'gerando .md'}{RESET}", prefix_str)
    res_path = srt_to_md(srt_path, vid_id_str, title_str, video_date_str=date_str, threshold_float=DEFAULT_THRESHOLD, indentation_prefix_str="      ")
    
    if res_path:
        print_ok(f"salvo: {DIM}{res_path.name}{RESET}", "      ")
        return 1
    print_warn("falha ou vazio", "      ")
    return -1


def _extract_video_id_from_srt(srt_path: Path) -> str:
    """
    Extrai o ID do vídeo (YouTube=11 chars ou Vimeo=numérico) do nome do arquivo SRT.
    Utiliza a lógica robusta centralizada em utils.py.
    """
    return extract_video_id(srt_path.name)


def _print_regen_summary(conv_int: int, skip_int: int, total_int: int) -> None:
    """Imprime o resumo da regeneração."""
    print()
    print(f"  {BOLD}{BWHITE}Regeneração concluída{RESET}")
    print(f"  {ICON_OK}  Convertidos : {BGREEN}{conv_int}{RESET}")
    print(f"  {ICON_SKIP}  Pulados     : {DIM}{skip_int}{RESET}")
    print(f"  {ICON_INFO}  Total       : {total_int}")
    print()


def _scan_md_files(cwd_path: Path) -> list[tuple[Path, str]]:
    """Busca todos os arquivos .md no cwd e nas pastas archive/ e archives/."""
    scan_dirs_list = [(cwd_path, "./")]
    for arch_dir in ["archive", "archives"]:
        if (cwd_path / arch_dir).is_dir():
            scan_dirs_list.append((cwd_path / arch_dir, f"{arch_dir}/"))
    
    md_files_list = []
    for scan_dir_path, label_str in scan_dirs_list:
        for md_path in sorted(scan_dir_path.glob("*.md")):
            md_files_list.append((md_path, label_str))
    return md_files_list


def _extract_old_metadata(content_str: str) -> dict:
    """Extrai metadados do formato de cabeçalho antigo."""
    header_regex = re.compile(
        r'^##\s+(?P<title>.+?)\n'
        r'(?:\*\*URL:\*\*\s*(?P<url>\S+?)\s*\n)?'
        r'(?:\*\*Data:\*\*\s*(?P<date>\S+?)\s*\n)?'
        r'(?:\*\*Duração:\*\*\s*(?P<duration>\S+?)\s*\n)?',
        re.MULTILINE
    )
    match_obj = header_regex.search(content_str)
    return match_obj.groupdict() if match_obj else {}


def upgrade_md_headers() -> None:
    """Atualiza o cabeçalho de arquivos .md para o novo formato YAML."""
    cwd_path = Path.cwd()
    all_md_files_list = _scan_md_files(cwd_path)
    if not all_md_files_list:
        print_err("Nenhum arquivo .md encontrado para upgrade.")
        return

    _print_upgrade_header(cwd_path, len(all_md_files_list))

    counts_list = [0, 0, 0, 0] # upgraded, already_new, skipped, error
    for idx_int, (md_path, _) in enumerate(all_md_files_list, start=1):
        _upgrade_single_md(md_path, idx_int, len(all_md_files_list), counts_list)

    _print_upgrade_summary(counts_list, len(all_md_files_list))


def _print_upgrade_header(cwd_path: Path, total_int: int) -> None:
    """Imprime cabeçalho do upgrade."""
    print_info(f"Canal alvo: {BOLD}{cwd_path.name}{RESET}")
    print_info(f"Modo: Upgrade de Cabeçalho MD ({total_int} arquivos)")


def _upgrade_single_md(md_path: Path, idx_int: int, total_int: int, counts_list: list[int]) -> None:
    """Realiza o upgrade de um único arquivo MD."""
    prefix_str = f"  {BLUE}[{idx_int:>{len(str(total_int))}}/{total_int}]{RESET}"
    content_str = md_path.read_text(encoding="utf-8-sig")
    
    if content_str.startswith("---"):
        counts_list[1] += 1
        return

    meta_dict = _extract_old_metadata(content_str)
    if not meta_dict:
        counts_list[2] += 1
        return

    _save_upgraded_md(md_path, content_str, meta_dict, prefix_str, counts_list)


def _save_upgraded_md(md_path: Path, content_str: str, meta_dict: dict, prefix_str: str, counts_list: list[int]) -> None:
    """Gera o novo cabeçalho e salva o arquivo MD."""
    header_str = _build_new_md_header(md_path, meta_dict)
    body_str = _extract_md_body(content_str)
    
    try:
        md_path.write_text(header_str + body_str, encoding="utf-8-sig")
        print_ok(f"{md_path.name}  {DIM}cabeçalho atualizado{RESET}", prefix_str)
        counts_list[0] += 1
    except Exception as e_obj:
        print_warn(f"{md_path.name}  erro ao salvar: {e_obj}", prefix_str)
        counts_list[3] += 1


def _build_new_md_header(md_path: Path, meta_dict: dict) -> str:
    """Extrai ID e gera novo cabeçalho YAML."""
    vid_id_str = "unknown"
    if "vimeo.com/" in meta_dict.get("url", ""):
        vimeo_id_match = re.search(r"vimeo\.com/(\d+)", meta_dict.get("url", ""))
        if vimeo_id_match: vid_id_str = vimeo_id_match.group(1)
    else:
        yt_id_match = re.search(r"watch\?v=([A-Za-z0-9_-]{11})", meta_dict.get("url", ""))
        if yt_id_match: vid_id_str = yt_id_match.group(1)
    
    header_list = generate_md_header(
        meta_dict.get("title", md_path.stem),
        vid_id_str,
        meta_dict.get("date", "Desconhecida"),
        meta_dict.get("duration", "N/A"),
        "unknown",
        VERSION
    )
    return "".join(header_list)


def _extract_md_body(content_str: str) -> str:
    """Extrai o corpo do markdown, removendo o cabeçalho antigo."""
    body_match_obj = re.search(r'(?m)^###\s+Segmentos', content_str)
    if body_match_obj:
        return content_str[body_match_obj.start():]
    
    lines_list = content_str.splitlines(keepends=True)
    body_start_int = 0
    for idx_int, line_str in enumerate(lines_list):
        if not (line_str.startswith("## ") or line_str.startswith("**") or line_str.strip() == "" or line_str.startswith(">")):
            body_start_int = idx_int
            break
    return "".join(lines_list[body_start_int:])


def _print_upgrade_summary(counts_list: list[int], total_int: int) -> None:
    """Imprime o resumo do upgrade de cabeçalhos."""
    upgraded_int, already_new_int, skipped_int, error_int = counts_list
    print(f"\n  {BOLD}{BWHITE}Upgrade de Cabeçalho MD concluído{RESET}")
    print(f"  {ICON_OK}  Atualizados  : {BGREEN}{upgraded_int}{RESET}")
    print(f"  {ICON_SKIP}  Já atualizados: {DIM}{already_new_int}{RESET}")
    print(f"  {ICON_SKIP}  Pulados       : {DIM}{skipped_int}{RESET}")
    if error_int:
        print(f"  {ICON_ERR}  Erros         : {BRED}{error_int}{RESET}")
    print(f"  {ICON_INFO}  Total         : {total_int}\n")



def _validate_direct_download_target(canal_arg_any: list | str | None) -> tuple[str, str]:
    """Valida o alvo do download direto e retorna URL e tipo."""
    if not canal_arg_any:
        print_err("Por favor, especifique uma URL ou ID de vídeo/playlist para download de vídeo.")
        sys.exit(1)
        
    url_str, input_type_str, _ = parse_input_type(str(canal_arg_any))
    if input_type_str == "channel":
        print_err("Download de vídeo original (-dv/--download-video) não é permitido para CANAL completo.")
        print_err("Por favor, execute o download de vídeo apenas para um vídeo individual ou playlist.")
        sys.exit(1)
        
    return url_str, input_type_str


def _filter_cookies_if_present(cwd_path: Path, provider_str: str) -> None:
    """Filtra cookies caso o arquivo exista, dependendo do provedor."""
    cookies_txt_path = cwd_path / "cookies.txt"
    if cookies_txt_path.is_file():
        if provider_str == "vimeo":
            filter_vimeo_cookies(cookies_txt_path)
            print_info("Cookies filtrados limitados ao Vimeo.")
        else:
            filter_youtube_cookies(cookies_txt_path)
            print_info("Cookies filtrados limitados ao YouTube.")


def _build_yt_dlp_direct_cmd(url_str: str, yt_dlp_cmd_list: list[str], cookies_list: list[str]) -> list[str]:
    """Gera a lista de argumentos yt-dlp para download de vídeo direto em HD sem áudio."""
    return yt_dlp_cmd_list + cookies_list + [
        "--ignore-no-formats-error",
        "--restrict-filenames",
        "-f", "bestvideo[height<=1080]",
        "--remux-video", "mp4",
        "-o", "%(title)s [%(id)s].%(ext)s",
        url_str
    ]


def _execute_direct_download(cmd_list: list[str]) -> None:
    """Executa o processo yt-dlp de download direto de vídeo."""
    try:
        process_result_obj = subprocess.run(cmd_list)
        if process_result_obj.returncode != 0:
            print_err(f"O download falhou com código de retorno {process_result_obj.returncode}.")
            sys.exit(process_result_obj.returncode)
    except Exception as error_obj:
        print_err(f"Erro inesperado durante o download do vídeo: {error_obj}")
        sys.exit(1)


def _run_direct_video_download_flow(cli_args_ns: argparse.Namespace) -> None:
    """Fluxo principal para download direto de vídeo MP4 HD sem áudio (-dv)."""
    url_str, _ = _validate_direct_download_target(cli_args_ns.canal)
    script_dir_path, yt_dlp_cmd_list = youtube.setup_environment()
    provider_str = get_provider(url_str)
    
    cookies_list = configure_cookies(Path.cwd(), script_dir_path, cli_args_ns.refresh_cookies, silent_bool=False, browser_str=getattr(cli_args_ns, "browser", "firefox"))
    _filter_cookies_if_present(Path.cwd(), provider_str)
    
    print_info(f"Iniciando download de vídeo direto em Full HD...")
    print_info(f"Destino: {url_str}")
    
    cmd_list = _build_yt_dlp_direct_cmd(url_str, yt_dlp_cmd_list, cookies_list)
    _execute_direct_download(cmd_list)
    print_ok("Download de vídeo direto concluído com sucesso!")


def main() -> None:
    setup_sigint_handler()
    if "--status" not in sys.argv:
        print_header(VERSION)
    cli_args_ns = parse_args()
    _normalize_canal_arg(cli_args_ns)

    if getattr(cli_args_ns, "download_video", False):
        _run_direct_video_download_flow(cli_args_ns)
        return

    if _handle_cli_pre_flows(cli_args_ns):
        return

    cwd_path = Path.cwd()
    json_path = get_latest_json_path(cwd_path)
    user_canal_str = cli_args_ns.canal

    if user_canal_str and json_path.exists():
        _, input_type, _ = parse_input_type(user_canal_str)
        if input_type != "video":
            if _handle_new_channel_flow(json_path, user_canal_str, cli_args_ns, cwd_path):
                return

    _run_main_sync_flow(json_path, user_canal_str, cli_args_ns, cwd_path)


def _run_main_sync_flow(json_path: Path, user_canal_str: str | None, cli_args_ns: argparse.Namespace, cwd_path: Path) -> None:
    """Executa o fluxo principal de sincronização (multi-canal ou padrão)."""
    channels_list = _get_channels_to_sync(json_path, user_canal_str)
    if len(channels_list) > 1:
        _run_multi_channel_flow(channels_list, cli_args_ns, cwd_path)
    else:
        if len(channels_list) == 1:
            cli_args_ns.canal = channels_list[0]
        _run_default_flow(cli_args_ns)


def _normalize_canal_arg(cli_args: argparse.Namespace) -> None:
    """Normaliza o argumento 'canal' se vier como lista."""
    if not isinstance(cli_args.canal, list) or not cli_args.canal:
        if isinstance(cli_args.canal, list): cli_args.canal = None
        return
    
    if cli_args.canal[0].startswith("http"):
        cli_args.canal = "".join(cli_args.canal)
    else:
        cli_args.canal = " ".join(cli_args.canal)


def exibir_status_canais_json() -> None:
    """Localiza todos os arquivos de banco de dados escriba_*.json na pasta de trabalho e exibe suas estatísticas como JSON."""
    import json
    from pathlib import Path
    
    cwd_path = Path.cwd()
    db_files = list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json"))
    seen = set()
    unique_dbs = []
    for p in db_files:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_dbs.append(p)
            
    channels_status = []
    for db_path in unique_dbs:
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            videos = data.get("videos")
            if not isinstance(videos, list):
                if isinstance(data, list):
                    videos = data
                    data = {}
                else:
                    videos = []
                    
            total_videos = len(videos)
            downloaded = sum(1 for v in videos if v.get("subtitle_downloaded"))
            no_subtitle = sum(1 for v in videos if v.get("has_no_subtitle"))
            pending = total_videos - downloaded - no_subtitle
            
            channels_status.append({
                "banco_dados": db_path.name,
                "caminho_absoluto": str(db_path.resolve()),
                "idioma_detectado": data.get("detected_language") if isinstance(data, dict) else None,
                "canais_youtube": data.get("youtube_channels", []) if isinstance(data, dict) else [],
                "canais_vimeo": data.get("vimeo_channels", []) if isinstance(data, dict) else [],
                "estatisticas": {
                    "total_videos": total_videos,
                    "baixados": downloaded,
                    "sem_legenda": no_subtitle,
                    "pendentes": pending
                }
            })
        except Exception as e:
            channels_status.append({
                "banco_dados": db_path.name,
                "erro": str(e)
            })
            
    print(json.dumps(channels_status, indent=4, ensure_ascii=False))


def _handle_cli_pre_flows(cli_args: argparse.Namespace) -> bool:
    """Executa fluxos de pré-processamento disparados por flags da CLI."""
    if cli_args.status:
        exibir_status_canais_json()
        return True
    if cli_args.regen_md:
        regen_md_from_srt_files(force_bool=getattr(cli_args, 'force', False))
        return True
    if cli_args.upgrade_md:
        upgrade_md_headers()
        return True
    if cli_args.migrate:
        migrate_all_databases(Path.cwd())
        return True
    if (cli_args.consolidar or cli_args.lexis_reset) and not cli_args.canal:
        consolidar_por_canal(str(Path.cwd()), reset_mode_bool=cli_args.lexis_reset)  # -j / --juntar / --consolidar
        return True
    return False


def _handle_new_channel_flow(json_path: Path, canal_str: str, cli_args_ns: argparse.Namespace, cwd_path: Path) -> bool:
    """Trata a detecção e processamento de um novo canal."""
    provider = get_provider(canal_str)
    is_new_bool, _ = register_channel_in_json(json_path, canal_str, provider_str=provider)
    if not is_new_bool:
        return False

    print_section("Novo Canal Detectado")
    print_info(f"Canal {BOLD}{canal_str}{RESET} é novo. Processando apenas este canal.")
    
    conf_obj = setup_session(cli_args_ns)
    cookies_list, lang_str = init_auth_and_language(conf_obj, cli_args_ns.lang, cli_args_ns.refresh_cookies)
    res_tuple = process_videos(conf_obj, cookies_list, lang_str, cli_args_ns, channel_filter_str=canal_str, is_first_channel_bool=False)
    
    _finish_session_flow(res_tuple, cli_args_ns, cwd_path)
    return True


def _get_channels_to_sync(json_path: Path, user_canal_str: str | None) -> list[str]:
    """Retorna a lista de canais para sincronizar a partir do JSON."""
    if user_canal_str or not json_path.exists():
        return []
    try:
        data_dict = json.loads(json_path.read_text(encoding="utf-8"))
        yt_chans = data_dict.get("youtube_channels", [])
        vi_chans = data_dict.get("vimeo_channels", [])
        
        all_chans = []
        if isinstance(yt_chans, list): all_chans.extend(yt_chans)
        if isinstance(vi_chans, list): all_chans.extend(vi_chans)
        
        return all_chans
    except Exception:
        return []


def _run_multi_channel_flow(channels_list: list[str], cli_args_ns: argparse.Namespace, cwd_path: Path) -> None:
    """Executa a sincronização para múltiplos canais."""
    is_multi_bool = len(channels_list) > 1
    _print_sync_header(channels_list, is_multi_bool)

    global_cookies_list = []
    if channels_list:
        # Setup inicial de cookies para evitar múltiplas extrações do navegador.
        # Usamos o primeiro canal da lista como "mestre" para o warm-up de cookies.
        orig_canal = cli_args_ns.canal
        cli_args_ns.canal = channels_list[0]
        conf_obj = setup_session(cli_args_ns)
        global_cookies_list = _ensure_global_cookies(conf_obj, cli_args_ns)
        cli_args_ns.canal = orig_canal

    stats_list = [0, 0, 0, 0, 0] # dl, skip, err, tot, chan_tot
    interrupted_bool = False
    
    # Desativado: Subinterpretadores são incompatíveis com yt-dlp/urllib3 (daemon threads são proibidas em subinterpretadores)
    if False and _interpreters is not None and len(channels_list) > 1:
        print_info("CPython 3.14: Inicializando Subinterpretadores independentes com per-interpreter GIL...")
        threads = []
        temp_files = []
        interpreters_to_destroy = []
        
        cli_args_ns_dict = vars(cli_args_ns)
        script_dir_path = Path(__file__).parent.resolve()
        
        for idx_int, channel_str in enumerate(channels_list, 1):
            temp_file_path = cwd_path / f".escriba_stats_{idx_int}.json"
            temp_files.append((temp_file_path, idx_int))
            
            try:
                sub_id = _interpreters.create()
                sub_id_int = sub_id[0] if isinstance(sub_id, tuple) else sub_id
                interpreters_to_destroy.append(sub_id_int)
                
                # Código a ser executado isoladamente em cada subinterpretador
                code = f"""
import sys
sys.path.insert(0, r"{script_dir_path}")
import escriba
import json
from pathlib import Path

# Reconstituir cli_args_ns
args_dict = {cli_args_ns_dict}
class CLIArgs:
    def __init__(self, d):
        for k, v in d.items():
            setattr(self, k, v)
cli_args_ns = CLIArgs(args_dict)

# Configura o canal atual para este subinterpretador
cli_args_ns.canal = {repr(channel_str)}

# Executa o processamento do canal
res = escriba._process_channel_sync_item(
    {repr(channel_str)}, cli_args_ns, {idx_int}, {is_multi_bool},
    global_cookies_list={repr(global_cookies_list)}
)

# Grava o resultado no arquivo temporario
temp_path = Path(r"{temp_file_path}")
try:
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(res, f)
except Exception:
    pass
"""
                
                def _thread_target(s_id, c_string, ch_name):
                    try:
                        _interpreters.run_string(s_id, c_string)
                    except Exception as e:
                        print_err(f"Erro no subinterpretador para o canal {ch_name}: {e}")
                
                t = threading.Thread(target=_thread_target, args=(sub_id_int, code, channel_str), name=f"Escriba-{channel_str}")
                threads.append(t)
                
            except Exception as e:
                print_err(f"Falha ao inicializar subinterpretador para o canal {channel_str}: {e}")
                
        # Executa todas as threads em paralelo
        for t in threads:
            t.start()
            
        # Aguarda a conclusão
        for t in threads:
            try:
                t.join()
            except KeyboardInterrupt:
                interrupted_bool = True
                
        # Recupera as estatísticas de cada subinterpretador
        for temp_file_path, idx_int in temp_files:
            if temp_file_path.exists():
                try:
                    with open(temp_file_path, "r", encoding="utf-8") as f:
                        res_tuple = json.load(f)
                    if res_tuple:
                        _accumulate_multi_stats(stats_list, res_tuple)
                        if res_tuple[5]:
                            interrupted_bool = True
                except Exception:
                    pass
                finally:
                    try:
                        temp_file_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                        
        # Destrói os subinterpretadores
        for sub_id_int in interpreters_to_destroy:
            try:
                _interpreters.destroy(sub_id_int)
            except Exception:
                pass
    else:
        # Fallback: executa de forma sequencial (comportamento clássico)
        try:
            for idx_int, channel_str in enumerate(channels_list, 1):
                cli_args_ns.canal = channel_str
                res_tuple = _process_channel_sync_item(
                    channel_str, cli_args_ns, idx_int, is_multi_bool, 
                    global_cookies_list=global_cookies_list
                )
                if res_tuple:
                    _accumulate_multi_stats(stats_list, res_tuple)
                    if res_tuple[5]:
                        interrupted_bool = True
                        break
        except KeyboardInterrupt:
            interrupted_bool = True
            print()
            print_warn(f"Interrompido pelo usuário. {DIM}Encerrando sincronização...{RESET}")

    print_info(f"\nTodos os {BOLD}{len(channels_list)}{RESET} canal(is) verificados.")
    _finish_session_flow((*stats_list, interrupted_bool), cli_args_ns, cwd_path, multi=is_multi_bool)


def _accumulate_multi_stats(stats_list: list[int], res_tuple: tuple) -> None:
    """Acumula estatísticas de um canal no total da sessão."""
    for i_int in range(5):
        stats_list[i_int] += res_tuple[i_int]


def _print_sync_header(channels_list: list[str], is_multi_bool: bool) -> None:
    """Imprime cabeçalho da sincronização."""
    print_section("Sincronização Multi-Canal" if is_multi_bool else "Sincronização de Canal")
    for i_int, ch_str in enumerate(channels_list, 1):
        print_info(f"  {BOLD}{i_int}.{RESET} {ch_str}")
    print()


def _process_channel_sync_item(
    channel_str: str, 
    cli_args_ns: argparse.Namespace, 
    idx_int: int, 
    is_multi_bool: bool,
    global_cookies_list: list[str] = None
) -> tuple | None:
    """Processa um único canal no fluxo multi-canal."""
    try:
        conf_obj = setup_session(cli_args_ns)
        
        # Se já temos os cookies globais, não repetimos a autenticação
        if global_cookies_list:
            cookies_list = global_cookies_list
            print_section("Idioma")
            # Detectamos apenas o idioma, pois os cookies já estão prontos
            lang_str = _detect_and_report_language(conf_obj, cookies_list, cli_args_ns.lang)
        else:
            cookies_list, lang_str = init_auth_and_language(conf_obj, cli_args_ns.lang, cli_args_ns.refresh_cookies)

        return process_videos(
            conf_obj, cookies_list, lang_str, cli_args_ns,
            channel_filter_str=channel_str if is_multi_bool else None,
            is_first_channel_bool=(idx_int == 1)
        )
    except Exception as e_obj:
        print_err(f"Erro ao processar canal {channel_str}: {e_obj}")
        return None


def print_summary(
    downloaded_videos_count: int,
    skipped_videos_count: int,
    error_videos_count: int,
    total_videos_count: int,
    channel_total_count: int = 0
) -> None:
    """Exibe o resumo das estatísticas da sessão."""
    # Se channel_total_count não for informado, usa o total_videos_count
    chan_tot = channel_total_count if channel_total_count > 0 else total_videos_count
    
    print(f"  {ICON_OK}  Baixados    : {BGREEN}{downloaded_videos_count}{RESET}")
    print(f"  {ICON_SKIP}  Pulados     : {DIM}{skipped_videos_count}{RESET}")
    if error_videos_count > 0:
        print(f"  {ICON_ERR}  Erros       : {BRED}{error_videos_count}{RESET}")
    print(f"  {ICON_DL}  Processados : {total_videos_count} de {chan_tot}")
    print()


def _run_default_flow(cli_args_ns: argparse.Namespace) -> None:
    """Fluxo padrão de processamento (único canal ou primeira execução)."""
    conf_obj = setup_session(cli_args_ns)
    cookies_list, lang_str = init_auth_and_language(conf_obj, cli_args_ns.lang, cli_args_ns.refresh_cookies)
    res_tuple = process_videos(conf_obj, cookies_list, lang_str, cli_args_ns)
    _finish_session_flow(res_tuple, cli_args_ns, Path.cwd())


def _finish_session_flow(res_tuple: tuple, cli_args_ns: argparse.Namespace, cwd_path: Path, multi: bool = False) -> None:
    """Finaliza o fluxo, imprime resumo e limpa estado."""
    dl_int, sk_int, er_int, tot_int, chan_tot_int, interrupted_bool = res_tuple
    print_section("Resumo Multi-Canal" if multi else "Resumo")
    print_summary(dl_int, sk_int, er_int, tot_int, chan_tot_int)
    if (cli_args_ns.consolidar or cli_args_ns.lexis_reset):
        consolidar_por_canal(str(cwd_path), reset_mode_bool=cli_args_ns.lexis_reset)  # -j / --juntar / --consolidar
    if interrupted_bool:
        sys.exit(130)



if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except KeyboardInterrupt:
        print()
        print_warn(f"Interrompido pelo usuário (Ctrl+C).  {DIM}Saindo...{RESET}")
        cwd = Path.cwd()
        if cwd.name != "escriba":
            cleanup_temp_files(cwd, cwd.name)
        sys.exit(130)  # Código 130 = SIGINT (padrão Unix)
