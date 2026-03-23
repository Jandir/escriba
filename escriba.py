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
# Isso garante que todas as dependências (requests, urllib3, yt-dlp) sejam as do projeto.
_script_dir = Path(__file__).parent.resolve()
_venv_bin = _script_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin")
_venv_python = _venv_bin / ("python.exe" if os.name == "nt" else "python3")

if _venv_python.exists() and Path(sys.executable).resolve() != _venv_python.resolve():
    try:
        os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)
    except Exception:
        pass # Fallback suave

# Suprime avisos de dependência ANTES de importar o requests
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*doesn't match a supported version.*")

import argparse
import glob
import json
import re
import random
import shutil
import time
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
import requests

from collections import Counter

VERSION = "2.4.2"

@functools.lru_cache(None)
def _load_ekklezia_rules() -> list[tuple[str, str]]:
    """Carrega as regras de substituição do arquivo rules.txt (raiz e corrente)."""
    # 1. Regras padrão hardcoded
    rules_dict = {
        "Sete Montanhas": "Sete Montes",
        "Ecclesia": "Ekklezia"
    }
    
    # 2. Caminhos dos arquivos
    global_rules_path = _script_dir / "rules.txt"
    local_rules_path = Path.cwd() / "rules.txt"
    
    for path in [global_rules_path, local_rules_path]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"): continue
                        
                        # Suporta 'Original,Novo' ou 'Original=Novo'
                        sep = "," if "," in line else "="
                        if sep in line:
                            orig, novo = line.split(sep, 1)
                            rules_dict[orig.strip()] = novo.strip()
            except Exception:
                pass
    
    # Retorna lista de tuplas para iteração (estável para substituições múltiplas)
    return list(rules_dict.items())


def clean_ekklezia_terms(text: str) -> str:
    """Aplica as regras de substituição de termos lidas de rules.txt."""
    if not text: return text
    rules_list = _load_ekklezia_rules()
    for orig, novo in rules_list:
        text = text.replace(orig, novo)
    return text


@dataclass
class SessionConfig:
    """Configuração de sessão montada durante o setup inicial."""
    cwd_path: Path
    channel_dir_name: str
    script_dir_path: Path
    yt_dlp_cmd_list: list[str]
    channel_input_url_or_handle: str
    channel_url: str

# Carrega variáveis do .env (localizado no diretório do script)
load_dotenv(Path(__file__).parent / ".env")

# Node.js path para o js-runtime do yt-dlp
# Prioridade: variável NODE_PATH do .env → node encontrado no PATH do sistema
NODE_PATH = os.getenv("NODE_PATH") or shutil.which("node") or ""

# ─── Paleta ANSI ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

# Cores base
RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE   = "\033[0;34m"
WHITE  = "\033[0;37m"

# Bright
BRED   = "\033[1;31m"
BGREEN = "\033[1;32m"
BYELLW = "\033[1;33m"

BCYAN  = "\033[1;36m"
BWHITE = "\033[1;37m"


# ─── Ícones semânticos ──────────────────────────────────────────────────────────
ICON_OK   = f"{BGREEN}✓{RESET}"   # sucesso
ICON_ERR  = f"{BRED}✗{RESET}"    # erro
ICON_WARN = f"{BYELLW}⚠{RESET}"  # aviso
ICON_SKIP = f"{DIM}↷{RESET}"    # pulando
ICON_DL   = f"{BCYAN}▶{RESET}"   # baixando
ICON_WAIT = f"{YELLOW}◌{RESET}"  # aguardando
ICON_INFO = f"{BLUE}•{RESET}"   # informação


# ─── Utilitários de Layout ────────────────────────────────────────────────────

DIV_THIN  = f"{DIM}{'─' * 60}{RESET}"
DIV_THICK = f"{BLUE}{'━' * 60}{RESET}"


def _print_formatted(icon: str, message: str, indentation_prefix: str = "  ", end_char: str = "\n") -> None:
    """Print genérico com ícone. indentation_prefix controla a indentação inicial."""
    print(f"{indentation_prefix} {icon}  {message}", end=end_char, flush=True)


def print_ok(message: str, indentation_prefix: str = "  ")  -> None: _print_formatted(ICON_OK,   f"{GREEN}{message}{RESET}", indentation_prefix)
def print_err(message: str, indentation_prefix: str = "  ") -> None: _print_formatted(ICON_ERR,  f"{BRED}{message}{RESET}", indentation_prefix)
def print_warn(message: str, indentation_prefix: str = "  ")-> None: _print_formatted(ICON_WARN, f"{YELLOW}{message}{RESET}", indentation_prefix)
def print_info(message: str, indentation_prefix: str = "  ")-> None: _print_formatted(ICON_INFO, f"{DIM}{message}{RESET}", indentation_prefix)
def print_skip(message: str, indentation_prefix: str = "  ")-> None: _print_formatted(ICON_SKIP, f"{DIM}{message}{RESET}", indentation_prefix)
def print_dl(message: str, indentation_prefix: str = "  ")  -> None: _print_formatted(ICON_DL,   f"{BCYAN}{message}{RESET}", indentation_prefix)


def print_section(section_title: str) -> None:
    """Imprime um separador de seção com título."""
    print(f"\n{DIV_THIN}")
    print(f"  {BOLD}{BWHITE}{section_title}{RESET}")
    print(f"{DIV_THIN}")


def print_header(channel_name: str, script_version: str, execution_mode: str) -> None:
    """Header principal em box drawing."""
    header_line_1 = f" escriba  v{script_version} "
    header_line_2 = f" Canal: {channel_name} "
    header_line_3 = f" Modo:  {execution_mode} "
    max_width = max(len(header_line_1), len(header_line_2), len(header_line_3)) + 2
    horizontal_bar = "━" * max_width
    print()
    print(f"{BCYAN}┏{horizontal_bar}┓{RESET}")
    print(f"{BCYAN}┃{RESET}{BOLD}{header_line_1:<{max_width}}{RESET}{BCYAN}┃{RESET}")
    print(f"{BCYAN}┃{RESET}{DIM}{header_line_2:<{max_width}}{RESET}{BCYAN}┃{RESET}")
    print(f"{BCYAN}┃{RESET}{DIM}{header_line_3:<{max_width}}{RESET}{BCYAN}┃{RESET}")
    print(f"{BCYAN}┗{horizontal_bar}┛{RESET}")
    print()


def print_countdown(seconds_count: int, message: str, indentation_prefix: str = "  ") -> None:
    """Contagem regressiva com barra visual inline."""
    visual_bar_width = 20
    try:
        for remaining_seconds in range(seconds_count, -1, -1):
            filled_blocks  = int((seconds_count - remaining_seconds) / seconds_count * visual_bar_width) if seconds_count else visual_bar_width
            progress_bar_str = f"{GREEN}{'█' * filled_blocks}{DIM}{'░' * (visual_bar_width - filled_blocks)}{RESET}"
            progress_percentage = int((seconds_count - remaining_seconds) / seconds_count * 100) if seconds_count else 100
            sys.stdout.write(f"\r{indentation_prefix} {ICON_WAIT}  {message} [{progress_bar_str}] {progress_percentage:>3}%  {DIM}{remaining_seconds}s{RESET}  \x1b[K")
            sys.stdout.flush()
            if remaining_seconds > 0:
                time.sleep(1)
        sys.stdout.write(f"\r\x1b[K")
        sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write(f"\r\x1b[K")
        sys.stdout.flush()
        raise


# ─── Configuração do Ambiente ─────────────────────────────────────────────────

def setup_environment() -> tuple[Path, list[str]]:
    """
    Valida e retorna:
      - script_dir_path: diretório onde este .py está salvo
      - yt_dlp_cmd_list: comando base para invocar o yt-dlp (python do venv + -m yt_dlp)
    """
    script_dir_path = Path(__file__).parent.resolve()
    # Descoberta do executável Python no ambiente virtual (Cross-platform)
    if os.name == "nt":
        python_executable_path = script_dir_path / ".venv" / "Scripts" / "python.exe"
    else:
        python_executable_path = script_dir_path / ".venv" / "bin" / "python3"

    if not python_executable_path.is_file():
        print_err(f"Ambiente virtual não encontrado em {python_executable_path}")
        print_info("Certifique-se de que a pasta .venv/ existe e as dependências foram instaladas.")
        sys.exit(1)

    yt_dlp_cmd_list = [
        str(python_executable_path), 
        "-m", "yt_dlp", 
        "--remote-components", "ejs:github"
    ]
    if NODE_PATH:
        yt_dlp_cmd_list.extend(["--js-runtimes", f"node:{NODE_PATH}"])
        
    return script_dir_path, yt_dlp_cmd_list


# ─── Cookies ──────────────────────────────────────────────────────────────────

def configure_cookies(cwd_path: Path, script_dir_path: Path, force_refresh_cookies: bool) -> list[str]:
    """
    Retorna os argumentos de cookie para o yt-dlp.
    Se force_refresh_cookies=True, apaga o cookies.txt existente na cwd_path antes de continuar.
    """
    cookies_file_path = cwd_path / "cookies.txt"

    if force_refresh_cookies:
        print_warn("--refresh-cookies ativo. Apagando cache antigo...")
        cookies_file_path.unlink(missing_ok=True)

    def is_valid_cookie_file(path: Path) -> bool:
        if not path.is_file(): return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(100)
                # Verifica se é um arquivo vazio ou se tem a diretiva correta do Netscape
                if not content.strip() or "Netscape" in content or "TRUE" in content:
                    return True
        except Exception:
            pass
        return False

    if is_valid_cookie_file(cookies_file_path):
        print_info(f"Cookies em cache: {cookies_file_path.name}")
        return ["--cookies", str(cookies_file_path)]
    elif cookies_file_path.is_file():
        print_warn(f"Cache de cookies corrompido detectado e removido: {cookies_file_path.name}")
        cookies_file_path.unlink()

    # Fallback: busca no diretório do script
    global_script_cookies_path = script_dir_path / "cookies.txt"
    if global_script_cookies_path.is_file() and not force_refresh_cookies:
        print_info("Cookies do diretório do script.")
        return ["--cookies", str(global_script_cookies_path)]

    print_warn(f"Extraindo cookies do Chrome → {cookies_file_path.name}")
    return ["--cookies-from-browser", "chrome", "--cookies", str(cookies_file_path)]


def filter_youtube_cookies(cookies_path: Path) -> None:
    """
    Filtra o arquivo cookies.txt (Netscape) mantendo apenas cookies do YouTube/Google.
    Remove trackers, extensões e lixos cruzados que o Chrome exporta.
    """
    if not cookies_path.is_file():
        return
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        filtered_lines = []
        for line in lines:
            if line.startswith("#") or not line.strip():
                filtered_lines.append(line)
                continue
            
            parts = line.split('\t')
            if len(parts) >= 6:
                domain = parts[0].strip()
                # Manter apenas domínios relativos ao Google/YouTube para autenticação
                if "youtube.com" in domain or "google.com" in domain:
                    filtered_lines.append(line)
        
        with open(cookies_path, "w", encoding="utf-8") as f:
            f.writelines(filtered_lines)
    except Exception as e:
        print_warn(f"Falha ao filtrar cookies {cookies_path.name}: {e}")


# ─── Detecção de Idioma ───────────────────────────────────────────────────────

def detect_language(yt_dlp_cmd_list: list[str], cookie_args_list: list[str], channel_url: str, cached_lang: str | None = None) -> str:
    """
    Detecta o idioma predominante do canal. 
    Se cached_lang for fornecido, usa ele imediatamente (Prioridade Local).
    """
    if cached_lang and cached_lang != "N/A":
        print_ok(f"Usando idioma em cache: {BOLD}{cached_lang.strip('^$')}{RESET}")
        return cached_lang

    print_info("Detectando idioma nativo (amostragem de 5 vídeos)...")
    
    # 1. Carregar Idioma default do .env caso exista (Fallback Máximo)
    global_default_lang = os.getenv("DEFAULT_LANGUAGE") or os.getenv("LANG") or "pt"
    if global_default_lang and len(global_default_lang) > 2:
        global_default_lang = global_default_lang[:2].lower() # Ex: 'pt_BR' -> 'pt'

    # Ajustar URL para garantir que pegamos vídeos se for canal
    detect_url = channel_url
    if "watch?v=" not in detect_url and "playlist?list=" not in detect_url:
        is_generic_channel = True
        for suffix in ["/videos", "/shorts", "/streams", "/live"]:
            if detect_url.endswith(suffix):
                is_generic_channel = False
                break
        if is_generic_channel:
            detect_url = detect_url.rstrip("/") + "/videos"

    # Comando otimizado para pegar 5 idiomas rapidamente
    # --flat-playlist é muito rápido mas nem sempre popula o campo 'language'
    cmd = yt_dlp_cmd_list + cookie_args_list + [
        "--print", "language",
        "--playlist-end", "5",
        "--ignore-errors",
        "--flat-playlist", 
        detect_url
    ]

    detected_languages = []
    try:
        # Tenta com flat-playlist primeiro (ultra-rápido)
        subprocess_result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        detected_languages = [lang.strip().lower() for lang in subprocess_result.stdout.splitlines() if lang.strip()]
        
        if not detected_languages:
            # Fallback sem --flat-playlist (mais lento, pois faz download de info parcial de cada um)
            if "--flat-playlist" in cmd: cmd.remove("--flat-playlist")
            if "--playlist-end" in cmd:
                idx = cmd.index("--playlist-end")
                cmd[idx + 1] = "3" # Reduz amostragem no fallback lento pra salvar tempo
            
            subprocess_result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            detected_languages = [lang.strip().lower() for lang in subprocess_result.stdout.splitlines() if lang.strip()]
            
        # Ignore invalid tags returned from yt-dlp when metadata is missing
        invalid_tags = {"na", "n/a", "none", "null", "undefined"}
        detected_languages = [l for l in detected_languages if l not in invalid_tags]

    except Exception as e:
        print_warn(f"Erro na rotina de detecção automática: {e}")

    if detected_languages:
        # Pega o idioma mais comum na amostra
        most_common_lang, count = Counter(detected_languages).most_common(1)[0]
        # Sanitizar para 2 caracteres (ex: pt-BR -> pt)
        clean_lang = most_common_lang.split("-")[0].split("_")[0]
        language_regex_filter = f"^{clean_lang}$"
        
        print_ok(f"Idioma detectado ({count}/{len(detected_languages)}): {BOLD}{clean_lang}{RESET} {DIM}(filtro: {language_regex_filter}){RESET}")
        return language_regex_filter

    # Fallback final se nada for detectado
    print_warn(f"Não foi possível detectar o idioma. Assumindo fallback: {BOLD}{global_default_lang}{RESET}")
    print_info(f"Dica: utilize {WHITE}--lang [código]{RESET} para forçar um idioma específico.")
    return f"^{global_default_lang}$"


# ─── Listagem de IDs e JSON State ───────────────────────────────────────────────

def get_video_exact_date(video_id: str, yt_dlp_cmd_list: list[str], cookie_args_list: list[str]) -> dict:
    """Extrai a data exata de um único vídeo (usado via ThreadPoolExecutor)."""
    cmd_list = yt_dlp_cmd_list + cookie_args_list + [
        "--dump-json",
        "--skip-download",
        "--ignore-errors",
        "--remote-components", "ejs:github",
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    try:
        process_instance = subprocess.run(cmd_list, capture_output=True, text=True, timeout=30)
        if process_instance.stdout:
            video_json_dict = json.loads(process_instance.stdout)
            upload_date_string = video_json_dict.get("upload_date", "N/A")
            if upload_date_string and len(upload_date_string) == 8:
                upload_date_string = f"{upload_date_string[:4]}-{upload_date_string[4:6]}-{upload_date_string[6:]}"
            return {"id": video_id, "date": upload_date_string, "title": video_json_dict.get("title", "N/A")}
    except Exception:
        pass
    return {"id": video_id, "date": "N/A", "title": "N/A"}


def generate_fast_list_json(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    channel_url: str,
    max_workers_count: int = 40,
    local_history_map: dict | None = None
) -> list[dict]:
    """
    Novo mecanismo de descoberta de alta velocidade:
    
    Fase 1 — Extrai id, title e upload_date diretamente do stream JSON do 
             --flat-playlist. Isso evita a necessidade de abrir múltiplos 
             processos yt-dlp apenas para buscar metadados básicos.
             Utiliza o `local_history_map` (carregado via load_all_local_history)
             como cache prioritário para preencher datas ausentes no índice.
    
    Fase 2 — Fallback paralelo (threads) acionado apenas para vídeos onde
             o campo 'upload_date' estiver ausente tanto no índice quanto no cache local.
    """
    print_info(f"Fase 1: Descoberta de IDs + Metadados ({BOLD}{channel_url}{RESET})...")
    discovery_cmd_list = yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist",
        "--dump-json",
        "--ignore-errors",
        "--remote-components", "ejs:github",
        channel_url
    ]
    
    raw_video_list: list[dict] = []
    try:
        discovery_process = subprocess.Popen(
            discovery_cmd_list, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        for line_content in discovery_process.stdout:
            try:
                obj = json.loads(line_content.strip())
                video_id = obj.get("id")
                if not video_id:
                    continue

                title = obj.get("title") or obj.get("fulltitle") or "N/A"

                # Tentar extrair data do índice flat-playlist (evita Fase 2 para a maioria)
                raw_date = obj.get("upload_date") or ""
                if not raw_date:
                    # Alguns canais expõem timestamp unix
                    ts = obj.get("timestamp")
                    if ts:
                        raw_date = datetime.utcfromtimestamp(int(ts)).strftime("%Y%m%d")
                publish_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if len(str(raw_date)) == 8 else "N/A"

                if publish_date == "N/A" and local_history_map and video_id in local_history_map:
                    hist_entry = local_history_map[video_id]
                    if hist_entry.get("publish_date") and hist_entry["publish_date"] != "N/A":
                        publish_date = hist_entry["publish_date"]

                raw_video_list.append({"id": video_id, "title": title, "publish_date": publish_date})
                sys.stdout.write(
                    f"\r  {ICON_WAIT}  {BCYAN}IDs encontrados: {len(raw_video_list)}{RESET}"
                )
                sys.stdout.flush()
            except Exception:
                continue
        discovery_process.wait()
    except Exception as error_msg:
        print()
        print_warn(f"Erro na descoberta: {error_msg}")
        return []

    print()

    if not raw_video_list:
        print_warn("Nenhum vídeo encontrado para mapear state JSON.")
        return []

    has_dates_count = sum(1 for v in raw_video_list if v["publish_date"] != "N/A")
    print_ok(f"Descoberta completa: {has_dates_count}/{len(raw_video_list)} com data no índice.")
    print_info(f"O restante terá seus metadados recuperados apenas se não estiverem no cache.")

    # Montar lista final preservando a ordem original do flat-playlist
    return [
        {
            "video_id": v["id"],
            "publish_date": v["publish_date"],
            "title": v["title"],
            "subtitle_downloaded": False,
            "info_downloaded": False,
            "has_no_subtitle": False,
        }
        for v in raw_video_list
    ]


def get_latest_json_path(cwd_path: Path, channel_name_safe: str | None = None) -> Path | None:
    if channel_name_safe:
        specific_path = cwd_path / f"escriba_{channel_name_safe}.json"
        if specific_path.exists():
            return specific_path
        specific_path_legacy = cwd_path / f"lista_{channel_name_safe}.json"
        if specific_path_legacy.exists():
            return specific_path_legacy
        return None
            
    json_files_list = glob.glob(str(cwd_path / "escriba_*.json"))
    if not json_files_list:
        json_files_list = glob.glob(str(cwd_path / "lista_*.json"))
    if not json_files_list:
        return None
    return Path(max(json_files_list, key=os.path.getmtime))

def load_all_local_history(cwd_path: Path) -> dict[str, dict]:
    """
    Escaneia recursivamente o diretório atual e subpastas (ex: 'audios/') em busca de 
    arquivos .json para consolidar dados de vídeos.
    Extrai metadados (título, data, channel_id, uploader) usando o ID do vídeo como chave.
    Suporta arquivos escriba_*.json, lista_*.json, e arquivos individuais como 
    [folder]-[video_id]-[lang].json ou [video_id].info.json.
    """
    history_map = {}
    blacklist = {"package.json", "package-lock.json", "requirements.json", "env.json"}
    
    # ID de 11 caracteres (padrão YouTube) 
    video_id_regex = re.compile(r"([A-Za-z0-9_-]{11})")
    
    try:
        search_dirs = [cwd_path] + [d for d in cwd_path.iterdir() if d.is_dir() and d.name not in (".git", ".venv", "__pycache__")]
    except Exception:
        search_dirs = [cwd_path]
    
    for directory in search_dirs:
        try:
            for jf in directory.glob("*.json"):
                if jf.name in blacklist: continue
                
                # 1. Histórico consolidado
                if jf.name.startswith(("escriba_", "lista_")):
                    try:
                        with open(jf, "r", encoding="utf-8") as fd:
                            json_data = json.load(fd)
                            v_list = json_data["videos"] if isinstance(json_data, dict) and "videos" in json_data else json_data
                            if isinstance(v_list, list):
                                for v in v_list:
                                    vid_id = v.get("video_id") or v.get("id")
                                    if not vid_id: continue
                                    _merge_video_data(history_map, vid_id, v)
                    except Exception: pass
                    continue

                # 2. Arquivo per-vídeo (info.json ou similar)
                match = video_id_regex.search(jf.name)
                if match:
                    vid_id = match.group(1)
                    try:
                        with open(jf, "r", encoding="utf-8") as fd:
                            meta = json.load(fd)
                            if not isinstance(meta, dict): continue
                            
                            upload_date = meta.get("upload_date") or meta.get("publish_date") or meta.get("date")
                            if upload_date and len(str(upload_date)) == 8 and str(upload_date).isdigit():
                                s_date = str(upload_date)
                                upload_date = f"{s_date[:4]}-{s_date[4:6]}-{s_date[6:]}"
                            
                            v_data = {
                                "video_id": vid_id,
                                "title": meta.get("title") or meta.get("fulltitle") or meta.get("video_title") or "Avulso",
                                "publish_date": upload_date or "N/A",
                                "subtitle_downloaded": meta.get("subtitle_downloaded", False),
                                "info_downloaded": True if upload_date else False,
                                "channel_id": meta.get("channel_id") or meta.get("uploader_id"),
                                "uploader": meta.get("uploader") or meta.get("channel"),
                                "uploader_id": meta.get("uploader_id") or meta.get("channel_id")
                            }
                            _merge_video_data(history_map, vid_id, v_data)
                    except Exception: pass
        except Exception: pass

    return history_map


def _merge_video_data(history_map: dict, vid_id: str, new_data: dict):
    """
    Combina dados de vídeos de múltiplas fontes (JSONs diferentes).
    Prioriza:
    1. Datas válidas (formato YYYY-MM-DD vs "N/A")
    2. Títulos reais (evita "Avulso" ou strings vazias)
    3. Flags de download verdadeiras (subtitle_downloaded, info_downloaded, etc)
    """
    if vid_id not in history_map:
        history_map[vid_id] = new_data.copy()
    else:
        existing = history_map[vid_id]
        # Prioriza data válida
        if new_data.get("publish_date") and new_data["publish_date"] != "N/A":
            if not existing.get("publish_date") or existing["publish_date"] == "N/A":
                existing["publish_date"] = new_data["publish_date"]
        # Prioriza título real
        if new_data.get("title") and new_data["title"] not in ("N/A", "", "Avulso"):
            if not existing.get("title") or existing["title"] in ("N/A", "", "Avulso"):
                existing["title"] = new_data["title"]
        # Flags de download
        if new_data.get("subtitle_downloaded"): existing["subtitle_downloaded"] = True
        if new_data.get("info_downloaded"): existing["info_downloaded"] = True
        if new_data.get("has_no_subtitle"): existing["has_no_subtitle"] = True



def load_or_create_channel_state(
    cwd_path: Path, 
    yt_dlp_cmd_list: list[str], 
    cookie_args_list: list[str], 
    channel_url: str,
    only_peek_lang: bool = False
) -> tuple[Path | None, list[dict], str | None]:
    """
    Carrega o banco de dados JSON do canal e sincroniza com metadados locais.
    Realiza:
    1. Carregamento de todos os JSONs locais (history_map).
    2. Listagem rápida do canal no YouTube.
    3. Importação Reversa: vídeos locais que pertencem ao canal mas não estão na lista atual.
    4. Persistência do estado consolidado.
    """
    channel_name_safe = None
    identifier = ""
    
    # Extração de identificador (Handle ou ID de Playlist ou ID de Vídeo)
    # Identificação de Canal para vídeos individuais: busca o uploader antes de definir o JSON
    target_channel_id = None
    target_uploader_id = None

    if "watch?v=" in channel_url or "youtu.be/" in channel_url:
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", channel_url)
        identifier = match.group(1) if match else "video"
        
        # 0. Verificação em cache local antes de chamar o YouTube
        history_map = load_all_local_history(cwd_path)
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
        history_map = load_all_local_history(cwd_path)
    elif "list=" in channel_url:
        match = re.search(r"list=([A-Za-z0-9_-]+)", channel_url)
        identifier = match.group(1) if match else "playlist"
        
        # 0. Verificação em cache local para playlists
        history_map = load_all_local_history(cwd_path)
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
            except Exception:
                pass
            
        if not channel_name_safe:
            channel_name_safe = f"playlist_{identifier}"

    else:
        channel_name_safe = "canal"

    # Seleção inteligente do JSON
    json_path = None
    # 1. Tenta correspondência exata com o canal identificado
    target_filename = f"escriba_{channel_name_safe}.json"
    if (cwd_path / target_filename).exists():
        json_path = cwd_path / target_filename
    else:
        # 2. Se houver apenas um escriba_*.json na pasta, usa ele (contexto de pasta única)
        existing_jsons = list(cwd_path.glob("escriba_*.json"))
        if not existing_jsons:
            existing_jsons = list(cwd_path.glob("lista_*.json"))
            
        if len(existing_jsons) == 1:
            json_path = existing_jsons[0]
            print_info(f"Usando JSON corriente detectado: {BOLD}{json_path.name}{RESET}")
        elif len(existing_jsons) > 1:
            # Tenta achar um que bata com o canal atual
            for ej in existing_jsons:
                if channel_name_safe and channel_name_safe in ej.name:
                    json_path = ej
                    break
            if not json_path:
                # Pega o mais recente como fallback
                json_path = Path(max([str(j) for j in existing_jsons], key=os.path.getmtime))
                print_info(f"Sincronizando com JSON mais recente: {BOLD}{json_path.name}{RESET}")
        else:
            json_path = cwd_path / target_filename

    # Carregar/Identificar idioma persistente
    detected_lang_cached = None
    if json_path and json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as fd:
                data = json.load(fd)
                if isinstance(data, dict):
                    detected_lang_cached = data.get("detected_language")
        except Exception: pass

    if only_peek_lang:
        return json_path, [], detected_lang_cached

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
            if state_map:
                print_info(f"Base carregada: {BOLD}{len(state_map)}{RESET} vídeos preservados do banco de dados.")
        except Exception: pass

    # 2. Já carregamos history_map lá no início para identificação de canal
    
    # 3. Buscar os vídeos da URL atual
    current_videos_list = generate_fast_list_json(yt_dlp_cmd_list, cookie_args_list, channel_url, local_history_map=history_map)
    if not current_videos_list and not state_map:
        return None, [], detected_lang_cached

    # 4. Integrar novos vídeos descobertos
    new_videos_count = 0
    imported_count = 0
    
    playlist_ctx = identifier if "list=" in channel_url else None

    # Se ainda não temos os IDs de canal/uploader, tenta pegar do primeiro vídeo da lista atual
    if not target_channel_id and not target_uploader_id and current_videos_list:
        v0 = current_videos_list[0]
        v0_id = v0["video_id"]
        if v0_id in history_map:
            target_channel_id = history_map[v0_id].get("channel_id")
            target_uploader_id = history_map[v0_id].get("uploader_id")

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
        else:
            # Novo vídeo
            if playlist_ctx: vid_entry["playlists"] = [playlist_ctx]
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
            state_map[vid_id] = hist_entry.copy()
            imported_count += 1

    final_results_list = list(state_map.values())
    
    if new_videos_count > 0:
        print_ok(f"Descobertos {BOLD}{new_videos_count}{RESET} novos vídeos na URL alvo.")
    if imported_count > 0:
        print_ok(f"Importados {BOLD}{imported_count}{RESET} vídeos do histórico local.")

    return json_path, final_results_list, detected_lang_cached


def save_channel_state_json(json_path: Path | None, videos_list: list[dict], channel_handle: str | None = None, detected_language: str | None = None):
    """
    Atualiza atomicamente arquivo JSON em disco. 
    Garante deduplicação de video_id e preservação do idioma detectado.
    """
    if not json_path:
        return
        
    # 1. Deduplicação e mesclagem final antes de salvar
    dedup_map = {}
    for v in videos_list:
        vid_id = v.get("video_id") or v.get("id")
        if not vid_id: continue
        if vid_id not in dedup_map:
            dedup_map[vid_id] = v.copy()
        else:
            existing = dedup_map[vid_id]
            # Mesclar flags binárias (quem tem True vence)
            for flag in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
                if v.get(flag): existing[flag] = True
            
            # Mesclar strings se o atual for fraco
            if v.get("publish_date") and v["publish_date"] != "N/A":
                if not existing.get("publish_date") or existing["publish_date"] == "N/A":
                    existing["publish_date"] = v["publish_date"]
            if v.get("title") and v["title"] not in ("N/A", "Avulso", ""):
                if not existing.get("title") or existing["title"] in ("N/A", "Avulso", ""):
                    existing["title"] = v["title"]
            
            # Mesclar playlists
            if "playlists" in v:
                if "playlists" not in existing: existing["playlists"] = []
                for p in v["playlists"]:
                    if p not in existing["playlists"]: existing["playlists"].append(p)

    final_videos = list(dedup_map.values())

    # 2. Determinar handle do canal
    if not channel_handle:
        match = re.search(r"(?:escriba_|lista_)(.+)\.json", json_path.name)
        if match:
            channel_handle = f"@{match.group(1)}"
            
    output_data = {
        "channel": channel_handle if channel_handle else "N/A",
        "videos": final_videos
    }
    
    if detected_language:
        output_data["detected_language"] = detected_language

    # Tenta preservar campos existentes se não passamos novos (ex: idioma)
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                if isinstance(old_data, dict):
                    if not channel_handle:
                        output_data["channel"] = old_data.get("channel", output_data["channel"])
                    if not detected_language and "detected_language" in old_data:
                        output_data["detected_language"] = old_data["detected_language"]
        except: pass
    
    # Force the path to strictly be the modern format if it isn't already
    target_write_path = json_path
    if json_path.name.startswith("lista_"):
        target_write_path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    
    temp_path = target_write_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as file_descriptor:
            json.dump(output_data, file_descriptor, indent=4, ensure_ascii=False)
        temp_path.replace(target_write_path)
        
        # Cleanup legacy file if migration occurred successfully
        if json_path.name.startswith("lista_") and json_path.exists():
            json_path.unlink(missing_ok=True)
            
    except Exception as e:
        print_warn(f"Ignorando erro ao salvar JSON de state: {e}")


def auto_migrate_legacy_files(cwd_path: Path, state_list: list[dict]) -> bool:
    """
    Se existirem arquivos texto antigos do projeto (historico.txt, historico-info.txt, videos_sem_legenda.txt),
    lê e consolida os dados no state_list em memória, e depois os renomeia para .bak para não repetir.
    Retorna True se alguma modificação nos dicionários foi feita.
    """
    historico_ids = set()
    historico_path = cwd_path / "historico.txt"
    if historico_path.is_file():
        with open(historico_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("youtube "): historico_ids.add(line.strip()[len("youtube "):])

    info_ids = set()
    info_path = cwd_path / "historico-info.txt"
    if info_path.is_file():
        with open(info_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("youtube "): info_ids.add(line.strip()[len("youtube "):])

    no_sub_ids = set()
    no_sub_path = cwd_path / "videos_sem_legenda.txt"
    if no_sub_path.is_file():
        with open(no_sub_path, "r", encoding="utf-8") as f:
            for line in f:
                if "watch?v=" in line:
                    vid = line.strip().split("watch?v=")[-1].strip()
                    if vid: no_sub_ids.add(vid)

    if not historico_ids and not info_ids and not no_sub_ids:
        return False

    migrated_count = 0
    for item in state_list:
        video_id = item.get("video_id")
        if not video_id: continue

        if video_id in historico_ids and not item.get("subtitle_downloaded"):
            item["subtitle_downloaded"] = True
            migrated_count += 1
            
        if video_id in info_ids and not item.get("info_downloaded"):
            item["info_downloaded"] = True
            migrated_count += 1
            
        if video_id in no_sub_ids and not item.get("has_no_subtitle"):
            item["has_no_subtitle"] = True
            migrated_count += 1

    if historico_path.is_file(): historico_path.rename(historico_path.with_suffix(".txt.bak"))
    if info_path.is_file(): info_path.rename(info_path.with_suffix(".txt.bak"))
    if no_sub_path.is_file(): no_sub_path.rename(no_sub_path.with_suffix(".txt.bak"))

    if migrated_count > 0:
        print_ok(f"Migração de arquivos de log textuais (legacy) detectada e concluída ({migrated_count} updates no JSON).")
    return True


def filter_state_list(
    full_state_list: list[dict], 
    date_limit_filter: str
) -> list[dict]:
    """
    Retorna a lista filtrada contendo apenas os ponteiros dos dicts onde os requisitos
    se encaixam no filtro de datas (se houver).
    Como python passa dicionários por referência, alterar a lista clonada altera o state orignal também.
    """
    if not full_state_list:
        return []

    # Aplica filtro de data (quando -d foi passado)
    if date_limit_filter:
        try:
            from yt_dlp.utils import DateRange
            parsed_date_str = DateRange.day(date_limit_filter).start
            if parsed_date_str:
                date_limit_filter = parsed_date_str.replace("-", "")
        except Exception:
            pass  # Fallback to string comparison
            
        filtered_list = []
        for v_dict in full_state_list:
            d_str = v_dict.get("publish_date", "N/A")
            if d_str and d_str != "N/A":
                # Remove hifens para comparação (YYYYMMDD ou len 8)
                d_str_clean = d_str.replace("-", "")
                if d_str_clean >= date_limit_filter:
                    filtered_list.append(v_dict)
        return filtered_list
        
    return list(full_state_list)


# ─── Pós-processamento de Legendas ────────────────────────────────────────────

SUBTITLE_INDEX_REGEX_PATTERN = re.compile(r"^\d+$")
SUBTITLE_TIMESTAMP_REGEX_PATTERN = re.compile(
    r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}"
)





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

        # ── Fase 4: Metadados de cabeçalho ────────────────────────────────────
        duration_str = str(subs[-1].end).split(',')[0]
        video_url = f"https://youtube.com/watch?v={video_id}"
        video_index = 1  # identificador sequencial padrão

        md_lines = [
            f"## {video_title} <a name=\"video-{video_index:02d}\"></a>\n",
            f"**URL:** {video_url}  \n",
            f"**Data:** {video_date}  \n",
            f"**Duração:** {duration_str}\n",
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
        md_lines.append("> **Nota do Sistema:** Transcrição limpa via Escriba.\n\n")

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
    Remove variações duplicadas de legenda geradas pelo yt-dlp,
    mantendo apenas o arquivo com o menor nome (ex: prefere 'pt' sobre 'pt-BR').
    Renomeia de '.pt.srt' para '-pt.srt'.
    Se convert_srt_to_md=True, retorna o Path para processamento MD posterior.
    Retorna (True, Path) se processou alguma legenda, caso contrário (False, None).
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

def download_video(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    video_id: str,
    language_opt_string: str,
    channel_dir_name: str,
    audio_only_flag: bool,
    output_dir_path: Path | None = None,
) -> int:
    """
    Executa o yt-dlp para baixar legendas ou áudio de um único vídeo.
    Retorna o exit code.
    """
    output_template_string = f"{channel_dir_name}-{video_id}"
    if audio_only_flag:
        output_template_string += ".%(ext)s"
        
    if output_dir_path:
        output_template_string = str(output_dir_path / output_template_string)

    download_cmd_list = (
        yt_dlp_cmd_list
        + ["--js-runtimes", f"node:{NODE_PATH}"]
        + ["--ignore-no-formats-error"]
        + ["--write-info-json"]
        + (["-f", "ba[ext=webm]"] if audio_only_flag else ["--skip-download", "--write-auto-sub", "--convert-subs", "srt"])
        + cookie_args_list
        + (["--sub-langs", language_opt_string] if not audio_only_flag else [])
        + ["-o", output_template_string]
        + [f"https://www.youtube.com/watch?v={video_id}"]
    )

    subprocess_instance = subprocess.Popen(download_cmd_list)
    try:
        subprocess_instance.wait()
    except KeyboardInterrupt:
        subprocess_instance.terminate()
        try:
            subprocess_instance.wait(timeout=5)
        except subprocess.TimeoutExpired:
            subprocess_instance.kill()
        raise  # repropaga para o handler principal
    return subprocess_instance.returncode


def harvest_and_delete_info_json(
    cwd_path: Path,
    channel_dir_name: str,
    video_id: str,
    video_dict: dict,
) -> bool:
    """
    Extrai metadados do arquivo .info.json (título, data, duração, views),
    atualiza o dicionário do vídeo em memória e remove o arquivo temporário.
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
    except Exception:
        pass
    finally:
        try:
            if info_json_path.exists():
                info_json_path.unlink()
        except Exception:
            pass
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
    cli_parser.add_argument("canal", nargs="?", default=None, help="Canal, playlist, vídeo ou URL (ex: @Canal, VIDEO_ID, URL de vídeo/playlist)")
    cli_parser.add_argument("-l", "--lang", default="", metavar="LANG",
                        help="Idioma das legendas (ex: pt, en). Padrão: idioma nativo do canal")
    cli_parser.add_argument("-a", "--audio-only", action="store_true",
                        help="Baixa APENAS o áudio do vídeo (webm/opus), sem legendas")
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
    cli_parser.add_argument("-v", "--version", action="version", version=f"Versão: {VERSION}")
    return cli_parser.parse_args()


# ─── Main ─────────────────────────────────────────────────────────────────────

# Regex para detectar YouTube video ID (exatamente 11 chars alfanuméricos + _ e -)
VIDEO_ID_REGEX_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_input_type(channel_input_string: str) -> tuple[str, str, str]:
    """
    Classifica a entrada do usuário e retorna (channel_url_string, input_type_string, video_id_string | "").
    input_type_string: 'video', 'playlist', ou 'channel'
    """
    # URL completa de vídeo
    if "watch?v=" in channel_input_string or "youtu.be/" in channel_input_string:
        channel_url_string = channel_input_string if channel_input_string.startswith("http") else f"https://www.youtube.com/watch?v={channel_input_string}"
        # Extrair video ID da URL
        regex_match_result = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", channel_url_string)
        video_id = regex_match_result.group(1) if regex_match_result else ""
        return channel_url_string, "video", video_id

    # ID avulso de vídeo (11 caracteres)
    if VIDEO_ID_REGEX_PATTERN.match(channel_input_string):
        channel_url_string = f"https://www.youtube.com/watch?v={channel_input_string}"
        return channel_url_string, "video", channel_input_string

    # Playlist
    if "playlist?list=" in channel_input_string:
        channel_url_string = channel_input_string if channel_input_string.startswith("http") else f"https://www.youtube.com/{channel_input_string}"
        return channel_url_string, "playlist", ""

    # Canal (handle ou URL)
    channel_url_string = channel_input_string if channel_input_string.startswith("http") else f"https://www.youtube.com/{channel_input_string}"
    return channel_url_string, "channel", ""


def setup_session(cli_args: argparse.Namespace) -> SessionConfig:
    """
    Etapa 1: monta a configuração da sessão, imprime header e seção de config.
    """
    cwd_path = Path.cwd()
    channel_dir_name = cwd_path.name
    script_dir_path, yt_dlp_cmd_list = setup_environment()
    
    # Auto-detecção de canal pelo state list quando não informado
    if not cli_args.canal:
        latest_json_path = get_latest_json_path(cwd_path)
        if not latest_json_path:
            print_err("Parâmetro 'canal' não fornecido e nenhum arquivo escriba_*.json encontrado para auto-completar.")
            print_info(f"{BOLD}Como usar:{RESET}")
            print_info(f"  python3 escriba.py {BCYAN}@Canal{RESET}")
            print_info(f"  python3 escriba.py {BCYAN}https://www.youtube.com/playlist?list=...{RESET}")
            print_info(f"  python3 escriba.py {BCYAN}VIDEO_ID{RESET}")
            sys.exit(1)
            
        try:
            with open(latest_json_path, "r", encoding="utf-8") as file_descriptor:
                json_data = json.load(file_descriptor)
                
            if isinstance(json_data, dict) and "channel" in json_data:
                cli_args.canal = json_data["channel"]
            else:
                match = re.search(r"(?:escriba_|lista_)(.+)\.json", latest_json_path.name)
                if match:
                    cli_args.canal = f"@{match.group(1)}"
                else:
                    print_err("Não foi possível inferir o canal a partir do JSON.")
                    sys.exit(1)
            print_info(f"Canal detectado automaticamente a partir de {latest_json_path.name}")
        except Exception as e:
            print_err(f"Erro ao ler JSON para auto-detecção: {e}")
            sys.exit(1)

    # Classificar entrada
    channel_input_string = cli_args.canal
    channel_url_string, input_type_string, single_video_id = parse_input_type(channel_input_string)

    # Modo de operação para o header
    md_label = "+MD" if cli_args.md else ""
    execution_mode_label = "Áudio" if cli_args.audio_only else f"Legendas/SRT{md_label} ({cli_args.lang or 'auto'})"
    if cli_args.date:
        execution_mode_label += f"  ·  a partir de {cli_args.date}"
    if cli_args.fast:
        execution_mode_label += "  ·  rápido"
    print_header(channel_input_string, VERSION, execution_mode_label)

    return SessionConfig(
        cwd_path=cwd_path,
        channel_dir_name=channel_dir_name,
        script_dir_path=script_dir_path,
        yt_dlp_cmd_list=yt_dlp_cmd_list,
        channel_input_url_or_handle=channel_input_string,
        channel_url=channel_url_string,
    )


def init_auth_and_language(
    session_config: SessionConfig, language_argument_string: str, force_refresh_cookies_flag: bool
) -> tuple[list[str], str]:
    """
    Etapa 2: configura cookies e detecta/define o idioma.
    Retorna (cookie_args_list, language_opt_string).
    """
    print_section("Autenticação")
    cookie_args_list = configure_cookies(session_config.cwd_path, session_config.script_dir_path, force_refresh_cookies_flag)

    print_section("Idioma")
    # Tenta obter cache antes de detectar
    _, _, cached_lang = load_or_create_channel_state(
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
        if not cookies_txt_path.is_file():
            print_warn("Executando warm-up para extrair cookies do Chrome silenciosamente...")
            subprocess.run(
                session_config.yt_dlp_cmd_list + cookie_args_list + ["--dump-json", "--playlist-items", "0", session_config.channel_url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        
        # Filtrar o lixo exportado
        filter_youtube_cookies(cookies_txt_path)
        
        # Reconfigurar para usar apenas o TXT lido do cache a partir de agora
        cookie_args_list = configure_cookies(session_config.cwd_path, session_config.script_dir_path, False)
        print_info("Cookies filtrados limitados ao YouTube (trackers removidos).")

    return cookie_args_list, language_opt_string


def process_videos(
    session_config: SessionConfig,
    cookie_args_list: list[str],
    language_opt_string: str,
    cli_args: argparse.Namespace,
) -> tuple[int, int, int, int]:
    """
    Etapa 3: itera o banco de dados JSON de estado (escriba_*.json), executando
    filtros incrementais em memória e processando as requisições yt-dlp.
    Retorna os contadores numéricos formatados para o summary da Etapa 4.
    """
    # Detectar se é vídeo avulso
    _, input_type_string, single_video_id = parse_input_type(session_config.channel_input_url_or_handle)
    
    print_section("Listagem de Vídeos e Tracking State")
    json_state_path, full_state_list, detected_lang_cached = load_or_create_channel_state(
        session_config.cwd_path, session_config.yt_dlp_cmd_list, cookie_args_list, session_config.channel_url
    )
    
    # Garantir que o idioma detectado esteja no arquivo caso tenha sido descoberto agora
    if language_opt_string and language_opt_string != detected_lang_cached:
        save_channel_state_json(json_state_path, full_state_list, detected_language=language_opt_string)
    
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

    if not working_state_list:
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
            save_channel_state_json(json_state_path, full_state_list, detected_language=language_opt_string)
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

                    if not cli_args.fast:
                        print_countdown(1, "Aguardando", sub_indent_space)
                else:
                    downloaded_videos_count += 1
                    
                    # Marcar o estado JSON se baixamos a legenda
                    if not cli_args.audio_only and has_downloaded_subtitle_flag:
                        video_dict["subtitle_downloaded"] = True
                        _dirty += 1
                        _flush()
                        
                    if not cli_args.fast:
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
        _flush(force=True)  # garante que nenhuma mutação pendente seja perdida

    # ---------- Processamento Deferido de MD --------------
    if pending_md_conversions:
        print()
        print_info(f"Fase 4: Clusterização de IA (TF-IDF) para {BOLD}{len(pending_md_conversions)}{RESET} vídeos...")
        for srt_path, vid_id, vid_title, vid_date in pending_md_conversions:
            if not srt_path.exists():
                continue
            
            print_dl(f"{vid_id}{RESET}  {DIM}gerando Cluster MD{RESET}", "  ")
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

    return downloaded_videos_count, skipped_videos_count, error_videos_count, total_videos_count, was_interrupted


def print_summary(downloaded_videos_count: int, skipped_videos_count: int, error_videos_count: int, total_videos_count: int) -> None:
    """Etapa 4: imprime o resumo final da sessão."""
    print(f"\n{DIV_THICK}")
    print(f"  {BOLD}{BWHITE}Sessão concluída{RESET}")
    print(f"{DIV_THICK}")
    print(f"  {ICON_OK}  Baixados   : {BGREEN}{downloaded_videos_count}{RESET}")
    print(f"  {ICON_SKIP}  Pulados    : {DIM}{skipped_videos_count}{RESET}")
    if error_videos_count:
        print(f"  {ICON_ERR}  Erros      : {BRED}{error_videos_count}{RESET}")
    print(f"  {ICON_INFO}  Total fila : {total_videos_count}")
    print()


def regen_md_from_srt_files() -> None:
    """Modo offline: varre archive/ e depois a pasta atual buscando .srt e regenera .md via TF-IDF."""
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

    print_header(cwd_path.name, VERSION, "Regeneração MD offline")

    total_count = len(srt_files_list)
    converted_count = 0
    skipped_count = 0
    current_label = ""

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
        if md_path.exists():
            print_skip(f"{srt_path.name}  {DIM}.md já existe — pulando{RESET}", indentation_prefix)
            skipped_count += 1
            continue

        print_dl(f"{srt_path.name}{RESET}  {DIM}gerando .md{RESET}", indentation_prefix)
        result_path = srt_to_md(srt_path, video_id, video_title, threshold=0.3, indentation_prefix="      ")

        if result_path:
            print_ok(f"salvo: {DIM}{result_path.name}{RESET}", "      ")
            converted_count += 1
        else:
            print_warn(f"falha ou vazio", "      ")

    # Resumo
    print(f"\n{DIV_THICK}")
    print(f"  {BOLD}{BWHITE}Regeneração concluída{RESET}")
    print(f"{DIV_THICK}")
    print(f"  {ICON_OK}  Convertidos : {BGREEN}{converted_count}{RESET}")
    print(f"  {ICON_SKIP}  Pulados     : {DIM}{skipped_count}{RESET}")
    print(f"  {ICON_INFO}  Total       : {total_count}")
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
    cli_args = parse_args()

    # Short-circuit: modo offline de regeneração MD
    if cli_args.regen_md:
        regen_md_from_srt_files()
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
    session_config = setup_session(cli_args)
    cookie_args_list, language_opt_string = init_auth_and_language(
        session_config, cli_args.lang, cli_args.refresh_cookies
    )
    downloaded_videos_count, skipped_videos_count, error_videos_count, total_videos_count, was_interrupted = process_videos(
        session_config, cookie_args_list, language_opt_string, cli_args
    )
    print_summary(downloaded_videos_count, skipped_videos_count, error_videos_count, total_videos_count)
    if was_interrupted:
        sys.exit(130)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print_warn(f"Interrompido pelo usuário (Ctrl+C).  {DIM}Saindo...{RESET}")
        sys.exit(130)  # Código 130 = SIGINT (padrão Unix)
