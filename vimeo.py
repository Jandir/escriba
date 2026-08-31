import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from enum import IntEnum
from pathlib import Path
from typing import Any

import yt_dlp

from utils import (
    BCYAN,
    BOLD,
    ICON_WAIT,
    RESET,
    format_date,
    print_err,
    print_info,
    print_ok,
    print_warn,
)

"""
MÓDULO VIMEO: Acesso ao Vimeo via yt-dlp
---------------------------------------
Este módulo é responsável por toda a comunicação externa com a plataforma Vimeo.
Ele funciona de forma muito similar ao youtube.py, mas com adaptações necessárias
para as particularidades da API do Vimeo e da sua estrutura de arquivos/vídeos.

Explicação para Iniciantes (Reutilização de Código / Abstração):
- Em vez de reescrever toda a lógica complexa de cookies, nós simplesmente importamos
  a função `configure_cookies` do módulo `youtube.py` (`from youtube import configure_cookies`).
  Isso segue o princípio DRY (Don't Repeat Yourself - Não se Repita), diminuindo a
  duplicação de código e tornando a manutenção futura muito mais fácil!
"""


class DownloadResult(IntEnum):
    """Códigos de retorno padronizados para operações de download."""
    SUCCESS = 0
    SKIPPED = 1
    FAILED = 2


DEFAULT_LANGUAGE_FALLBACK: str = "pt"
MAX_CONSECUTIVE_KNOWN: int = 10

# Identifica o js-runtime Node.js
NODE_PATH_STR: str = os.getenv("NODE_PATH") or shutil.which("node") or ""


def _is_rate_limit_error(error_obj: Exception) -> bool:
    """Identifica se o erro é especificamente HTTP 429 ou limite de requisições excedido."""
    error_msg_str: str = str(error_obj).lower()
    return "429" in error_msg_str or "too many requests" in error_msg_str


def _refresh_cookies_on_error(cwd_path_obj: Path, script_dir_path_obj: Path) -> list[str]:
    """
    Técnica de Auto-Cura para o Vimeo.
    Se a requisição retornar falha de segurança, removemos o cache local
    e re-importamos a rotina de extração automática de cookies.
    """
    print_warn("Erro ao acessar Vimeo. Tentando renovar cookies do Chrome...")
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    cookies_path_obj.unlink(missing_ok=True)
    from youtube import configure_cookies
    return configure_cookies(
        cwd_path_obj,
        script_dir_path_obj,
        force_refresh_bool=True,
        silent_bool=True
    )


def _sample_channel_video_ids(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    channel_url_str: str
) -> list[str]:
    """Obtém os IDs dos 3 primeiros vídeos do canal para amostragem."""
    list_cmd_list: list[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist", "--dump-json", "--playlist-items", "1-3", channel_url_str
    ]
    video_ids_list: list[str] = []
    try:
        proc_obj = subprocess.run(
            list_cmd_list, capture_output=True, text=True, encoding="utf-8", timeout=30
        )
        if proc_obj.returncode == 0:
            for line_str in proc_obj.stdout.splitlines():
                try:
                    video_dict: dict[str, Any] = json.loads(line_str.strip())
                    v_id_str: str = str(video_dict.get("id", ""))
                    if v_id_str:
                        video_ids_list.append(v_id_str)
                except (json.JSONDecodeError, ValueError):
                    continue
    except (subprocess.SubprocessError, OSError) as error_obj:
        print_warn(f"Erro ao listar vídeos para amostragem no Vimeo: {error_obj}")
    return video_ids_list


def _fetch_video_available_languages(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    video_id_str: str
) -> list[str]:
    """Obtém as faixas de legendas disponíveis para um vídeo específico do Vimeo."""
    meta_cmd_list: list[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--dump-json", "--skip-download", f"https://vimeo.com/{video_id_str}"
    ]
    try:
        meta_res_obj = subprocess.run(
            meta_cmd_list, capture_output=True, text=True, encoding="utf-8", timeout=20
        )
        if meta_res_obj.returncode == 0 and meta_res_obj.stdout:
            meta_data_dict: dict[str, Any] = json.loads(meta_res_obj.stdout)
            subs_dict: dict[str, Any] = meta_data_dict.get("subtitles") or {}
            auto_subs_dict: dict[str, Any] = meta_data_dict.get("automatic_captions") or {}
            return list(subs_dict.keys()) + list(auto_subs_dict.keys())
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        pass
    return []


def _determine_most_common_lang(
    detected_langs_list: list[str],
    fallback_lang_str: str
) -> str:
    """Calcula o idioma mais frequente da lista ou aplica o padrão de fallback."""
    if detected_langs_list:
        most_common_tuple: tuple[str, int] = Counter(detected_langs_list).most_common(1)[0]
        most_common_lang_str: str = most_common_tuple[0]
        base_lang_str: str = most_common_lang_str.split("-")[0].split("_")[0]
        print_ok(f"Idioma detectado por amostragem: {BOLD}{base_lang_str}{RESET}")
        return f"^{base_lang_str}.*"

    print_warn(f"Detecção falhou. Usando padrão de fallback: {BOLD}{fallback_lang_str}{RESET}")
    return f"^{fallback_lang_str}.*"


def detect_language(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    channel_url_str: str,
    cached_lang_str: str | None = None
) -> str:
    """
    Detecta o idioma predominante das legendas de um canal do Vimeo por amostragem rápida.
    """
    if cached_lang_str and cached_lang_str != "N/A":
        print_ok(f"Idioma carregado do histórico (Vimeo): {BOLD}{cached_lang_str.strip('^$')}{RESET}")
        return cached_lang_str

    print_info("Detectando idioma predominante no canal Vimeo (amostragem dos 3 primeiros vídeos)...")
    video_ids_list: list[str] = _sample_channel_video_ids(
        yt_dlp_cmd_list, cookie_args_list, channel_url_str
    )

    detected_langs_list: list[str] = []
    for v_id_str in video_ids_list:
        available_langs_list: list[str] = _fetch_video_available_languages(
            yt_dlp_cmd_list, cookie_args_list, v_id_str
        )
        detected_langs_list.extend(available_langs_list)

    fallback_lang_str: str = os.getenv("DEFAULT_LANGUAGE", DEFAULT_LANGUAGE_FALLBACK)
    return _determine_most_common_lang(detected_langs_list, fallback_lang_str)


def _build_fast_list_cmd(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    channel_url_str: str
) -> list[str]:
    """Monta a lista de argumentos de comando para varredura veloz do Vimeo."""
    return yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist", "--dump-json", "--ignore-errors", channel_url_str
    ]


def _parse_vimeo_video_record(
    line_str: str,
    channel_url_str: str,
    history_dict: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Converte uma linha JSON do dump de listagem do Vimeo em registro estruturado."""
    try:
        video_data_dict: dict[str, Any] = json.loads(line_str.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    video_id_str: str = str(video_data_dict.get("id", ""))
    if not video_id_str:
        return None

    raw_date_any = (
        video_data_dict.get("upload_date")
        or video_data_dict.get("publish_date")
        or video_data_dict.get("date")
    )
    if not raw_date_any and history_dict:
        publish_date_str: str = history_dict.get(video_id_str, {}).get("publish_date", "Desconhecida")
    else:
        publish_date_str = format_date(raw_date_any)

    return {
        "video_id": video_id_str,
        "title": video_data_dict.get("title") or "N/A",
        "publish_date": publish_date_str,
        "source_channel": channel_url_str,
        "subtitle_downloaded": False,
        "info_downloaded": False,
        "has_no_subtitle": False,
    }


def generate_fast_list_json(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    channel_url_str: str,
    history_dict: dict[str, Any] | None = None,
    stop_at_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """
    Varre um canal/showcase do Vimeo listando os vídeos de forma veloz com Smart Sync.
    """
    print_info("Fase 1: Mapeando vídeos do Vimeo...")
    cmd_list: list[str] = _build_fast_list_cmd(yt_dlp_cmd_list, cookie_args_list, channel_url_str)
    videos_found_list: list[dict[str, Any]] = []
    consecutive_known_count_int: int = 0

    try:
        with subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8"
        ) as process_obj:
            if process_obj.stdout:
                for line_str in process_obj.stdout:
                    record_dict: dict[str, Any] | None = _parse_vimeo_video_record(
                        line_str, channel_url_str, history_dict
                    )
                    if not record_dict:
                        continue

                    video_id_str: str = record_dict["video_id"]
                    if stop_at_ids and video_id_str in stop_at_ids:
                        consecutive_known_count_int += 1
                        if consecutive_known_count_int >= MAX_CONSECUTIVE_KNOWN:
                            process_obj.terminate()
                            break
                    else:
                        consecutive_known_count_int = 0

                    videos_found_list.append(record_dict)
                    sys.stdout.write(
                        f"\r{ICON_WAIT}  {BCYAN}Vídeos mapeados: {len(videos_found_list)}{RESET}"
                    )
                    sys.stdout.flush()

            process_obj.wait()
            print()

            if process_obj.returncode != 0 and not videos_found_list and not (stop_at_ids and process_obj.returncode == -15):
                _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())

        return videos_found_list

    except (subprocess.SubprocessError, OSError) as error_obj:
        print_err(f"Falha crítica na descoberta do Vimeo: {error_obj}")
        return []


def escriba_progress_hook(d: dict[str, Any]) -> None:
    """Callback invocado periodicamente pelo yt-dlp durante o download de arquivos."""
    if getattr(sys, "_escriba_interrupted", False):
        raise KeyboardInterrupt


def _build_vimeo_base_args(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    lang_filter_str: str,
    output_template_str: str,
    vimeo_url_str: str,
    download_video_only_hd_bool: bool
) -> list[str]:
    """Monta a lista de argumentos base para download de vídeo e metadados no Vimeo."""
    base_args_list: list[str] = yt_dlp_cmd_list[3:] + cookie_args_list + [
        "--ignore-no-formats-error",
        "--write-info-json",
        "--restrict-filenames",
    ]
    download_args_list: list[str] = (
        ["-f", "bestvideo[height<=1080]"]
        if download_video_only_hd_bool
        else ["--skip-download"]
    )
    base_args_list.extend(download_args_list)
    base_args_list.extend([
        "--write-sub",
        "--write-auto-sub",
        "--convert-subs", "srt",
        "--sub-langs", f"{lang_filter_str},pt.*,en.*",
        "--extractor-args", "vimeo:dash_manifest=false",
        "-o", output_template_str,
        vimeo_url_str
    ])
    return base_args_list


def _find_best_vimeo_subtitle(
    subtitles_dict: dict[str, Any],
    auto_captions_dict: dict[str, Any],
    lang_filter_str: str
) -> tuple[str | None, bool]:
    """Identifica a melhor legenda disponível respeitando a ordem de prioridades."""
    from youtube import _normalize_lang_pattern

    patterns_to_try_list: list[tuple[str, bool]] = [
        (lang_filter_str, False),
        (lang_filter_str, True),
        ("^pt.*", False),
        ("^pt.*", True),
        ("^en.*", False),
        ("^en.*", True),
    ]

    for pat_str, want_auto_bool in patterns_to_try_list:
        if not pat_str:
            continue
        normalized_pat_str: str = _normalize_lang_pattern(pat_str)
        regex_obj = re.compile(normalized_pat_str, re.IGNORECASE)
        source_dict: dict[str, Any] = auto_captions_dict if want_auto_bool else subtitles_dict

        for lang_code_str in source_dict.keys():
            if regex_obj.match(lang_code_str):
                return lang_code_str, want_auto_bool

    return None, False


def _configure_requested_subtitles(
    info_dict: dict[str, Any],
    download_opts_dict: dict[str, Any],
    chosen_lang_str: str | None,
    is_auto_bool: bool
) -> None:
    """Configura o dicionário de opções do yt-dlp e as faixas de legenda solicitadas."""
    if not chosen_lang_str:
        download_opts_dict.update({
            "writesubtitles": False,
            "writeautomaticsub": False,
            "subtitleslangs": [],
        })
        info_dict["requested_subtitles"] = {}
        return

    download_opts_dict.update({
        "writesubtitles": not is_auto_bool,
        "writeautomaticsub": is_auto_bool,
        "subtitleslangs": [chosen_lang_str],
    })

    source_dict: dict[str, Any] = (
        info_dict.get("automatic_captions", {})
        if is_auto_bool
        else info_dict.get("subtitles", {})
    )
    formats_list: list[dict[str, Any]] = source_dict.get(chosen_lang_str, [])
    if formats_list:
        selected_format_dict: dict[str, Any] = next(
            (f for f in formats_list if f.get("ext") == "vtt"),
            formats_list[0]
        )
        info_dict["requested_subtitles"] = {
            chosen_lang_str: {
                "ext": selected_format_dict.get("ext"),
                "data": selected_format_dict.get("data"),
                "url": selected_format_dict.get("url"),
            }
        }
    else:
        info_dict["requested_subtitles"] = {}


def _try_extract_and_download(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    vimeo_url_str: str,
    output_template_str: str,
    lang_filter_str: str,
    download_video_only_hd_bool: bool
) -> None:
    """Executa a extração e o download de legendas/vídeo do Vimeo."""
    base_args_list: list[str] = _build_vimeo_base_args(
        yt_dlp_cmd_list=yt_dlp_cmd_list,
        cookie_args_list=cookie_args_list,
        lang_filter_str=lang_filter_str,
        output_template_str=output_template_str,
        vimeo_url_str=vimeo_url_str,
        download_video_only_hd_bool=download_video_only_hd_bool,
    )
    parsed_opts_tuple = yt_dlp.parse_options(base_args_list)
    parsed_opts_dict: dict[str, Any] = parsed_opts_tuple[3]

    extract_opts_dict: dict[str, Any] = dict(parsed_opts_dict)
    extract_opts_dict.update({
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
    })

    with yt_dlp.YoutubeDL(extract_opts_dict) as ydl_extractor_obj:
        info_dict: dict[str, Any] | None = ydl_extractor_obj.extract_info(vimeo_url_str, download=False)

    if info_dict is None:
        raise ValueError("Não foi possível extrair informações do vídeo Vimeo (info é None)")

    subtitles_dict: dict[str, Any] = info_dict.get("subtitles") or {}
    auto_captions_dict: dict[str, Any] = info_dict.get("automatic_captions") or {}
    chosen_lang_str, is_auto_bool = _find_best_vimeo_subtitle(
        subtitles_dict, auto_captions_dict, lang_filter_str
    )

    download_opts_dict: dict[str, Any] = dict(parsed_opts_dict)
    download_opts_dict["progress_hooks"] = [escriba_progress_hook]
    _configure_requested_subtitles(info_dict, download_opts_dict, chosen_lang_str, is_auto_bool)

    with yt_dlp.YoutubeDL(download_opts_dict) as ydl_downloader_obj:
        ydl_downloader_obj.process_info(info_dict)


def download_video(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    video_id_str: str,
    lang_filter_str: str,
    folder_name_str: str,
    download_video_only_hd: bool = False
) -> int:
    """
    Baixa metadados e apenas uma legenda específica para um vídeo do Vimeo com auto-healing.
    """
    if not (video_id_str and re.match(r"^\d{7,12}$", video_id_str)):
        print_err(f"ID do Vimeo inválido ou truncado: {video_id_str}")
        return int(DownloadResult.FAILED)

    output_template_str: str = f"{folder_name_str}-{video_id_str}.%(ext)s"
    vimeo_url_str: str = f"https://vimeo.com/{video_id_str}"
    current_cookies_list: list[str] = list(cookie_args_list)
    auto_heal_attempted_bool: bool = False

    while True:
        try:
            _try_extract_and_download(
                yt_dlp_cmd_list=yt_dlp_cmd_list,
                cookie_args_list=current_cookies_list,
                vimeo_url_str=vimeo_url_str,
                output_template_str=output_template_str,
                lang_filter_str=lang_filter_str,
                download_video_only_hd_bool=download_video_only_hd,
            )
            return int(DownloadResult.SUCCESS)

        except Exception as error_obj:
            if getattr(sys, "_escriba_interrupted", False):
                raise KeyboardInterrupt

            if _is_rate_limit_error(error_obj):
                print_warn(f"\n⚠ [HTTP 429] Limite de requisições excedido no Vimeo ({video_id_str}).")
                return int(DownloadResult.FAILED)

            if not auto_heal_attempted_bool:
                auto_heal_attempted_bool = True
                print_warn(f"Erro ao baixar vídeo Vimeo {video_id_str}: {error_obj}. Tentando renovar cookies...")
                try:
                    current_cookies_list = _refresh_cookies_on_error(
                        Path.cwd(), Path(__file__).parent.resolve()
                    )
                    continue
                except (OSError, RuntimeError) as refresh_err_obj:
                    print_err(f"Falha ao renovar cookies Vimeo: {refresh_err_obj}")
                    return int(DownloadResult.FAILED)

            print_err(f"Erro crítico Vimeo após renovar cookies no vídeo {video_id_str}: {error_obj}")
            return int(DownloadResult.FAILED)


def _is_allowed_vimeo_domain(domain_str: str, allowed_domains_list: list[str]) -> bool:
    """Verifica se um domínio de cookie pertence ao Vimeo ou CDNs autorizadas."""
    return any(domain_str.endswith("." + allowed) or domain_str == allowed for allowed in allowed_domains_list)


def filter_vimeo_cookies(cookies_path_obj: Path) -> None:
    """
    Limpa o arquivo de cookies extraído, mantendo apenas cookies do Vimeo e Akamai CDN.
    """
    if not cookies_path_obj.is_file():
        return

    try:
        with open(cookies_path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            lines_list: list[str] = file_descriptor_obj.readlines()

        filtered_lines_list: list[str] = []
        allowed_domains_list: list[str] = ["vimeo.com", "akamaized.net"]

        for line_str in lines_list:
            if line_str.startswith("#") and not line_str.startswith("#HttpOnly_"):
                filtered_lines_list.append(line_str)
                continue

            cookie_line_str: str = line_str[10:] if line_str.startswith("#HttpOnly_") else line_str
            parts_list: list[str] = cookie_line_str.split("\t")
            if parts_list:
                domain_str: str = parts_list[0].strip()
                if _is_allowed_vimeo_domain(domain_str, allowed_domains_list):
                    filtered_lines_list.append(line_str)

        with open(cookies_path_obj, "w", encoding="utf-8") as file_descriptor_obj:
            file_descriptor_obj.writelines(filtered_lines_list)

        try:
            cookies_path_obj.chmod(0o600)
        except OSError:
            pass

    except OSError as error_obj:
        print_warn(f"Não foi possível higienizar os cookies Vimeo: {error_obj}")
