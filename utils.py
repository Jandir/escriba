import os
import sys
import time
import re
from pathlib import Path
from typing import Optional, List, Dict

_EXT_RE = re.compile(r'\.(srt|md|txt|json|vtt)$', flags=re.IGNORECASE)
_ORIG_RE = re.compile(r'-orig$', flags=re.IGNORECASE)
_LANG_RE = re.compile(r'[.\-][a-z]{2}(?:-[a-z]{2,3})?$', flags=re.IGNORECASE)
_ID_MATCH_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')
_FIND_ID_RE = re.compile(r'([A-Za-z0-9_-]{11})')
_VALID_CHAR_RE = re.compile(r'[A-Za-z0-9_-]')

# ─── Paleta ANSI (Explicação para Iniciantes) ──────────────────────────────────
# Códigos ANSI são sequências especiais de caracteres não imprimíveis que o Terminal
# interpreta como comandos especiais para mudar a cor do texto, estilo de fonte (como negrito)
# ou controlar o cursor.
# Exemplo: A string "\033[0;31m" diz ao terminal: "Mude a cor do texto para vermelho daqui em diante".
# O prefixo '\033[' (ou '\x1b[') é o sinalizador de controle (ESC), e 'm' indica que estamos
# definindo atributos gráficos de exibição.
RESET: str = "\033[0m"  # Reseta qualquer estilo de cor ou fonte de volta ao padrão do console.
BOLD: str = "\033[1m"   # Aplica negrito (bright).
DIM: str = "\033[2m"    # Aplica efeito esmaecido/opaco (útil para detalhes menos importantes).

# Cores base (Usadas para dar feedback visual instantâneo: verde=sucesso, vermelho=erro)
RED: str = "\033[0;31m"
GREEN: str = "\033[0;32m"
YELLOW: str = "\033[0;33m"
BLUE: str = "\033[0;34m"
WHITE: str = "\033[0;37m"

# Cores Brilhantes / Intensas (Bright)
BRED: str = "\033[1;31m"
BGREEN: str = "\033[1;32m"
BYELLW: str = "\033[1;33m"
BCYAN: str = "\033[1;36m"
BWHITE: str = "\033[1;37m"

# ─── Ícones semânticos ──────────────────────────────────────────────────────────
# Usamos ícones visuais para que o usuário identifique o status atual de cada vídeo
# sem precisar ler a mensagem inteira.
ICON_OK: str = f"{BGREEN}✓{RESET}"    # Indica sucesso de processamento ou download.
ICON_ERR: str = f"{BRED}✗{RESET}"     # Indica falha crítica no vídeo.
ICON_WARN: str = f"{BYELLW}⚠{RESET}"   # Indica atenção ou ação corretiva em andamento (ex: cookies expirados).
ICON_SKIP: str = f"{DIM}↷{RESET}"     # Indica vídeo ignorado porque já foi baixado anteriormente.
ICON_DL: str = f"{BCYAN}▶{RESET}"     # Indica processo ativo de download ou rede.
ICON_WAIT: str = f"{YELLOW}◌{RESET}"   # Caractere de carregamento (loading).
ICON_INFO: str = f"{BLUE}•{RESET}"    # Ponto azul para indicar notas e avisos informativos.


def _print_formatted(icon_str: str, message_str: str, indentation_prefix_str: str = "", end_char_str: str = "\n") -> None:
    """
    Função interna centralizada para exibição de mensagens formatadas com ícones, cores e identação.
    
    Explicação para Iniciantes:
    Centralizar funções de I/O de console (como impressões) é uma excelente prática de Clean Code.
    Se um dia quisermos mudar como os logs são escritos (ex: salvar em arquivo ou enviar para a web),
    só precisamos alterar esta função, em vez de centenas de instruções 'print' espalhadas pelo sistema.
    - `flush=True` obriga o interpretador a esvaziar o buffer de saída do terminal imediatamente.
      Sem isso, o Python pode 'guardar' o texto na memória por milissegundos adicionais,
      o que causa lag visual nas animações da CLI.
    """
    print(f"{indentation_prefix_str}{icon_str}  {message_str}", end=end_char_str, flush=True)


def print_ok(message_str: str, indentation_prefix_str: str = "") -> None:
    """Exibe uma mensagem verde de sucesso com o ícone ✓."""
    _print_formatted(ICON_OK, f"{GREEN}{message_str}{RESET}", indentation_prefix_str)


def print_err(message_str: str, indentation_prefix_str: str = "") -> None:
    """Exibe uma mensagem vermelha intensa de erro com o ícone ✗."""
    _print_formatted(ICON_ERR, f"{BRED}{message_str}{RESET}", indentation_prefix_str)


def print_warn(message_str: str, indentation_prefix_str: str = "") -> None:
    """Exibe uma mensagem amarela de atenção com o ícone ⚠."""
    _print_formatted(ICON_WARN, f"{YELLOW}{message_str}{RESET}", indentation_prefix_str)


def print_info(message_str: str, indentation_prefix_str: str = "") -> None:
    """Exibe uma mensagem informativa esmaecida com um marcador azul central."""
    _print_formatted(ICON_INFO, f"{DIM}{message_str}{RESET}", indentation_prefix_str)


def print_skip(message_str: str, indentation_prefix_str: str = "") -> None:
    """Exibe uma mensagem de item ignorado/pulado com estilo opaco e ícone de seta ↷."""
    _print_formatted(ICON_SKIP, f"{DIM}{message_str}{RESET}", indentation_prefix_str)


def print_dl(message_str: str, indentation_prefix_str: str = "") -> None:
    """Exibe uma mensagem indicando download ativo com cor ciano e seta de reprodução ▶."""
    _print_formatted(ICON_DL, f"{BCYAN}{message_str}{RESET}", indentation_prefix_str)


def print_section(section_title_str: str) -> None:
    """Imprime uma quebra de seção visual bonita e destacada em negrito branco no terminal."""
    print()
    print(f"{BOLD}{BWHITE}{section_title_str}{RESET}")
    print()


def print_header(script_version_str: str) -> None:
    """Exibe o cabeçalho oficial do Escriba com sua versão atual."""
    print()
    print(f"{BOLD}{BCYAN}Escriba v{script_version_str}{RESET}")
    print()


def print_countdown(seconds_int: int, message_str: str, indentation_prefix_str: str = "") -> None:
    """
    Exibe uma barra de progresso visual interativa com contagem regressiva que se atualiza na mesma linha.
    
    Explicação para Iniciantes:
    - O loop `range(seconds_int, -1, -1)` faz a contagem de trás para frente, de X segundos até 0.
    - Usamos `sys.stdout.write` para termos controle absoluto de saída de strings.
    - O caractere de controle `\r` (Carriage Return) diz ao console: "Mova o cursor de volta ao início
      desta mesma linha atual". Isso nos permite escrever por cima do texto anterior.
    - A sequência ANSI `\x1b[K` (Clear Line from Cursor) é fundamental: ela apaga tudo que restou na linha
      da direita do cursor até a borda da janela do terminal. Isso evita que caracteres antigos
      sobrem se a nova mensagem impressa for mais curta que a anterior.
    - Capturamos `KeyboardInterrupt` (quando o usuário aperta Ctrl+C) para limpar a linha imediatamente
      antes de repassar a exceção com o comando `raise`, mantendo o console limpo e organizado.
    """
    bar_width_int: int = 20
    try:
        for remaining_int in range(seconds_int, -1, -1):
            _update_countdown_line(remaining_int, seconds_int, bar_width_int, message_str, indentation_prefix_str)
            if remaining_int > 0:
                time.sleep(1)
        # Limpa o texto da tela ao finalizar
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()
    except KeyboardInterrupt:
        # Se interrompido, garante que o terminal seja limpo de forma elegante
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()
        raise


def _update_countdown_line(remaining_int: int, total_int: int, width_int: int, msg_str: str, indent_str: str) -> None:
    """
    Função auxiliar que calcula as proporções matemáticas e pinta a barra de progresso no terminal.
    
    Explicação para Iniciantes:
    1. O caractere '█' representa a porção concluída, e '░' a porção pendente.
    2. Calculamos a fração concluída e multiplicamos pela largura da barra (`width_int`)
       para saber exatamente quantos blocos preenchidos desenhar.
    3. O alinhamento `{:>3}` na formatação de string alinha o número à direita com largura fixa de 3
       caracteres (evitando trepidação visual na tela quando o percentual muda de 9% para 100%).
    """
    filled_int: int = int((total_int - remaining_int) / total_int * width_int) if total_int else width_int
    bar_str: str = f"{GREEN}{'█' * filled_int}{DIM}{'░' * (width_int - filled_int)}{RESET}"
    pct_int: int = int((total_int - remaining_int) / total_int * 100) if total_int else 100
    sys.stdout.write(f"\r{indent_str}{ICON_WAIT}  {msg_str} [{bar_str}] {pct_int:>3}%  {DIM}{remaining_int}s{RESET}  \x1b[K")
    sys.stdout.flush()


def extract_video_id(filename_or_path: str) -> str:
    """
    Extrai o ID único de vídeo (11 caracteres do YouTube ou numérico do Vimeo) de caminhos de arquivos.
    
    Lógica Didática (Explicação para Iniciantes):
    Os arquivos baixados pelo yt-dlp costumam terminar com o ID e a extensão
    (ex: "meu_canal-ZHbX0yoC8uo.info.json" ou "canal-123456789.pt.srt").
    
    Passos do Algoritmo:
    1. Usamos `os.path.basename` para descartar toda a estrutura de pastas do sistema
       operacional, isolando apenas o nome do arquivo final (ex: "/usr/bin/arq.txt" vira "arq.txt").
    2. Removemos as extensões comuns de metadados como ".info.json" ou ".srt" usando substituição de Regex.
    3. Limpamos os sufixos de idioma que costumam ser anexados pelas ferramentas (ex: ".pt-br" ou "-en").
    4. Analisamos se os últimos 11 caracteres batem com o padrão base de identificação do YouTube:
       letras maiúsculas, minúsculas, números, traços e sublinhas (`[A-Za-z0-9_-]{11}`).
    5. Se falhar, fazemos um fallback rodando uma varredura geral por trás em busca de qualquer
       sequência alfanumérica de 11 dígitos, pegando a que estiver mais próxima da ponta direita.
    """
    name: str = os.path.basename(filename_or_path)
    
    # 1. Remove as extensões de arquivo sem se importar com maiúsculas/minúsculas
    if name.lower().endswith(".info.json"):
        name = name[:-10]
    else:
        name = _EXT_RE.sub('', name)
        
    # 2. Remove o sufixo '-orig' se presente no final (comum em arquivos markdown processados)
    name = _ORIG_RE.sub('', name)
        
    # 3. Remove sufixos de idioma como '.pt-br', '.en', '-en'
    # O regex `[.\-][a-z]{2}(?:-[a-z]{2,3})?$` procura um traço ou ponto, seguido de duas letras,
    # opcionalmente seguido de outro traço e mais 2 ou 3 letras, ancorado no final da string ($).
    name = _LANG_RE.sub('', name)
    
    # 3. Verifica se o final do nome restante é um ID legítimo do YouTube (11 caracteres de padrão fixo)
    if len(name) >= 11:
        candidate: str = name[-11:]
        if _ID_MATCH_RE.match(candidate):
            return candidate
            
    # 4. Caso não esteja na ponta (Vimeo ou nomes alterados), varremos toda a string por grupos de 11 caracteres.
    matches: List[str] = _FIND_ID_RE.findall(name)
    if matches:
        # Percorremos a lista ao contrário para priorizar o ID mais próximo do fim do arquivo
        for m in reversed(matches):
            pos: int = name.rfind(m)
            # Uma medida extra de segurança: o ID legítimo não pode ter letras ou números grudados a ele,
            # pois isso indicaria que ele faz parte de uma palavra maior (como o próprio nome do canal).
            if pos + 11 == len(name) or not _VALID_CHAR_RE.match(name[pos+11]):
                return m
        return matches[-1]

    return "Sem ID"


def format_date(raw_date_any: Optional[str | int]) -> str:
    """
    Formata datas cruas vindas do YouTube/Vimeo para o padrão de leitura humana YYYY-MM-DD.
    
    Explicação para Iniciantes:
    1. Se a API retornar vazia, tratamos como 'Desconhecida' em vez de deixar o script dar erro.
    2. O YouTube tradicionalmente devolve datas como string numérica de 8 dígitos (ex: "20260316").
       Fatiamos essa string (slice) usando índices:
       - `date_str[:4]` pega os primeiros 4 caracteres ("2026").
       - `date_str[4:6]` pega os caracteres de índice 4 e 5 ("03").
       - `date_str[6:]` pega do índice 6 até o final ("16").
    3. Se já vier formatada corretamente (ex: "2026-03-16"), apenas retornamos direto graças ao teste de regex.
    """
    if not raw_date_any:
        return "Desconhecida"
        
    date_str: str = str(raw_date_any).strip()
    
    # Caso 1: Formato padrão do YouTube (8 dígitos numéricos grudados: YYYYMMDD)
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    
    # Caso 2: Já está no formato adequado ISO (YYYY-MM-DD)
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str
        
    # Fallback suave caso venha qualquer string inusitada (por exemplo, "None" ou "N/A")
    return date_str if date_str not in ("N/A", "", "None") else "Desconhecida"
