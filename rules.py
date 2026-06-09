import re
import functools
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Pattern
from utils import print_err

# EXPLICAÇÃO PARA INICIANTES:
# O Path(__file__) aponta para este arquivo físico específico. O '.parent' nos dá a pasta
# onde ele reside e o '.resolve()' converte caminhos relativos (como '.' ou '..') em um
# caminho absoluto definitivo no disco rígido do sistema (ex: /Users/usuario/.../rules.py).
# Isso garante que não importando de onde executamos o script, ele sempre saberá onde ele mesmo está.
_SCRIPT_DIR_PATH: Path = Path(__file__).parent.resolve()

"""
MÓDULO RULES: O Tradutor de Termos
----------------------------------
Este módulo é responsável por garantir que termos específicos sejam escritos 
corretamente nas transcrições (ex: nomes próprios, siglas ou termos técnicos).
Ele funciona como um sistema de "Localizar e Substituir" inteligente.

Explicação para Iniciantes:
Em sistemas de transcrição e inteligência artificial, é muito comum que termos 
específicos (como gírias, nomes próprios, termos em inglês ou palavras religiosas)
sejam transcritos incorretamente pelo motor de voz para texto (ex: transcrever "Ekklezia" 
como "eklesia" ou "igreja"). Este módulo lê dicionários de regras fornecidos pelo usuário
e os aplica de forma otimizada sobre o texto final para fazer as devidas correções.
"""


def _parse_rules_file(path_obj: Path, rules_dict: Dict[str, str]) -> None:
    """
    Lê um arquivo de texto de regras e extrai as regras de 'troca de palavras'
    injetando-as diretamente no dicionário recebido.
    
    Explicação para Iniciantes:
    1. Usamos 'path_obj.exists()' para testar de antemão se o arquivo realmente está no disco,
       evitando que o programa dê erro de 'Arquivo Não Encontrado' (FileNotFoundError).
    2. O 'with open(...) as file_descriptor_obj' é o padrão recomendado no Python (Context Manager).
       Ele garante que o arquivo seja fechado automaticamente pelo sistema operacional assim que
       terminarmos de ler, mesmo se ocorrer um erro inesperado no meio do caminho.
    3. Usamos 'encoding="utf-8"' de forma explícita para garantir compatibilidade com caracteres
       acentuados e emojis, independente se o script está rodando no Windows, Linux ou macOS.
    """
    if not path_obj.exists():
        return
    try:
        with open(path_obj, "r", encoding="utf-8") as file_descriptor_obj:
            for raw_line_str in file_descriptor_obj:
                _process_rule_line(raw_line_str, rules_dict)
    except Exception as error_obj:
        # Se ocorrer qualquer falha física ao ler o arquivo (ex: sem permissão),
        # usamos nossa função utilitária para imprimir no terminal de forma legível.
        print_err(f"Erro ao ler regras em {path_obj.name}: {error_obj}")


def _process_rule_line(raw_line_str: str, rules_dict: Dict[str, str]) -> None:
    """
    Transforma uma linha de texto do tipo 'termo_antigo,termo_novo' ou 'antigo=novo'
    em uma entrada válida em nosso dicionário de mapeamento.
    
    Explicação para Iniciantes:
    - O método '.strip()' remove espaços em branco, quebras de linha ('\n') e tabulações
      das pontas da linha. Isso evita ler linhas que parecem vazias mas têm espaços.
    - Linhas iniciadas com '#' são tratadas como comentários, assim o usuário pode documentar
      suas próprias regras de substituição sem quebrar o processamento.
    - O split(',', 1) ou split('=', 1) faz a divisão em no máximo duas partes (original e novo).
      O '1' impede que o termo novo seja cortado se ele próprio contiver uma vírgula ou sinal de igual.
    """
    clean_line_str: str = raw_line_str.strip()
    # Ignora linhas totalmente vazias ou que comecem com '#' (comentários)
    if not clean_line_str or clean_line_str.startswith("#"):
        return

    # Aceitamos tanto vírgula quanto sinal de igual como separador de termos
    separator_str: str = "," if "," in clean_line_str else "="
    if separator_str in clean_line_str:
        # O split(..., 1) divide na primeira ocorrência do separador
        original_term_str, new_term_str = clean_line_str.split(separator_str, 1)
        # .strip() remove os espaços extras: " palavra " vira "palavra"
        rules_dict[original_term_str.strip()] = new_term_str.strip()


@functools.lru_cache(None)
def _load_ekklezia_rules() -> List[Tuple[str, str]]:
    """
    Carrega as regras de substituição do arquivo rules.txt em dois níveis.
    
    Explicação para Iniciantes:
    1. O '@functools.lru_cache(None)' é um decorator que implementa o padrão 'Memoization'.
       A leitura de disco é lenta (I/O custoso). Com o cache ativado, na primeira vez que
       a função é chamada, o Python lê o arquivo físico. Nas chamadas seguintes, ele entrega
       o resultado direto da memória RAM instantaneamente, sem encostar no disco rígido.
    2. Lemos as regras em dois níveis:
       - Primeiro a regra "global" da pasta do script (`_SCRIPT_DIR_PATH / "rules.txt"`).
       - Depois a regra "local" da pasta atual onde o terminal está (`Path.cwd() / "rules.txt"`).
       Dessa forma, as regras locais sobrescrevem ou complementam as globais se houver colisões.
    """
    all_rules_dict: Dict[str, str] = {}
    
    # 1. Carrega regras globais (do diretório onde os arquivos do script Escriba vivem)
    _parse_rules_file(_SCRIPT_DIR_PATH / "rules.txt", all_rules_dict)
    
    # 2. Carrega regras locais (da pasta de execução onde estamos gravando as saídas)
    _parse_rules_file(Path.cwd() / "rules.txt", all_rules_dict)
    
    # Retorna uma lista de tuplas para podermos ordenar mais tarde
    return list(all_rules_dict.items())


@functools.lru_cache(None)
def _get_ekklezia_regex() -> Tuple[Optional[Pattern], Dict[str, str]]:
    r"""
    Compila todas as regras de palavras em uma única e poderosa "Expressão Regular".
    
    Explicação para Iniciantes:
    - Procurar 500 palavras individualmente em um texto longo exigiria passar pelo texto 500 vezes,
      o que tornaria o script extremamente lento (complexidade de tempo O(N * M)).
      Em vez disso, unimos todas as palavras usando o caractere '|' (que significa 'OU' no Regex)
      e compilamos em um único motor automatizado que varre o texto em uma única passada!
    - Ordenamos as chaves por comprimento (`len`) decrescente:
      Se tivermos regras para "São" e "São Paulo", e o texto tiver "São Paulo", queremos que
      a regra mais específica e longa ("São Paulo") tenha prioridade. Caso contrário, se
      procurássemos "São" primeiro, substituiríamos apenas a primeira palavra, estragando o nome composto.
    - O `re.escape()` coloca barras de escape (ex: '\.') em qualquer caractere especial do regex que
      esteja na palavra original, garantindo que o ponto físico '.' seja interpretado como um ponto literal,
      e não como 'qualquer caractere' (que é a função do ponto puro no Regex).
    """
    rules_list: List[Tuple[str, str]] = _load_ekklezia_rules()
    if not rules_list:
        return None, {}

    # Ordena as regras da maior palavra para a menor
    sorted_rules_list: List[Tuple[str, str]] = sorted(rules_list, key=lambda x_tuple: len(x_tuple[0]), reverse=True)
    
    # Une todas as palavras escapadas com 'OU' (ex: "palavra1|palavra2|expressao\\d")
    regex_pattern_str: str = "|".join(re.escape(original_str) for original_str, _ in sorted_rules_list)
    lookup_dict: Dict[str, str] = {original_str: new_str for original_str, new_str in sorted_rules_list}

    # re.compile traduz a string do padrão em um objeto de regex otimizado e compilado em nível de C
    return re.compile(regex_pattern_str), lookup_dict


def clean_ekklezia_terms(text_str: str) -> str:
    """
    Aplica todas as regras de substituição de termos cadastrados usando expressão regular otimizada.
    
    Explicação para Iniciantes:
    - Esta é a função pública chamada pelo pipeline de limpeza de texto.
    - Usamos a função `regex_pattern_obj.sub(_replace_callback, text_str)`.
      A beleza de passar uma função callback (`_replace_callback`) como primeiro parâmetro do `.sub()` é
      que, para cada ocorrência encontrada no texto, o Python chama a nossa função passando o objeto `Match`.
      A nossa função olha no mapa (`lookup_dict`) e devolve o substituto correto de forma dinâmica!
    """
    if not text_str:
        return text_str

    regex_pattern_obj, lookup_dict = _get_ekklezia_regex()
    if not regex_pattern_obj:
        return text_str

    def _replace_callback(match_obj: re.Match) -> str:
        """
        Função interna que decide qual termo novo usar com base no casamento (match) obtido.
        
        Explicação para Iniciantes:
        O 'match_obj.group(0)' contém o termo bruto exato que o motor Regex capturou no texto.
        Usamos esse termo como chave no nosso dicionário de tradução (`lookup_dict`) para retornar
        o valor substituído correspondente de forma instantânea (tempo constante O(1)).
        """
        return lookup_dict[match_obj.group(0)]

    # Aplica todas as substituições e retorna o texto higienizado
    return regex_pattern_obj.sub(_replace_callback, text_str)
