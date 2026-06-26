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

# O NODE_PATH é necessário porque algumas páginas modernas do YouTube contêm scripts
# complicados para burlar bots. O yt-dlp roda esses scripts usando o Node.js instalado
# na máquina do usuário para simular um navegador de verdade.
NODE_PATH_STR: str = os.getenv("NODE_PATH") or shutil.which("node") or ""


def _refresh_cookies_on_error(cwd_path_obj: Path, script_dir_path_obj: Path) -> List[str]:
    """
    Técnica de Auto-Cura (Auto-Healing): Se o YouTube bloquear o acesso (erro HTTP 403),
    nós apagamos os cookies locais expirados e extraímos credenciais frescas do Google Chrome.
    
    Explicação para Iniciantes:
    Cookies são pequenos pedaços de dados salvos pelo navegador que identificam você nas sessões.
    Para o YouTube, cookies válidos provam que você é um usuário humano que está logado no Chrome,
    evitando que o sistema bloqueie o download como se fosse um ataque automatizado de DDoS.
    """
    print_warn("Erro ao acessar YouTube. Tentando corrigir cookies automaticamente...")
    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    # O método '.unlink(missing_ok=True)' apaga o arquivo se ele existir,
    # e simplesmente não faz nada se ele já tiver sido apagado (evita disparar FileNotFoundError).
    cookies_path_obj.unlink(missing_ok=True)
    return configure_cookies(cwd_path_obj, script_dir_path_obj, force_refresh_bool=True, silent_bool=True)


def _get_python_executable(script_dir_path_obj: Path) -> Path:
    """
    Identifica didaticamente o executável do Python correto que reside dentro da 'bolha' (venv).
    Isso impede que o subprocesso use o interpretador global e acabe não encontrando o yt-dlp.
    """
    if os.name == "nt":  # Windows
        return script_dir_path_obj / ".venv" / "Scripts" / "python.exe"
    return script_dir_path_obj / ".venv" / "bin" / "python3"  # Mac/Linux


def setup_environment() -> Tuple[Path, List[str]]:
    """
    Prepara o ambiente e define o comando base para chamar o yt-dlp.
    
    Explicação para Iniciantes:
    Q: Por que usamos `[python, "-m", "yt_dlp"]` em vez de chamar a string "yt-dlp" diretamente?
    A: Chamar apenas "yt-dlp" assume que ele está instalado globalmente no PATH do sistema.
       Se o usuário tiver outra versão instalada globalmente, pode dar conflito de versão.
       Chamar o python do venv apontando para o módulo (`-m yt_dlp`) garante 100% que usaremos
       a biblioteca específica que instalamos localmente pelo `requirements.txt`.
    """
    script_dir_path_obj: Path = Path(__file__).parent.resolve()
    python_path_obj: Path = _get_python_executable(script_dir_path_obj)
    
    if not python_path_obj.is_file():
        print_err(f"Ambiente virtual não encontrado em {python_path_obj}")
        print_info("Dica: Monte o ambiente rodando: 'python3 -m venv .venv && pip install -r requirements.txt'")
        sys.exit(1)
        
    # Comando base configurado para rodar o yt-dlp como módulo
    # `--remote-components ejs:github` diz ao yt-dlp para baixar scripts auxiliares atualizados
    # diretamente do GitHub se o YouTube mudar as chaves de assinatura do player de vídeo.
    yt_dlp_cmd_list: List[str] = [str(python_path_obj), "-m", "yt_dlp", "--remote-components", "ejs:github"]
    
    if NODE_PATH_STR:
        yt_dlp_cmd_list.extend(["--js-runtimes", f"node:{NODE_PATH_STR}"])
        
    return script_dir_path_obj, yt_dlp_cmd_list


CHOSEN_BROWSER: str = "firefox"


def configure_cookies(
    cwd_path_obj: Path, 
    script_dir_path_obj: Path, 
    force_refresh_bool: bool, 
    silent_bool: bool = False,
    browser_str: Optional[str] = None
) -> List[str]:
    """
    Configura os cookies de autenticação para as requisições de download.
    
    Explicação para Iniciantes:
    - Se o usuário usar `--refresh-cookies`, apagamos o arquivo local cookies.txt.
    - Se o arquivo cookies.txt existir e for válido, usamos ele como cache local de cookies.
    - Se não houver arquivo cookies.txt no disco, o yt-dlp possui uma funcionalidade incrível
      que consegue ler os cookies que o usuário já tem salvos no navegador local
      (`--cookies-from-browser navegador`), exportando-os para o arquivo cookies.txt para as próximas execuções.
    """
    global CHOSEN_BROWSER
    if browser_str is not None:
        CHOSEN_BROWSER = browser_str
    else:
        browser_str = CHOSEN_BROWSER

    cookies_path_obj: Path = cwd_path_obj / "cookies.txt"
    
    if force_refresh_bool:
        if not silent_bool: 
            print_warn("--refresh-cookies ativo. Purgando cookies em cache...")
        cookies_path_obj.unlink(missing_ok=True)
        
    # Se já temos o cache de cookies local, retornamos o argumento apontando para ele
    if _is_valid_cookie_file(cookies_path_obj):
        if not silent_bool: 
            print_info(f"Usando arquivo de cookies: {cookies_path_obj.name}")
        return ["--cookies", str(cookies_path_obj)]
        
    # Caso contrário, extrai do navegador do sistema operacional
    if not silent_bool: 
        print_warn(f"Extraindo credenciais de sessão do navegador '{browser_str}' → {cookies_path_obj.name}")
    return ["--cookies-from-browser", browser_str, "--cookies", str(cookies_path_obj)]


def _is_valid_cookie_file(path_obj: Path) -> bool:
    """Verifica se o arquivo de cookies existe e segue o formato padrão Netscape/cURL."""
    if not path_obj.is_file(): 
        return False
    try:
        with open(path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            content_snippet_str: str = file_descriptor_obj.read(100)
            # Arquivos Netscape Cookies sempre começam com comentários específicos ou colunas delimitadas
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
    Detecta o idioma principal das legendas do canal analisando apenas os vídeos mais recentes.
    
    Explicação para Iniciantes (Estratégia de Amostragem):
    Se um canal possui 5.000 vídeos, seria inviável baixar dados de todos para saber qual idioma
    o autor fala. Usamos uma técnica matemática chamada 'amostragem': lemos os últimos 5 vídeos
    e assumimos que a língua predominante deles representa o canal inteiro.
    - O `Counter` da biblioteca padrão do Python conta a frequência de ocorrências na lista.
      Ex: `['pt', 'pt', 'pt', 'en', 'pt']` vira `[('pt', 4), ('en', 1)]`.
      O método `.most_common(1)` pega o item mais frequente, no caso 'pt'.
    """
    if cached_lang_str and cached_lang_str != "N/A":
        # Garante compatibilidade de padrões antigos salvos no JSON histórico
        normalized_lang_str = _normalize_lang_pattern(cached_lang_str)
        print_ok(f"Idioma carregado do histórico: {BOLD}{normalized_lang_str.strip('^$.*')}{RESET}")
        return normalized_lang_str
        
    print_info("Detectando idioma predominante por amostragem (últimos 5 vídeos)...")
    
    # Mapeia URLs possíveis de abas para o caso de canais que fazem lives
    urls_to_try: List[str] = [
        channel_url_str.rstrip("/"),
        channel_url_str.rstrip("/") + "/live",
        channel_url_str.rstrip("/") + "/videos"
    ]
    
    if "watch?v=" in channel_url_str:
        urls_to_try = [channel_url_str]

    langs_list: List[str] = []
    
    for url in urls_to_try:
        if langs_list: 
            break  # Se já conseguimos obter amostras, não precisa tentar outras URLs
        
        # `--playlist-end 5` limita a busca aos primeiros 5 vídeos da playlist
        # `--print language` diz ao yt-dlp para imprimir apenas o idioma do áudio/legenda na saída padrão
        cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
            "--print", "language", 
            "--playlist-end", "5", 
            "--ignore-errors", 
            "--no-warnings", 
            "--flat-playlist", 
            url
        ]
        
        try:
            # Roda o comando de forma síncrona esperando até 20 segundos
            process_result_obj = subprocess.run(cmd_list, capture_output=True, text=True, encoding="utf-8", timeout=20)
            current_langs = [
                line_str.strip().lower() 
                for line_str in process_result_obj.stdout.splitlines() 
                if line_str.strip() and line_str.lower() not in ("na", "none")
            ]
            langs_list.extend(current_langs)
        except Exception as error_obj:
            print_warn(f"Aba {url} indisponível: {error_obj}")
    
    if langs_list:
        most_common_tuple: Tuple[str, int] = Counter(langs_list).most_common(1)[0]
        most_common_lang_str: str = most_common_tuple[0]
        # Corta extensões regionais (ex: "pt-BR" ou "en_US" vira "pt" ou "en")
        clean_lang_str: str = most_common_lang_str.split("-")[0].split("_")[0]
        print_ok(f"Idioma detectado com maior frequência: {BOLD}{clean_lang_str}{RESET}")
        return f"^{clean_lang_str}.*"
        
    fallback_lang_str: str = os.getenv("DEFAULT_LANGUAGE", "pt")
    # Caso a detecção automática falhe por completo, usamos os idiomas padrões configurados
    if fallback_lang_str == "pt":
        print_warn(f"Idioma não detectado. Usando padrão expansivo: {BOLD}pt, en{RESET}")
        return "^(pt|en).*"
        
    print_warn(f"Idioma não detectado. Usando padrão de fallback: {BOLD}{fallback_lang_str}{RESET}")
    return f"^{fallback_lang_str}.*"


def generate_fast_list_json(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    channel_url_str: str, 
    history_dict: Optional[Dict[str, Any]] = None,
    stop_at_ids: Optional[set] = None
) -> List[Dict[str, Any]]:
    """
    Varre o canal do YouTube listando todos os vídeos de forma extremamente rápida.
    
    Explicação para Iniciantes (Streaming de Processo e Smart Sync):
    1. Usamos a flag `--flat-playlist`. Isso instrui o yt-dlp a apenas listar as propriedades
       básicas do vídeo (como ID e título) da página principal, sem ter que fazer requisições
       pesadas adicionais para extrair streams de vídeo de cada item individualmente.
    2. Usamos `subprocess.Popen` em vez de `subprocess.run()`.
       Q: Qual a diferença?
       A: `subprocess.run()` é síncrona: ela bloqueia o nosso script inteiro e espera
          o comando terminar para depois entregar toda a saída de uma vez só.
          `subprocess.Popen` é assíncrona/streaming: ela inicia o comando e nos permite ler
          as linhas da saída padrão (`process_obj.stdout`) em tempo real enquanto o yt-dlp
          ainda está buscando os dados na internet. Isso é muito melhor para a experiência do usuário.
    3. Otimização Smart Sync:
       Se o canal tiver 8.000 vídeos, a listagem pode demorar minutos.
       Durante a leitura em streaming da saída do yt-dlp (que é ordenada do mais novo para o mais antigo),
       se detectarmos que encontramos 10 vídeos seguidos (`MAX_CONSECUTIVE_KNOWN`) que já constam em nosso
       banco de dados local (`stop_at_ids`), assumimos que o canal está atualizado.
       Interrompemos o subprocesso imediatamente usando o comando `process_obj.terminate()`.
       Isso poupa banda do usuário e tempo de execução!
    """
    print_info(f"Fase 1: Mapeando vídeos do canal...")
    
    urls_to_try = [channel_url_str]
    is_channel_base = ("@" in channel_url_str or "/channel/" in channel_url_str or "/c/" in channel_url_str)
    
    if is_channel_base and not any(channel_url_str.rstrip("/").endswith(x) for x in ["/videos", "/streams", "/shorts", "/releases", "/playlists"]):
        base_url = channel_url_str.rstrip("/")
        urls_to_try = [f"{base_url}/videos", f"{base_url}/streams", f"{base_url}/shorts"]
    
    videos_found_list: List[Dict[str, Any]] = []
    
    for current_url in urls_to_try:
        consecutive_known_count = 0
        MAX_CONSECUTIVE_KNOWN = 10  # Margem de tolerância para ignorar vídeos fixados (pinned) no topo
        
        cmd_list: List[str] = yt_dlp_cmd_list + cookie_args_list + [
            "--flat-playlist", "--dump-json", "--ignore-errors", "--no-warnings", 
            "--extractor-args", "youtubetab:approximate_date",
            current_url
        ]
        
        try:
            # Cria o subprocesso com pipe para capturar a saída padrão (stdout)
            process_obj = subprocess.Popen(
                cmd_list, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8"
            )
            
            if process_obj.stdout:
                # Lê a saída em streaming linha por linha
                for line_str in process_obj.stdout:
                    try:
                        video_data_dict: Dict = json.loads(line_str.strip())
                        video_id_str: str = video_data_dict.get("id", "")
                        if not video_id_str: 
                            continue
                        
                        # Smart Sync check
                        if stop_at_ids and video_id_str in stop_at_ids:
                            consecutive_known_count += 1
                            if consecutive_known_count >= MAX_CONSECUTIVE_KNOWN:
                                # Matamos o processo filho para interromper a listagem de vídeos antigos
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
                            "subtitle_downloaded": False,
                            "info_downloaded": False,
                            "has_no_subtitle": False
                        })
                        
                        # Reescreve o contador na mesma linha usando Carriage Return (\r)
                        sys.stdout.write(f"\r{ICON_WAIT}  {BCYAN}Vídeos mapeados: {len(videos_found_list)}{RESET}")
                        sys.stdout.flush()
                        
                    except Exception:
                        continue
            
            # Aguarda a finalização definitiva do subprocesso para liberar recursos do SO
            process_obj.wait()
            print()  # Quebra de linha após o término do contador
            
            # Se o yt-dlp retornou erro (diferente de 0) e não baixou nada, pode ser problema com cookies
            if process_obj.returncode != 0 and not videos_found_list and not (stop_at_ids and process_obj.returncode == -15):
                _refresh_cookies_on_error(Path.cwd(), Path(__file__).parent.resolve())
            
        except Exception as error_obj:
            print_err(f"Falha crítica na descoberta: {error_obj}")
            return []
    
    return videos_found_list


def _normalize_lang_pattern(lang_str: str) -> str:
    """
    Garante que a string do idioma esteja no formato de regex esperado pelo yt-dlp.
    
    Explicação para Iniciantes:
    O yt-dlp usa Regex para casar códigos de legenda. Um valor cru como "en" só
    bateria exatamente com a string "en". Passar "^en.*" garante casamento com
    "en", "en-US", "en-GB", etc.
    """
    if not lang_str or lang_str == "N/A":
        return lang_str
    if lang_str.startswith("^") or ".*" in lang_str or "|" in lang_str:
        return lang_str
    return f"^{lang_str}.*"


def escriba_progress_hook(d):
    """Callback invocado periodicamente pelo yt-dlp durante o download de arquivos.
    No Windows, o interpretador Python fica bloqueado durante chamadas de rede C (I/O).
    Executar código Python (como esta função) força o interpretador a checar por sinais
    pendentes (como SIGINT/Ctrl+C) e disparar a KeyboardInterrupt imediatamente.
    """
    import sys
    if getattr(sys, "_escriba_interrupted", False):
        raise KeyboardInterrupt


def download_video(
    yt_dlp_cmd_list: List[str], 
    cookie_args_list: List[str], 
    video_id_str: str, 
    lang_filter_str: str, 
    folder_name_str: str,
    download_video_only_hd: bool = False
) -> int:
    """
    Orquestra o download específico de metadados e legendas de um vídeo do YouTube.
    
    Explicação para Iniciantes (Chamada Interna da API Python vs Linha de Comando):
    Q: O que está acontecendo aqui? O código parece muito mais complexo do que rodar uma linha de comando!
    A: Sim! Em vez de apenas chamar o comando no terminal que baixa tudo que vê pela frente (incluindo
       dezenas de legendas automáticas traduzidas que não queremos), nós usamos o `YoutubeDL` como uma biblioteca.
    
    Passo a passo da inteligência de download:
    1. Fase de Extração (`download=False`):
       Fazemos uma requisição rápida ao YouTube apenas para obter a lista de quais legendas manuais
       e legendas automáticas existem para aquele vídeo.
    2. Decisão Inteligente:
       Procuramos primeiro se há uma legenda escrita por humanos no idioma que queremos (`subtitles`).
       Se não houver, procuramos na lista de legendas geradas automaticamente por IA (`automatic_captions`).
    3. Download Focado:
       Assim que decidimos qual é o idioma ideal, reconfiguramos as opções do `YoutubeDL` para
       fazer o download físico de exatamente apenas aquela única legenda selecionada, convertendo-a
       para o formato SRT e salvando o arquivo `.info.json` correspondente.
    4. Auto-Healing de Erros de Conexão:
       Se o download inicial estourar um erro de HTTP/Privacidade, o script captura a exceção,
       roda a rotina de renovação de cookies do navegador Chrome e faz uma segunda tentativa
       de download com as credenciais limpas antes de desistir.
    """
    output_template_str: str = f"{folder_name_str}-{video_id_str}.%(ext)s"
    url = f"https://www.youtube.com/watch?v={video_id_str}"
    
    # Valida se o ID do vídeo é válido para o YouTube (exatamente 11 caracteres)
    if not (video_id_str and len(video_id_str) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", video_id_str)):
        print_err(f"Incomplete YouTube ID {video_id_str}. URL {url} looks truncated.")
        return 2
    
    download_args = ["-f", "bestvideo[height<=1080]"] if download_video_only_hd else ["--skip-download"]
    
    lang_pattern = _normalize_lang_pattern(lang_filter_str)
    lang_regex = re.compile(lang_pattern, re.IGNORECASE)
    
    current_cookies = list(cookie_args_list)
    
    while True:
        base_args = yt_dlp_cmd_list[3:] + current_cookies + [
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
        
        try:
            # Traduz a lista de comandos CLI em um dicionário estruturado compatível com a API Python do yt-dlp
            parsed_opts = yt_dlp.parse_options(base_args)[3]
            
            # Cria cópia de opções apenas para extração de metadados iniciais
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
            
            chosen_lang = None
            is_auto = False
            
            # Prioridade 1: Buscar legenda manual (humana) que case com o idioma procurado
            for lang_code in subtitles.keys():
                if lang_regex.match(lang_code):
                    chosen_lang = lang_code
                    is_auto = False
                    break
                    
            # Prioridade 2: Buscar legenda automática (IA) como plano de fundo
            if not chosen_lang:
                for lang_code in auto_captions.keys():
                    if lang_regex.match(lang_code):
                        chosen_lang = lang_code
                        is_auto = True
                        break
                        
            # Modifica as opções de download para instruir progresso e restringir apenas ao idioma selecionado
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
                # Se não encontrou nenhuma legenda válida para o idioma, desativa os downloads de subs
                download_opts.update({
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                    'subtitleslangs': [],
                })
                info['requested_subtitles'] = {}
                
            # Executa o download real em memória
            with yt_dlp.YoutubeDL(download_opts) as ydl_dl:
                ydl_dl.process_info(info)
                
            return 0
        except Exception as error_obj:
            if getattr(sys, "_escriba_interrupted", False):
                raise KeyboardInterrupt
            error_str = str(error_obj)
            is_429 = "429" in error_str or "too many requests" in error_str.lower()
            
            if is_429:
                print_warn(f"\n⚠ [HTTP 429] Limite de requisições excedido no vídeo {video_id_str}.")
                print_warn("O YouTube bloqueou temporariamente este IP ou sessão (Too Many Requests).")
                print_warn("Por favor, realize os seguintes passos para liberação:")
                print_warn("  1. Abra o YouTube no navegador Google Chrome desta máquina.")
                print_warn("  2. Reproduza qualquer vídeo para verificar/resolver CAPTCHAs.")
                print_warn("  3. Caso o IP esteja bloqueado, altere a VPN ou mude sua conexão.")
                print_info("Pressione ENTER para renovar os cookies e tentar novamente, digite 'p' + ENTER para pular este vídeo, ou Ctrl+C para abortar...")
                try:
                    user_input = input().strip().lower()
                except KeyboardInterrupt, EOFError:
                    print_err("\nProcesso interrompido pelo usuário.")
                    raise KeyboardInterrupt
                
                if user_input == "p":
                    print_warn(f"Vídeo {video_id_str} pulado pelo usuário devido a limite de requisições.")
                    return 1
                
                # Tenta renovar cookies e reinicia o loop
                try:
                    current_cookies = _refresh_cookies_on_error(
                        Path.cwd(), Path(__file__).parent.resolve()
                    )
                except Exception as e:
                    print_warn(f"Erro ao renovar cookies: {e}")
                continue
            
            # Se não for 429, tenta o fluxo de auto-healing padrão com cookies uma vez
            print_warn(f"Erro ao baixar vídeo {video_id_str}: {error_obj}. Tentando renovar cookies do navegador...")
            try:
                new_cookies_args_list: List[str] = _refresh_cookies_on_error(
                    Path.cwd(), Path(__file__).parent.resolve()
                )
                
                # Reconstrói a chamada completa para nova tentativa
                base_args_retry = yt_dlp_cmd_list[3:] + new_cookies_args_list + [
                    "--ignore-no-formats-error",
                    "--write-info-json",
                    "--restrict-filenames",
                ] + download_args + [
                    "--write-sub",
                    "--write-auto-sub",
                    "--convert-subs", "srt",
                    "--no-warnings",
                    "--sub-langs", lang_pattern,
                    "-o", output_template_str,
                    url
                ]
                
                parsed_opts_retry = yt_dlp.parse_options(base_args_retry)[3]
                extract_opts_retry = dict(parsed_opts_retry)
                extract_opts_retry.update({
                    'skip_download': True,
                    'quiet': True,
                    'no_warnings': True,
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                })
                
                with yt_dlp.YoutubeDL(extract_opts_retry) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                if info is None:
                    raise ValueError("Não foi possível extrair informações do vídeo após renovação de cookies (info é None)")
                    
                subtitles = info.get('subtitles') or {}
                auto_captions = info.get('automatic_captions') or {}
                
                chosen_lang = None
                is_auto = False
                for lang_code in subtitles.keys():
                    if lang_regex.match(lang_code):
                        chosen_lang = lang_code
                        is_auto = False
                        break
                if not chosen_lang:
                    for lang_code in auto_captions.keys():
                        if lang_regex.match(lang_code):
                            chosen_lang = lang_code
                            is_auto = True
                            break
                            
                download_opts_retry = dict(parsed_opts_retry)
                download_opts_retry['progress_hooks'] = [escriba_progress_hook]
                if chosen_lang:
                    download_opts_retry.update({
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
                    download_opts_retry.update({
                        'writesubtitles': False,
                        'writeautomaticsub': False,
                        'subtitleslangs': [],
                    })
                    info['requested_subtitles'] = {}
                    
                with yt_dlp.YoutubeDL(download_opts_retry) as ydl_dl:
                    ydl_dl.process_info(info)
                return 0
            except Exception as retry_error:
                if getattr(sys, "_escriba_interrupted", False):
                    raise KeyboardInterrupt
                retry_str = str(retry_error)
                if "429" in retry_str or "too many requests" in retry_str.lower():
                    print_warn(f"\n⚠ [HTTP 429] Limite de requisições excedido no vídeo {video_id_str} após tentativa de correção automática.")
                    print_warn("Por favor, realize os seguintes passos para liberação:")
                    print_warn("  1. Abra o YouTube no navegador Google Chrome desta máquina.")
                    print_warn("  2. Reproduza qualquer vídeo para verificar/resolver CAPTCHAs.")
                    print_warn("  3. Caso o IP esteja bloqueado, altere a VPN ou mude sua conexão.")
                    print_info("Pressione ENTER para renovar os cookies e tentar novamente, digite 'p' + ENTER para pular este vídeo, ou Ctrl+C para abortar...")
                    try:
                        user_input = input().strip().lower()
                    except KeyboardInterrupt, EOFError:
                        print_err("\nProcesso interrompido pelo usuário.")
                        raise KeyboardInterrupt
                    
                    if user_input == "p":
                        print_warn(f"Vídeo {video_id_str} pulado pelo usuário devido a limite de requisições.")
                        return 1
                    
                    try:
                        current_cookies = _refresh_cookies_on_error(
                            Path.cwd(), Path(__file__).parent.resolve()
                        )
                    except Exception as e:
                        print_warn(f"Erro ao renovar cookies: {e}")
                    continue
                
                print_err(f"Erro crítico após renovar cookies no vídeo {video_id_str}: {retry_error}")
                return 2


def filter_youtube_cookies(cookies_path_obj: Path) -> None:
    """
    Limpa o arquivo de cookies extraído, mantendo apenas o que pertence ao Google/YouTube.
    
    Explicação para Iniciantes (Privacidade e Segurança):
    Q: Por que limpar os cookies?
    A: Quando o yt-dlp extrai cookies do Chrome, ele lê TODAS as sessões do navegador
       (incluindo bancos, redes sociais e e-mails) e salva em texto puro no arquivo `cookies.txt`.
       Isso é uma grande brecha de segurança!
       Esta função lê o arquivo linha por linha e mantém APENAS as linhas que contêm
       comentários ou os domínios ".youtube.com" e ".google.com". Todas as credenciais de outros sites
       são imediatamente destruídas no arquivo final, garantindo a privacidade do desenvolvedor.
    """
    if not cookies_path_obj.exists():
        return

    try:
        with open(cookies_path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            lines_list: List[str] = file_descriptor_obj.readlines()

        filtered_lines_list: List[str] = []
        for line_str in lines_list:
            if line_str.startswith("#") or "youtube.com" in line_str or "google.com" in line_str:
                filtered_lines_list.append(line_str)

        # Grava de volta o arquivo higienizado
        with open(cookies_path_obj, "w", encoding="utf-8") as file_descriptor_obj:
            file_descriptor_obj.writelines(filtered_lines_list)
            
    except Exception as error_obj:
        print_warn(f"Não foi possível higienizar os cookies extraídos: {error_obj}")
