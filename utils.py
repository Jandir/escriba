import sys
import time
from typing import Optional

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


def _print_formatted(icon_str: str, message_str: str, indentation_prefix: str = "", end_char: str = "\n") -> None:
    """Função base para impressão formatada com ícones e cores."""
    print(f"{indentation_prefix}{icon_str}  {message_str}", end=end_char, flush=True)


def print_ok(message_str: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_OK, f"{GREEN}{message_str}{RESET}", indentation_prefix)


def print_err(message_str: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_ERR, f"{BRED}{message_str}{RESET}", indentation_prefix)


def print_warn(message_str: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_WARN, f"{YELLOW}{message_str}{RESET}", indentation_prefix)


def print_info(message_str: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_INFO, f"{DIM}{message_str}{RESET}", indentation_prefix)


def print_skip(message_str: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_SKIP, f"{DIM}{message_str}{RESET}", indentation_prefix)


def print_dl(message_str: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_DL, f"{BCYAN}{message_str}{RESET}", indentation_prefix)


def print_section(section_title_str: str) -> None:
    print()
    print(f"{BOLD}{BWHITE}{section_title_str}{RESET}")
    print()


def print_header(script_version_str: str) -> None:
    print()
    print(f"{BOLD}{BCYAN}Escriba v{script_version_str}{RESET}")
    print()


def print_countdown(seconds_int: int, message_str: str, indentation_prefix: str = "") -> None:
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
            _update_countdown_line(remaining_int, seconds_int, bar_width_int, message_str, indentation_prefix)
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


def _update_countdown_line(rem_int: int, total_int: int, width_int: int, msg_str: str, indent_str: str) -> None:
    """Helper para atualizar a linha da barra de progresso no console."""
    filled_int: int = int((total_int - rem_int) / total_int * width_int) if total_int else width_int
    bar_str: str = f"{GREEN}{'█' * filled_int}{DIM}{'░' * (width_int - filled_int)}{RESET}"
    pct_int: int = int((total_int - rem_int) / total_int * 100) if total_int else 100
    sys.stdout.write(f"\r{indent_str}{ICON_WAIT}  {msg_str} [{bar_str}] {pct_int:>3}%  {DIM}{rem_int}s{RESET}  \x1b[K")
    sys.stdout.flush()

