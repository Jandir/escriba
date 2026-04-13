import sys
import time
from typing import Optional

# ─── Paleta ANSI ──────────────────────────────────────────────────────────────
RESET: str  = "\033[0m"
BOLD: str   = "\033[1m"
DIM: str    = "\033[2m"

# Cores base
RED: str    = "\033[0;31m"
GREEN: str  = "\033[0;32m"
YELLOW: str = "\033[0;33m"
BLUE: str   = "\033[0;34m"
WHITE: str  = "\033[0;37m"

# Bright
BRED: str   = "\033[1;31m"
BGREEN: str = "\033[1;32m"
BYELLW: str = "\033[1;33m"
BCYAN: str  = "\033[1;36m"
BWHITE: str = "\033[1;37m"

# ─── Ícones semânticos ──────────────────────────────────────────────────────────
ICON_OK: str   = f"{BGREEN}✓{RESET}"   # sucesso
ICON_ERR: str  = f"{BRED}✗{RESET}"    # erro
ICON_WARN: str = f"{BYELLW}⚠{RESET}"  # aviso
ICON_SKIP: str = f"{DIM}↷{RESET}"    # pulando
ICON_DL: str   = f"{BCYAN}▶{RESET}"   # baixando
ICON_WAIT: str = f"{YELLOW}◌{RESET}"  # aguardando
ICON_INFO: str = f"{BLUE}•{RESET}"   # informação


def _print_formatted(icon: str, message: str, indentation_prefix: str = "", end_char: str = "\n") -> None:
    print(f"{indentation_prefix}{icon}  {message}", end=end_char, flush=True)

def print_ok(message: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_OK, f"{GREEN}{message}{RESET}", indentation_prefix)

def print_err(message: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_ERR, f"{BRED}{message}{RESET}", indentation_prefix)

def print_warn(message: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_WARN, f"{YELLOW}{message}{RESET}", indentation_prefix)

def print_info(message: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_INFO, f"{DIM}{message}{RESET}", indentation_prefix)

def print_skip(message: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_SKIP, f"{DIM}{message}{RESET}", indentation_prefix)

def print_dl(message: str, indentation_prefix: str = "") -> None:
    _print_formatted(ICON_DL, f"{BCYAN}{message}{RESET}", indentation_prefix)

def print_section(section_title: str) -> None:
    print()
    print(f"{BOLD}{BWHITE}{section_title}{RESET}")
    print()

def print_header(script_version: str) -> None:
    print()
    print(f"{BOLD}{BCYAN}Escriba v{script_version}{RESET}")
    print()

def print_countdown(seconds_count: int, message: str, indentation_prefix: str = "") -> None:
    visual_bar_width: int = 20
    try:
        for remaining_seconds in range(seconds_count, -1, -1):
            filled_blocks = int((seconds_count - remaining_seconds) / seconds_count * visual_bar_width) if seconds_count else visual_bar_width
            progress_bar_str = f"{GREEN}{'█' * filled_blocks}{DIM}{'░' * (visual_bar_width - filled_blocks)}{RESET}"
            progress_percentage = int((seconds_count - remaining_seconds) / seconds_count * 100) if seconds_count else 100
            sys.stdout.write(f"\r{indentation_prefix}{ICON_WAIT}  {message} [{progress_bar_str}] {progress_percentage:>3}%  {DIM}{remaining_seconds}s{RESET}  \x1b[K")
            sys.stdout.flush()
            if remaining_seconds > 0:
                time.sleep(1)
        sys.stdout.write(f"\r\x1b[K")
        sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write(f"\r\x1b[K")
        sys.stdout.flush()
        raise
