import os
import sys
import subprocess
import json
import shutil
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from collections import Counter
from utils import (
    print_ok, print_warn, print_info, print_err, 
    ICON_WAIT, BOLD, RESET, BCYAN, format_date
)

"""
MÓDULO VIMEO: Acesso ao Vimeo via yt-dlp
---------------------------------------
Este módulo é responsável pela comunicação com o Vimeo.
"""

NODE_PATH_STR: str = os.getenv("NODE_PATH") or shutil.which("node") or ""

def _refresh_cookies_on_error(cwd_path_obj: Path, script_dir_path_obj: Path) -> List[str]:
    print_warn("Erro ao acessar Vimeo. Tentando corrigir cookies...")
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    cookies_path_obj.unlink(missing_ok=True)
    from youtube import configure_cookies # Reutiliza a lógica de cookies do youtube.py
    return configure_cookies(cwd_path_obj, script_dir_path_obj, force_refresh_bool=True, silent_bool=True)

def detect_language(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    channel_url_str: str, 
    cached_lang_str: Optional[str] = None
) -> str:
    """
    Detecta o idioma predominante no canal Vimeo amostrando os primeiros vídeos.
    """
    if cached_lang_str and cached_lang_str != "N/A":
        print_ok(f"Idioma em cache: {BOLD}{cached_lang_str.strip('^$')}{RESET}")
        return cached_lang_str
        
    print_info(f"Detectando idioma predominante no canal Vimeo...")
    
    # Amostra os primeiros 3 vídeos para detectar o idioma das legendas
    list_cmd: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist", "--dump-json", "--playlist-items", "1-3", channel_url_str
    ]
    
    detected_langs_list: List[str] = []
    try:
        process_obj = subprocess.run(list_cmd, capture_output=True, text=True, timeout=30)
        if process_obj.returncode == 0:
            for line_str in process_obj.stdout.splitlines():
                try:
                    video_brief_dict = json.loads(line_str)
                    v_id_str = video_brief_dict.get("id")
                    if v_id_str:
                        # Obtém metadados completos do vídeo para ver as legendas
                        meta_cmd = yt_dlp_cmd_list + cookie_args_list + [
                            "--dump-json", "--skip-download", f"https://vimeo.com/{v_id_str}"
                        ]
                        meta_res_obj = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=20)
                        if meta_res_obj.returncode == 0:
                            meta_data_dict = json.loads(meta_res_obj.stdout)
                            subs_dict = meta_data_dict.get("subtitles", {})
                            auto_subs_dict = meta_data_dict.get("automatic_captions", {})
                            
                            # Coleta todos os códigos de idioma disponíveis
                            available_langs = list(subs_dict.keys()) + list(auto_subs_dict.keys())
                            detected_langs_list.extend(available_langs)
                except Exception:
                    continue
    except Exception as error_obj:
        print_warn(f"Erro durante amostragem de idioma: {error_obj}")

    if detected_langs_list:
        # Pega o idioma mais comum, ignorando dialetos específicos se possível
        most_common_lang_str = Counter(detected_langs_list).most_common(1)[0][0]
        base_lang_str = most_common_lang_str.split("-")[0].split("_")[0]
        final_filter_str = f"^{base_lang_str}.*"
        print_ok(f"Idioma detectado via amostragem: {BOLD}{base_lang_str}{RESET}")
        return final_filter_str

    fallback_lang_str: str = os.getenv("DEFAULT_LANGUAGE", "pt")
    print_warn(f"Detecção automática falhou. Usando padrão: {BOLD}{fallback_lang_str}{RESET}")
    return f"^{fallback_lang_str}.*"

def generate_fast_list_json(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    channel_url_str: str, 
    history_dict: Optional[Dict[str, Any]] = None,
    stop_at_ids: Optional[set] = None
) -> List[Dict[str, Any]]:
    print_info(f"Fase 1: Mapeando vídeos do Vimeo...")
    
    cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist", "--dump-json", "--ignore-errors", channel_url_str
    ]
    videos_found_list: List[Dict[str, Any]] = []
    
    try:
        process_obj = subprocess.Popen(
            cmd_list, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        
        if process_obj.stdout:
            for line_str in process_obj.stdout:
                try:
                    video_data_dict: Dict = json.loads(line_str.strip())
                    video_id_str: str = str(video_data_dict.get("id", ""))
                    if not video_id_str: 
                        continue
                    
                    if stop_at_ids and video_id_str in stop_at_ids:
                        process_obj.terminate()
                        break

                    raw_date_any = video_data_dict.get("upload_date") or video_data_dict.get("publish_date") or video_data_dict.get("date")
                    if not raw_date_any and history_dict:
                        publish_date_str = history_dict.get(video_id_str, {}).get("publish_date", "Desconhecida")
                    else:
                        publish_date_str = format_date(raw_date_any)
                    
                    videos_found_list.append({
                        "video_id": video_id_str,
                        "title": video_data_dict.get("title") or "N/A",
                        "publish_date": publish_date_str,
                        "source_channel": channel_url_str,
                        "subtitle_downloaded": False,
                        "info_downloaded": False,
                        "has_no_subtitle": False
                    })
                    
                    sys.stdout.write(f"\r{ICON_WAIT}  {BCYAN}Vídeos mapeados: {len(videos_found_list)}{RESET}")
                    sys.stdout.flush()
                    
                except Exception:
                    continue
                    
        process_obj.wait()
        print()
        
        if process_obj.returncode != 0 and not videos_found_list and not (stop_at_ids and process_obj.returncode == -15):
            _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())
            
        return videos_found_list
    
    except Exception as error_obj:
        print_err(f"Falha crítica na descoberta Vimeo: {error_obj}")
        return []

def download_video(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    video_id_str: str, 
    lang_filter_str: str, 
    folder_name_str: str
) -> int:
    output_template_str: str = f"{folder_name_str}-{video_id_str}"
    
    # Vimeo URL format: https://vimeo.com/{video_id}
    vimeo_url = f"https://vimeo.com/{video_id_str}"
    
    cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--ignore-no-formats-error",
        "--write-info-json",
        "--restrict-filenames",
        "--skip-download",
        "--write-sub",
        "--write-auto-sub",
        "--all-subs", # Garante que baixamos tudo se o filtro falhar
        "--convert-subs", "srt",
        "--sub-langs", f"{lang_filter_str},pt.*,en.*", # Tenta o detectado, depois pt/en
        "--extractor-args", "vimeo:dash_manifest=false", # Ignora DASH para evitar erros de XML
        "-o", output_template_str,
        vimeo_url
    ]
    
    try:
        process_result_obj = subprocess.run(cmd_list)
        
        if process_result_obj.returncode != 0:
            new_cookies_args_list: List[str] = _refresh_cookies_on_error(
                Path.cwd(), Path(__file__).parent.resolve()
            )
            cmd_with_new_cookies_list: List[str] = yt_dlp_cmd_list + new_cookies_args_list + cmd_list[len(yt_dlp_cmd_list) + len(cookie_args_list):]
            process_result_obj = subprocess.run(cmd_with_new_cookies_list)
            
        return process_result_obj.returncode
    except Exception as error_obj:
        print_err(f"Erro ao baixar vídeo Vimeo {video_id_str}: {error_obj}")
        return 1

def filter_vimeo_cookies(cookies_path_obj: Path) -> None:
    if not cookies_path_obj.exists():
        return

    try:
        with open(cookies_path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            lines_list: List[str] = file_descriptor_obj.readlines()

        filtered_lines_list: List[str] = []
        for line_str in lines_list:
            if line_str.startswith("#") or "vimeo.com" in line_str or "akamaized.net" in line_str:
                filtered_lines_list.append(line_str)

        with open(cookies_path_obj, "w", encoding="utf-8") as file_descriptor_obj:
            file_descriptor_obj.writelines(filtered_lines_list)
            
    except Exception as error_obj:
        print_warn(f"Aviso: Não foi possível filtrar o arquivo de cookies Vimeo: {error_obj}")
