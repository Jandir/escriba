import sys
import time
import re
from pathlib import Path
from typing import Optional, List, Dict

# ─── Paleta ANSI (Explicação para Juniores) ──────────────────────────────────
# Códigos ANSI são sequências especiais de caracteres que o Terminal entende 
# como comandos para mudar a cor do texto ou aplicar negrito. 
# Exemplo: \033[0;31m diz ao terminal: "mude a cor para vermelho daqui em diante".
RESET: str = "\033[0m"
BOLD: str = "\033[1m"
DIM: str = "\033[2m"

# Cores base (Usadas para dar feedback visual rápido: verde=sucesso, vermelho=erro)
RED: str = "\033[0;31m"
GREEN: str = "\033[0;32m"
YELLOW: str = "\033[0;33m"
BLUE: str = "\033[0;34m"
WHITE: str = "\033[0;37m"

# Cores Brilhantes (Bright)
BRED: str = "\033[1;31m"
BGREEN: str = "\033[1;32m"
BYELLW: str = "\033[1;33m"
BCYAN: str = "\033[1;36m"
BWHITE: str = "\033[1;37m"

# ─── Ícones semânticos ──────────────────────────────────────────────────────────
# Usamos ícones para que o usuário identifique o status do processo num relance.
ICON_OK: str = f"{BGREEN}✓{RESET}"   # Tudo certo
ICON_ERR: str = f"{BRED}✗{RESET}"    # Algo deu errado
ICON_WARN: str = f"{BYELLW}⚠{RESET}"  # Atenção
ICON_SKIP: str = f"{DIM}↷{RESET}"    # Já foi feito, pulando
ICON_DL: str = f"{BCYAN}▶{RESET}"   # Fazendo download
ICON_WAIT: str = f"{YELLOW}◌{RESET}"  # Aguardando tempo ou resposta
ICON_INFO: str = f"{BLUE}•{RESET}"   # Apenas informação


def _print_formatted(icon_str: str, message_str: str, indentation_prefix_str: str = "", end_char_str: str = "\n") -> None:
    """Função base para impressão formatada com ícones e cores."""
    print(f"{indentation_prefix_str}{icon_str}  {message_str}", end=end_char_str, flush=True)


def print_ok(message_str: str, indentation_prefix_str: str = "") -> None:
    _print_formatted(ICON_OK, f"{GREEN}{message_str}{RESET}", indentation_prefix_str)


def print_err(message_str: str, indentation_prefix_str: str = "") -> None:
    _print_formatted(ICON_ERR, f"{BRED}{message_str}{RESET}", indentation_prefix_str)


def print_warn(message_str: str, indentation_prefix_str: str = "") -> None:
    _print_formatted(ICON_WARN, f"{YELLOW}{message_str}{RESET}", indentation_prefix_str)


def print_info(message_str: str, indentation_prefix_str: str = "") -> None:
    _print_formatted(ICON_INFO, f"{DIM}{message_str}{RESET}", indentation_prefix_str)


def print_skip(message_str: str, indentation_prefix_str: str = "") -> None:
    _print_formatted(ICON_SKIP, f"{DIM}{message_str}{RESET}", indentation_prefix_str)


def print_dl(message_str: str, indentation_prefix_str: str = "") -> None:
    _print_formatted(ICON_DL, f"{BCYAN}{message_str}{RESET}", indentation_prefix_str)


def print_section(section_title_str: str) -> None:
    print()
    print(f"{BOLD}{BWHITE}{section_title_str}{RESET}")
    print()


def print_header(script_version_str: str) -> None:
    print()
    print(f"{BOLD}{BCYAN}Escriba v{script_version_str}{RESET}")
    print()


def print_countdown(seconds_int: int, message_str: str, indentation_prefix_str: str = "") -> None:
    """
    Exibe uma barra de progresso com contagem regressiva que se atualiza na mesma linha.
    
    Explicação para Juniores:
    Usamos '\r' (Carriage Return) para voltar o cursor ao início da linha no terminal,
    permitindo que a gente "escreva por cima" do texto anterior. Isso cria a ilusão
    de animação.
    """
    bar_width_int: int = 20
    try:
        # Loop que vai de 'seconds_int' até 0
        for remaining_int in range(seconds_int, -1, -1):
            _update_countdown_line(remaining_int, seconds_int, bar_width_int, message_str, indentation_prefix_str)
            if remaining_int > 0:
                time.sleep(1)
        # Limpa a linha ao final (\x1b[K limpa do cursor até o fim da linha)
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()
    except KeyboardInterrupt:
        # Se o usuário apertar Ctrl+C, limpamos a linha e repassamos o erro
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()
        raise


def _update_countdown_line(remaining_int: int, total_int: int, width_int: int, msg_str: str, indent_str: str) -> None:
    """Helper para atualizar a linha da barra de progresso no console."""
    filled_int: int = int((total_int - remaining_int) / total_int * width_int) if total_int else width_int
    bar_str: str = f"{GREEN}{'█' * filled_int}{DIM}{'░' * (width_int - filled_int)}{RESET}"
    pct_int: int = int((total_int - remaining_int) / total_int * 100) if total_int else 100
    sys.stdout.write(f"\r{indent_str}{ICON_WAIT}  {msg_str} [{bar_str}] {pct_int:>3}%  {DIM}{remaining_int}s{RESET}  \x1b[K")
    sys.stdout.flush()


def extract_video_id(filename_or_path: str) -> str:
    """
    Extrai o ID do YouTube (exatamente 11 caracteres) de um nome de arquivo ou caminho.
    
    Lógica robusta (Explicação para Juniores):
    1. Limpa extensões (.srt, .md, .info.json).
    2. Remove códigos de idioma (ex: -en, .pt-br) que ficam no fim do nome.
    3. Identifica os 11 caracteres do ID, priorizando o final do nome.
    4. Evita confundir o ID com o nome do canal (mesmo se o canal tiver 11+ letras).
    """
    # Se for um objeto Path, pegamos apenas o nome do arquivo.
    name: str = str(Path(filename_or_path).name)
    
    # 1. Remove extensões comuns de forma insensível a maiúsculas/minúsculas.
    if name.lower().endswith(".info.json"):
        name = name[:-10]
    else:
        name = re.sub(r'\.(srt|md|txt|json|vtt)$', '', name, flags=re.IGNORECASE)
        
    # 2. Remove sufixos de idioma (ex: -en, .en, -pt-br, .pt-br).
    # Padrão: um separador (. ou -) seguido de 2 letras, opcionalmente com região (-br).
    name = re.sub(r'[.\-][a-z]{2}(?:-[a-z]{2,3})?$', '', name, flags=re.IGNORECASE)
    
    # 3. Prioridade Máxima: Se o que sobrou termina em exatamente 11 caracteres válidos, 
    # esse é quase certamente o ID do YouTube (padrão do yt-dlp).
    if len(name) >= 11:
        candidate: str = name[-11:]
        if re.match(r'^[A-Za-z0-9_-]{11}$', candidate):
            return candidate
            
    # 4. Fallback: Se não está no final, busca todos os blocos de 11 caracteres.
    matches: List[str] = re.findall(r'([A-Za-z0-9_-]{11})', name)
    if matches:
        # Percorremos de trás para frente para pegar o que está mais próximo do fim.
        for m in reversed(matches):
            pos: int = name.rfind(m)
            # Um ID legítimo não deve ser seguido por outros caracteres alfanuméricos 
            # (pois isso indicaria que ele é parte de uma palavra maior, como o nome do canal).
            if pos + 11 == len(name) or not re.match(r'[A-Za-z0-9_-]', name[pos+11]):
                return m
        return matches[-1]

    return "Sem ID"


def format_date(raw_date_any: Optional[str | int]) -> str:
    """
    Formata uma data de várias origens para o padrão YYYY-MM-DD.
    Suporta: '20231225' (YYYYMMDD) e já formatadas '2023-12-25'.
    """
    if not raw_date_any:
        return "Desconhecida"
        
    date_str: str = str(raw_date_any).strip()
    
    # Caso 1: YYYYMMDD (8 dígitos)
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    
    # Caso 2: Já está no formato YYYY-MM-DD (ou próximo disso)
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str
        
    # Fallback: retorna como string se não for nulo/vazio
    return date_str if date_str not in ("N/A", "", "None") else "Desconhecida"

