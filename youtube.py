import os
import sys
import subprocess
import json
import shutil
import re
from enum import IntEnum
from pathlib import Path
from collections import Counter
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from utils import (
    print_ok, print_warn, print_info, print_err, 
    ICON_WAIT, BOLD, RESET, BCYAN, format_date
)

"""
MÓDULO YOUTUBE: A Ponte com a Internet
--------------------------------------
Este módulo é responsável por toda a comunicação externa com o YouTube.
Ele utiliza a biblioteca/ferramenta 'yt-dlp' (um fork moderno do famoso youtube-dl) para:
1. Descobrir quais vídeos um canal possui (Scraping/Discovery).
2. Identificar o idioma predominante do canal por amostragem.
3. Baixar as legendas (.srt) e informações técnicas (.info.json) de cada vídeo.

Explicação para Iniciantes (Processos e Subprocessos):
O yt-dlp é um utilitário escrito em Python, mas é executado como uma aplicação
independente de linha de comando. Para falar com ele, o Python cria um "subprocesso"
(uma janela de terminal invisível rodando em segundo plano) usando o módulo `subprocess`
do próprio Python. Dessa forma, é como se nosso script estivesse controlando outra
aplicação de forma automática por baixo dos panos.
"""

class DownloadResult(IntEnum):
    """Códigos de retorno padronizados para operações de download."""
    SUCCESS = 0
    SKIPPED = 1
    FAILED = 2


DEFAULT_BROWSER: str = "firefox"
DEFAULT_LANGUAGE_FALLBACK: str = "pt"

# O NODE_PATH é necessário porque algumas páginas modernas do YouTube contêm scripts
# complicados para burlar bots. O yt-dlp roda esses scripts usando o Node.js instalado
# na máquina do usuário para simular um navegador de verdade.
NODE_PATH_STR: str = os.getenv("NODE_PATH") or shutil.which("node") or ""


def _is_rate_limit_error(error: Exception) -> bool:
    """Identifica se o erro é especificamente HTTP 429 ou limite de requisições excedido."""
    error_msg = str(error).lower()
    return "429" in error_msg or "too many requests" in error_msg


def _refresh_cookies_on_error(
    cwd_path_obj: Path, 
    script_dir_path_obj: Path, 
    browser_str: str = DEFAULT_BROWSER
) -> list[str]:
    """
    Técnica de Auto-Cura (Auto-Healing): Se o YouTube bloquear o acesso (erro HTTP 403),
    nós apagamos os cookies locais expirados e extraímos credenciais frescas do navegador.
    """
    print_warn("Erro ao acessar YouTube. Tentando corrigir cookies automaticamente...")
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    cookies_path_obj.unlink(missing_ok=True)
    return configure_cookies(
        cwd_path_obj, 
        script_dir_path_obj, 
        force_refresh_bool=True, 
        silent_bool=True, 
        browser_str=browser_str
    )


def _get_python_executable(script_dir_path_obj: Path) -> Path:
    """
    Identifica o executável do Python correto que reside dentro do ambiente virtual (.venv).
    Isso impede que o subprocesso use o interpretador global e acabe não encontrando o yt-dlp.
    """
    if os.name == "nt":  # Windows
        return script_dir_path_obj / ".venv" / "Scripts" / "python.exe"
    return script_dir_path_obj / ".venv" / "bin" / "python3"  # Mac/Linux


def setup_environment() -> tuple[Path, list[str]]:
    """
    Prepara o ambiente e define o comando base para chamar o yt-dlp.
    """
    script_dir_path_obj: Path = Path(__file__).parent.resolve()
    python_path_obj: Path = _get_python_executable(script_dir_path_obj)
    
    if not python_path_obj.is_file():
        print_err(f"Ambiente virtual não encontrado em {python_path_obj}")
        print_info("Dica: Monte o ambiente rodando: 'python3 -m venv .venv && pip install -r requirements.txt'")
        sys.exit(1)
        
    yt_dlp_cmd_list: list[str] = [str(python_path_obj), "-m", "yt_dlp", "--remote-components", "ejs:github"]
    
    if NODE_PATH_STR:
        yt_dlp_cmd_list.extend(["--js-runtimes", f"node:{NODE_PATH_STR}"])
        
    return script_dir_path_obj, yt_dlp_cmd_list


def configure_cookies(
    cwd_path_obj: Path, 
    script_dir_path_obj: Path, 
    force_refresh_bool: bool, 
    silent_bool: bool = False,
    browser_str: str | None = None
) -> list[str]:
    """
    Configura os cookies de autenticação para as requisições de download de forma pura,
    sem mutação de estado global.
    """
    active_browser = browser_str or DEFAULT_BROWSER
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    
    if force_refresh_bool:
        if not silent_bool: 
            print_warn("--refresh-cookies ativo. Purgando cookies em cache...")
        cookies_path_obj.unlink(missing_ok=True)
        
    # Se já temos o cache de cookies local válido, usamos diretamente
    if _is_valid_cookie_file(cookies_path_obj):
        if not silent_bool: 
            print_info(f"Usando arquivo de cookies: {cookies_path_obj.name}")
        return ["--cookies", str(cookies_path_obj)]
        
    # Caso contrário, extrai do navegador selecionado
    if not silent_bool: 
        print_warn(f"Extraindo credenciais de sessão do navegador '{active_browser}' → {cookies_path_obj.name}")
    return ["--cookies-from-browser", active_browser, "--cookies", str(cookies_path_obj)]


def _is_valid_cookie_file(path_obj: Path) -> bool:
    """Verifica se o arquivo de cookies existe e segue o formato padrão Netscape/cURL."""
    if not path_obj.is_file(): 
        return False
    try:
        with open(path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            content_snippet_str: str = file_descriptor_obj.read(100)
            return "Netscape" in content_snippet_str or "TRUE" in content_snippet_str
    except OSError:
        return False


def detect_language(
    yt_dlp_cmd_list: list[str], 
    cookie_args_list: list[str], 
    channel_url_str: str, 
    cached_lang_str: str | None = None
) -> str:
    """
    Detecta o idioma principal das legendas do canal analisando apenas os vídeos mais recentes por amostragem.
    """
    if cached_lang_str and cached_lang_str != "N/A":
        normalized_lang_str = _normalize_lang_pattern(cached_lang_str)
        print_ok(f"Idioma carregado do histórico: {BOLD}{normalized_lang_str.strip('^$.*')}{RESET}")
        return normalized_lang_str
        
    print_info("Detectando idioma predominante por amostragem (últimos 5 vídeos)...")
    
    urls_to_try: list[str] = [
        channel_url_str.rstrip("/"),
        channel_url_str.rstrip("/") + "/live",
        channel_url_str.rstrip("/") + "/videos"
    ]
    
    if "watch?v=" in channel_url_str:
        urls_to_try = [channel_url_str]

    langs_list: list[str] = []
    
    for url in urls_to_try:
        if langs_list: 
            break
        
        cmd_list: list[str] = yt_dlp_cmd_list + cookie_args_list + [
            "--print", "language", 
            "--playlist-end", "5", 
            "--ignore-errors", 
            "--no-warnings", 
            "--flat-playlist", 
            url
        ]
        
        try:
            process_result_obj = subprocess.run(
                cmd_list, capture_output=True, text=True, encoding="utf-8", timeout=20
            )
            current_langs = [
                line_str.strip().lower() 
                for line_str in process_result_obj.stdout.splitlines() 
                if line_str.strip() and line_str.lower() not in ("na", "none")
            ]
            langs_list.extend(current_langs)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as error_obj:
            print_warn(f"Aba {url} indisponível: {error_obj}")
    
    if langs_list:
        most_common_tuple: tuple[str, int] = Counter(langs_list).most_common(1)[0]
        most_common_lang_str: str = most_common_tuple[0]
        clean_lang_str: str = most_common_lang_str.split("-")[0].split("_")[0]
        print_ok(f"Idioma detectado com maior frequência: {BOLD}{clean_lang_str}{RESET}")
        return f"^{clean_lang_str}.*"
        
    fallback_lang_str: str = os.getenv("DEFAULT_LANGUAGE", DEFAULT_LANGUAGE_FALLBACK)
    if fallback_lang_str == "pt":
        print_warn(f"Idioma não detectado. Usando padrão expansivo: {BOLD}pt, en{RESET}")
        return "^(pt|en).*"
        
    print_warn(f"Idioma não detectado. Usando padrão de fallback: {BOLD}{fallback_lang_str}{RESET}")
    return f"^{fallback_lang_str}.*"


def generate_fast_list_json(
    yt_dlp_cmd_list: list[str], 
    cookie_args_list: list[str], 
    channel_url_str: str, 
    history_dict: dict[str, Any] | None = None,
    stop_at_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """
    Varre o canal do YouTube listando todos os vídeos de forma rápida via streaming de processo e Smart Sync.
    """
    print_info("Fase 1: Mapeando vídeos do canal...")
    
    urls_to_try = [channel_url_str]
    is_channel_base = ("@" in channel_url_str or "/channel/" in channel_url_str or "/c/" in channel_url_str)
    
    # Bolt: Replaced any() with tuple in endswith() for faster suffix matching
    if is_channel_base and not channel_url_str.rstrip("/").endswith(("/videos", "/streams", "/shorts", "/releases", "/playlists")):
        base_url = channel_url_str.rstrip("/")
        urls_to_try = [f"{base_url}/videos", f"{base_url}/streams", f"{base_url}/shorts"]
    
    videos_found_list: list[dict[str, Any]] = []
    stop_reached = False
    
    for current_url in urls_to_try:
        if stop_reached:
            break
        consecutive_known_count = 0
        MAX_CONSECUTIVE_KNOWN = 10
        
        cmd_list: list[str] = yt_dlp_cmd_list + cookie_args_list + [
            "--flat-playlist", "--dump-json", "--ignore-errors", "--no-warnings", 
            "--extractor-args", "youtubetab:approximate_date",
            current_url
        ]
        
        try:
            with subprocess.Popen(
                cmd_list, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8"
            ) as process_obj:
                if process_obj.stdout:
                    for line_str in process_obj.stdout:
                        stripped_line = line_str.strip()
                        if not stripped_line:
                            continue
                        try:
                            video_data_dict: dict[str, Any] = json.loads(stripped_line)
                        except json.JSONDecodeError:
                            continue
                        
                        video_id_str: str = video_data_dict.get("id", "")
                        if not video_id_str: 
                            continue
                        
                        if stop_at_ids and video_id_str in stop_at_ids:
                            consecutive_known_count += 1
                            if consecutive_known_count >= MAX_CONSECUTIVE_KNOWN:
                                process_obj.terminate()
                                stop_reached = True
                                break
                        else:
                            consecutive_known_count = 0

                        raw_date_any = video_data_dict.get("upload_date") or video_data_dict.get("publish_date") or video_data_dict.get("date")
                        if not raw_date_any and history_dict:
                            publish_date_str = history_dict.get(video_id_str, {}).get("publish_date", "Desconhecida")
                        else:
                            publish_date_str = format_date(raw_date_any)
                        
                        videos_found_list.append({
                            "video_id": video_id_str,
                            "title": video_data_dict.get("title") or "N/A",
                            "publish_date": publish_date_str,
                            "subtitle_downloaded": False,
                            "info_downloaded": False,
                            "has_no_subtitle": False
                        })
                        
                        sys.stdout.write(f"\r{ICON_WAIT}  {BCYAN}Vídeos mapeados: {len(videos_found_list)}{RESET}")
                        sys.stdout.flush()
                
                process_obj.wait()
                print()
                
                if process_obj.returncode != 0 and not videos_found_list and not (stop_at_ids and process_obj.returncode == -15):
                    _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())
                
        except (subprocess.SubprocessError, OSError) as error_obj:
            print_err(f"Falha crítica na descoberta: {error_obj}")
            return []
    
    return videos_found_list


def _normalize_lang_pattern(lang_str: str) -> str:
    """Garante que a string do idioma esteja no formato de regex esperado pelo yt-dlp."""
    if not lang_str or lang_str == "N/A":
        return lang_str
    if lang_str.startswith("^") or ".*" in lang_str or "|" in lang_str:
        return lang_str
    return f"^{lang_str}.*"


def escriba_progress_hook(d: dict[str, Any]) -> None:
    """
    Callback invocado periodicamente pelo yt-dlp durante o download de arquivos.
    No Windows, força o interpretador a checar sinais pendentes (KeyboardInterrupt).
    """
    if getattr(sys, "_escriba_interrupted", False):
        raise KeyboardInterrupt


def _try_extract_and_download(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    url: str,
    output_template_str: str,
    lang_pattern: str,
    lang_regex: re.Pattern,
    download_video_only_hd: bool
) -> None:
    """
    Executa a extração em memória e download de legendas/metadados com yt-dlp.
    Lança exceções específicas em caso de falha.
    """
    download_args = ["-f", "bestvideo[height<=1080]"] if download_video_only_hd else ["--skip-download"]
    
    base_args = yt_dlp_cmd_list[3:] + cookie_args_list + [
        "--ignore-no-formats-error",
        "--write-info-json",
        "--restrict-filenames",
    ]
    base_args.extend(download_args)
    base_args.extend([
        "--write-sub",
        "--write-auto-sub",
        "--convert-subs", "srt",
        "--no-warnings",
        "--sub-langs", lang_pattern,
        "-o", output_template_str,
        url
    ])

    parsed_opts = yt_dlp.parse_options(base_args)[3]

    extract_opts = dict(parsed_opts)
    extract_opts.update({
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
    })

    with yt_dlp.YoutubeDL(extract_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise ValueError("Não foi possível extrair informações do vídeo (info é None)")

    subtitles = info.get('subtitles') or {}
    auto_captions = info.get('automatic_captions') or {}

    chosen_lang: str | None = None
    is_auto: bool = False

    # Prioridade 1: Legenda manual (humana)
    for lang_code in subtitles.keys():
        if lang_regex.match(lang_code):
            chosen_lang = lang_code
            is_auto = False
            break

    # Prioridade 2: Legenda automática (IA)
    if not chosen_lang:
        for lang_code in auto_captions.keys():
            if lang_regex.match(lang_code):
                chosen_lang = lang_code
                is_auto = True
                break

    download_opts = dict(parsed_opts)
    download_opts['progress_hooks'] = [escriba_progress_hook]

    if chosen_lang:
        download_opts.update({
            'writesubtitles': not is_auto,
            'writeautomaticsub': is_auto,
            'subtitleslangs': [chosen_lang],
        })

        source_dict = auto_captions if is_auto else subtitles
        formats = source_dict.get(chosen_lang, [])
        if formats:
            selected_format = next((f for f in formats if f.get('ext') == 'vtt'), formats[0])
            info['requested_subtitles'] = {
                chosen_lang: {
                    'ext': selected_format.get('ext'),
                    'data': selected_format.get('data'),
                    'url': selected_format.get('url'),
                }
            }
        else:
            info['requested_subtitles'] = {}
    else:
        download_opts.update({
            'writesubtitles': False,
            'writeautomaticsub': False,
            'subtitleslangs': [],
        })
        info['requested_subtitles'] = {}

    with yt_dlp.YoutubeDL(download_opts) as ydl_dl:
        ydl_dl.process_info(info)


def download_video(
    yt_dlp_cmd_list: list[str], 
    cookie_args_list: list[str], 
    video_id_str: str, 
    lang_filter_str: str, 
    folder_name_str: str,
    download_video_only_hd: bool = False
) -> int:
    """
    Orquestra o download de metadados e legendas de um vídeo do YouTube,
    com política de auto-healing para renovação de cookies e tratamento de rate limits.
    """
    output_template_str: str = f"{folder_name_str}-{video_id_str}.%(ext)s"
    url = f"https://www.youtube.com/watch?v={video_id_str}"
    
    # Valida formato do ID (exatamente 11 caracteres para YouTube)
    if not (video_id_str and len(video_id_str) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", video_id_str)):
        print_err(f"Incomplete YouTube ID {video_id_str}. URL {url} looks truncated.")
        return int(DownloadResult.FAILED)
    
    lang_pattern = _normalize_lang_pattern(lang_filter_str)
    lang_regex = re.compile(lang_pattern, re.IGNORECASE)
    current_cookies = list(cookie_args_list)
    auto_heal_attempted = False

    while True:
        try:
            _try_extract_and_download(
                yt_dlp_cmd_list=yt_dlp_cmd_list,
                cookie_args_list=current_cookies,
                url=url,
                output_template_str=output_template_str,
                lang_pattern=lang_pattern,
                lang_regex=lang_regex,
                download_video_only_hd=download_video_only_hd
            )
            return int(DownloadResult.SUCCESS)

        except Exception as error_obj:
            if getattr(sys, "_escriba_interrupted", False):
                raise KeyboardInterrupt

            if _is_rate_limit_error(error_obj):
                print_warn(f"\n⚠ [HTTP 429] Limite de requisições excedido no vídeo {video_id_str}.")
                print_warn("O YouTube bloqueou temporariamente este IP ou sessão (Too Many Requests).")
                print_warn("Por favor, realize os seguintes passos para liberação:")
                print_warn("  1. Abra o YouTube no navegador Google Chrome desta máquina.")
                print_warn("  2. Reproduza qualquer vídeo para verificar/resolver CAPTCHAs.")
                print_warn("  3. Caso o IP esteja bloqueado, altere a VPN ou mude sua conexão.")
                print_info("Pressione ENTER para renovar os cookies e tentar novamente, digite 'p' + ENTER para pular este vídeo, ou Ctrl+C para abortar...")

                try:
                    if not sys.stdin.isatty():
                        print_warn("Ambiente não-interativo detectado. Pulando vídeo automaticamente devido a erro HTTP 429.")
                        return int(DownloadResult.SKIPPED)
                    user_input = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print_err("\nProcesso interrompido pelo usuário.")
                    raise KeyboardInterrupt

                if user_input == "p":
                    print_warn(f"Vídeo {video_id_str} pulado pelo usuário devido a limite de requisições.")
                    return int(DownloadResult.SKIPPED)

                try:
                    current_cookies = _refresh_cookies_on_error(
                        Path.cwd(), Path(__file__).parent.resolve()
                    )
                except OSError as e:
                    print_warn(f"Erro ao renovar cookies: {e}")
                continue

            # Auto-healing padrão para erros normais de autenticação / cookies expirados
            if not auto_heal_attempted:
                auto_heal_attempted = True
                print_warn(f"Erro ao baixar vídeo {video_id_str}: {error_obj}. Tentando renovar cookies do navegador...")
                try:
                    current_cookies = _refresh_cookies_on_error(
                        Path.cwd(), Path(__file__).parent.resolve()
                    )
                    continue
                except OSError as e:
                    print_err(f"Falha ao renovar cookies: {e}")
                    return int(DownloadResult.FAILED)

            print_err(f"Erro crítico após renovar cookies no vídeo {video_id_str}: {error_obj}")
            return int(DownloadResult.FAILED)


def filter_youtube_cookies(cookies_path_obj: Path) -> None:
    """
    Limpa o arquivo de cookies extraído, mantendo apenas o que pertence ao Google/YouTube
    e restringindo permissões do arquivo (0o600).
    """
    if not cookies_path_obj.exists():
        return

    try:
        with open(cookies_path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            lines_list: list[str] = file_descriptor_obj.readlines()

        filtered_lines_list: list[str] = []
        allowed_domains = ["youtube.com", "google.com"]
        for line_str in lines_list:
            if line_str.startswith("#") and not line_str.startswith("#HttpOnly_"):
                filtered_lines_list.append(line_str)
                continue

            cookie_line = line_str[10:] if line_str.startswith("#HttpOnly_") else line_str
            parts = cookie_line.split("\t")
            if parts:
                domain = parts[0].strip()
                for allowed in allowed_domains:
                    if domain.endswith("." + allowed) or domain == allowed:
                        filtered_lines_list.append(line_str)
                        break

        with open(cookies_path_obj, "w", encoding="utf-8") as file_descriptor_obj:
            file_descriptor_obj.writelines(filtered_lines_list)
        
        try:
            cookies_path_obj.chmod(0o600)
        except OSError:
            pass  # Em alguns sistemas de arquivo Windows, chmod pode ser no-op
            
    except OSError as error_obj:
        print_warn(f"Não foi possível higienizar os cookies extraídos: {error_obj}")
