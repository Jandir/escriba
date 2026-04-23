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
MÓDULO YOUTUBE: A Ponte com a Internet
--------------------------------------
Este módulo é responsável por toda a comunicação externa com o YouTube.
Ele utiliza a ferramenta 'yt-dlp' (um canivete suíço para vídeos) para:
1. Descobrir quais vídeos um canal possui.
2. Identificar qual o idioma predominante do canal.
3. Baixar as legendas e informações técnicas de cada vídeo.

Explicação para Juniores:
O yt-dlp é um programa de linha de comando. Aqui, nós o chamamos via Python
usando o módulo 'subprocess'. É como se o Python estivesse "digitando" no 
terminal para nós.
"""

# O NODE_PATH é necessário porque algumas funções avançadas do yt-dlp 
# rodam pequenos códigos Javascript para burlar proteções do YouTube.
NODE_PATH_STR: str = os.getenv("NODE_PATH") or shutil.which("node") or ""


def _refresh_cookies_on_error(cwd_path_obj: Path, script_dir_path_obj: Path) -> List[str]:
    """
    Técnica de Auto-Cura: Se o YouTube nos bloquear, tentamos renovar os cookies.
    
    Explicação para Juniores:
    O YouTube usa cookies para saber que você não é um robô mal-intencionado. 
    Às vezes esses cookies "vencem" (expiram) ou o YouTube desconfia do acesso. 
    Apagar o arquivo antigo e pedir novos para o Chrome costuma resolver o problema.
    """
    print_warn("Erro ao acessar YouTube. Tentando corrigir cookies...")
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    cookies_path_obj.unlink(missing_ok=True)
    return configure_cookies(cwd_path_obj, script_dir_path_obj, force_refresh_bool=True, silent_bool=True)


def _get_python_executable(script_dir_path_obj: Path) -> Path:
    """
    Busca o Python dentro da 'bolha' (ambiente virtual) do projeto.
    Isso garante que usaremos as bibliotecas corretas instaladas para o Escriba.
    """
    if os.name == "nt":  # Windows
        return script_dir_path_obj / ".venv" / "Scripts" / "python.exe"
    return script_dir_path_obj / ".venv" / "bin" / "python3"  # Mac/Linux


def setup_environment() -> Tuple[Path, List[str]]:
    """
    Prepara o terreno para o script rodar.
    Retorna o caminho do script e o comando base para chamar o yt-dlp.
    """
    script_dir_path_obj: Path = Path(__file__).parent.resolve()
    python_path_obj: Path = _get_python_executable(script_dir_path_obj)
    
    if not python_path_obj.is_file():
        print_err(f"Ambiente virtual não encontrado em {python_path_obj}")
        print_info("Dica: Rode 'python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt'")
        sys.exit(1)
        
    # Comando base configurado para rodar o yt-dlp como um módulo do Python
    # Explicação para Juniores: Usamos '-m yt_dlp' para garantir que usamos a versão
    # instalada no nosso ambiente virtual, e não uma versão global do sistema.
    yt_dlp_cmd_list: List[str] = [str(python_path_obj), "-m", "yt_dlp", "--remote-components", "ejs:github"]
    
    if NODE_PATH_STR:
        yt_dlp_cmd_list.extend(["--js-runtimes", f"node:{NODE_PATH_STR}"])
        
    return script_dir_path_obj, yt_dlp_cmd_list


def configure_cookies(
    cwd_path_obj: Path, 
    script_dir_path_obj: Path, 
    force_refresh_bool: bool, 
    silent_bool: bool = False
) -> List[str]:
    """
    Configura os Cookies de acesso. 
    Cookies são como 'crachás' que dizem ao YouTube que você é um usuário real.
    """
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    
    if force_refresh_bool:
        if not silent_bool: 
            print_warn("--refresh-cookies ativo. Renovando credenciais...")
        cookies_path_obj.unlink(missing_ok=True)
        
    # Se já temos um arquivo de cookies válido na pasta, usamos ele (é mais rápido)
    if _is_valid_cookie_file(cookies_path_obj):
        if not silent_bool: 
            print_info(f"Usando cookies em cache: {cookies_path_obj.name}")
        return ["--cookies", str(cookies_path_obj)]
        
    # Se não houver cache, tentamos extrair do Chrome do usuário
    if not silent_bool: 
        print_warn(f"Extraindo novos cookies do Chrome → {cookies_path_obj.name}")
    return ["--cookies-from-browser", "chrome", "--cookies", str(cookies_path_obj)]


def _is_valid_cookie_file(path_obj: Path) -> bool:
    """Verifica se o arquivo de cookies não está vazio e tem formato Netscape."""
    if not path_obj.is_file(): 
        return False
    try:
        with open(path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            content_snippet_str: str = file_descriptor_obj.read(100)
            return "Netscape" in content_snippet_str or "TRUE" in content_snippet_str
    except Exception:
        return False


def detect_language(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    channel_url_str: str, 
    cached_lang_str: Optional[str] = None
) -> str:
    """
    Estratégia: Em vez de ler todos os vídeos, olhamos apenas os 5 mais recentes.
    
    Explicação para Juniores:
    Se um canal tem 1000 vídeos, demoraria muito para descobrir o idioma de todos.
    Partimos do princípio que o dono do canal não mudou de língua nos últimos 5 vídeos.
    Essa técnica de olhar apenas uma parte do todo se chama 'amostragem'.
    """
    if cached_lang_str and cached_lang_str != "N/A":
        print_ok(f"Idioma em cache: {BOLD}{cached_lang_str.strip('^$')}{RESET}")
        return cached_lang_str
        
    print_info("Detectando idioma do canal (amostragem de 5 vídeos)...")
    
    # URL formatada para pegar a lista de vídeos
    detect_url_str: str = channel_url_str.rstrip("/") + "/videos" if "watch?v=" not in channel_url_str else channel_url_str
    
    cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--print", "language", 
        "--playlist-end", "5", 
        "--ignore-errors", 
        "--flat-playlist", 
        detect_url_str
    ]
    
    try:
        process_result_obj = subprocess.run(cmd_list, capture_output=True, text=True, timeout=20)
        langs_list: List[str] = [
            line_str.strip().lower() 
            for line_str in process_result_obj.stdout.splitlines() 
            if line_str.strip() and line_str.lower() not in ("na", "none")
        ]
        
        if langs_list:
            # Pega o idioma que mais apareceu na amostra
            most_common_tuple: Tuple[str, int] = Counter(langs_list).most_common(1)[0]
            most_common_lang_str: str = most_common_tuple[0]
            clean_lang_str: str = most_common_lang_str.split("-")[0].split("_")[0]
            print_ok(f"Idioma detectado: {BOLD}{clean_lang_str}{RESET}")
            return f"^{clean_lang_str}$"
            
    except Exception as error_obj:
        print_warn(f"Erro na detecção de idioma: {error_obj}")
        
    fallback_lang_str: str = os.getenv("DEFAULT_LANGUAGE", "pt")
    print_warn(f"Idioma não detectado. Usando padrão: {BOLD}{fallback_lang_str}{RESET}")
    return f"^{fallback_lang_str}$"


def generate_fast_list_json(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    channel_url_str: str, 
    history_dict: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    FASE DE DESCOBERTA (Discovery)
    -----------------------------
    Varre o canal e cria uma lista de todos os vídeos disponíveis.
    Usa a flag '--flat-playlist' para não baixar detalhes pesados, apenas ID e Título.
    """
    print_info(f"Fase 1: Mapeando vídeos do canal...")
    
    cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--flat-playlist", "--dump-json", "--ignore-errors", channel_url_str
    ]
    videos_found_list: List[Dict[str, Any]] = []
    
    try:
        # Popen permite que leiamos a saída do comando enquanto ele ainda está rodando (streaming)
        # Explicação para Juniores: 
        # Diferente do 'subprocess.run' (que espera o comando acabar), o 'Popen' abre um 
        # "cano" (pipe) de comunicação. Conforme o yt-dlp descobre um vídeo, ele "gospe" 
        # a informação no cano e nós pegamos na mesma hora. Assim o usuário vê o contador 
        # subindo em tempo real.
        process_obj = subprocess.Popen(
            cmd_list, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        
        if process_obj.stdout:
            for line_str in process_obj.stdout:
                try:
                    video_data_dict: Dict = json.loads(line_str.strip())
                    video_id_str: str = video_data_dict.get("id", "")
                    if not video_id_str: 
                        continue
                    
                    # Extrai e formata a data usando a utilidade centralizada
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
                    
                    # Feedback visual de progresso na mesma linha
                    sys.stdout.write(f"\r{ICON_WAIT}  {BCYAN}Vídeos mapeados: {len(videos_found_list)}{RESET}")
                    sys.stdout.flush()
                    
                except Exception:
                    continue
                    
        process_obj.wait()
        print()  # Quebra de linha após o contador
        
        if process_obj.returncode != 0 and not videos_found_list:
            _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())
            
        return videos_found_list
        
    except Exception as error_obj:
        print_err(f"Falha crítica na descoberta: {error_obj}")
        return []


def download_video(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    video_id_str: str, 
    lang_filter_str: str, 
    folder_name_str: str
) -> int:
    """
    BAIXA OS ARQUIVOS DO VÍDEO
    --------------------------
    Baixa o .info.json (metadados) e as legendas (.srt).
    Não baixa o vídeo (MP4), pois só queremos o texto.
    """
    output_template_str: str = f"{folder_name_str}-{video_id_str}"
    
    # Explicação dos parâmetros yt-dlp:
    # --skip-download: Não baixa o vídeo/áudio (economiza GBs de espaço).
    # --write-auto-sub: Baixa legendas geradas automaticamente pelo YouTube.
    # --convert-subs srt: Converte VTT para SRT (formato mais simples de ler).
    # --write-info-json: Salva todos os detalhes do vídeo em um arquivo JSON.
    
    cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
        "--ignore-no-formats-error",
        "--write-info-json",
        "--restrict-filenames",
        "--skip-download",
        "--write-auto-sub",
        "--convert-subs", "srt",
        "--sub-langs", lang_filter_str,
        "-o", output_template_str,
        f"https://www.youtube.com/watch?v={video_id_str}"
    ]
    
    try:
        process_result_obj = subprocess.run(cmd_list)
        
        # Se falhou, pode ser cookie expirado. Tenta renovar UMA vez.
        if process_result_obj.returncode != 0:
            new_cookies_args_list: List[str] = _refresh_cookies_on_error(
                Path.cwd(), Path(__file__).parent.resolve()
            )
            # Reconstrói o comando com os novos cookies
            cmd_with_new_cookies_list: List[str] = yt_dlp_cmd_list + new_cookies_args_list + cmd_list[len(yt_dlp_cmd_list) + len(cookie_args_list):]
            process_result_obj = subprocess.run(cmd_with_new_cookies_list)
            
        return process_result_obj.returncode
    except Exception as error_obj:
        print_err(f"Erro ao baixar vídeo {video_id_str}: {error_obj}")
        return 1


def filter_youtube_cookies(cookies_path_obj: Path) -> None:
    """
    PROTEÇÃO DE PRIVACIDADE E LIMPEZA
    ---------------------------------
    Remove cookies que não são do YouTube ou Google do arquivo extraído.
    Isso evita enviar rastreadores desnecessários para o YouTube e mantém
    o arquivo de cookies leve e focado.
    """
    if not cookies_path_obj.exists():
        return

    try:
        with open(cookies_path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            lines_list: List[str] = file_descriptor_obj.readlines()

        filtered_lines_list: List[str] = []
        for line_str in lines_list:
            # Mantém comentários (que explicam o formato) e domínios relevantes
            if line_str.startswith("#") or "youtube.com" in line_str or "google.com" in line_str:
                filtered_lines_list.append(line_str)

        with open(cookies_path_obj, "w", encoding="utf-8") as file_descriptor_obj:
            file_descriptor_obj.writelines(filtered_lines_list)
            
    except Exception as error_obj:
        # Se falhar a limpeza, não paramos o script, apenas avisamos.
        print_warn(f"Aviso: Não foi possível filtrar o arquivo de cookies: {error_obj}")
