#!/usr/bin/env python3
"""
=============================================================================
ESCRIBA: Orquestrador de Download de Legendas do YouTube
=============================================================================

SUMÁRIO DO SCRIPT:
Baixa legendas de todos os vídeos de um canal do YouTube.
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
        os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)
    except Exception:
        pass # Fallback suave

# Suprime avisos chatos de dependências (urllib3/requests)
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
import shutil
import time
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import print_ok, print_err, print_warn, print_info, print_skip, print_dl, print_section, print_header, print_countdown, BOLD, RESET, DIM, GREEN, RED, YELLOW, BLUE, WHITE, BCYAN, BWHITE, BRED, BGREEN, BYELLW, ICON_OK, ICON_ERR, ICON_WARN, ICON_SKIP, ICON_DL, ICON_WAIT, ICON_INFO
from rules import clean_ekklezia_terms
from history import get_latest_json_path, load_all_local_history, save_channel_state_json, auto_migrate_legacy_files, migrate_all_databases, filter_state_list, register_channel_in_json
from youtube import setup_environment, configure_cookies, filter_youtube_cookies, detect_language, get_video_exact_date, generate_fast_list_json, download_video
from datetime import datetime
from dataclasses import dataclass
from lexis import consolidate_by_channel

from typing import Optional
from dotenv import load_dotenv
import requests

from collections import Counter

VERSION = "2.6.0"

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
    mp3: bool = False
    discovered_uploader_id: Optional[str] = None


@dataclass
class DownloadConfig:
    """Configurações para download de um vídeo específico."""
    language: str  # Idioma das legendas
    audio_only: bool = False  # Baixar apenas áudio
    output_dir: Path | None = None  # Diretório customizado
    keep_srt: bool = False  # Manter .srt após converter para .md

# Carrega variáveis do .env (localizado no diretório do script)
load_dotenv(Path(__file__).parent / ".env")

# Node.js path para o js-runtime do yt-dlp.
# Por que isso? O yt-dlp às vezes precisa de JavaScript para processar certain páginas.
# Prioridade: variável NODE_PATH do .env (se você definir) → node encontrado no PATH do sistema
NODE_PATH = os.getenv("NODE_PATH") or shutil.which("node") or ""

def load_or_create_channel_state(
    cwd_path: Path, 
    yt_dlp_cmd_list: list[str], 
    cookie_args_list: list[str], 
    channel_url: str,
    only_peek_lang: bool = False
) -> tuple[Path | None, list[dict], str | None, int]:
    """
    Carrega ou cria o banco de dados JSON do canal.
    
    Essa é uma das funções mais importantes do Escriba. Ela:
    
    1. Detecta que tipo de entrada é (vídeo único, playlist, canal)
    2. Identifica o canal/uploader (importante para naming de arquivos)
    3. Carrega dados existentes do JSON
    4. Busca vídeos atuais no YouTube
    5. Mescla: vídeos novos + vídeos que você já tem localmente
    6. Faz "importação reversa": se você tem um vídeo baixado mas ele não
       aparece mais no canal (foi deletado), a gente mantém ele!
    
    O parâmetro only_peek_lang=True é um atalho: se você só quer saber
    o idioma (sem carregar toda a lista de vídeos), usa isso.
    """
    history_map = load_all_local_history(cwd_path)
    channel_name_safe = None
    identifier = ""
    
    # Extração de identificador (Handle ou ID de Playlist ou ID de Vídeo)
    # Identificação de Canal para vídeos individuais: busca o uploader antes de definir o JSON
    target_channel_id = None
    target_uploader_id = None

    if "watch?v=" in channel_url or "youtu.be/" in channel_url:
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", channel_url)
        identifier = match.group(1) if match else "video"
        
        if identifier in history_map:
            hist_entry = history_map[identifier]
            target_uploader_id = hist_entry.get("uploader_id")
            target_channel_id = hist_entry.get("channel_id")
            if target_uploader_id:
                channel_name_safe = target_uploader_id.lstrip("@")
                print_ok(f"Origem identificada (cache local): {BOLD}@{channel_name_safe}{RESET}")

        if not channel_name_safe:
            # Tenta descobrir o uploader sem baixar nada pesado
            print_info(f"Identificando canal de origem para o vídeo {BOLD}{identifier}{RESET}...")
            meta_cmd = yt_dlp_cmd_list + cookie_args_list + ["--dump-json", "--skip-download", f"https://www.youtube.com/watch?v={identifier}"]
            try:
                p = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=15)
                if p.stdout:
                    video_meta = json.loads(p.stdout)
                    target_uploader_id = video_meta.get("uploader_id")
                    target_channel_id = video_meta.get("channel_id")
                    
                    if target_uploader_id:
                        # Remove @
                        channel_name_safe = target_uploader_id.lstrip("@")
                        print_ok(f"Origem identificada: {BOLD}@{channel_name_safe}{RESET}")
            except Exception:
                pass
            
        if not channel_name_safe:
            channel_name_safe = f"video_{identifier}"
    elif "@" in channel_url:
        match = re.search(r"@([A-Za-z0-9_-]+)", channel_url)
        channel_name_safe = match.group(1) if match else "canal"
        # Carregamos o histórico aqui também para uso posterior
    elif "list=" in channel_url:
        match = re.search(r"list=([A-Za-z0-9_-]+)", channel_url)
        identifier = match.group(1) if match else "playlist"
        
        # 0. Verificação em cache local para playlists
        for vid, entry in history_map.items():
            if "playlists" in entry and identifier in entry["playlists"]:
                target_uploader_id = entry.get("uploader_id")
                target_channel_id = entry.get("channel_id")
                if target_uploader_id:
                    channel_name_safe = target_uploader_id.lstrip("@")
                    print_ok(f"Dono da playlist identificado (cache local): {BOLD}@{channel_name_safe}{RESET}")
                    break
        
        if not channel_name_safe:
            # O mesmo escudo aplicado a vídeos avulsos, mas focando no índice 1 da playlist
            print_info(f"Identificando canal dono da playlist {BOLD}{identifier}{RESET}...")
            meta_cmd = yt_dlp_cmd_list + cookie_args_list + [
                "--dump-json", "--flat-playlist", "--playlist-end", "1", 
                "--ignore-errors", channel_url
            ]
            
            try:
                p = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=15)
                if p.stdout:
                    # O flat-playlist cospe um JSON por linha de saída
                    first_line = p.stdout.splitlines()[0]
                    playlist_meta = json.loads(first_line)
                    
                    target_uploader_id = playlist_meta.get("uploader_id")
                    target_channel_id = playlist_meta.get("channel_id")
                    
                    if target_uploader_id:
                        channel_name_safe = target_uploader_id.lstrip("@")
                        print_ok(f"Origem da playlist identificada: {BOLD}@{channel_name_safe}{RESET}")
                    elif playlist_meta.get("uploader"):
                         channel_name_safe = playlist_meta.get("uploader").replace(" ","_")
                         print_ok(f"Canal da playlist (nome): {BOLD}{channel_name_safe}{RESET}")
            except Exception:
                pass
            
        if not channel_name_safe:
            channel_name_safe = f"playlist_{identifier}"

    else:
        channel_name_safe = "canal"

    folder_name = cwd_path.name
    # channel_dir_name será usado nos nomes dos arquivos (legado agora sincronizado com a pasta)
    channel_dir_name = folder_name
    json_path = cwd_path / f"escriba_{folder_name}.json"
    
    # Migração automática de JSONs antigos para o novo formato de pasta (Consolidação)
    legacy_jsons = list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json"))
    for lj in legacy_jsons:
        if lj.resolve() == json_path.resolve():
            continue
        
        if not json_path.exists():
            print_info(f"Migrando base antiga para o novo padrão: {BOLD}{lj.name}{RESET} -> {BOLD}{json_path.name}{RESET}")
            lj.rename(json_path)
        else:
            print_info(f"Consolidando base antiga (merge): {BOLD}{lj.name}{RESET} -> {BOLD}{json_path.name}{RESET}")
            lj.rename(lj.with_suffix(".bak"))

    # Carregar/Identificar idioma persistente
    detected_lang_cached = None
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as fd:
                data = json.load(fd)
                if isinstance(data, dict):
                    detected_lang_cached = data.get("detected_language")
        except (json.JSONDecodeError, KeyError) as e:
            print_warn(f"Idioma_CACHE: JSON inválido ignorado ({json_path.name})")
        except OSError as e:
            print_warn(f"Idioma_CACHE: Arquivo não encontrado ({json_path.name})")

    if only_peek_lang:
        return json_path, [], detected_lang_cached, 0

    # 1. Carregar lista mestre do JSON alvo (se existir) para garantir preservação total
    state_map: dict[str, dict] = {}
    if json_path and json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as fd:
                json_data = json.load(fd)
                v_list = json_data["videos"] if isinstance(json_data, dict) and "videos" in json_data else json_data
                if isinstance(v_list, list):
                    for v in v_list:
                        vid_id = v.get("video_id") or v.get("id")
                        if vid_id:
                            state_map[vid_id] = v
        except (json.JSONDecodeError, KeyError) as e:
            print_warn(f"Estado: JSON ignorado ({json_path.name})")
        except OSError as e:
            print_warn(f"Estado: Erro ao ler ({json_path.name})")

    # 3. Buscar os vídeos da URL atual
    current_videos_list = generate_fast_list_json(yt_dlp_cmd_list, cookie_args_list, channel_url, local_history_map=history_map)
    
    if not current_videos_list and not state_map:
        return None, [], detected_lang_cached, 0

    # 4. Integrar novos vídeos descobertos
    new_videos_count = 0
    imported_count = 0
    
    playlist_ctx = identifier if "list=" in channel_url else None

    # Determinar o identificador do canal de origem para tagging de vídeos
    source_channel_tag = None
    if "/@" in channel_url:
        m = re.search(r'/@([A-Za-z0-9_-]+)', channel_url)
        if m: source_channel_tag = f"@{m.group(1)}"
    elif target_uploader_id:
        source_channel_tag = target_uploader_id if target_uploader_id.startswith("@") else f"@{target_uploader_id}"
    elif channel_name_safe and channel_name_safe not in ("canal",):
        source_channel_tag = f"@{channel_name_safe}"

    # Agora que temos o source_channel_tag, reportamos quantos vídeos deste canal já temos no banco
    if state_map and source_channel_tag:
        db_channel_count = sum(1 for v in state_map.values() if v.get("source_channel") == source_channel_tag)
        if db_channel_count > 0:
            print_info(f"Base carregada: {BOLD}{db_channel_count}{RESET} vídeo(s) do canal {BOLD}{source_channel_tag}{RESET} preservados.")
        else:
            # Se for zero, talvez seja a primeira vez que estamos processando este canal nesta pasta consolidada
            # ou o uploader ainda não foi associado. Mostramos o total apenas se não houver tag.
            total_db = len(state_map)
            if total_db > 0:
                print_info(f"Base carregada: {BOLD}{total_db}{RESET} vídeos totais no banco. Nenhuma entrada prévia para {source_channel_tag}.")

    # Se ainda não temos os IDs de canal/uploader, tenta pegar do primeiro vídeo da lista atual
    if not target_channel_id and not target_uploader_id and current_videos_list:
        v0 = current_videos_list[0]
        v0_id = v0["video_id"]
        if v0_id in history_map:
            target_channel_id = history_map[v0_id].get("channel_id")
            target_uploader_id = history_map[v0_id].get("uploader_id")
            if not source_channel_tag and target_uploader_id:
                source_channel_tag = target_uploader_id if target_uploader_id.startswith("@") else f"@{target_uploader_id}"

    playlist_ctx = identifier if "list=" in channel_url else None

    # Adicionar vídeos da listagem atual do YouTube
    for vid_entry in current_videos_list:
        vid_id = vid_entry["video_id"]
        
        if vid_id in state_map:
            # Já existe: atualizar metadados se os atuais forem fracos
            existing = state_map[vid_id]
            if vid_entry.get("publish_date") and vid_entry["publish_date"] != "N/A":
                if not existing.get("publish_date") or existing["publish_date"] == "N/A":
                    existing["publish_date"] = vid_entry["publish_date"]
            if vid_entry.get("title") and vid_entry["title"] not in ("N/A", "", "Avulso"):
                if not existing.get("title") or existing["title"] in ("N/A", "", "Avulso"):
                    existing["title"] = vid_entry["title"]
            
            # Mesclar playlists
            if playlist_ctx:
                if "playlists" not in existing: existing["playlists"] = []
                if playlist_ctx not in existing["playlists"]:
                    existing["playlists"].append(playlist_ctx)
            
            # Associar ao canal de origem (se ainda não atribuído)
            if source_channel_tag and not existing.get("source_channel"):
                existing["source_channel"] = source_channel_tag
        else:
            # Novo vídeo
            if playlist_ctx: vid_entry["playlists"] = [playlist_ctx]
            if source_channel_tag: vid_entry["source_channel"] = source_channel_tag
            state_map[vid_id] = vid_entry
            new_videos_count += 1

    # 4. Importação Reversa: Vídeos que estão nos JSONs locais mas não apareceram na lista atual
    for vid_id, hist_entry in history_map.items():
        if vid_id in state_map: continue
        
        # Heurística de importação por canal
        is_same_channel = False
        if target_channel_id and hist_entry.get("channel_id") == target_channel_id: is_same_channel = True
        elif target_uploader_id and hist_entry.get("uploader_id") == target_uploader_id: is_same_channel = True
        elif channel_name_safe and channel_name_safe.lower() in str(hist_entry.get("uploader", "")).lower(): is_same_channel = True
        
        if is_same_channel:
            imported = hist_entry.copy()
            if source_channel_tag and not imported.get("source_channel"):
                imported["source_channel"] = source_channel_tag
            state_map[vid_id] = imported
            imported_count += 1

    # 5. Backfill: Associar vídeos órfãos a um canal via metadados do .info.json
    orphan_resolved = 0
    for vid_id, vid_entry in state_map.items():
        if vid_entry.get("source_channel"):
            continue  # Já tem canal atribuído
        
        # Tentar resolver via history_map (dados dos .info.json locais)
        if vid_id in history_map:
            hist = history_map[vid_id]
            uploader_id = hist.get("uploader_id")
            if uploader_id:
                tag = uploader_id if uploader_id.startswith("@") else f"@{uploader_id}"
                vid_entry["source_channel"] = tag
                orphan_resolved += 1
    
    if orphan_resolved > 0:
        print_info(f"Associados {BOLD}{orphan_resolved}{RESET} vídeos órfãos a canais via metadados locais.")

    # 6. Auto-Cura (Remoção de Fantasmas): Remove IDs corrompidos pelo bug antigo do Regex
    # Ex: se o nome da pasta é "braveco", exclui qualquer ID salvo como "braveco-3ih"
    corrupted_prefix = f"{folder_name}-"
    if any(k.startswith(corrupted_prefix) for k in state_map.keys()):
        cleaned_map = {k: v for k, v in state_map.items() if not k.startswith(corrupted_prefix)}
        ghosts_count = len(state_map) - len(cleaned_map)
        print_ok(f"Limpeza Automática: Removidos {BOLD}{ghosts_count}{RESET} IDs fantasmas do banco de dados (Bug 2.4.x).")
        state_map = cleaned_map

    final_results_list = list(state_map.values())
    
    if new_videos_count > 0:
        print_ok(f"Descobertos {BOLD}{new_videos_count}{RESET} novos vídeos na URL alvo.")
    if imported_count > 0:
        print_ok(f"Importados {BOLD}{imported_count}{RESET} vídeos do histórico local.")

    return json_path, final_results_list, detected_lang_cached, len(current_videos_list)

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
    Importa as dependências de ML (pysrt, sklearn, nltk) uma única vez por processo.
    O resultado é cacheado via @lru_cache, garantindo que o tempo de importação
    pesado só ocorra no primeiro download ou na primeira re-geração de MD.
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


@functools.lru_cache(maxsize=8)
def get_merged_stopwords(lang_code: str) -> frozenset:
    """
    Retorna o frozenset de stopwords (NLTK + marcadores orais) para o idioma.
    O cache via @lru_cache evita a re-geração do set e o re-acesso ao NLTK 
    durante o loop de múltiplos vídeos.
    """
    deps = _load_ml_deps()
    if deps is None:
        return frozenset()
    _, _, nltk, nltk_stopwords, _, _ = deps

    nltk_lang_map = {
        "pt": ("portuguese", ORAL_MARKERS_PT),
        "en": ("english",    ORAL_MARKERS_EN),
        "es": ("spanish",    ORAL_MARKERS_ES)
    }

    prefix = lang_code[:2] if lang_code else "pt"
    if prefix not in nltk_lang_map:
        prefix = "pt"

    nltk_lang_name, oral_markers = nltk_lang_map[prefix]

    try:
        base_stopwords = set(nltk_stopwords.words(nltk_lang_name))
    except LookupError:
        nltk.download('stopwords', quiet=True)
        base_stopwords = set(nltk_stopwords.words(nltk_lang_name))

    return frozenset(base_stopwords | oral_markers)

def srt_to_md(
    srt_path: Path,
    video_id: str,
    video_title: str,
    video_date: str = "Desconhecida",
    threshold: float = 0.3,
    indentation_prefix: str = "  "
) -> Path | None:
    """
    Converte um arquivo .srt em .md estruturado com segmentação por tópicos (TF-IDF).
    Depêndencias de ML são carregadas via `_load_ml_deps()` e cacheadas por processo,
    eliminando overhead de import nas chamadas subsequentes.
    """
    deps = _load_ml_deps()
    if deps is None:
        print_err("Faltam depêndencias de ML (pysrt, sklearn, nltk) para MD. Instale-as ou rode com --no-md", indentation_prefix)
        return None
    pysrt, np, _nltk, _nltk_sw, TfidfVectorizer, cosine_similarity = deps

    try:
        subs = pysrt.open(str(srt_path), encoding='utf-8')
        if not subs:
            return None

        # ── Fase 1: Janelas adaptativas (à duração total do vídeo) ─────────────
        total_duration_s = (
            subs[-1].end.hours * 3600 +
            subs[-1].end.minutes * 60 +
            subs[-1].end.seconds
        )
        # Escala: <30 min = 30s | 30-60 min = 60s | >60 min = 90s
        if total_duration_s < 1800:
            window_size_s = 30
        elif total_duration_s < 3600:
            window_size_s = 60
        else:
            window_size_s = 90

        # Threshold TF-IDF adaptativo: vídeos mais longos precisam de
        # threshold maior para gerar segmentos mais significativos
        if total_duration_s < 1800:
            adaptive_threshold = 0.25
        elif total_duration_s < 3600:
            adaptive_threshold = 0.35
        else:
            adaptive_threshold = 0.50


        def _strip_rollup(text: str, prev_text: str, overlap_ratio: float = 0.5) -> str:
            """
            Remove do início de 'text' a porção que já foi vista em 'prev_text'.
            Opera no nível de tokens (palavras) usando longest-common-prefix.
            Se mais de 'overlap_ratio' do texto novo é igual ao anterior, descarta.
            """
            prev_tokens = prev_text.split()
            cur_tokens  = text.split()
            if not prev_tokens or not cur_tokens:
                return text
            # Encontrar o maior prefixo comum
            overlap = 0
            for i, token in enumerate(cur_tokens):
                if i < len(prev_tokens) and token == prev_tokens[i]:
                    overlap += 1
                else:
                    break
            # Se mais de 50% do texto novo é overlap, descarta completamente
            if overlap / len(cur_tokens) > overlap_ratio:
                return ""
            return " ".join(cur_tokens[overlap:])

        windows = []
        current_window_subs = []
        start_time = subs[0].start
        prev_sub_text = ""

        for sub in subs:
            raw_text = re.sub(r"<[^>]+>", "", sub.text.replace('\n', ' ')).strip()
            clean_text = _strip_rollup(raw_text, prev_sub_text)
            if clean_text:
                prev_sub_text = raw_text
                # Substituir o texto do sub pelo texto sem roll-up para a janela
                sub._clean_text = clean_text
            else:
                sub._clean_text = ""
            current_window_subs.append(sub)
            if (sub.end - start_time).seconds > window_size_s:
                window_text = " ".join(
                    s._clean_text for s in current_window_subs if s._clean_text
                )
                if window_text:
                    windows.append({
                        'text': window_text,
                        'timestamp': str(current_window_subs[0].start).split(',')[0],
                        'subs': current_window_subs,
                    })
                current_window_subs = []
                start_time = sub.start

        if current_window_subs:
            window_text = " ".join(
                s._clean_text for s in current_window_subs if s._clean_text
            )
            if window_text:
                windows.append({
                    'text': window_text,
                    'timestamp': str(current_window_subs[0].start).split(',')[0],
                    'subs': current_window_subs,
                })

        if not windows:
            return None

        # Extrair stopwords fundidas cedo para uso em todo o processo
        lang_code = "pt" # Default
        lang_match = re.search(r"-([a-z]{2}(-[A-Z]{2})?)\.srt$", srt_path.name)
        if lang_match:
            lang_code = lang_match.group(1).lower()
        
        oral_stopwords = get_merged_stopwords(lang_code)

        # ── Fase 2: Detecção de mudanças de tópico via TF-IDF ──────────────
        vectorizer = TfidfVectorizer(stop_words=list(oral_stopwords), min_df=1)
        tfidf_matrix = vectorizer.fit_transform([w['text'] for w in windows])

        # Calcular similaridade entre janelas adjacentes
        similarities = []
        for i in range(1, len(windows)):
            sim = cosine_similarity(tfidf_matrix[i], tfidf_matrix[i - 1])[0][0]
            similarities.append((i, sim))

        # Segmentação por percentil: quebrar nos N% com menor similaridade
        # N é calibrado pela duração: vídeos longos recebem mais segmentos
        if total_duration_s < 1200:          # < 20 min → ~3 segmentos mín
            min_segments = 3
        elif total_duration_s < 2400:        # < 40 min → ~5 segmentos mín
            min_segments = 5
        elif total_duration_s < 3600:        # < 60 min → ~7 segmentos mín
            min_segments = 7
        else:                                # > 60 min → ~10 segmentos mín
            min_segments = 10

        # Quantos breaks precisamos (segmentos - 1 pois o índice 0 é sempre break)
        target_breaks = max(min_segments - 1, 1)

        topic_break_indices = {0}
        
        # ── Quebras por Threshold dinâmico (Similaridade < adaptive_threshold)
        if similarities:
            for i, sim in similarities:
                if sim < adaptive_threshold:
                    topic_break_indices.add(i)

            # ── Quebras Forçadas (Garantir densidade mínima se o threshold falhar)
            # Ordenar por similaridade crescente e pegar os target_breaks mais baixos para complementar
            sorted_by_sim = sorted(similarities, key=lambda x: x[1])
            forced_breaks = min(target_breaks, len(sorted_by_sim))
            for idx, _sim in sorted_by_sim[:forced_breaks]:
                topic_break_indices.add(idx)

        # ── Fase 3: Montar segmentos de tópico ────────────────────────────────
        segments = []  # list of (timestamp, label_idx, all_windows_in_segment)
        seg_windows = []
        for i, window in enumerate(windows):
            if i in topic_break_indices and seg_windows:
                segments.append((seg_windows[0]['timestamp'], len(segments) + 1, seg_windows))
                seg_windows = []
            seg_windows.append(window)
        if seg_windows:
            segments.append((seg_windows[0]['timestamp'], len(segments) + 1, seg_windows))

        # ── Fallback: Segmentação Uniforme por Tempo ───────────────────────────
        # Quando o TF-IDF produz segmentos insuficientes para a duração do vídeo
        # (conteúdo monotopíco, vocabulário limitado, ou voz pausada com janelas
        # de alta similaridade), redistribuímos as janelas em chunks uniformes.
        #
        # Condição: vídeo tem janelas suficientes para min_segments, mas o
        # TF-IDF não detectou quebras suficientes.
        if len(segments) < min_segments and len(windows) >= min_segments:
            chunk_size = max(1, len(windows) // min_segments)
            uniform_break_indices = set(range(0, len(windows), chunk_size))

            segments = []
            seg_windows = []
            for i, window in enumerate(windows):
                if i in uniform_break_indices and seg_windows:
                    segments.append((seg_windows[0]['timestamp'], len(segments) + 1, seg_windows))
                    seg_windows = []
                seg_windows.append(window)
            if seg_windows:
                segments.append((seg_windows[0]['timestamp'], len(segments) + 1, seg_windows))

        # ── Fase 4: Metadados de cabeçalho ────────────────────────────────────
        duration_str = str(subs[-1].end).split(',')[0]
        video_url = f"https://youtube.com/watch?v={video_id}"

        # Extrai o código de idioma do nome do arquivo (ex: canal-ID-pt.srt → "pt")
        _lang_hdr_match = re.search(r"-([a-z]{2}(?:-[A-Z]{2})?)\.srt$", srt_path.name)
        lang_hdr = _lang_hdr_match.group(1) if _lang_hdr_match else lang_code

        # Cabeçalho YAML frontmatter: lido por Obsidian, parsers de RAG e pelo Lexis
        # Permite que o NotebookLM indexe metadados estruturados por documento
        md_lines = [
            f"---\n",
            f"title: \"{video_title}\"\n",
            f"video_id: \"{video_id}\"\n",
            f"url: \"{video_url}\"\n",
            f"date: \"{video_date}\"\n",
            f"duration: \"{duration_str}\"\n",
            f"language: \"{lang_hdr}\"\n",
            f"source: \"Escriba v{VERSION}\"\n",
            f"---\n",
            "\n",
            f"# {video_title}\n",
            "\n",
            f"> **Data:** {video_date} · **Duração:** {duration_str} · **Idioma:** {lang_hdr}  \n",
            f"> 🔗 [{video_url}]({video_url})\n",
            "\n",
        ]

        # ── Fase 5: Sumário de tópicos (TOC) ──────────────────────────────────
        
        def _smart_ts(pysrt_time) -> str:
            """Usa HH:MM:SS só quando necessário (≥1h), senão MM:SS."""
            total_s = pysrt_time.hours * 3600 + pysrt_time.minutes * 60 + pysrt_time.seconds
            h, rem = divmod(total_s, 3600)
            m, s = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

        def _seg_duration(seg_wins: list) -> str:
            """Calcula duração aproximada de um segmento em minutos."""
            all_subs = [sub for w in seg_wins for sub in w['subs']]
            if len(all_subs) < 2:
                return "~1 min"
            total_s = (all_subs[-1].end - all_subs[0].start).seconds
            mins = max(1, round(total_s / 60))
            return f"~{mins} min"

        def _seg_keywords(seg_wins: list, tfidf_vec, tfidf_mat, win_indices: list[int], top_n: int = 3) -> str:
            """Extrai as top-N palavras-chave do segmento via TF-IDF e as formata como 'palavra · palavra'."""
            import numpy as np
            feature_names = tfidf_vec.get_feature_names_out()
            # Soma os scores TF-IDF de todas as janelas do segmento
            seg_vector = np.asarray(tfidf_mat[win_indices, :].sum(axis=0)).flatten()
            top_indices = seg_vector.argsort()[::-1]
            keywords = []
            for i in top_indices:
                word = feature_names[i]
                if len(word) > 2 and word.lower() not in oral_stopwords and word.isalpha():
                    keywords.append(word.lower())
                if len(keywords) >= top_n:
                    break
            return " · ".join(keywords) if keywords else ""

        def _clean_preview(seg_wins: list, max_words: int = 12) -> str:
            """Gera preview limpo do segmento completo, filtrando oral stopwords do início."""
            full_text = " ".join(w['text'] for w in seg_wins)
            words = [w for w in full_text.split() if w.lower() not in oral_stopwords and len(w) > 1]
            if not words:
                return ""
            preview = " ".join(words[:max_words])
            return f"{preview}..." if len(words) > max_words else preview

        # Mapear índices globais de janelas para cada segmento
        window_idx = 0
        seg_window_indices: list[list[int]] = []
        for _, _, seg_wins in segments:
            indices = list(range(window_idx, window_idx + len(seg_wins)))
            seg_window_indices.append(indices)
            window_idx += len(seg_wins)

        md_lines.append("### Segmentos de Tópicos (Timestamps)\n")
        topic_labels = []
        for (ts, idx, seg_wins), win_indices in zip(segments, seg_window_indices):
            # Timestamps dos subs reais do segmento
            first_sub = seg_wins[0]['subs'][0] if seg_wins[0]['subs'] else None
            ts_fmt = _smart_ts(first_sub.start) if first_sub else ts.split(',')[0]

            # Palavras-chave TF-IDF como label semântico
            keywords = _seg_keywords(seg_wins, vectorizer, tfidf_matrix, win_indices)
            if idx == 1:
                label = f"Introdução" + (f" — {keywords}" if keywords else "")
            else:
                label = keywords if keywords else f"Tópico {idx}"
            topic_labels.append(label)

            duration = _seg_duration(seg_wins)
            preview = _clean_preview(seg_wins)
            md_lines.append(f"* `[{ts_fmt}]` **{label}** *({duration})* — {preview}\n")

        md_lines.append("\n---\n")

        # ── Fase 6: Transcrição estruturada ───────────────────────────────────
        # Helpers locais
        _SENTENCE_END = re.compile(r'[.!?]["\']?\s*$')

        def _fmt_ts(pysrt_time) -> str:
            """Formata pysrt time como MM:SS para âncoras de parágrafo."""
            total_s = pysrt_time.hours * 3600 + pysrt_time.minutes * 60 + pysrt_time.seconds
            h, rem = divmod(total_s, 3600)
            m, s = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

        def _dedup_lines(lines: list[str]) -> list[str]:
            """Remove roll-up duplicatas: pula linha se começa com o token da linha anterior."""
            out = []
            for line in lines:
                if out:
                    prev_normalized = re.sub(r'\s+', ' ', out[-1]).lower()
                    cur_normalized  = re.sub(r'\s+', ' ', line).lower()
                    # Ignora se a linha atual é substring da anterior (roll-up parcial)
                    if cur_normalized in prev_normalized or prev_normalized in cur_normalized:
                        # Mantém a mais longa
                        if len(cur_normalized) > len(prev_normalized):
                            out[-1] = line
                        continue
                out.append(line)
            return out

        def _flush_paragraph(lines: list[str], para_ts: str, out: list[str]) -> None:
            """Normaliza e emite um parágrafo capturado, com âncora de tempo."""
            if not lines:
                return
            text = re.sub(r' {2,}', ' ', " ".join(lines)).strip()
            if text:
                first_char = text[0].upper()
                text = first_char + text[1:]
                out.append(f"[{para_ts}] {clean_ekklezia_terms(text)}\n\n")

        md_lines.append("### Transcrição Estruturada\n")

        for (ts, idx, seg_wins), label in zip(segments, topic_labels):
            md_lines.append(f"#### [{ts}] - Tópico: {label}\n")

            paragraph_lines: list[str] = []
            paragraph_start = None

            for window in seg_wins:
                for sub in window['subs']:
                    sub_text = getattr(sub, '_clean_text', None)
                    if sub_text is None:
                        sub_text = re.sub(r"<[^>]+>", "", sub.text.replace('\n', ' ')).strip()
                    sub_text = re.sub(r'\s+', ' ', sub_text)
                    if not sub_text:
                        continue

                    if paragraph_start is None:
                        paragraph_start = sub.start

                    paragraph_lines.append(sub_text)

                    # Quebra: ≥60s E fim de frase, ou ≥120s forçado
                    elapsed = (sub.end - paragraph_start).seconds
                    ends_sentence = bool(_SENTENCE_END.search(sub_text))

                    if elapsed >= 60 and ends_sentence:
                        deduped = _dedup_lines(paragraph_lines)
                        _flush_paragraph(deduped, _fmt_ts(paragraph_start), md_lines)
                        paragraph_lines = []
                        paragraph_start = None
                    elif elapsed >= 120:
                        deduped = _dedup_lines(paragraph_lines)
                        _flush_paragraph(deduped, _fmt_ts(paragraph_start), md_lines)
                        paragraph_lines = []
                        paragraph_start = None

            if paragraph_lines:
                deduped = _dedup_lines(paragraph_lines)
                _flush_paragraph(deduped, _fmt_ts(paragraph_start), md_lines)

        md_file_path = srt_path.with_suffix(".md")
        with open(md_file_path, "w", encoding="utf-8") as file_descriptor:
            file_descriptor.write("".join(md_lines))

        return md_file_path
    except Exception as e:
        print_warn(f"Falha ao processar segmentação MD: {e}", indentation_prefix)
        return None


def cleanup_temp_files(cwd_path: Path, channel_dir_name: str) -> int:
    """
    Remove arquivos temporários deixados pelo yt-dlp em caso de interrupção.
    
    Arquivos temporários:
    - *.part (download incompleto)
    - *.ytdl (cache do yt-dlp)
    - *.temp / *.tmp (escrita intermediária)
    - *.info.json (metadados não colhidos)
    
    Returns:
        Número de arquivos removidos.
    """
    patterns = ["*.part", "*.ytdl", "*.temp", "*.tmp"]
    cleaned = 0
    
    for pattern in patterns:
        for temp_file in cwd_path.glob(pattern):
            try:
                temp_file.unlink()
                cleaned += 1
            except Exception:
                pass
    
    for info_file in cwd_path.glob(f"{channel_dir_name}-*.info.json"):
        try:
            info_file.unlink()
            cleaned += 1
        except Exception:
            pass
    
    if cleaned > 0:
        print_info(f"{DIM}Cleanup: {cleaned} arquivo(s) temporário(s) removido(s){RESET}")
    return cleaned


def cleanup_subtitles(
    cwd_path: Path,
    channel_dir_name: str,
    video_id: str,
    video_title: str = "Vídeo Sem Título",
    convert_srt_to_md: bool = False,
    flag_keep_srt: bool = False,
    indentation_prefix: str = "  ",
) -> tuple[bool, Path | None]:
    """
    Limpa e organiza arquivos de legenda baixados.
    
    Por que precisa? O yt-dlp às vezes baixa múltiplas versões da mesma legenda:
    - video-id.pt.srt
    - video-id.pt-BR.srt  
    - video-id.en.srt
    
    Essa função:
    1. Detecta se há múltiplas legendas
    2. Mantém apenas a mais curta (geralmente a mais simples, ex: 'pt' vs 'pt-BR')
    3. Renomeia o arquivo para formato padronizado (canal-ID-pt.srt)
    
    Args:
        cwd_path: pasta onde estão os arquivos
        channel_dir_name: nome do canal (para naming)
        video_id: ID do vídeo
        convert_srt_to_md: se True, marca para converter depois
        flag_keep_srt: se True, mantém o .srt após converter para .md
    
    Returns:
        (sucesso: bool, caminho_do_arquivo: Path ou None)
    """
    subtitle_file_pattern = str(cwd_path / f"{channel_dir_name}-{video_id}*.srt")
    matching_subtitle_files_list = glob.glob(subtitle_file_pattern)

    if not matching_subtitle_files_list:
        return False, None

    if len(matching_subtitle_files_list) > 1:
        print_warn(f"{len(matching_subtitle_files_list)} variações de legenda detectadas — mantendo apenas uma.", indentation_prefix)
        shortest_subtitle_file_path = min(matching_subtitle_files_list, key=len)
        for iterable_file_path in matching_subtitle_files_list:
            if iterable_file_path != shortest_subtitle_file_path:
                os.unlink(iterable_file_path)
        target_subtitle_file_path = Path(shortest_subtitle_file_path)
    else:
        target_subtitle_file_path = Path(matching_subtitle_files_list[0])

    # Renomear: FOLDER-ID.lang.srt → FOLDER-ID-lang.srt
    base_prefix_string = f"{channel_dir_name}-{video_id}"
    language_suffix_extracted = target_subtitle_file_path.name[len(base_prefix_string):]

    if language_suffix_extracted.startswith(".") and target_subtitle_file_path.suffix == ".srt" and language_suffix_extracted.count(".") >= 2:
        new_language_suffix = "-" + language_suffix_extracted.lstrip(".")
        new_subtitle_filename_path = target_subtitle_file_path.parent / f"{base_prefix_string}{new_language_suffix}"
        target_subtitle_file_path.rename(new_subtitle_filename_path)
        target_subtitle_file_path = new_subtitle_filename_path

    # Conversão SRT → MD é delegada para o final do loop principal
    if convert_srt_to_md:
        print_info(f"SRT mantido temp: {DIM}{target_subtitle_file_path.name}{RESET}", indentation_prefix)
    else:
        print_info(f"Legenda salva: {DIM}{target_subtitle_file_path.name}{RESET}", indentation_prefix)

    return True, target_subtitle_file_path


# ─── Download Individual ──────────────────────────────────────────────────────




def harvest_and_delete_info_json(
    cwd_path: Path,
    channel_dir_name: str,
    video_id: str,
    video_dict: dict,
) -> bool:
    """
    Colhe (harvest) metadados do arquivo .info.json criado pelo yt-dlp.
    
    Quando o yt-dlp baixa um vídeo ou legenda, ele também cria um arquivo
    .info.json com metadados (título, data, duração, views, etc).
    
    Essa função:
    1. Lê esse arquivo .info.json
    2. Extrai os dados úteis para o nosso dicionário de vídeo
    3. Apaga o arquivo (não precisamos mais dele)
    
    "Harvest" = colher, coletar - termo comum em scraping.
    """
    info_json_path = cwd_path / f"{channel_dir_name}-{video_id}.info.json"
    if not info_json_path.exists():
        return False
    
    harvested_flag = False
    try:
        with open(info_json_path, encoding="utf-8") as f:
            meta = json.load(f)

        if not video_dict.get("title") or video_dict["title"] in ("N/A", "", "Avulso"):
            video_dict["title"] = meta.get("title") or video_dict.get("title", "N/A")
        if not video_dict.get("publish_date") or video_dict["publish_date"] in ("N/A", ""):
            raw_date = meta.get("upload_date", "")
            if raw_date and len(raw_date) == 8:
                video_dict["publish_date"] = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        if not video_dict.get("duration_s"):
            video_dict["duration_s"] = meta.get("duration")
        if not video_dict.get("channel"):
            video_dict["channel"] = meta.get("channel") or meta.get("uploader")
        if not video_dict.get("view_count"):
            video_dict["view_count"] = meta.get("view_count")
        
        harvested_flag = True
    except Exception as e:
        print_warn(f"Erro ao processar info.json de {video_id}: {e}")
    finally:
        try:
            if info_json_path.exists():
                info_json_path.unlink()
        except Exception as e:
            print_warn(f"Erro ao remover arquivo temporário {info_json_path.name}: {e}")
    return harvested_flag


# ─── Argparse ─────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    cli_parser = argparse.ArgumentParser(
        prog="escriba.py",
        description=(
            "Baixa legendas de todos os vídeos de um canal ou playlist do YouTube.\n"
            f"Versão: {VERSION}\n\n"
            "Substituições: Aplica regras de limpeza de termos (Ekklezia) usando arquivos\n"
            "'rules.txt' na pasta raiz do script e/ou na pasta atual (CWD).\n"
            "Formato: 'Termo Original, Termo Novo' ou 'Original=Novo'.\n\n"
            "Padrão: [NOME_DA_PASTA]-[ID_VIDEO]-[LANG].srt\n"
            "Vídeos sem legenda são registrados no JSON de estado e ignorados automaticamente."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cli_parser.add_argument("canal", nargs="*", default=None, help="Canal, playlist, vídeo ou URL (ex: @Canal, VIDEO_ID, URL de vídeo/playlist)")
    cli_parser.add_argument("-l", "--lang", default="", metavar="LANG",
                        help="Idioma das legendas (ex: pt, en). Padrão: idioma nativo do canal")
    cli_parser.add_argument("--audio-only", action="store_true",
                        help="Baixa APENAS o áudio do vídeo (formato nativo webm/opus)")
    cli_parser.add_argument("-a", "--mp3", action="store_true",
                        help="Converte o áudio para MP3 (ativa modo áudio automaticamente)")
    cli_parser.add_argument("-m", "--md", action="store_true", default=True,
                        help="Exporta legendas em .md segmentado por IA via TF-IDF (Padrão: Ativo)")
    cli_parser.add_argument("--no-md", action="store_false", dest="md",
                        help="Desativa a exportação em .md")
    cli_parser.add_argument("-n", "--notion", action="store_true",
                        help="Ativa o upload automático das páginas .md para o Notion")
    cli_parser.add_argument("--notion-db", default="fcc67a22-df9c-466c-8670-1d508e4bb35b",
                        help="ID do banco de dados do Notion (padrão: Controle de Leitura)")
    cli_parser.add_argument("--notion-file", default=None, metavar="PATH",
                        help="Envia um arquivo .md específico para o Notion e encerra o script")
    cli_parser.add_argument("--keep-srt", action="store_true",
                        help="Mantém o arquivo .srt no disco após a conversão para .md")
    cli_parser.add_argument("--audio-fallback", action="store_true",
                        help="Baixa o áudio quando a legenda não está disponível (padrão: apenas registra)")
    cli_parser.add_argument("-d", "--date", default="", metavar="DATA",
                        help="Data limite (posterior a). Formato: YYYYMMDD (ex: 20260101)")
    cli_parser.add_argument("-rc", "--refresh-cookies", action="store_true",
                        help="Força a extração de novos cookies do Chrome (apaga cookies.txt existente)")
    cli_parser.add_argument("--ignore-metadata", action="store_true",
                        help="Pula a auto-recuperação de datas e títulos ausentes no histórico JSON")
    cli_parser.add_argument("-f", "--fast", action="store_true",
                        help="Modo rápido: pula o tempo de espera entre downloads")
    cli_parser.add_argument("--regen-md", action="store_true",
                        help="Modo offline: regenera .md a partir de todos os .srt na pasta atual (não faz downloads)")
    cli_parser.add_argument("--force", action="store_true",
                        help="Combinado com --regen-md: sobrescreve .md existentes e força re-segmentação pelo algoritmo atual")
    cli_parser.add_argument("--upgrade-md", action="store_true",
                        help="Converte in-place o cabeçalho dos .md existentes para o novo formato (YAML + H1) sem reprocessar o TF-IDF")
    cli_parser.add_argument("--consolidate", action="store_true",
                        help="Gera ou atualiza os volumes unificados do NotebookLM para o canal atual")
    cli_parser.add_argument("--lexis-reset", action="store_true",
                        help="Apaga os volumes do NotebookLM do canal e reprocessa todos os arquivos do zero")
    cli_parser.add_argument("--migrate", action="store_true",
                        help="Adapta bancos de dados JSON antigos para a nova versão (youtube_channel)")
    cli_parser.add_argument("-v", "--version", action="version", version=f"Versão: {VERSION}")
    return cli_parser.parse_args()


# ─── Main ─────────────────────────────────────────────────────────────────────

# Regex para detectar YouTube video ID (exatamente 11 chars alfanuméricos + _ e -)
VIDEO_ID_REGEX_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_input_type(channel_input_string: str) -> tuple[str, str, str]:
    """
    Detecta o tipo de entrada que o usuário passou.
    
    O usuário pode passar várias coisas:
    - @canal → é um canal (handle)
    - https://youtube.com/@canal → canal (URL)
    - https://youtube.com/watch?v=VIDEOID → vídeo único
    - https://youtube.com/shorts/VIDEOID → shorts (vídeo único)
    - https://youtube.com/live/VIDEOID → live (vídeo único)
    - VIDEOID (11 chars) → vídeo curto
    - https://youtube.com/playlist?list=XYZ → playlist
    
    Returns:
        (URL normalizada, tipo, video_id se for vídeo)
    """
    # 1. Tentar detectar se é um VÍDEO (vários formatos de URL ou ID direto)
    # Padrões comuns de vídeo: watch?v=, youtu.be/, shorts/, live/, embed/, v/
    # Usamos re.search para encontrar o ID em qualquer lugar da string (importante para URLs sem aspas que podem ter 'lixo')
    video_regex = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/|v/)([A-Za-z0-9_-]{11})")
    video_match = video_regex.search(channel_input_string)
    
    if video_match:
        video_id = video_match.group(1)
        # Se contiver 'list=' e for uma URL, poderíamos tratar como playlist, 
        # mas no Escriba o comportamento padrão para links watch?v=...&list=... é focar no vídeo.
        # Se o usuário quiser a playlist, ele deve passar o link da playlist (detectado abaixo).
        
        # Reconstrói a URL se necessário
        if not channel_input_string.startswith("http"):
            channel_url_string = f"https://www.youtube.com/watch?v={video_id}"
        else:
            channel_url_string = channel_input_string
        return channel_url_string, "video", video_id

    # 2. Playlist (identificada por 'list=' ou pelo path '/playlist/')
    if "list=" in channel_input_string or "/playlist/" in channel_input_string:
        channel_url_string = channel_input_string if channel_input_string.startswith("http") else f"https://www.youtube.com/{channel_input_string.lstrip('/')}"
        return channel_url_string, "playlist", ""

    # 3. ID avulso de vídeo (exatamente 11 caracteres que batem no regex de ID)
    if VIDEO_ID_REGEX_PATTERN.match(channel_input_string):
        return f"https://www.youtube.com/watch?v={channel_input_string}", "video", channel_input_string

    # 4. Canal (padrão)
    channel_url_string = channel_input_string if channel_input_string.startswith("http") else f"https://www.youtube.com/{channel_input_string}"
    return channel_url_string, "channel", ""


def setup_session(cli_args: argparse.Namespace) -> SessionConfig:
    """
    Etapa 1: configura tudo que precisamos antes de começar.
    
    Essa função faz o "setup" inicial:
    1. Detecta se o usuário passou um canal ou não
    2. Se não passou, tenta descobrir a partir do JSON existente
    3. Normaliza a URL (converte @canal → https://youtube.com/@canal)
    4. Valida o ambiente (existe .venv?)
    5. Imprime o header bonitão
    
    Retorna um objeto SessionConfig com tudo que as outras funções precisam.
    """
    cwd_path = Path.cwd()
    channel_dir_name = cwd_path.name
    script_dir_path, yt_dlp_cmd_list = setup_environment()
    
    # Auto-detecção de canal pelo state list quando não informado
    latest_json_path = None
    if not cli_args.canal:
        latest_json_path = get_latest_json_path(cwd_path)
        if not latest_json_path.exists():
            print_err("Parâmetro 'canal' não fornecido e nenhum banco de dados (escriba_*.json) encontrado.")
            print_info(f"{BOLD}Como usar:{RESET}")
            print_info(f"  python3 escriba.py {BCYAN}@Canal{RESET}")
            print_info(f"  python3 escriba.py {BCYAN}https://www.youtube.com/playlist?list=...{RESET}")
            print_info(f"  python3 escriba.py {BCYAN}VIDEO_ID{RESET}")
            sys.exit(1)
            
        try:
            with open(latest_json_path, "r", encoding="utf-8") as file_descriptor:
                json_data = json.load(file_descriptor)
                
            if isinstance(json_data, dict):
                # Prioridade 1: Nova lista de canais
                if "youtube_channels" in json_data and isinstance(json_data["youtube_channels"], list) and json_data["youtube_channels"]:
                    cli_args.canal = json_data["youtube_channels"][0] # Padrão: primeiro da lista
                # Prioridade 2: Campos singulares legacy
                elif "youtube_channel" in json_data:
                    cli_args.canal = json_data["youtube_channel"]
                elif "channel" in json_data:
                    cli_args.canal = json_data["channel"]
                elif "channel_context" in json_data:
                    cli_args.canal = json_data["channel_context"]
            
            if not cli_args.canal:
                match = re.search(r"(?:escriba_|lista_)(.+)\.json", latest_json_path.name)
                if match:
                    cli_args.canal = f"@{match.group(1)}"
                else:
                    print_err("Não foi possível inferir o canal a partir do JSON.")
                    sys.exit(1)
        except Exception as e:
            print_err(f"Erro ao ler JSON para auto-detecção: {e}")
            sys.exit(1)

    # Classificar entrada
    channel_input_string = cli_args.canal
    channel_url_string, input_type_string, single_video_id = parse_input_type(channel_input_string)

    # Modo de operação para o header
    md_label = "+MD" if cli_args.md else ""
    if cli_args.mp3:
        cli_args.audio_only = True
        execution_mode_label = "Modo MP3"
    else:
        execution_mode_label = "Áudio" if cli_args.audio_only else f"Legendas/SRT{md_label} ({cli_args.lang or 'auto'})"
    if cli_args.date:
        execution_mode_label += f"  ·  a partir de {cli_args.date}"
    if cli_args.fast:
        execution_mode_label += "  ·  rápido"
    
    print_info(f"Canal alvo: {BOLD}{channel_input_string}{RESET}")
    print_info(f"Modo: {execution_mode_label}")

    # Mensagem de auto-detecção do canal (depois do header)
    if latest_json_path:
        print_info(f"Canal detectado automaticamente a partir de {latest_json_path.name}")
    return SessionConfig(
        cwd_path=cwd_path,
        channel_dir_name=channel_dir_name,
        script_dir_path=script_dir_path,
        yt_dlp_cmd_list=yt_dlp_cmd_list,
        channel_input_url_or_handle=channel_input_string,
        channel_url=channel_url_string,
        mp3=cli_args.mp3
    )

def init_auth_and_language(
    session_config: SessionConfig, language_argument_string: str, force_refresh_cookies_flag: bool
) -> tuple[list[str], str]:
    """
    Etapa 2: configura autenticação e idioma.
    
    Duas coisas importantes aqui:
    
    1. Cookies: necessários para acessar conteúdo restrito do YouTube
       - Primeiro tenta usar cache existente
       - Se não tem, extrai do Chrome
       - Filtra para manter só cookies do YouTube
    
    2. Idioma: qual legenda baixar?
       - Se usuário passou --lang, usa esse
       - Se não, detecta automaticamente a partir do canal
       - Salva no cache para não precisar detectar de novo
    
    Returns:
        (cookie_args para yt-dlp, idioma a usar)
    """
    print_section("Autenticação")
    cookie_args_list = configure_cookies(session_config.cwd_path, session_config.script_dir_path, force_refresh_cookies_flag)

    print_section("Idioma")
    # Tenta obter cache antes de detectar
    _, _, cached_lang, _ = load_or_create_channel_state(
        session_config.cwd_path, session_config.yt_dlp_cmd_list, cookie_args_list, session_config.channel_url,
        only_peek_lang=True
    )

    language_opt_string = language_argument_string if language_argument_string else detect_language(
        session_config.yt_dlp_cmd_list, cookie_args_list, session_config.channel_url, cached_lang
    )
    if language_argument_string:
        print_ok(f"Idioma definido pelo usuário: {BOLD}{language_opt_string}{RESET}")

    # Se estamos no modo de extração de browser original e 'detect_language' foi pulado,
    # precisamos forçar uma extração leve do yt-dlp agora para gerar o cookies.txt e filtrá-lo.
    if "--cookies-from-browser" in cookie_args_list:
        cookies_txt_path = session_config.cwd_path / "cookies.txt"
        
        # Só executa warm-up se o arquivo ainda não existe (pode ter sido criado por 'detect_language' ou 'load_state')
        if not cookies_txt_path.is_file():
            print_warn("Executando warm-up para extrair cookies do Chrome silenciosamente...")
            subprocess.run(
                session_config.yt_dlp_cmd_list + cookie_args_list + ["--dump-json", "--playlist-items", "0", session_config.channel_url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        
        # Filtrar o lixo exportado
        if cookies_txt_path.is_file():
            filter_youtube_cookies(cookies_txt_path)
            # Reconfigurar para usar apenas o TXT lido do cache a partir de agora (modo silencioso)
            cookie_args_list = configure_cookies(session_config.cwd_path, session_config.script_dir_path, False, silent=True)
            print_info("Cookies filtrados limitados ao YouTube (trackers removidos).")
        else:
            print_err("Falha na extração de cookies do navegador.")

    return cookie_args_list, language_opt_string


def process_videos(
    session_config: SessionConfig,
    cookie_args_list: list[str],
    language_opt_string: str,
    cli_args: argparse.Namespace,
    channel_filter: str | None = None,
    is_first_channel: bool = True,
) -> tuple[int, int, int, int, int, bool]:
    """
    Etapa 3: o coração do script - baixa as legendas.
    
    Esse é o loop principal que:
    1. Carrega a lista de vídeos do banco JSON
    2. Para cada vídeo:
       - Já foi baixado? → pula
       - Já marcou "sem legenda"? → pula  
       - Baixa a legenda com yt-dlp
       - Colhe metadados do .info.json
       - Limpa arquivos de legenda
       - Converte para MD (se habilitado)
       - Salva progresso no JSON (a cada 5 vídeos)
    3. No final, converte todas as legendas pendentes para MD
    
    Retorna contadores para o resumo final:
    (baixados, pulados, erros, fila, canal_total, interrompido)
    """
    # Detectar se é vídeo avulso
    _, input_type_string, single_video_id = parse_input_type(session_config.channel_input_url_or_handle)
    
    print_section("Listagem de Vídeos e Tracking State")
    json_state_path, full_state_list, detected_lang_cached, channel_total = load_or_create_channel_state(
        session_config.cwd_path, session_config.yt_dlp_cmd_list, cookie_args_list, session_config.channel_url
    )
    
    # Persistência imediata: se novos vídeos foram descobertos, salva logo no início
    if json_state_path:
        save_channel_state_json(json_state_path, full_state_list, detected_language=detected_lang_cached, youtube_channel=session_config.channel_url)
    
    # Se descobrimos um uploader/canal novo agora (ex: via playlist), salva no JSON
    if session_config.discovered_uploader_id:
        save_channel_state_json(
            json_state_path, 
            full_state_list, 
            channel_handle=session_config.discovered_uploader_id,
            youtube_channel=session_config.channel_url
        )
    
    # Garantir que o idioma detectado esteja no arquivo caso tenha sido descoberto agora
    if language_opt_string and language_opt_string != detected_lang_cached:
        save_channel_state_json(
            json_state_path, 
            full_state_list, 
            detected_language=language_opt_string,
            youtube_channel=session_config.channel_url
        )
    
    # Se o modo for vídeo único, filtramos a lista carregada para focar apenas nele
    if input_type_string == "video" and single_video_id:
        is_single_video_mode = True
        working_state_list = [v for v in full_state_list if v["video_id"] == single_video_id]
        
        # Se não estiver no canal (vídeo novo), adiciona na mão para processar
        if not working_state_list:
            new_entry = {
                "video_id": single_video_id, 
                "publish_date": "N/A", 
                "title": "Avulso", 
                "subtitle_downloaded": False,
                "info_downloaded": False,
                "has_no_subtitle": False,
            }
            full_state_list.append(new_entry)
            working_state_list = [new_entry]
        
        print_info(f"Foco em vídeo único: {BOLD}{single_video_id}{RESET}")
    else:
        is_single_video_mode = False
        working_state_list = filter_state_list(full_state_list, cli_args.date)

        # Filtro por canal de origem: em modo multi-canal, processar apenas vídeos deste canal
        if channel_filter:
            # Normalizar o filtro para handle (@Canal)
            _filter_handle = channel_filter
            if "/@" in _filter_handle:
                m = re.search(r'/@([A-Za-z0-9_-]+)', _filter_handle)
                if m: _filter_handle = f"@{m.group(1)}"
            elif not _filter_handle.startswith("@"):
                _filter_handle = f"@{_filter_handle}"

            filtered_by_channel = []
            orphan_videos = []
            for v in working_state_list:
                sc = v.get("source_channel", "")
                if sc == _filter_handle:
                    filtered_by_channel.append(v)
                elif not sc:
                    orphan_videos.append(v)
                # else: vídeo pertence a outro canal → ignora nesta iteração

            # Órfãos só são processados no primeiro canal da lista
            if is_first_channel and orphan_videos:
                print_info(f"Incluindo {BOLD}{len(orphan_videos)}{RESET} vídeo(s) sem canal associado (órfãos) nesta passada.")
                filtered_by_channel.extend(orphan_videos)

            working_state_list = filtered_by_channel
            print_info(f"Canal filtrado: {BOLD}{_filter_handle}{RESET} → {len(working_state_list)} vídeo(s) para processar.")

    if not working_state_list:
        if channel_filter:
            print_info(f"Nenhum vídeo pendente para este canal. {DIM}Avançando...{RESET}")
            return 0, 0, 0, 0, channel_total, False
        print_err("Nenhum vídeo retornado pela listagem ou filtro.")
        sys.exit(1)

    info_downloaded_count = sum(1 for v in working_state_list if v.get("info_downloaded"))
    no_subtitle_count = sum(1 for v in working_state_list if v.get("has_no_subtitle"))
    print_info(f"Histórico: {info_downloaded_count} metadados no JSON · {no_subtitle_count} sem legenda")

    # Contadores de sessão
    downloaded_videos_count = 0
    skipped_videos_count = 0
    error_videos_count = 0
    total_videos_count = len(working_state_list)
    sub_indent_space = " " * (8 + 2 * len(str(total_videos_count)))

    print_section(f"Download  {DIM}(0/{total_videos_count}){RESET}")

    # ─── Loop principal ────────────────────────────────────────────────────────
    # O processamento é incremental. Para cada vídeo, verificamos se já está no JSON.
    # Novas entradas disparam persistência periódica (_dirty counter) para poupar I/O.
    was_interrupted = False

    # ─── Flush periódico do JSON ─────────────────────────────────────────────
    FLUSH_EVERY = 5  # salva a cada N mutações de estado
    _dirty = 0       # contador de mudanças pendentes

    def _flush(force: bool = False) -> None:
        """Salva o JSON se o contador atingiu o limite ou se force=True."""
        nonlocal _dirty
        if force or _dirty >= FLUSH_EVERY:
            save_channel_state_json(
                json_state_path, 
                full_state_list, 
                detected_language=language_opt_string,
                youtube_channel=session_config.channel_url,
                channel_handle=session_config.discovered_uploader_id
            )
            _dirty = 0

    pending_md_conversions = []

    try:
        for loop_iteration_idx, video_dict in enumerate(working_state_list, start=1):
            video_id = video_dict["video_id"]
            indentation_prefix = f"  {BLUE}[{loop_iteration_idx:>{len(str(total_videos_count))}}/{total_videos_count}]{RESET}"

            # 1. Verificação instantânea no JSON de estado do canal
            if video_dict.get("subtitle_downloaded") and not cli_args.audio_only:
                skipped_videos_count += 1
                print_skip(f"{video_id}  {DIM}legenda já registrada no state JSON{RESET}", indentation_prefix)
                continue

            if video_dict.get("has_no_subtitle") and not cli_args.audio_only:
                skipped_videos_count += 1
                print_skip(f"{video_id}  {DIM}marcado como sem legenda no JSON{RESET}", indentation_prefix)
                continue

            # Verificação por arquivos em disco (caso o histórico esteja dessincronizado)
            is_srt_file_present = bool(glob.glob(str(session_config.cwd_path / f"{session_config.channel_dir_name}-{video_id}*.srt")))
            is_md_file_present  = bool(glob.glob(str(session_config.cwd_path / f"{session_config.channel_dir_name}-{video_id}*.md")))

            if is_srt_file_present or is_md_file_present:
                # Se existe .srt mas NÃO existe .md, e MD está ativo → agenda conversão
                if is_srt_file_present and not is_md_file_present and cli_args.md:
                    srt_glob = glob.glob(str(session_config.cwd_path / f"{session_config.channel_dir_name}-{video_id}*.srt"))
                    if srt_glob:
                        srt_path_found = Path(srt_glob[0])
                        pending_md_conversions.append((
                            srt_path_found,
                            video_id,
                            video_dict.get("title", "Sem Título"),
                            video_dict.get("publish_date", "Desconhecida")
                        ))
                        print_skip(f"{video_id}  {DIM}.srt encontrado → agendado para conversão MD{RESET}", indentation_prefix)
                else:
                    print_skip(f"{video_id}  {DIM}arquivos já presentes no disco{RESET}", indentation_prefix)
                skipped_videos_count += 1
                video_dict["info_downloaded"] = True
                video_dict["subtitle_downloaded"] = True
                _dirty += 1
                _flush()
                continue

            execution_mode_string = "ÁUDIO" if cli_args.audio_only else f"legenda/{language_opt_string}"
            print_dl(f"{video_id}{RESET}  {DIM}{execution_mode_string}{RESET}", indentation_prefix)

            download_exit_code = download_video(
                yt_dlp_cmd_list=session_config.yt_dlp_cmd_list,
                cookie_args_list=cookie_args_list,
                video_id=video_id,
                language_opt_string=language_opt_string,
                channel_dir_name=session_config.channel_dir_name,
                audio_only_flag=cli_args.audio_only,
                mp3_flag=session_config.mp3,
            )

            # --- Harvest: Absorver metadados independente do exit code (ex: sem legenda gera erro mas tem info) ---
            info_harvested = harvest_and_delete_info_json(
                session_config.cwd_path, session_config.channel_dir_name,
                video_id, video_dict
            )
            
            # --- Auto-healing: Backup caso o harvest tenha falhado ou retornado metadados vazios ---
            if not cli_args.ignore_metadata:
                if video_dict.get("title", "N/A") == "N/A" or video_dict.get("publish_date", "N/A") == "N/A":
                    # Só tenta auto-healing se o harvest falhou ou se os dados ainda são N/A
                    print_info(f"{video_id}  {DIM}recuperando metadados ausentes (título/data)...{RESET}", indentation_prefix)
                    recovered_meta_dict = get_video_exact_date(video_id, session_config.yt_dlp_cmd_list, cookie_args_list)
                    meta_updated_flag = False
                    
                    if recovered_meta_dict["title"] != "N/A" and video_dict.get("title", "N/A") == "N/A":
                        video_dict["title"] = recovered_meta_dict["title"]
                        meta_updated_flag = True
                    if recovered_meta_dict["date"] != "N/A" and video_dict.get("publish_date", "N/A") == "N/A":
                        video_dict["publish_date"] = recovered_meta_dict["date"]
                        meta_updated_flag = True
                    
                    if meta_updated_flag:
                        info_harvested = True
                        print_ok(f"metadados atualizados via auto-healing", sub_indent_space)

            if info_harvested:
                video_dict["info_downloaded"] = True
                _dirty += 1
                _flush() # Garante persistência imediata de metadados básicos

            if download_exit_code == 0:
                has_downloaded_subtitle_flag = True
                srt_path_ret = None
                if not cli_args.audio_only:
                    has_downloaded_subtitle_flag, srt_path_ret = cleanup_subtitles(
                        session_config.cwd_path, session_config.channel_dir_name, video_id,
                        video_title=video_dict.get("title", "Sem Título"),
                        convert_srt_to_md=cli_args.md,
                        flag_keep_srt=cli_args.keep_srt,
                        indentation_prefix=sub_indent_space
                    )
                    
                    if has_downloaded_subtitle_flag and srt_path_ret and cli_args.md:
                        pending_md_conversions.append((
                            srt_path_ret, 
                            video_id, 
                            video_dict.get("title", "Sem Título"),
                            video_dict.get("publish_date", "Desconhecida")
                        ))

                if not has_downloaded_subtitle_flag:
                    if cli_args.audio_fallback:
                        print_warn(f"sem legenda — baixando áudio fallback", sub_indent_space)
                        
                        fallback_audios_dir_path = session_config.cwd_path / "audios"
                        fallback_audios_dir_path.mkdir(exist_ok=True)
                        
                        audio_fallback_exit_code = download_video(
                            yt_dlp_cmd_list=session_config.yt_dlp_cmd_list,
                            cookie_args_list=cookie_args_list,
                            video_id=video_id,
                            language_opt_string=language_opt_string,
                            channel_dir_name=session_config.channel_dir_name,
                            audio_only_flag=True,
                            output_dir_path=fallback_audios_dir_path,
                            mp3_flag=session_config.mp3,
                        )
                        
                        if audio_fallback_exit_code == 0:
                            print_ok(f"áudio fallback salvo em audios/", sub_indent_space)
                        else:
                            print_err(f"falha ao baixar áudio fallback", sub_indent_space)
                    else:
                        print_warn(f"sem legenda — pulando", sub_indent_space)

                    skipped_videos_count += 1

                    # Só marca como "sem legenda" se o vídeo tem mais de 7 dias
                    is_old_enough_flag = True  # fallback: marca se não conseguir ler a data
                    publish_date_string = video_dict.get("publish_date", "N/A")
                    if publish_date_string != "N/A":
                        try:
                            publish_datetime_object = datetime.strptime(publish_date_string, "%Y-%m-%d")
                            days_ago_count = (datetime.now() - publish_datetime_object).days
                            is_old_enough_flag = days_ago_count > 7
                        except ValueError:
                            pass

                    if is_old_enough_flag:
                        video_dict["has_no_subtitle"] = True
                        _dirty += 1
                        _flush()  # marca como sem legenda — flush imediato
                    else:
                        print_info(f"vídeo recente ({days_ago_count}d) — não marcado como sem legenda", sub_indent_space)

                    if not cli_args.fast and loop_iteration_idx < total_videos_count:
                        print_countdown(1, "Aguardando", sub_indent_space)
                else:
                    downloaded_videos_count += 1
                    
                    # Marcar o estado JSON se baixamos a legenda
                    if not cli_args.audio_only and has_downloaded_subtitle_flag:
                        video_dict["subtitle_downloaded"] = True
                        _dirty += 1
                        _flush()
                        
                    if not cli_args.fast and loop_iteration_idx < total_videos_count:
                        sleep_duration_seconds = random.randint(1, 5)
                        print_countdown(sleep_duration_seconds, "Aguardando", sub_indent_space)
                    else:
                        print_ok("ok", sub_indent_space)
            else:
                error_videos_count += 1
                print_err(f"falha (código {download_exit_code}) — possível bloqueio 429", sub_indent_space)
                if not cli_args.fast:
                    print_countdown(300, "Resfriamento", sub_indent_space)
                print_info("Retomando...", sub_indent_space)

        # Flush final após o loop para garantir persistência de todos os status da sessão
        _flush(force=True)

    except KeyboardInterrupt:
        print()
        print_warn(f"Processamento interrompido. {DIM}Gerando resumo parcial...{RESET}")
        was_interrupted = True
        cleanup_temp_files(session_config.cwd_path, session_config.channel_dir_name)
        _flush(force=True)  # garante que nenhuma mutação pendente seja perdida

    # ---------- Processamento Deferido de MD --------------
    if pending_md_conversions:
        total_md = len(pending_md_conversions)
        print()
        print_info(f"Fase 4: Clusterização de IA (TF-IDF) — {BOLD}{total_md} arquivo(s) .md a processar{RESET}")
        for idx, (srt_path, vid_id, vid_title, vid_date) in enumerate(pending_md_conversions, start=1):
            idx_prefix = f"{BLUE}[{idx:>{len(str(total_md))}}/{total_md}]{RESET}"
            if not srt_path.exists():
                continue
            
            print_dl(f"{idx_prefix} {vid_id}{RESET}  {DIM}gerando .md{RESET}", "  ")
            md_path = srt_to_md(srt_path, vid_id, vid_title, video_date=vid_date, threshold=0.3, indentation_prefix="    ")
            
            # Notion upload: APENAS em modo de vídeo único (user request)
            if md_path and cli_args.notion:
                if is_single_video_mode:
                    notion_token = os.getenv("NOTION_TOKEN")
                    if notion_token:
                        print_dl(f"{vid_id}{RESET}  {DIM}enviando p/ Notion{RESET}", "    ")
                        exporter = NotionExporter(notion_token, cli_args.notion_db)
                        with open(md_path, "r", encoding="utf-8") as f:
                            md_content = f.read()
                        blocks = exporter.md_to_blocks(md_content)
                        video_url = f"https://www.youtube.com/watch?v={vid_id}"
                        page_id = exporter.create_page(vid_title, blocks, video_url=video_url)
                        if page_id:
                            print_ok(f"Página Notion criada: {DIM}{page_id}{RESET}", "      ")
                    else:
                        print_warn("NOTION_TOKEN não encontrado para upload automático.", "      ")
                else:
                    print_info(f"Upload para Notion {DIM}ignorado{RESET} (modo canal/playlist ativo).", "    ")
            
            elif md_path:
                print_ok(f"MD clusterizado salvo: {DIM}{md_path.name}{RESET}", "    ")
            
            if not cli_args.keep_srt and srt_path.exists():
                srt_path.unlink()

    return downloaded_videos_count, skipped_videos_count, error_videos_count, total_videos_count, channel_total, was_interrupted


def print_summary(downloaded_videos_count: int, skipped_videos_count: int, error_videos_count: int, total_videos_count: int, channel_total_count: int = 0) -> None:
    """Etapa 4: imprime o resumo final da sessão."""
    print()
    print(f"  {BOLD}{BWHITE}Sessão concluída{RESET}")
    print(f"  {ICON_OK}  Baixados   : {BGREEN}{downloaded_videos_count}{RESET}")
    print(f"  {ICON_SKIP}  Pulados    : {DIM}{skipped_videos_count}{RESET}")
    if error_videos_count:
        print(f"  {ICON_ERR}  Erros      : {BRED}{error_videos_count}{RESET}")
    
    if channel_total_count > 0:
        print(f"  {ICON_INFO}  No canal   : {channel_total_count}")
    
    print(f"  {ICON_INFO}  Total fila : {total_videos_count}")
    print()


def regen_md_from_srt_files(force: bool = False) -> None:
    """Modo offline: varre archive/ e depois a pasta atual buscando .srt e regenera .md via TF-IDF.

    Args:
        force: Se True, sobrescreve .md existentes (permite re-segmentar arquivos já gerados).
    """
    cwd_path = Path.cwd()
    archive_path = cwd_path / "archive"

    # Montar lista de (srt_path, origem_label) varrendo archive/ primeiro, depois cwd
    scan_dirs = []
    if archive_path.is_dir():
        scan_dirs.append((archive_path, "archive/"))
    scan_dirs.append((cwd_path, "./"))

    srt_files_list: list[tuple[Path, str]] = []
    for scan_dir, label in scan_dirs:
        for srt in sorted(scan_dir.glob("*.srt")):
            srt_files_list.append((srt, label))

    if not srt_files_list:
        print_err("Nenhum arquivo .srt encontrado em archive/ ou na pasta atual.")
        sys.exit(1)

    # Carregar JSON de estado uma única vez
    json_state_path = get_latest_json_path(cwd_path)
    videos_lookup_dict: dict[str, str] = {}
    if json_state_path and json_state_path.is_file():
        try:
            with open(json_state_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
                videos_list = json_data.get("videos", json_data) if isinstance(json_data, dict) else json_data
                for v in videos_list:
                    vid = v.get("video_id", "")
                    if vid:
                        videos_lookup_dict[vid] = v.get("title", "")
        except Exception:
            pass

    print_info(f"Canal alvo: {BOLD}{cwd_path.name}{RESET}")
    print_info(f"Modo: Regeneração MD offline")

    total_count = len(srt_files_list)
    converted_count = 0
    skipped_count = 0
    current_label = ""

    print_info(f"{BOLD}Total de {total_count} arquivo(s) .srt para processar...{RESET}")

    for idx, (srt_path, origin_label) in enumerate(srt_files_list, start=1):
        # Imprimir seção ao trocar de diretório
        if origin_label != current_label:
            current_label = origin_label
            section_files = sum(1 for _, l in srt_files_list if l == origin_label)
            print_section(f"{origin_label}  {DIM}({section_files} arquivos .srt){RESET}")

        indentation_prefix = f"  {BLUE}[{idx:>{len(str(total_count))}}/{total_count}]{RESET}"

        # Extrair video_id do nome: <prefixo>-<VIDEO_ID>.<lang>.srt
        stem_parts = srt_path.stem
        video_id_match = re.search(r"([A-Za-z0-9_-]{11})", stem_parts)
        video_id = video_id_match.group(1) if video_id_match else srt_path.stem

        # Título via lookup
        video_title = videos_lookup_dict.get(video_id, srt_path.stem)

        # Verificar se .md já existe
        md_path = srt_path.with_suffix(".md")
        if md_path.exists() and not force:
            print_skip(f"{srt_path.name}  {DIM}.md já existe — pulando{RESET}", indentation_prefix)
            skipped_count += 1
            continue
        elif md_path.exists() and force:
            print_dl(f"{srt_path.name}{RESET}  {DIM}re-segmentando (--force){RESET}", indentation_prefix)

        print_dl(f"{srt_path.name}{RESET}  {DIM}gerando .md{RESET}", indentation_prefix)
        result_path = srt_to_md(srt_path, video_id, video_title, threshold=0.3, indentation_prefix="      ")

        if result_path:
            print_ok(f"salvo: {DIM}{result_path.name}{RESET}", "      ")
            converted_count += 1
        else:
            print_warn(f"falha ou vazio", "      ")

    # Resumo
    print()
    print(f"  {BOLD}{BWHITE}Regeneração concluída{RESET}")
    print(f"  {ICON_OK}  Convertidos : {BGREEN}{converted_count}{RESET}")
    print(f"  {ICON_SKIP}  Pulados     : {DIM}{skipped_count}{RESET}")
    print(f"  {ICON_INFO}  Total       : {total_count}")
    print()


# ─── Upgrade de Cabeçalho MD ─────────────────────────────────────────────────

def upgrade_md_headers() -> None:
    """
    Converte in-place o cabeçalho dos .md gerados por versões anteriores do Escriba
    para o novo formato com YAML frontmatter + H1 + blockquote de metadados.

    O corpo do arquivo (### Segmentos de Tópicos, ### Transcrição Estruturada)
    NÃO é alterado — apenas as primeiras linhas do cabeçalho são reescritas.
    Isso é equivalente a reprocessar sem recalcular o TF-IDF.

    Formato antigo detectado:
        ## Título do Vídeo
        **URL:** https://youtube.com/watch?v=...
        **Data:** YYYY-MM-DD
        **Duração:** HH:MM:SS

    Formato novo gerado:
        ---
        title: "Título do Vídeo"
        video_id: "xXxXxXxXxXx"
        url: "https://..."
        date: "YYYY-MM-DD"
        duration: "HH:MM:SS"
        language: "pt"
        source: "Escriba vX.Y.Z"
        ---

        # Título do Vídeo

        > **Data:** YYYY-MM-DD · **Duração:** HH:MM:SS · **Idioma:** pt
        > 🔗 [https://...](https://...)
    """
    cwd_path = Path.cwd()
    archive_path = cwd_path / "archive"

    # Padrão de cabeçalho antigo: ## Título seguido de pelo menos uma linha **CAMPO:**
    _OLD_HEADER_RE = re.compile(
        r'^##\s+(?P<title>.+?)\n'
        r'(?:\*\*URL:\*\*\s*(?P<url>\S+?)\s*\n)?'
        r'(?:\*\*Data:\*\*\s*(?P<date>\S+?)\s*\n)?'
        r'(?:\*\*Duração:\*\*\s*(?P<duration>\S+?)\s*\n)?',
        re.MULTILINE,
    )

    # Padrão de arquivo já atualizado (YAML frontmatter)
    _NEW_HEADER_MARKER = re.compile(r'^---\n', re.MULTILINE)

    # Varre cwd e archive/
    scan_dirs: list[tuple[Path, str]] = [(cwd_path, "./")]
    if archive_path.is_dir():
        scan_dirs.append((archive_path, "archive/"))

    all_md_files: list[tuple[Path, str]] = []
    for scan_dir, label in scan_dirs:
        for md in sorted(scan_dir.glob("*.md")):
            all_md_files.append((md, label))

    if not all_md_files:
        print_err("Nenhum arquivo .md encontrado na pasta atual ou em archive/.")
        sys.exit(1)

    print_info(f"Modo: Upgrade de Cabeçalho MD")
    print_info(f"{BOLD}{len(all_md_files)} arquivo(s) .md encontrado(s){RESET}")
    print()

    upgraded_count = 0
    skipped_count  = 0
    already_new    = 0
    error_count    = 0
    current_label  = ""

    for idx, (md_path, origin_label) in enumerate(all_md_files, start=1):
        idx_prefix = f"{BLUE}[{idx:>{len(str(len(all_md_files)))}}/{len(all_md_files)}]{RESET}"

        if origin_label != current_label:
            current_label = origin_label
            section_files = sum(1 for _, l in all_md_files if l == origin_label)
            print_section(f"{origin_label}  {DIM}({section_files} arquivo(s)){RESET}")

        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception as e:
            print_warn(f"{md_path.name}  erro ao ler: {e}", idx_prefix)
            error_count += 1
            continue

        # Já está no novo formato?
        if _NEW_HEADER_MARKER.match(content):
            print_skip(f"{md_path.name}  {DIM}já atualizado{RESET}", idx_prefix)
            already_new += 1
            continue

        # Detectar cabeçalho antigo
        m = _OLD_HEADER_RE.match(content)
        if not m:
            print_skip(f"{md_path.name}  {DIM}formato não reconhecido — pulando{RESET}", idx_prefix)
            skipped_count += 1
            continue

        title    = (m.group("title")    or md_path.stem).strip()
        url      = (m.group("url")      or "").strip().rstrip("/")
        date_str = (m.group("date")     or "Desconhecida").strip()
        duration = (m.group("duration") or "?").strip()

        # Extrai video_id da URL ou do nome do arquivo
        vid_id_match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
        if not vid_id_match:
            vid_id_match = re.search(r"([A-Za-z0-9_-]{11})", md_path.stem)
        video_id = vid_id_match.group(1) if vid_id_match else "desconhecido"

        # Extrai código de idioma do nome do arquivo (ex: canal-ID-pt.md → "pt")
        lang_match = re.search(r"-([a-z]{2}(?:-[A-Z]{2})?)\.md$", md_path.name)
        lang_code  = lang_match.group(1) if lang_match else "pt"

        if not url:
            url = f"https://youtube.com/watch?v={video_id}"

        # Montar novo cabeçalho YAML + H1
        new_header = (
            f"---\n"
            f'title: "{title}"\n'
            f'video_id: "{video_id}"\n'
            f'url: "{url}"\n'
            f'date: "{date_str}"\n'
            f'duration: "{duration}"\n'
            f'language: "{lang_code}"\n'
            f'source: "Escriba v{VERSION} (upgrade)"\n'
            f"---\n"
            f"\n"
            f"# {title}\n"
            f"\n"
            f"> **Data:** {date_str} · **Duração:** {duration} · **Idioma:** {lang_code}  \n"
            f"> 🔗 [{url}]({url})\n"
            f"\n"
        )

        # Corpo = tudo após o cabeçalho antigo
        body = content[m.end():].lstrip("\n")
        new_content = new_header + body

        try:
            md_path.write_text(new_content, encoding="utf-8")
            print_ok(f"{md_path.name}  {DIM}cabeçalho atualizado{RESET}", idx_prefix)
            upgraded_count += 1
        except Exception as e:
            print_warn(f"{md_path.name}  erro ao salvar: {e}", idx_prefix)
            error_count += 1

    # ── Resumo ────────────────────────────────────────────────────────────────
    print()
    print(f"  {BOLD}{BWHITE}Upgrade de Cabeçalho MD concluído{RESET}")
    print(f"  {ICON_OK}  Atualizados  : {BGREEN}{upgraded_count}{RESET}")
    print(f"  {ICON_SKIP}  Já atualizados: {DIM}{already_new}{RESET}")
    print(f"  {ICON_SKIP}  Pulados       : {DIM}{skipped_count}{RESET}")
    if error_count:
        print(f"  {ICON_ERR}  Erros         : {BRED}{error_count}{RESET}")
    print(f"  {ICON_INFO}  Total         : {len(all_md_files)}")
    print()


# ─── Notion Exporter ─────────────────────────────────────────────────────────

class NotionExporter:
    """Conversor e exportador de Markdown para Notion Blocks com limpeza de termos."""
    
    def __init__(self, token: str, database_id: str):
        self.token = token
        self.database_id = database_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }

    def _clean_text(self, text: str) -> str:
        """Helper interno para aplicar limpeza de termos em strings do Notion."""
        return clean_ekklezia_terms(text)

    def _parse_rich_text(self, text: str) -> list[dict]:
        """Converte markdown simples (bold e code) em blocos de rich text da Notion, com chunking de 2000 chars."""
        import re
        parts = []
        pattern = r'(\*\*.*?\*\*|`.*?`|[^*`]+)'
        
        for m in re.findall(pattern, text):
            if m.startswith('**') and m.endswith('**'):
                content = self._clean_text(m[2:-2])
                if not content: continue
                for i in range(0, len(content), 2000):
                    parts.append({
                        "type": "text",
                        "text": {"content": content[i:i+2000]},
                        "annotations": {"bold": True}
                    })
            elif m.startswith('`') and m.endswith('`'):
                content = self._clean_text(m[1:-1])
                if not content: continue
                for i in range(0, len(content), 2000):
                    parts.append({
                        "type": "text",
                        "text": {"content": content[i:i+2000]},
                        "annotations": {"code": True}
                    })
            else:
                content = self._clean_text(m)
                if not content: continue
                for i in range(0, len(content), 2000):
                    parts.append({
                        "type": "text",
                        "text": {"content": content[i:i+2000]}
                    })
        return parts

    def md_to_blocks(self, md_text: str) -> list[dict]:
        """Converte MD para lista de blocos do Notion."""
        blocks = []
        lines = md_text.split('\n')
        in_code_block = False
        code_content = []
        language = "plain text"

        for line in lines:
            stripped = line.strip()
            if not stripped and not in_code_block: continue

            # Code blocks
            if stripped.startswith('```'):
                if in_code_block:
                    blocks.append({
                        "object": "block",
                        "type": "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": '\n'.join(code_content)}}],
                            "language": language
                        }
                    })
                    in_code_block, code_content = False, []
                else:
                    in_code_block = True
                    lang_map = {"bash": "bash", "python": "python", "json": "json", "md": "markdown"}
                    language = lang_map.get(stripped[3:].strip(), "plain text")
                continue
            
            if in_code_block:
                code_content.append(line)
                continue

            # Headings & List Items
            if stripped.startswith('# '):
                blocks.append({"object": "block", "type": "heading_1", "heading_1": {"rich_text": self._parse_rich_text(stripped[2:])}})
            elif stripped.startswith('## '):
                blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": self._parse_rich_text(stripped[3:])}})
            elif stripped.startswith('### '):
                blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": self._parse_rich_text(stripped[4:])}})
            elif stripped.startswith(('* ', '- ', '• ')):
                blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": self._parse_rich_text(stripped[2:])}})
            elif stripped == '---':
                blocks.append({"object": "block", "type": "divider", "divider": {}})
            else:
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._parse_rich_text(stripped)}})
        
        return blocks

    def create_page(self, title: str, blocks: list[dict], video_url: str = None) -> Optional[str]:
        """Cria uma página no Notion com propriedades enriquecidas (URL, Status)."""
        url = "https://api.notion.com/v1/pages"
        
        properties = {
            "Name": {"title": [{"text": {"content": self._clean_text(title) or "Sem Título"}}]}
        }
        
        if video_url:
            properties["URL"] = {"url": video_url}
        
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
            "children": blocks[:100]  # Limite da Notion API por request
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            if response.status_code != 200 and response.status_code != 201:
                error_detail = response.json()
                print_err(f"Falha ao exportar para Notion: {response.status_code} - {error_detail.get('message', 'Sem detalhes')}")
                # Se for 400, talvez queiramos ver o payload para debug (opcional, mas útil agora)
                # print_info(f"Payload enviado: {json.dumps(payload, indent=2)}")
                return None
            
            page_data = response.json()
            page_id = page_data.get("id")
            
            # Se houver mais blocos, faz o patch subsequente
            if len(blocks) > 100:
                self._append_remaining_blocks(page_id, blocks[100:])
                
            return page_id
        except Exception as e:
            print_err(f"Erro inesperado ao exportar para Notion: {e}")
            return None

    def _append_remaining_blocks(self, page_id: str, remaining_blocks: list[dict]):
        """Adiciona os blocos excedentes em lotes de 100."""
        url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        for i in range(0, len(remaining_blocks), 100):
            batch = remaining_blocks[i:i+100]
            try:
                requests.patch(url, headers=self.headers, json={"children": batch}).raise_for_status()
            except Exception as e:
                print_err(f"Erro ao adicionar lote de blocos ao Notion: {e}")


def main() -> None:
    print_header(VERSION)
    cli_args = parse_args()
    
    # Se 'canal' foi passado como lista (nargs='*'), junta tudo.
    # Se o primeiro item parece o início de uma URL (http), unimos sem espaços 
    # para tentar reconstruir URLs que o shell pode ter quebrado em tokens (ex: por causa de & não escapado).
    if isinstance(cli_args.canal, list) and cli_args.canal:
        if cli_args.canal[0].startswith("http"):
            cli_args.canal = "".join(cli_args.canal)
        else:
            cli_args.canal = " ".join(cli_args.canal)
    elif isinstance(cli_args.canal, list):
        cli_args.canal = None

    # Short-circuit: modo offline de regeneração MD
    if cli_args.regen_md:
        regen_md_from_srt_files(force=getattr(cli_args, 'force', False))
        return

    # Short-circuit: upgrade de cabeçalho MD in-place
    if cli_args.upgrade_md:
        upgrade_md_headers()
        return

    # Short-circuit: migração de bancos de dados
    if cli_args.migrate:
        migrate_all_databases(Path.cwd())
        return

    # --- Modo de Operação Especial: Notion File ---
    if cli_args.notion_file:
        file_path = Path(cli_args.notion_file).resolve()
        if not file_path.is_file():
            print_err(f"Arquivo não encontrado: {file_path}")
            sys.exit(1)
        
        notion_token = os.getenv("NOTION_TOKEN")
        if not notion_token:
            print_err("NOTION_TOKEN não encontrado no ambiente (.env)")
            sys.exit(1)
            
        print_section("Upload Individual Notion")
        exporter = NotionExporter(notion_token, cli_args.notion_db)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        blocks = exporter.md_to_blocks(content)
        page_id = exporter.create_page(file_path.stem, blocks)
        if page_id:
            print_ok(f"Arquivo exportado com sucesso! ID: {page_id}")
        sys.exit(0)

    # --- Fluxo Normal do Script ---

    # Guardamos o que o usuário digitou na linha de comando (ex: "@MeuCanal").
    # Fazemos isso ANTES de qualquer função poder modificar cli_args.canal,
    # garantindo que vamos comparar com o valor original do usuário.
    user_provided_canal = cli_args.canal

    # Descobrimos o caminho do JSON desta pasta de trabalho.
    # Cada pasta de canal tem seu próprio banco de dados chamado escriba_<NomeDaPasta>.json.
    # Ele guarda o histórico de vídeos já processados e os canais cadastrados.
    cwd_path = Path.cwd()
    latest_json_path = get_latest_json_path(cwd_path)
    json_exists = latest_json_path.exists()  # True se o banco já foi criado antes

    # ── [NOVO CANAL] ──────────────────────────────────────────────────────────
    # Este bloco trata a situação em que o usuário digita um canal que o Escriba
    # ainda não conhece nesta pasta.
    #
    # Exemplo de uso:
    #   A pasta já tem @CanalA cadastrado. O usuário agora roda:
    #     python escriba.py @CanalB
    #   Nesse caso, @CanalB é novo → queremos registrá-lo E baixar apenas dele.
    #
    # Condição: só entramos aqui se:
    #   1. O usuário passou um canal explicitamente (@Canal ou URL)
    #   2. Já existe um JSON nesta pasta (ou seja, não é a primeira execução)
    if user_provided_canal and json_exists:
        # register_channel_in_json verifica se o canal já existe e, se não existir,
        # adiciona à lista youtube_channels e salva o JSON.
        # Retorna (is_new=True, ...) quando o canal foi adicionado agora.
        is_new_channel, _registered_ok = register_channel_in_json(
            latest_json_path, user_provided_canal
        )

        if is_new_channel:
            # O canal acabou de ser registrado pela primeira vez nesta pasta.
            # Não queremos reprocessar todos os outros canais que já estão no banco.
            # Por isso passamos channel_filter= para o process_videos(), que faz
            # a filtragem e só baixa legendas deste canal específico.
            #
            # A verificação de arquivos já baixados também acontece dentro de
            # process_videos() automaticamente — não vamos re-baixar nada.
            print_section("Novo Canal Detectado")
            print_info(
                f"Canal {BOLD}{user_provided_canal}{RESET} é novo nesta pasta. "
                f"Processando apenas este canal."
            )
            session_config = setup_session(cli_args)
            cookie_args_list, language_opt_string = init_auth_and_language(
                session_config, cli_args.lang, cli_args.refresh_cookies
            )
            dl, sk, er, tot, chan_tot, was_interrupted = process_videos(
                session_config, cookie_args_list, language_opt_string, cli_args,
                channel_filter=user_provided_canal,  # Foca apenas no novo canal
                is_first_channel=False,              # False: impede que o novo canal adote ("roube") vídeos órfãos
            )
            print_section("Resumo")
            print_summary(dl, sk, er, tot, chan_tot)
            if cli_args.consolidate or cli_args.lexis_reset:
                consolidate_by_channel(str(cwd_path), reset_mode=cli_args.lexis_reset)
            if was_interrupted:
                sys.exit(130)  # Código 130 = interrupção por Ctrl+C (padrão Unix)
            return  # Encerra o main() — não precisa continuar para os outros modos

        # Se chegamos aqui, o canal informado JA está no banco.
        # Continuamos para o fluxo normal abaixo, que reprocessa o canal normalmente.

    # ── [MODO AUTO / MULTI-CANAL] ────────────────────────────────────────────
    # Quando o usuário não passa nenhum canal na linha de comando,
    # o Escriba lê os canais registrados no JSON e sincroniza todos automaticamente.
    # Isso é útil para rodar o script em um agendador (cron) sem precisar digitar nada.
    all_channels_to_sync = []
    if not user_provided_canal:
        if json_exists:
            try:
                with open(latest_json_path, "r", encoding="utf-8") as f:
                    json_data = json.load(f)
                if isinstance(json_data, dict):
                    channels_list = json_data.get("youtube_channels", [])
                    if isinstance(channels_list, list) and len(channels_list) >= 1:
                        all_channels_to_sync = list(channels_list)
            except Exception:
                pass  # Se o JSON estiver mal formado, deixamos a lista vazia e seguimos

    if all_channels_to_sync:
        # === MODO CANAL REGISTRADO ===
        is_multi = len(all_channels_to_sync) > 1
        if is_multi:
            print_section("Sincronização Multi-Canal")
            print_info(f"Detectados {BOLD}{len(all_channels_to_sync)}{RESET} canais registrados nesta pasta.")
        else:
            print_section("Sincronização de Canal")
            print_info(f"Canal registrado: {BOLD}{all_channels_to_sync[0]}{RESET}")
        for i, ch in enumerate(all_channels_to_sync, 1):
            print_info(f"  {BOLD}{i}.{RESET} {ch}")
        print()

        total_dl = 0
        total_skip = 0
        total_err = 0
        total_vids = 0
        total_chan_vids = 0
        was_interrupted = False

        for idx, channel_handle in enumerate(all_channels_to_sync, 1):
            is_first_channel = (idx == 1)
            print_section(f"Canal {idx}/{len(all_channels_to_sync)}: {channel_handle}")
            
            # Resetar o argumento canal para cada iteração
            cli_args.canal = channel_handle
            
            try:
                session_config = setup_session(cli_args)
                cookie_args_list, language_opt_string = init_auth_and_language(
                    session_config, cli_args.lang, cli_args.refresh_cookies
                )
                dl, sk, er, tot, chan_tot, interrupted = process_videos(
                    session_config, cookie_args_list, language_opt_string, cli_args,
                    channel_filter=channel_handle if is_multi else None,
                    is_first_channel=is_first_channel,
                )
                total_dl += dl
                total_skip += sk
                total_err += er
                total_vids += tot
                total_chan_vids += chan_tot
                
                if interrupted:
                    was_interrupted = True
                    break
            except Exception as e:
                print_err(f"Erro ao processar canal {channel_handle}: {e}")
                continue

        # Verificação explícita: não há mais canais a processar
        print()
        print_info(f"Todos os {BOLD}{len(all_channels_to_sync)}{RESET} canal(is) verificados. Nenhum canal pendente.")

        if is_multi:
            print_section("Resumo Multi-Canal")
        else:
            print_section("Resumo")
        print_summary(total_dl, total_skip, total_err, total_vids, total_chan_vids)
        if cli_args.consolidate or cli_args.lexis_reset:
            consolidate_by_channel(str(cwd_path), reset_mode=cli_args.lexis_reset)
        if was_interrupted:
            sys.exit(130)
    else:
        # === MODO SEM CANAL REGISTRADO (padrão / primeira execução) ===
        session_config = setup_session(cli_args)
        cookie_args_list, language_opt_string = init_auth_and_language(
            session_config, cli_args.lang, cli_args.refresh_cookies
        )
        downloaded_videos_count, skipped_videos_count, error_videos_count, total_videos_count, chan_tot, was_interrupted = process_videos(
            session_config, cookie_args_list, language_opt_string, cli_args
        )
        print_summary(downloaded_videos_count, skipped_videos_count, error_videos_count, total_videos_count, chan_tot)
        if cli_args.consolidate or cli_args.lexis_reset:
            consolidate_by_channel(str(cwd_path), reset_mode=cli_args.lexis_reset)
        if was_interrupted:
            sys.exit(130)



if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print_warn(f"Interrompido pelo usuário (Ctrl+C).  {DIM}Saindo...{RESET}")
        cwd = Path.cwd()
        if cwd.name != "escriba":
            cleanup_temp_files(cwd, cwd.name)
        sys.exit(130)  # Código 130 = SIGINT (padrão Unix)
