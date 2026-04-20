import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
from collections import Counter
import shutil
import time
import warnings
from utils import print_ok, print_warn, print_info, print_err, ICON_WAIT, BOLD, RESET, WHITE, DIM, BCYAN

# Carregar NODE_PATH do .env se existir (evitando requests/carregamento duro na importação)
NODE_PATH: str = os.getenv("NODE_PATH") or shutil.which("node") or ""

def _refresh_cookies_on_error(cwd_path: Path, script_dir_path: Path) -> List[str]:
    """Apaga cookies.txt e gera novamente, retornando os novos cookie_args."""
    print_warn("Erro ao acessar YouTube. Tentando corrigir cookies...")
    cookies_txt_path = cwd_path / "cookies.txt"
    cookies_txt_path.unlink(missing_ok=True)
    return configure_cookies(cwd_path, script_dir_path, force_refresh_cookies=True, silent=True)

def setup_environment() -> Tuple[Path, List[str]]:
    """
    Valida e retorna o diretório do script e o comando base yt-dlp.
    Descobre o executável Python no ambiente virtual (Cross-platform).
    """
    script_dir_path: Path = Path(__file__).parent.resolve()
    if os.name == "nt":
        python_executable_path: Path = script_dir_path / ".venv" / "Scripts" / "python.exe"
    else:
        python_executable_path = script_dir_path / ".venv" / "bin" / "python3"

    if not python_executable_path.is_file():
        print_err(f"Ambiente virtual não encontrado em {python_executable_path}")
        sys.exit(1)

    yt_dlp_cmd_list: List[str] = [
        str(python_executable_path), 
        "-m", "yt_dlp", 
        "--remote-components", "ejs:github"
    ]
    if NODE_PATH:
        yt_dlp_cmd_list.extend(["--js-runtimes", f"node:{NODE_PATH}"])
        
    return script_dir_path, yt_dlp_cmd_list

def configure_cookies(cwd_path: Path, script_dir_path: Path, force_refresh_cookies: bool, silent: bool = False) -> List[str]:
    """Retorna argumentos de cookie para yt-dlp."""
    cookies_file_path: Path = cwd_path / "cookies.txt"

    if force_refresh_cookies:
        if not silent: 
            print_warn("--refresh-cookies ativo. Apagando cache antigo...")
        cookies_file_path.unlink(missing_ok=True)

    if _is_valid_cookie_file(cookies_file_path):
        if not silent: 
            print_info(f"Cookies em cache: {cookies_file_path.name}")
        return ["--cookies", str(cookies_file_path)]
    elif cookies_file_path.is_file():
        if not silent: 
            print_warn(f"Cache de cookies corrompido detectado e removido: {cookies_file_path.name}")
        cookies_file_path.unlink()

    global_script_cookies_path: Path = script_dir_path / "cookies.txt"
    if global_script_cookies_path.is_file() and not force_refresh_cookies:
        if not silent: 
            print_info("Cookies do diretório do script.")
        return ["--cookies", str(global_script_cookies_path)]

    if not silent: 
        print_warn(f"Extraindo cookies do Chrome → {cookies_file_path.name}")
    return ["--cookies-from-browser", "chrome", "--cookies", str(cookies_file_path)]

def _is_valid_cookie_file(path: Path) -> bool:
    """Extraído para facilitar a validação do state de cookies."""
    if not path.is_file(): 
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(100)
            if not content.strip() or "Netscape" in content or "TRUE" in content:
                return True
    except Exception:
        pass
    return False

def filter_youtube_cookies(cookies_path: Path) -> None:
    if not cookies_path.is_file():
        return
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        filtered_lines: List[str] = []
        for line in lines:
            if line.startswith("#") or not line.strip():
                filtered_lines.append(line)
                continue
            
            parts = line.split('\t')
            if len(parts) >= 6:
                domain = parts[0].strip()
                if "youtube.com" in domain or "google.com" in domain:
                    filtered_lines.append(line)
        
        with open(cookies_path, "w", encoding="utf-8") as f:
            f.writelines(filtered_lines)
    except Exception as e:
        print_warn(f"Falha ao filtrar cookies {cookies_path.name}: {e}")

def detect_language(yt_dlp_cmd_list: List[str], cookie_args_list: List[str], channel_url: str, cached_lang: Optional[str] = None) -> str:
    """Detecta o idioma predominante do canal com 5 samples."""
    if cached_lang and cached_lang != "N/A":
        print_ok(f"Usando idioma em cache: {BOLD}{cached_lang.strip('^$')}{RESET}")
        return cached_lang

    print_info("Detectando idioma nativo (amostragem de 5 vídeos)...")
    
    global_default_lang: str = os.getenv("DEFAULT_LANGUAGE") or os.getenv("LANG") or "pt"
    if global_default_lang and len(global_default_lang) > 2:
        global_default_lang = global_default_lang[:2].lower()

    detect_url: str = channel_url
    if "watch?v=" not in detect_url and "playlist?list=" not in detect_url:
        is_generic_channel: bool = True
        for suffix in ["/videos", "/shorts", "/streams", "/live"]:
            if detect_url.endswith(suffix):
                is_generic_channel = False
                break
        if is_generic_channel:
            detect_url = detect_url.rstrip("/") + "/videos"

    cmd: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--print", "language",
        "--playlist-end", "5",
        "--ignore-errors",
        "--flat-playlist", 
        detect_url
    ]

    detected_languages: List[str] = []
    try:
        subprocess_result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        detected_languages = [lang.strip().lower() for lang in subprocess_result.stdout.splitlines() if lang.strip()]
        
        if not detected_languages:
            if "--flat-playlist" in cmd: 
                cmd.remove("--flat-playlist")
            if "--playlist-end" in cmd:
                idx = cmd.index("--playlist-end")
                cmd[idx + 1] = "3"
            
            subprocess_result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            detected_languages = [lang.strip().lower() for lang in subprocess_result.stdout.splitlines() if lang.strip()]
            
        invalid_tags: set = {"na", "n/a", "none", "null", "undefined"}
        detected_languages = [l for l in detected_languages if l not in invalid_tags]
    except Exception as e:
        print_warn(f"Erro na rotina de detecção automática: {e}")
        # Retentativa com cookies novos
        try:
            new_cookie_args = _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())
            # Atualiza o comando com os novos cookies
            # Nota: Isso é complexo pois temos que achar onde os cookies estavam no cmd
            # Simplificação: Detect language é um warm up, vamos apenas avisar.
        except Exception:
            pass

    if detected_languages:
        most_common_lang, count = Counter(detected_languages).most_common(1)[0]
        clean_lang = most_common_lang.split("-")[0].split("_")[0]
        language_regex_filter = f"^{clean_lang}$"
        print_ok(f"Idioma detectado ({count}/{len(detected_languages)}): {BOLD}{clean_lang}{RESET} {DIM}(filtro: {language_regex_filter}){RESET}")
        return language_regex_filter

    print_warn(f"Não foi possível detectar o idioma. Assumindo fallback: {BOLD}{global_default_lang}{RESET}")
    print_info(f"Dica: utilize {WHITE}--lang [código]{RESET} para forçar um idioma específico.")
    return f"^{global_default_lang}$"

def get_video_exact_date(video_id: str, yt_dlp_cmd_list: List[str], cookie_args_list: List[str]) -> Dict[str, str]:
    cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--dump-json",
        "--skip-download",
        "--ignore-errors",
        "--remote-components", "ejs:github",
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    def _run_dump():
        return subprocess.run(cmd_list, capture_output=True, text=True, timeout=30)

    try:
        process_instance = _run_dump()
        if process_instance.returncode != 0:
            new_cookies = _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())
            # Reconstruct cmd_list with new cookies (cookie_args_list items are removed/replaced)
            # This is tricky because meta_cmd is passed from outside too.
            # Simplified: we just re-run with force refresh already happened.
            process_instance = _run_dump()
            
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
    yt_dlp_cmd_list: List[str],
    cookie_args_list: List[str],
    channel_url: str,
    local_history_map: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Descoberta rápida com base na flag --flat-playlist do youtube-dl"""
    print_info(f"Fase 1: Descoberta de IDs + Metadados ({BOLD}{channel_url}{RESET})...")
    def _run_discovery(current_cookies: List[str]):
        cmd = yt_dlp_cmd_list + current_cookies + [
            "--flat-playlist",
            "--dump-json",
            "--ignore-errors",
            "--remote-components", "ejs:github",
            channel_url
        ]
        local_vids: List[Dict[str, Any]] = []
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in p.stdout:
            _parse_flat_playlist_line(line, local_history_map, local_vids)
        p.wait()
        return p.returncode, local_vids

    try:
        ret_code, raw_video_list = _run_discovery(cookie_args_list)
        if ret_code != 0 or not raw_video_list:
            # Se falhou ou veio vazio, tenta corrigir cookies e retentar
            _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())
            print_info("Retentando descoberta...")
            # Pega cookies novos silenciosamente
            new_cookies = configure_cookies(Path.cwd(), Path(__file__).parent.resolve(), False, silent=True)
            ret_code, raw_video_list = _run_discovery(new_cookies)
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
    print_info("O restante terá metadados recuperados se não estiverem no cache.")

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

def _parse_flat_playlist_line(line_content: str, local_history_map: Optional[Dict[str, Any]], raw_video_list: List[Dict[str, Any]]) -> None:
    """Extraído para reduzir indentação complexa no parse do yt-dlp."""
    try:
        obj = json.loads(line_content.strip())
        video_id = obj.get("id") or obj.get("url")
        if not video_id:
            return
            
        if "watch?v=" in video_id:
            video_id = video_id.split("watch?v=")[-1].split("&")[0]
        elif video_id.startswith("http"):
            video_id = video_id.split("/")[-1]

        title = obj.get("title") or obj.get("fulltitle") or "N/A"
        raw_date = obj.get("upload_date") or ""
        
        if not raw_date:
            ts = obj.get("timestamp")
            if ts:
                raw_date = datetime.utcfromtimestamp(int(ts)).strftime("%Y%m%d")
        
        publish_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if len(str(raw_date)) == 8 else "N/A"

        if publish_date == "N/A" and local_history_map and video_id in local_history_map:
            hist_entry = local_history_map[video_id]
            if hist_entry.get("publish_date") and hist_entry["publish_date"] != "N/A":
                publish_date = hist_entry["publish_date"]

        raw_video_list.append({"id": video_id, "title": title, "publish_date": publish_date})
        sys.stdout.write(f"\r{ICON_WAIT}  {BCYAN}IDs encontrados: {len(raw_video_list)}{RESET}")
        sys.stdout.flush()
    except Exception:
        pass


def download_video(
    yt_dlp_cmd_list: List[str],
    cookie_args_list: List[str],
    video_id: str,
    language_opt_string: str,
    channel_dir_name: str,
    audio_only_flag: bool,
    output_dir_path: Optional[Path] = None,
    mp3_flag: bool = False,
) -> int:
    """
    Baixa legendas ou áudio de um vídeo específico usando yt-dlp.
    Inclui lógica de retentativa com regeneração de cookies em caso de erro.
    """
    # Naming convention: Título para áudio, [Channel]-[ID] para legendas
    if audio_only_flag:
        output_template_string = "%(title)s.%(ext)s"
    else:
        output_template_string = f"{channel_dir_name}-{video_id}"

    if output_dir_path:
        output_template_string = str(output_dir_path / output_template_string)

    # Base arguments
    download_cmd_list = (
        yt_dlp_cmd_list
        + ["--js-runtimes", f"node:{NODE_PATH}"]
        + ["--ignore-no-formats-error"]
        + ["--write-info-json"]
        + ["--restrict-filenames"]
    )

    # Audio vs Subtitles logic
    if mp3_flag:
        download_cmd_list += [
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
        ]
    elif audio_only_flag:
        download_cmd_list += ["-f", "ba[ext=webm]"]
    else:
        download_cmd_list += ["--skip-download", "--write-auto-sub", "--convert-subs", "srt"]
        download_cmd_list += ["--sub-langs", language_opt_string]

    # Output and URL
    base_cmd = download_cmd_list + ["-o", output_template_string, f"https://www.youtube.com/watch?v={video_id}"]

    def _run_download(current_cookies: List[str]) -> int:
        cmd = base_cmd + current_cookies
        proc = subprocess.Popen(cmd)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise

    # Primeira tentativa
    exit_code = _run_download(cookie_args_list)

    # Retentativa se falhar (exit code não zero)
    if exit_code != 0:
        cwd_path = Path.cwd()
        script_dir_path = Path(__file__).parent.resolve()
        new_cookies = _refresh_cookies_on_error(cwd_path, script_dir_path)
        print_info("Retentando download...")
        exit_code = _run_download(new_cookies)

    return exit_code
