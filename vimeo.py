import os
import sys
import subprocess
import json
import shutil
import time
import re
import yt_dlp
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from collections import Counter
from dl_common import _download_video_common
from utils import (
    print_ok, print_warn, print_info, print_err, 
    ICON_WAIT, BOLD, RESET, BCYAN, format_date
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

# Identifica o js-runtime Node.js
NODE_PATH_STR: str = os.getenv("NODE_PATH") or shutil.which("node") or ""


def _refresh_cookies_on_error(cwd_path_obj: Path, script_dir_path_obj: Path) -> List[str]:
    """
    Técnica de Auto-Cura para o Vimeo.
    Se a requisição retornar falha de segurança, removemos o cache local
    e re-importamos a rotina de extração automática do YouTube.
    """
    print_warn("Erro ao acessar Vimeo. Tentando renovar cookies do Chrome...")
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    cookies_path_obj.unlink(missing_ok=True)
    from youtube import configure_cookies
    return configure_cookies(cwd_path_obj, script_dir_path_obj, force_refresh_bool=True, silent_bool=True)


def detect_language(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    channel_url_str: str, 
    cached_lang_str: Optional[str] = None
) -> str:
    """
    Detecta o idioma predominante das legendas de um canal do Vimeo por amostragem rápida.
    
    Explicação para Iniciantes:
    - O Vimeo expõe dados de legendas de forma um pouco diferente do YouTube.
    - Primeiro fazemos uma listagem rápida (`--flat-playlist`) dos primeiros 3 vídeos do canal.
    - Em seguida, fazemos uma requisição individual para cada um desses 3 vídeos (`--skip-download` e `--dump-json`)
      para ver quais faixas de legendas estão de fato associadas a eles.
    - Por fim, usamos a classe `Counter` para encontrar o idioma que aparece com maior frequência.
    """
    if cached_lang_str and cached_lang_str != "N/A":
        print_ok(f"Idioma carregado do histórico (Vimeo): {BOLD}{cached_lang_str.strip('^$')}{RESET}")
        return cached_lang_str
        
    print_info(f"Detectando idioma predominante no canal Vimeo (amostragem dos 3 primeiros vídeos)...")
    
    # Busca os IDs dos 3 primeiros vídeos da lista do canal
    list_cmd: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist", "--dump-json", "--playlist-items", "1-3", channel_url_str
    ]
    
    detected_langs_list: List[str] = []
    try:
        process_obj = subprocess.run(list_cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
        if process_obj.returncode == 0:
            for line_str in process_obj.stdout.splitlines():
                try:
                    video_brief_dict = json.loads(line_str)
                    v_id_str = video_brief_dict.get("id")
                    if v_id_str:
                        # Faz uma requisição individual rápida para obter as legendas específicas deste vídeo
                        meta_cmd = yt_dlp_cmd_list + cookie_args_list + [
                            "--dump-json", "--skip-download", f"https://vimeo.com/{v_id_str}"
                        ]
                        meta_res_obj = subprocess.run(meta_cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)
                        if meta_res_obj.returncode == 0:
                            meta_data_dict = json.loads(meta_res_obj.stdout)
                            subs_dict = meta_data_dict.get("subtitles", {})
                            auto_subs_dict = meta_data_dict.get("automatic_captions", {})
                            
                            # Une as chaves (códigos de idioma) de legendas manuais e automáticas
                            available_langs = list(subs_dict.keys()) + list(auto_subs_dict.keys())
                            detected_langs_list.extend(available_langs)
                except Exception:
                    continue
    except Exception as error_obj:
        print_warn(f"Erro durante amostragem de idioma no Vimeo: {error_obj}")

    if detected_langs_list:
        # Pega a língua mais comum e remove as sub-regiões (ex: "en-US" vira "en")
        most_common_lang_str = Counter(detected_langs_list).most_common(1)[0][0]
        base_lang_str = most_common_lang_str.split("-")[0].split("_")[0]
        final_filter_str = f"^{base_lang_str}.*"
        print_ok(f"Idioma detectado por amostragem: {BOLD}{base_lang_str}{RESET}")
        return final_filter_str

    fallback_lang_str: str = os.getenv("DEFAULT_LANGUAGE", "pt")
    print_warn(f"Detecção falhou. Usando padrão de fallback: {BOLD}{fallback_lang_str}{RESET}")
    return f"^{fallback_lang_str}.*"


def generate_fast_list_json(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    channel_url_str: str, 
    history_dict: Optional[Dict[str, Any]] = None,
    stop_at_ids: Optional[set] = None
) -> List[Dict[str, Any]]:
    """
    Varre um canal/showcase do Vimeo listando os vídeos de forma veloz.
    
    Explicação para Iniciantes (Smart Sync):
    - Mesma lógica do `youtube.py`: processamos em streaming via `subprocess.Popen`.
    - Paramos a listagem imediatamente se detectarmos mais de 10 vídeos seguidos (`MAX_CONSECUTIVE_KNOWN`)
      que já estejam registrados localmente no histórico (`stop_at_ids`), evitando listar vídeos velhos.
    """
    print_info(f"Fase 1: Mapeando vídeos do Vimeo...")
    
    cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist", "--dump-json", "--ignore-errors", channel_url_str
    ]
    videos_found_list: List[Dict[str, Any]] = []
    consecutive_known_count = 0
    MAX_CONSECUTIVE_KNOWN = 10
    
    try:
        process_obj = subprocess.Popen(
            cmd_list, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8"
        )
        
        if process_obj.stdout:
            for line_str in process_obj.stdout:
                try:
                    video_data_dict: Dict = json.loads(line_str.strip())
                    video_id_str: str = str(video_data_dict.get("id", ""))
                    if not video_id_str: 
                        continue
                    
                    # Smart Sync
                    if stop_at_ids and video_id_str in stop_at_ids:
                        consecutive_known_count += 1
                        if consecutive_known_count >= MAX_CONSECUTIVE_KNOWN:
                            process_obj.terminate()
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
        print_err(f"Falha crítica na descoberta do Vimeo: {error_obj}")
        return []


def download_video(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    video_id_str: str, 
    lang_filter_str: str, 
    folder_name_str: str,
    download_video_only_hd: bool = False
) -> int:
    """
    Baixa metadados e apenas uma legenda específica para um vídeo do Vimeo.
    
    Explicação para Iniciantes:
    - O Vimeo possui restrições em conexões DASH/HLS que o yt-dlp gerencia internamente.
    - Usamos a flag `--extractor-args "vimeo:dash_manifest=false"` para burlar falhas comuns
      de extração de manifesto de streaming do Vimeo.
    - Tentamos baixar os idiomas na ordem de prioridade: idioma padrão detectado -> português -> inglês.
    - O código utiliza o objeto `YoutubeDL` da biblioteca Python para orquestrar e gerenciar
      as tentativas de download de forma granular e limpa.
    """
    
    output_template_str: str = f"{folder_name_str}-{video_id_str}.%(ext)s"
    vimeo_url = f"https://vimeo.com/{video_id_str}"
    
    # Valida se o ID do vídeo é válido para o Vimeo (7 a 12 dígitos)
    if not (video_id_str and re.match(r"^\d{7,12}$", video_id_str)):
        print_err(f"ID do Vimeo inválido ou truncado: {video_id_str}")
        return 2
    
    download_args = ["-f", "bestvideo[height<=1080]"] if download_video_only_hd else ["--skip-download"]
    
    extra_dl_args = [
        "--write-sub",
        "--write-auto-sub",
        "--convert-subs", "srt",
        # Configura fallbacks de idioma do Vimeo
        "--sub-langs", f"{lang_filter_str},pt.*,en.*",
        "--extractor-args", "vimeo:dash_manifest=false",
        "-o", output_template_str,
        vimeo_url
    ]
    
    patterns_to_try = [
        (lang_filter_str, False),
        (lang_filter_str, True),
        ("^pt.*", False),
        ("^pt.*", True),
        ("^en.*", False),
        ("^en.*", True)
    ]

    return _download_video_common(
        video_id_str=video_id_str,
        url=vimeo_url,
        yt_dlp_cmd_list=yt_dlp_cmd_list,
        cookie_args_list=cookie_args_list,
        download_args=download_args,
        extra_dl_args=extra_dl_args,
        lang_filter_str=lang_filter_str,
        output_template_str=output_template_str,
        patterns_to_try=patterns_to_try,
        refresh_cookies_func=_refresh_cookies_on_error,
        is_vimeo=True
    )


def filter_vimeo_cookies(cookies_path_obj: Path) -> None:
    """
    Limpa o arquivo de cookies extraído, mantendo apenas cookies do Vimeo e Akamai CDN.
    Isso protege a privacidade das chaves de sessão de outros sites do usuário.
    """
    if not cookies_path_obj.exists():
        return

    try:
        with open(cookies_path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            lines_list: List[str] = file_descriptor_obj.readlines()

        filtered_lines_list: List[str] = []
        allowed_domains = ["vimeo.com", "akamaized.net"]
        for line_str in lines_list:
            # Mantém comentários, exceto HttpOnly que são cookies reais
            if line_str.startswith("#") and not line_str.startswith("#HttpOnly_"):
                filtered_lines_list.append(line_str)
                continue

            # Remove o prefixo HttpOnly para checar o domínio
            cookie_line = line_str[10:] if line_str.startswith("#HttpOnly_") else line_str
            parts = cookie_line.split("\t")
            if len(parts) > 0:
                domain = parts[0].strip()
                for allowed in allowed_domains:
                    if domain.endswith("." + allowed) or domain == allowed:
                        filtered_lines_list.append(line_str)
                        break

        with open(cookies_path_obj, "w", encoding="utf-8") as file_descriptor_obj:
            file_descriptor_obj.writelines(filtered_lines_list)
        cookies_path_obj.chmod(0o600)
            
    except Exception as error_obj:
        print_warn(f"Não foi possível higienizar os cookies Vimeo: {error_obj}")
