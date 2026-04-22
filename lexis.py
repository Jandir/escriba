#!/usr/bin/env python3
"""
=============================================================================
=============================================================================
LEXIS: Consolidador de Transcrições para NotebookLM
=============================================================================

O QUE ESTE MÓDULO FAZ (PARA PROGRAMADORES JUNIORES):
Este script funciona como um "empacotador" inteligente. Ele pega milhares de 
pequenos arquivos de texto (transcrições de vídeos) e os junta em arquivos 
maiores chamados "Volumes". 

POR QUE FAZEMOS ISSO?
IAs como o NotebookLM trabalham melhor quando recebem arquivos organizados e 
densos. Se enviarmos 1000 arquivos pequenos, a IA se perde. Se enviarmos 
volumes de ~1.8MB, ela consegue indexar o conteúdo com muito mais eficiência.

REGRAS DE OURO DO LEXIS:
1. Prioridade de Formato: Se um vídeo tem .md (capítulos), .txt (texto puro) 
   e .srt (legenda bruta), o Lexis escolhe o .md porque é mais rico.
2. Limpeza: Legendas do YouTube vêm com muita "sujeira" (tags <font>, 
   repetições de texto em roll-up). O Lexis limpa tudo para economizar espaço.
3. Memória (Estado): O Lexis "lembra" o que já processou consultando o arquivo
   `escriba_[canal].json`. Isso evita processar o mesmo vídeo duas vezes.
4. Organização: Tudo que já foi "lido" vai para uma pasta chamada `archive`.

COMO USAR:
- python lexis.py [pasta]: Processa apenas o que é novo (Incremental).
- python lexis.py --reset [pasta]: Apaga tudo e começa do zero.
=============================================================================
"""

import argparse
import os
import re
import shutil
import json
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Set, Pattern, Any
from utils import print_ok, print_err, print_warn, print_info, print_section, BOLD, RESET, DIM

# Nome da pasta onde guardamos os arquivos originais após o processamento.
# Isso mantém a pasta principal limpa e organizada.
ARCHIVE_DIR_NAME: str = "archive" 

# Por que 1.8MB? 
# Arquivos muito grandes podem travar alguns editores ou demorar para carregar em IAs.
# 1.8MB é um "ponto ideal" (sweet spot) entre densidade de informação e performance.
MAX_FILE_SIZE_MB: float = 1.8
MAX_CHARS: int = int(MAX_FILE_SIZE_MB * 1024 * 1024) 

def clean_srt_content(subtitle_content_str: str) -> str:
    """
    Transforma uma legenda .srt (cheia de números e tempos) em um parágrafo de texto fluido.
    
    Explicação para Juniores:
    Arquivos SRT são assim:
    1
    00:00:01 -> 00:00:03
    Olá pessoal!
    
    Esta função remove esses números e tempos, sobrando apenas o "Olá pessoal!".
    Também lida com o "roll-up" (quando a legenda sobe na tela repetindo linhas).
    """
    # Padroniza quebras de linha para evitar problemas entre Windows e Linux
    normalized_content_str: str = subtitle_content_str.replace('\r\n', '\n')
    
    # Esta Expressão Regular (Regex) busca o padrão: número, tempo, texto e espaço vazio.
    # Se você é novo em Regex: estamos capturando apenas o 'grupo 4', que é o texto.
    block_pattern: Pattern = re.compile(
        r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:(?!\n\n).)*?)(?=\n\n|$)', 
        re.DOTALL
    )
    
    subtitle_blocks_list: List[List[str]] = []
    for match_obj in block_pattern.finditer(normalized_content_str):
        # O grupo(4) contém o texto puro da legenda naquele segundo específico.
        _process_subtitle_block(match_obj.group(4).strip(), subtitle_blocks_list)

    # Junta todas as linhas processadas com um espaço simples entre elas.
    cleaned_lines_list: List[str] = []
    for block_list in subtitle_blocks_list:
        cleaned_lines_list.extend(block_list)
        
    return ' '.join(cleaned_lines_list)


def _process_subtitle_block(raw_text_str: str, subtitle_blocks_list: List[List[str]]) -> None:
    """
    Limpa tags HTML (como <b> ou <font>) e decide se o texto é novo ou repetido.
    
    POR QUE ISSO É NECESSÁRIO?
    Em legendas automáticas do YouTube, o sistema usa "roll-up": a mesma frase 
    aparece em múltiplos blocos seguidos enquanto novas palavras são adicionadas.
    Se não filtrarmos, o texto final ficaria assim:
    "Olá"
    "Olá tudo"
    "Olá tudo bem"
    
    Esta função garante que guardamos apenas a parte inédita de cada bloco.
    """
    # Remove qualquer tag entre < > (como <font color="white">) usando Regex simples
    clean_text_str: str = re.sub(r'<[^>]*>', '', raw_text_str)
    
    # Divide o texto em linhas e remove espaços inúteis nas pontas.
    # Usamos list comprehension para ser mais pythônico e performático.
    current_lines_list: List[str] = [line.strip() for line in clean_text_str.split('\n') if line.strip()]
    
    if not current_lines_list:
        return
        
    # Se for o primeiro bloco do arquivo, apenas adicionamos como base de comparação
    if not subtitle_blocks_list:
        subtitle_blocks_list.append(current_lines_list)
        return

    # Comparamos o que temos agora com o bloco imediatamente anterior
    previous_lines_list: List[str] = subtitle_blocks_list[-1]
    start_idx_int: int = _get_deduplication_start_index(previous_lines_list, current_lines_list)
        
    # Só adicionamos as linhas que o '_get_deduplication_start_index' marcou como novas
    if start_idx_int < len(current_lines_list):
        subtitle_blocks_list.append(current_lines_list[start_idx_int:])


def _get_deduplication_start_index(prev_list: List[str], curr_list: List[str]) -> int:
    """
    Compara o bloco anterior com o atual para saber onde começa o texto inédito.
    
    EXPLICAÇÃO PARA JUNIORES:
    Imagine que o bloco anterior (prev_list) terminou com "Olá".
    Se o bloco atual (curr_list) começa com "Olá", "Mundo", nós já lemos o "Olá".
    Então retornamos o índice 1 para dizer: "Comece a ler a partir da segunda palavra".

    Retorna o índice (int) de onde devemos começar a ler o bloco atual.
    """
    # Caso simples: a última linha que lemos é EXATAMENTE igual à primeira deste bloco.
    if prev_list and curr_list[0] == prev_list[-1]:
        return 1
        
    # Caso complexo: o bloco anterior era pequeno e está todo contido no início deste novo.
    # Exemplo: Anterior ["A", "B"], Atual ["A", "B", "C"]. Retorna 2 (pula "A" e "B").
    if len(prev_list) < len(curr_list) and curr_list[:len(prev_list)] == prev_list:
        return len(prev_list)
        
    # Se nada coincidir, o bloco é 100% novo. Retornamos 0.
    return 0

def get_metadata(file_path_str: str) -> Dict[str, str]:
    """
    Tenta descobrir a Data, o Título e o ID do vídeo para um arquivo de texto.
    
    Prioridade de busca:
    1. Arquivo .info.json (criado pelo yt-dlp): Contém tudo mastigado.
    2. Nome do arquivo: Se o .json sumir, tentamos extrair o ID do nome.
    """
    # Gera uma lista de possíveis nomes para o arquivo .info.json
    candidates_list: List[str] = _generate_json_candidates(file_path_str)

    for json_path_str in candidates_list:
        if os.path.exists(json_path_str):
            metadata_dict: Optional[Dict[str, str]] = _load_metadata_from_json(json_path_str)
            if metadata_dict:
                return metadata_dict
    
    # Se chegamos aqui, não achamos o JSON. Vamos tentar adivinhar pelo nome do arquivo.
    id_from_name_str: str = _extract_id_from_filename(file_path_str)
    return {
        "date": "Desconhecida",
        "title": "Sem Título",
        "id": id_from_name_str
    }


def _generate_json_candidates(file_path_str: str) -> List[str]:
    """
    Gera possíveis nomes para o arquivo .info.json associado.
    
    POR QUE ISSO É NECESSÁRIO?
    O yt-dlp às vezes nomeia os arquivos de forma inconsistente (ex: adiciona 
    a língua no final do .txt mas não no .json). Esta função tenta várias 
    combinações para garantir que acharemos os metadados.
    """
    base_name_str: str = os.path.splitext(file_path_str)[0]
    candidates_list: List[str] = [base_name_str + ".info.json"]
    
    # Tenta reduzir o nome removendo extensões de idioma (como .pt-br) ou sufixos de ID
    # Isso aumenta drasticamente a chance de encontrar o JSON correto.
    temp_str: str = base_name_str
    for sep_char in ['.', '-']:
        while sep_char in temp_str:
            temp_str = temp_str.rsplit(sep_char, 1)[0]
            if temp_str:
                candidates_list.append(temp_str + ".info.json")
    
    # Remove duplicatas mantendo a ordem (usando dict.fromkeys que é performático)
    return list(dict.fromkeys(candidates_list))


def _load_metadata_from_json(json_path_str: str) -> Optional[Dict[str, str]]:
    """Carrega metadados de um arquivo JSON específico."""
    try:
        with open(json_path_str, 'r', encoding='utf-8') as f:
            data_dict: Dict = json.load(f)
            return {
                "date": data_dict.get('upload_date', 'Desconhecida'),
                "title": data_dict.get('title', 'Sem Título'),
                "id": data_dict.get('id', 'Sem ID')
            }
    except Exception:
        return None


def _extract_id_from_filename(file_path_str: str) -> str:
    """Tenta extrair o ID do Youtube do nome do arquivo (fallback)."""
    try:
        base_name_str: str = os.path.basename(file_path_str).rsplit('.', 1)[0]
        parts_list: List[str] = base_name_str.split('-')
        for part_str in reversed(parts_list):
            if 9 <= len(part_str) <= 15 and re.match(r"^[A-Za-z0-9_-]+$", part_str):
                return part_str
    except Exception:
        pass
    return "Sem ID"

def process_content(raw_content_str: str, filename_str: str, full_path_str: str, metadata_dict: Optional[Dict[str, str]] = None) -> Tuple[str, str, str]:
    """
    O "Coração" do Processamento: Transforma o conteúdo bruto em um bloco limpo.
    
    O que acontece aqui:
    1. Extrai apenas o texto útil (ignora o que não é fala).
    2. Busca metadados (se não foram passados).
    3. Remove ruídos (avisos de pulos de tempo).
    4. Coloca molduras e cabeçalhos bonitos para a IA ler melhor.
    """
    # Passo 1: Pega o texto bruto e remove as partes técnicas (ex: cabeçalhos YAML)
    cleaned_transcription_str: str = _extract_transcription_text(raw_content_str, filename_str)
    
    if metadata_dict is None:
        metadata_dict = get_metadata(full_path_str)
    
    # Passo 2: Remove termos como "[Pulo de tempo]" que poluem a leitura
    cleaned_transcription_str = _clean_noise_patterns(cleaned_transcription_str)

    # Passo 3: Adiciona as bordas "=====" e os metadados (ID, Título) no topo do bloco
    formatted_block_str: str = _format_lexis_block(cleaned_transcription_str, filename_str, metadata_dict)

    return formatted_block_str, cleaned_transcription_str, ""


def _extract_transcription_text(raw_content_str: str, filename_str: str) -> str:
    """Identifica o formato do arquivo e extrai o texto da forma correta."""
    # Se o arquivo já tiver o marcador do Escriba, pega só o que vem depois dele
    if "TRANSCRIÇÃO INTEGRAL:" in raw_content_str:
        return raw_content_str.split("TRANSCRIÇÃO INTEGRAL:", 1)[-1].strip()
    
    # Legendas (.srt) precisam de uma limpeza especial (remover tempos)
    if filename_str.endswith('.srt'):
        return clean_srt_content(raw_content_str)
    
    # Arquivos Markdown (.md) costumam ter cabeçalhos complexos que limpamos
    if filename_str.endswith('.md'):
        return _extract_md_transcription(raw_content_str)
    
    return raw_content_str.strip()


def _extract_md_transcription(md_content_str: str) -> str:
    """
    Limpa arquivos .md, removendo o 'frontmatter' (aqueles dados entre ---).
    
    Explicação para Juniores:
    Muitos arquivos de texto modernos começam com um cabeçalho técnico assim:
    ---
    autor: Joao
    data: 2024
    ---
    Este código remove isso para que a IA foque apenas no texto principal.
    """
    content_str: str = md_content_str.strip()
    
    # Remove o bloco de metadados YAML (o frontmatter)
    yaml_stripped_str: str = re.sub(r"^---\n.*?\n---\n?", "", content_str, count=1, flags=re.DOTALL).strip()

    # Tenta manter o título principal (# Título) se ele existir
    header_block_str: str = _get_md_header_block(yaml_stripped_str) or _get_md_header_block(content_str, level=2) or ""
    
    # Procura onde começa a transcrição de verdade (ignora resumos iniciais)
    body_content_str: str = yaml_stripped_str
    markers_list: List[str] = ["### Segmentos de Tópicos", "### Transcrição Estruturada"]
    for marker_str in markers_list:
        if marker_str in yaml_stripped_str:
            body_content_str = marker_str + yaml_stripped_str.split(marker_str, 1)[1]
            break
            
    return (header_block_str + "\n\n" + body_content_str).strip() if header_block_str else body_content_str


def _get_md_header_block(text_str: str, level: int = 1) -> Optional[str]:
    """Helper para capturar o bloco de cabeçalho estruturado do MD."""
    prefix_str: str = "#" * level
    pattern_str: str = rf"^({re.escape(prefix_str)}\s+.+?\n(?:\n?>.*\n)*)"
    match_obj: Optional[re.Match] = re.match(pattern_str, text_str, re.MULTILINE)
    return match_obj.group(1).strip() if match_obj else None


def _clean_noise_patterns(text_str: str) -> str:
    """Remove padrões de ruído como [Pulo de tempo] e excesso de quebras de linha."""
    # Remove [Pulo de tempo], [Intervalo], etc.
    noise_pattern: Pattern = re.compile(r'\[(?:Pulo de tempo|Intervalo|Gap|Pulo):?.*?\]', flags=re.IGNORECASE)
    cleaned_str: str = noise_pattern.sub('', text_str)
    # Normaliza quebras de linha múltiplas
    return re.sub(r'\n{3,}', '\n\n', cleaned_str).strip()


def _format_lexis_block(text_str: str, filename_str: str, metadata_dict: Dict[str, str]) -> str:
    """Formata o bloco consolidado com separadores e metadados."""
    border_str: str = "=" * 60
    lines_list: List[str] = [
        f"\n{border_str}",
        f"ARQUIVO: {filename_str}",
        f"ID: {metadata_dict['id']}",
        f"DATA: {metadata_dict['date']}",
        f"TITULO: {metadata_dict['title']}",
        f"{'-' * 60}",
        f"{text_str}",
        f"{border_str}\n"
    ]
    return "\n".join(lines_list)

def _migrate_legacy_state(channel_dir_path_str: str, state_file_path_str: str) -> None:
    """
    MIGRAÇÃO DE SEGURANÇA: Converte o sistema antigo de arquivos ocultos para o novo JSON.
    
    POR QUE ISSO É NECESSÁRIO?
    Versões anteriores do Lexis salvavam o progresso em um arquivo oculto chamado 
    `.lexis-join-state.json`. Para centralizar tudo e facilitar o backup, agora 
    usamos o `escriba_[canal].json`. Esta função garante que ninguém perca o 
    trabalho já feito na transição de versões.
    """
    legacy_path_str: str = os.path.join(channel_dir_path_str, ".lexis-join-state.json")
    if not os.path.exists(legacy_path_str):
        return
        
    try:
        _perform_legacy_migration(legacy_path_str, state_file_path_str)
    except Exception as e:
        print_warn(f"Falha ao migrar estado legado: {e}", "  ")


def _perform_legacy_migration(legacy_path_str: str, state_file_path_str: str) -> None:
    """Lê os dados do arquivo antigo e injeta no novo arquivo de estado."""
    with open(legacy_path_str, 'r', encoding='utf-8') as f:
        legacy_state_dict: Dict = json.load(f)

    dest_data_dict: Dict = {}
    if os.path.exists(state_file_path_str):
        with open(state_file_path_str, 'r', encoding='utf-8') as f:
            dest_data_dict = json.load(f)

    # Se ainda não existe a chave 'lexis_state', nós a criamos com os dados antigos
    if "lexis_state" not in dest_data_dict:
        dest_data_dict["lexis_state"] = legacy_state_dict
        with open(state_file_path_str, 'w', encoding='utf-8') as f:
            json.dump(dest_data_dict, f, ensure_ascii=False, indent=2)
        print_info(f"🔀 Estado legado migrado → {os.path.basename(state_file_path_str)}", "  ")

    # Após migrar com sucesso, deletamos o arquivo antigo para não repetir o processo
    os.remove(legacy_path_str)
    print_info("🗑  .lexis-join-state.json legado removido.", "  ")


def load_state(state_file_path_str: str) -> Dict[str, Any]:
    """
    Lê o arquivo JSON para saber onde o Lexis parou na última vez.
    
    Explicação para Juniores:
    Imagine que o programa é interrompido. Sem um "estado", ele teria que 
    reprocessar todos os vídeos desde o início. O arquivo de estado é a 
    "memória de longo prazo" do script.
    """
    if not os.path.exists(state_file_path_str):
        return _get_default_state()
    try:
        with open(state_file_path_str, 'r', encoding='utf-8') as f:
            data_dict: Dict = json.load(f)
            # O Lexis guarda seus dados específicos na chave "lexis_state"
            return data_dict.get("lexis_state", _get_default_state())
    except Exception:
        # Se o arquivo estiver corrompido, começamos do zero por segurança
        return _get_default_state()


def _get_default_state() -> Dict[str, Any]:
    """Cria a estrutura básica de memória para um novo canal."""
    return {
        "processed_files": [], # Lista de nomes de arquivos (.txt, .md) já lidos
        "processed_ids": [],   # Lista de IDs do YouTube (11 caracteres) já lidos
        "last_volume": 1,      # Número do volume atual (ex: v001)
        "last_volume_size": 0  # Quantos caracteres já temos no volume atual
    }


def save_state(state_file_path_str: str, state_dict: Dict[str, Any]) -> None:
    """
    Salva o progresso atual no disco para persistência.
    
    POR QUE ISSO É NECESSÁRIO?
    Diferente de variáveis que somem quando o script fecha, arquivos no disco 
    garantem que o trabalho pesado (limpeza de legendas) seja feito apenas uma vez.
    """
    data_dict: Dict = {}
    
    # 1. Primeiro, tentamos ler o que já existe no arquivo para não sobrescrever
    # dados de outros módulos (como o do uploader ou do próprio escriba.py).
    if os.path.exists(state_file_path_str):
        try:
            with open(state_file_path_str, 'r', encoding='utf-8') as f:
                data_dict = json.load(f)
        except Exception:
            pass
    
    # 2. Atualizamos apenas a "caixinha" do Lexis
    data_dict["lexis_state"] = state_dict
    
    with open(state_file_path_str, 'w', encoding='utf-8') as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=2)
    print_info(f"💾 Estado Lexis salvo em {os.path.basename(state_file_path_str)}", "  ")

def get_channel_url(channel_name_str: str) -> str:
    """
    Retorna a URL completa do canal para referência futura.
    Exemplo: "jandir" -> "https://youtube.com/@jandir"
    """
    handle_str: str = channel_name_str
    if not handle_str.startswith("@"):
        handle_str = f"@{handle_str}"
    return f"https://youtube.com/{handle_str}"


def generate_volume_header(channel_name_str: str, channel_url_str: str) -> str:
    """
    Gera as primeiras linhas de cada arquivo de Volume.
    
    EXPLICAÇÃO PARA JUNIORES:
    Isso funciona como a "capa" de um livro. Ajuda o NotebookLM a entender 
    de qual canal é este conteúdo e quando este arquivo foi gerado.
    """
    now_str: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header_lines_list: List[str] = [
        f"{'='*60}",
        "METADADOS DO VOLUME",
        f"CANAL: {channel_name_str}",
        f"URL: {channel_url_str}",
        f"DATA DE CRIAÇÃO: {now_str}",
        f"{'='*60}\n"
    ]
    return "\n".join(header_lines_list)


def extract_metadata_from_volume(volume_content_str: str) -> List[Dict[str, str]]:
    """
    Lê um arquivo de volume já pronto e extrai a lista de vídeos que estão lá.
    
    POR QUE ISSO É NECESSÁRIO?
    Se o script travar no meio do volume v005, ao reiniciar ele lê o arquivo 
    v005 para saber quais vídeos ele já tinha colocado lá dentro, evitando 
    duplicar o conteúdo.
    """
    recovered_metadata_list: List[Dict[str, str]] = []
    
    # Regex que busca o padrão ID:, DATA: e TITULO: dentro do volume
    pattern_obj: Pattern = re.compile(
        r"ID:\s*(.*?)\nDATA:\s*(.*?)\nTITULO:\s*(.*?)\n-{" + str(60) + "}",
        re.MULTILINE
    )
    
    for match_obj in pattern_obj.finditer(volume_content_str):
        recovered_metadata_list.append({
            "id": match_obj.group(1).strip(),
            "date": match_obj.group(2).strip(),
            "title": match_obj.group(3).strip()
        })
        
    return recovered_metadata_list

def generate_volume_index(video_metadata_list: List[Dict[str, str]]) -> str:
    """
    Cria uma "Tabela de Conteúdo" ao final do arquivo de volume.
    
    EXPLICAÇÃO PARA JUNIORES:
    Como nossos volumes são arquivos de texto gigantes, o índice ajuda a 
    IA a encontrar rapidamente onde cada vídeo começa. É como o sumário de um livro.
    """
    if not video_metadata_list:
        return ""
    
    # 1. Remove duplicatas (caso um vídeo tenha sido processado duas vezes por erro)
    unique_metadata_list: List[Dict[str, str]] = _deduplicate_metadata(video_metadata_list)
    
    # 2. Ordena por data para que os vídeos fiquem em ordem cronológica no índice
    unique_metadata_list.sort(key=lambda x: (x.get("date", ""), x.get("title", "")))
    
    # 3. Constrói as linhas do índice
    index_lines_list: List[str] = _initialize_index_header()
    for meta_dict in unique_metadata_list:
        index_lines_list.append(_format_index_line(meta_dict))
        
    index_lines_list.append(f"{'='*60}\n")
    return "\n".join(index_lines_list)


def _initialize_index_header() -> List[str]:
    """Retorna as linhas iniciais do cabeçalho do índice formatado."""
    return [
        f"\n\n{'='*60}",
        "ÍNDICE DE VÍDEOS NESTE VOLUME (Detalhamento):",
        f"{'-'*60}",
        f"{'ID':<15} | {'DATA':<10} | {'TÍTULO'}",
        f"{'-'*60}"
    ]


def _format_index_line(meta_dict: Dict[str, str]) -> str:
    """Formata uma linha individual do índice com colunas alinhadas."""
    vid_id_str: str = meta_dict.get("id", "Sem ID")
    date_str: str = meta_dict.get("date", "Desconhecida")
    title_str: str = meta_dict.get("title", "Sem Título")
    
    # Limita o título para não quebrar a formatação da tabela se for muito longo
    if len(title_str) > 60:
        title_str = title_str[:57] + "..."
        
    return f"{vid_id_str:<15} | {date_str:<10} | {title_str}"


def _deduplicate_metadata(metadata_list: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Garante que cada ID de vídeo apareça apenas uma vez no índice."""
    seen_ids_set: Set[str] = set()
    unique_list: List[Dict[str, str]] = []
    
    for meta_dict in metadata_list:
        vid_id_str: str = meta_dict.get("id", "Sem ID")
        if vid_id_str not in seen_ids_set:
            unique_list.append(meta_dict)
            seen_ids_set.add(vid_id_str)
            
    return unique_list

def scan_volumes_for_files(output_dir_path_str: str, channel_name_str: str) -> Tuple[Set[str], Set[str], int, int]:
    """
    Verifica o que já existe fisicamente gravado no disco.
    
    ESTRATÉGIA DE "REALITY CHECK":
    Mesmo que o arquivo JSON diga que processamos 100 vídeos, se os arquivos 
    de Volume no disco sumirem (deletados por engano), o script deve ser 
    capaz de detectar isso e reprocessar o necessário. É uma camada extra de segurança.
    
    Retorna: (Arquivos_Lidos, IDs_Lidos, Ultimo_Volume_ID, Tamanho_Ultimo_Volume)
    """
    files_set: Set[str] = set()
    ids_set: Set[str] = set()
    max_idx_int: int = 0
    max_bytes_int: int = 0
    
    if not os.path.exists(output_dir_path_str):
        return files_set, ids_set, 0, 0
    
    # Procura arquivos que seguem o padrão "NomeDoCanal-v001.txt"
    vol_pattern_obj: Pattern = re.compile(rf"^{re.escape(channel_name_str)}-v(\d{{3}})\.txt$")
    
    for fname_str in os.listdir(output_dir_path_str):
        match_obj: Optional[re.Match] = vol_pattern_obj.match(fname_str)
        if match_obj:
            idx_int: int = int(match_obj.group(1))
            fpath_str: str = os.path.join(output_dir_path_str, fname_str)
            fsize_int: int = os.path.getsize(fpath_str)
            
            # Mantemos o controle do maior índice (v005 > v004) para saber 
            # de onde continuar sem sobrescrever volumes prontos.
            if idx_int > max_idx_int:
                max_idx_int, max_bytes_int = idx_int, fsize_int
                
            # Abre o volume e "re-aprende" quais vídeos estão lá dentro lendo o conteúdo
            _parse_volume_manifest(fpath_str, files_set, ids_set)
            
    return files_set, ids_set, max_idx_int, max_bytes_int


def _parse_volume_manifest(file_path_str: str, files_set: Set[str], ids_set: Set[str]) -> None:
    """
    Lê um arquivo de volume e descobre quais arquivos originais e IDs ele contém.
    Isso reconstrói o estado do sistema a partir dos arquivos físicos.
    """
    try:
        with open(file_path_str, 'r', encoding='utf-8') as f:
            for raw_line in f:
                # Buscamos as etiquetas que colocamos no topo de cada bloco de vídeo
                if raw_line.startswith("ARQUIVO: "):
                    files_set.add(raw_line.strip().replace("ARQUIVO: ", ""))
                elif raw_line.startswith("ID: "):
                    vid_id_str: str = raw_line.strip().replace("ID: ", "")
                    if vid_id_str and vid_id_str != "Sem ID":
                        ids_set.add(vid_id_str)
    except Exception:
        # Se um arquivo estiver ilegível, apenas ignoramos este bloco específico
        pass

def process_channel(channel_dir_path_str: str, channel_name_str: str, reset_mode_bool: bool = False) -> None:
    """
    Função Principal de um Canal: Coordena todo o trabalho de um canal do YouTube.
    
    EXPLICAÇÃO PARA JUNIORES:
    Esta função é o "gerente" do canal. Ela configura onde os arquivos estão, 
    limpa o que precisa ser limpo se estivermos resetando, e decide quais 
    vídeos novos precisam ser processados hoje.
    """
    paths_dict: Dict[str, str] = _prepare_lexis_paths(channel_dir_path_str, channel_name_str)
    
    if reset_mode_bool:
        # Se o usuário usou --reset, apagamos o passado e recomeçamos
        _reset_channel(channel_dir_path_str, channel_name_str, paths_dict)

    # Busca todos os arquivos de texto (.txt, .srt, .md) na pasta do canal
    eligible_files_list: List[str] = _get_eligible_files(channel_dir_path_str, channel_name_str)
    if not eligible_files_list:
        return

    # Sincroniza a memória (JSON) com a realidade física (Arquivos no disco)
    state_dict: Dict[str, Any] = _load_and_sync_state(paths_dict, channel_name_str, reset_mode_bool)
    
    # Escolhe o melhor arquivo (.md > .txt > .srt) e ignora os que já foram lidos.
    files_to_proc_list: List[str] = _select_files_to_process(
        channel_dir_path_str, eligible_files_list, state_dict["processed_ids"], paths_dict["archive"]
    )
    
    if not files_to_proc_list and not reset_mode_bool:
        print_ok(f"\n✅ Canal: {channel_name_str} — nenhum arquivo novo.")
        return

    # Inicia a "fábrica" de volumes (consolidação)
    _orchestrate_consolidation(channel_name_str, files_to_proc_list, state_dict, paths_dict, reset_mode_bool)


def _prepare_lexis_paths(channel_path_str: str, channel_name_str: str) -> Dict[str, str]:
    """Centraliza os caminhos de pastas e arquivos para evitar repetição no código."""
    return {
        "state": os.path.join(channel_path_str, f"escriba_{channel_name_str}.json"),
        "output": os.path.join(channel_path_str, "volumes_notebooklm"),
        "archive": os.path.join(channel_path_str, ARCHIVE_DIR_NAME)
    }


def _get_eligible_files(channel_path_str: str, channel_name_str: str) -> List[str]:
    """
    Filtra apenas arquivos que seguem o padrão de nomenclatura do canal.
    Ignora arquivos que já são Volumes (ex: -v001.txt).
    """
    # Regex que busca [Canal]--[ID_Video].[ext]
    pattern_obj: Pattern = re.compile(rf"^{re.escape(channel_name_str)}[-]+[A-Za-z0-9_-]{{9,15}}(?:-[a-zA-Z0-9-]+)?\.(txt|srt|md)$")
    vol_pattern_obj: Pattern = re.compile(rf"^{re.escape(channel_name_str)}-v\d{{3}}\.txt$")
    
    eligible_files_list: List[str] = [
        f for f in os.listdir(channel_path_str)
        if pattern_obj.match(f) and not vol_pattern_obj.match(f)
    ]
    eligible_files_list.sort()
    return eligible_files_list


def _reset_channel(channel_path_str: str, channel_name_str: str, paths_dict: Dict[str, str]) -> None:
    """
    Executa a limpeza completa para o modo Reset.
    
    EXPLICAÇÃO PARA JUNIORES:
    Resetar significa "esquecer tudo e apagar os volumes". 
    Isso é útil quando mudamos as regras de limpeza de texto e queremos 
    gerar volumes novos e melhores a partir dos arquivos originais.
    """
    print(f"\n🔄 Resetando Canal: {channel_name_str}")
    
    # 1. Apaga os arquivos de volume (.txt) na pasta de saída
    if os.path.exists(paths_dict["output"]):
        vol_pattern_obj: Pattern = re.compile(rf"^{re.escape(channel_name_str)}-v\d{{3}}\.txt$")
        for f_str in os.listdir(paths_dict["output"]):
            if vol_pattern_obj.match(f_str):
                os.remove(os.path.join(paths_dict["output"], f_str))

    # 2. Limpa a memória de processamento no arquivo JSON
    _clear_lexis_state(paths_dict["state"])
    
    # 3. Traz os arquivos originais de volta da pasta 'archive' para a pasta principal
    if os.path.exists(paths_dict["archive"]):
        _restore_from_archive(paths_dict["archive"], channel_path_str)


def _clear_lexis_state(state_path_str: str) -> None:
    """Remove a chave lexis_state do arquivo JSON para forçar reprocessamento."""
    if not os.path.exists(state_path_str):
        return
    try:
        with open(state_path_str, 'r', encoding='utf-8') as f:
            data_dict: Dict = json.load(f)
        if "lexis_state" in data_dict:
            del data_dict["lexis_state"]
            with open(state_path_str, 'w', encoding='utf-8') as f:
                json.dump(data_dict, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _restore_from_archive(archive_path_str: str, dest_path_str: str) -> None:
    """Move arquivos do archive de volta para a pasta de origem."""
    count_int: int = 0
    for f_str in os.listdir(archive_path_str):
        shutil.move(os.path.join(archive_path_str, f_str), os.path.join(dest_path_str, f_str))
        count_int += 1
    if count_int > 0:
        print_ok(f"  📦 Restaurados {count_int} arquivos do archive.")


def _load_and_sync_state(paths_dict: Dict[str, str], channel_name_str: str, reset_bool: bool) -> Dict[str, Any]:
    """
    Carrega o estado e sincroniza com os volumes físicos no disco.
    
    POR QUE ISSO É NECESSÁRIO?
    Às vezes deletamos arquivos manualmente. Esta função garante que o 
    "cérebro" (JSON) saiba o que realmente existe no "corpo" (Disco).
    """
    # Garante que estados antigos sejam migrados se necessário
    _migrate_legacy_state(os.path.dirname(paths_dict["state"]), paths_dict["state"])
    
    if reset_bool:
        return _get_default_state()
        
    # Carrega o que está no JSON
    state_dict: Dict[str, Any] = load_state(paths_dict["state"])
    
    # Faz o "Reality Check" lendo os volumes físicos
    scan_results_tuple: Tuple = scan_volumes_for_files(paths_dict["output"], channel_name_str)
    files_set, ids_set, max_idx_int, max_bytes_int = scan_results_tuple
    
    # Sincroniza usando conjuntos (Sets) para evitar duplicatas
    processed_files_set: Set[str] = set(state_dict["processed_files"]) | files_set
    processed_ids_set: Set[str] = set(state_dict["processed_ids"]) | ids_set
    
    state_dict["processed_files"] = sorted(list(processed_files_set))
    state_dict["processed_ids"] = sorted(list(processed_ids_set))
    state_dict["last_volume"] = max(state_dict.get("last_volume", 1), max_idx_int)
    state_dict["last_volume_size"] = max_bytes_int
    
    # Salva a versão sincronizada
    save_state(paths_dict["state"], state_dict)
    return state_dict


def _select_files_to_process(channel_path_str: str, all_files_list: List[str], processed_ids_list: List[str], archive_path_str: str) -> List[str]:
    """
    Aplica priorização de extensões e separa arquivos para processamento.
    
    POR QUE ISSO É NECESSÁRIO?
    Um vídeo pode ter .md, .txt e .srt ao mesmo tempo. Não queremos os três!
    Esta função escolhe o melhor e "joga fora" (arquiva) os outros.
    """
    id_map_dict: Dict[str, List[str]] = _group_files_by_id(channel_path_str, all_files_list)
    to_process_list: List[str] = []
    processed_ids_set: Set[str] = set(processed_ids_list)
    
    os.makedirs(archive_path_str, exist_ok=True)
    
    for vid_id_str, files_list in id_map_dict.items():
        # Ordena por prioridade: .md vem primeiro, depois .txt, depois .srt
        sorted_files_list: List[str] = sorted(files_list, key=_get_ext_priority)
        best_file_str: str = sorted_files_list[0]
        
        # Se este ID já foi processado no passado, arquivamos todos os arquivos dele
        if vid_id_str in processed_ids_set:
            _archive_files(channel_path_str, archive_path_str, files_list)
            continue
            
        to_process_list.append(best_file_str)
        
        # Arquiva os arquivos "reservas" (versões piores do mesmo vídeo)
        if len(sorted_files_list) > 1:
            _archive_files(channel_path_str, archive_path_str, sorted_files_list[1:])
            
    return to_process_list


def _group_files_by_id(channel_path_str: str, files_list: List[str]) -> Dict[str, List[str]]:
    """Agrupa diferentes extensões (.srt, .txt, .md) pelo mesmo ID de vídeo."""
    id_map_dict: Dict[str, List[str]] = {}
    for f_str in files_list:
        meta_dict: Dict[str, str] = get_metadata(os.path.join(channel_path_str, f_str))
        vid_id_str: str = meta_dict.get("id", f"FILE_{f_str}")
        if vid_id_str not in id_map_dict:
            id_map_dict[vid_id_str] = []
        id_map_dict[vid_id_str].append(f_str)
    return id_map_dict


def _get_ext_priority(filename_str: str) -> int:
    """
    Define a ordem de importância das extensões.
    Quanto menor o número, maior a prioridade.
    .md (0) > .txt (1) > .srt (2).
    """
    ext_str: str = os.path.splitext(filename_str)[1].lower()
    mapping_dict: Dict[str, int] = {'.md': 0, '.txt': 1, '.srt': 2}
    return mapping_dict.get(ext_str, 3)


def _archive_files(source_dir_path_str: str, archive_dir_path_str: str, files_list: List[str]) -> None:
    """Move arquivos para a pasta 'archive' para manter a pasta principal limpa."""
    for f_str in files_list:
        shutil.move(os.path.join(source_dir_path_str, f_str), os.path.join(archive_dir_path_str, f_str))
        
        # Se houver um arquivo .info.json acompanhando, movemos ele também
        json_f_str: str = f_str.rsplit('.', 1)[0] + ".info.json"
        json_p_str: str = os.path.join(source_dir_path_str, json_f_str)
        if os.path.exists(json_p_str):
            shutil.move(json_p_str, os.path.join(archive_dir_path_str, json_f_str))


def _orchestrate_consolidation(channel_name_str: str, files_list: List[str], state_dict: Dict[str, Any], paths_dict: Dict[str, str], reset_bool: bool) -> None:
    """
    O 'Loop Principal' de Montagem dos Volumes.
    
    EXPLICAÇÃO PARA JUNIORES:
    Imagine que você tem uma caixa (o Volume) que cabe 1.8MB de papel.
    Você vai pegando os textos dos vídeos e colocando na caixa.
    Quando a caixa enche, você fecha ela, gera um índice e abre uma caixa 
    nova (v002, v003...). Isso garante que os arquivos não fiquem gigantescos.
    """
    url_str: str = get_channel_url(channel_name_str)
    vol_idx_int: int = state_dict["last_volume"]
    
    # Tenta continuar de onde parou no volume atual (se ele não estiver cheio)
    vol_content_str: str = _initialize_volume_content(paths_dict, channel_name_str, vol_idx_int, reset_bool)
    
    # Extrai metadados dos vídeos que já estavam neste volume retomado
    vol_meta_list: List[Dict[str, str]] = extract_metadata_from_volume(vol_content_str)
    
    # Carrega a base global para enriquecer títulos/datas se necessário
    global_meta_dict: Dict[str, Any] = _load_global_metadata(paths_dict["state"]) if not reset_bool else {}

    for i_int, f_str in enumerate(files_list):
        fpath_str: str = os.path.join(os.path.dirname(paths_dict["state"]), f_str)
        
        # Processa o arquivo individualmente (limpeza de legendas + cabeçalho lexis)
        block_str, meta_dict = _process_single_file(fpath_str, f_str, global_meta_dict)
        if not block_str:
            continue

        # Checa se o novo bloco cabe no volume atual ou se precisamos de um novo arquivo
        if not vol_content_str or (len(vol_content_str) + len(block_str) > MAX_CHARS):
            if vol_content_str and len(vol_content_str) + len(block_str) > MAX_CHARS:
                # O volume atual encheu! Salvamos ele com o índice no final.
                _save_volume(paths_dict, channel_name_str, vol_idx_int, vol_content_str, vol_meta_list)
                vol_idx_int += 1
                
            # Começa um novo volume do zero
            vol_content_str = generate_volume_header(channel_name_str, url_str)
            vol_meta_list = []

        # Adiciona o texto do vídeo ao volume na memória
        vol_content_str += block_str
        vol_meta_list.append(meta_dict)
        
        # Marca como processado no "cérebro" (JSON) e move o arquivo para o 'archive'
def _update_processing_state(state_dict: Dict[str, Any], f_str: str, vid_id_str: str, archive_path_str: str) -> None:
    """
    Atualiza as listas de controle e move o arquivo para o archive.
    
    EXPLICAÇÃO PARA JUNIORES:
    Pense nisso como "marcar uma tarefa como concluída". 
    Nós anotamos o nome do arquivo e o ID do vídeo na nossa lista de 
    'já processados' e depois guardamos o arquivo original em uma 
    pasta de arquivo para ele não ficar nos atrapalhando na próxima vez.
    """
    state_dict["processed_files"].append(f_str)
    state_dict["processed_ids"].append(vid_id_str)
    
    # Move para o archive para não processar novamente na próxima execução
    source_dir_path_str: str = os.path.dirname(archive_path_str)
    _archive_files(source_dir_path_str, archive_path_str, [f_str])


def _initialize_volume_content(paths_dict: Dict[str, str], channel_name_str: str, vol_idx_int: int, reset_bool: bool) -> str:
    """
    Tenta carregar o conteúdo do volume atual para continuar de onde parou.
    
    POR QUE ISSO É NECESSÁRIO?
    Se o Volume 1 ainda tem espaço (menos de 1.8MB), não faz sentido 
    criar o Volume 2. Nós lemos o Volume 1 de volta, removemos o índice 
    antigo (que vai ficar desatualizado) e continuamos escrevendo nele.
    """
    if reset_bool:
        return ""
        
    vol_path_str: str = os.path.join(paths_dict["output"], f"{channel_name_str}-v{vol_idx_int:03d}.txt")
    if not os.path.exists(vol_path_str):
        return ""
        
    with open(vol_path_str, 'r', encoding='utf-8') as f:
        content_str: str = f.read()
    
    # Se o volume já estiver no limite, retornamos vazio para forçar a criação do v+1
    if len(content_str) >= MAX_CHARS:
        return "" 
        
    print_info(f"\n📂 Retomando Volume {vol_idx_int} ({len(content_str):,} chars)")
    
    # O índice antigo fica no final do arquivo. Precisamos removê-lo para adicionar 
    # mais conteúdo e depois gerar um índice novo e completo.
    marker_str: str = f"\n\n{'='*60}\nÍNDICE DE VÍDEOS NESTE VOLUME"
    return content_str.split(marker_str)[0]


def _process_single_file(full_path_str: str, filename_str: str, global_meta_dict: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
    """
    Lê, limpa e formata o conteúdo de um arquivo individual (.txt, .srt ou .md).
    
    EXPLICAÇÃO PARA JUNIORES:
    Esta é a "estação de tratamento". Ela pega o arquivo bruto, extrai 
    os metadados (título, data) e limpa a sujeira do texto. Se der erro 
    em um arquivo, ela avisa mas não deixa o programa inteiro travar.
    """
    try:
        with open(full_path_str, 'r', encoding='utf-8', errors='replace') as f:
            raw_content_str: str = f.read()
        
        # Tenta pegar metadados básicos
        meta_dict: Dict[str, str] = get_metadata(full_path_str)
        
        # Se acharmos esse vídeo na base global do Escriba, enriquecemos os dados
        # Isso garante que o título seja o real do YouTube, não o nome do arquivo.
        if meta_dict["id"] in global_meta_dict:
            _enrich_metadata(meta_dict, global_meta_dict[meta_dict["id"]])
            
        # Executa a limpeza profunda e formata o bloco para o volume
        formatted_str, _, _ = process_content(raw_content_str, filename_str, full_path_str, metadata_dict=meta_dict)
        return formatted_str, meta_dict
    except Exception as e:
        print_err(f"  ❌ Erro ao processar {filename_str}: {e}")
        return "", {}


def _enrich_metadata(meta_dict: Dict[str, str], global_video_dict: Dict[str, Any]) -> None:
    """
    Preenche metadados faltantes usando a base global do canal.
    
    POR QUE ISSO É NECESSÁRIO?
    Às vezes o arquivo .info.json sumiu, mas o Escriba já tem o título 
    e a data salvos no JSON principal da sessão. Aproveitamos isso aqui 
    para que o índice do volume fique bem completo e bonito.
    """
    if meta_dict["title"] == "Sem Título":
        meta_dict["title"] = global_video_dict.get("title", "Sem Título")
    if meta_dict["date"] == "Desconhecida":
        meta_dict["date"] = global_video_dict.get("upload_date", "Desconhecida")


def _load_global_metadata(state_path_str: str) -> Dict[str, Any]:
    """
    Carrega a lista de vídeos já conhecidos do arquivo escriba_[canal].json.
    
    EXPLICAÇÃO PARA JUNIORES:
    O Lexis não trabalha sozinho. Ele consulta o que o script 'escriba.py' 
    já descobriu sobre o canal. Transformamos isso em um dicionário para 
    que possamos encontrar informações de qualquer vídeo instantaneamente.
    """
    if not os.path.exists(state_path_str):
        return {}
    try:
        with open(state_path_str, 'r', encoding='utf-8') as f:
            data_dict: Dict = json.load(f)
            # Transformamos a lista de vídeos em um dicionário {id: dados}
            # O dicionário é muito mais rápido para buscas do que uma lista simples.
            return {v_dict["id"]: v_dict for v_dict in data_dict.get("videos", []) if "id" in v_dict}
    except Exception:
        return {}


def _save_volume(paths_dict: Dict[str, str], channel_name_str: str, idx_int: int, content_str: str, meta_list: List[Dict[str, str]]) -> None:
    """
    Adiciona o índice e persiste o volume no disco.
    
    EXPLICAÇÃO PARA JUNIORES:
    Esta é a hora de "fechar a caixa". Nós juntamos o conteúdo dos vídeos 
    com o índice que geramos e salvamos tudo em um arquivo final na 
    pasta 'volumes_notebooklm'.
    """
    os.makedirs(paths_dict["output"], exist_ok=True)
    full_content_str: str = content_str + generate_volume_index(meta_list)
    output_path_str: str = os.path.join(paths_dict["output"], f"{channel_name_str}-v{idx_int:03d}.txt")
    
    with open(output_path_str, 'w', encoding='utf-8') as f:
        f.write(full_content_str)
    print_ok(f"  📦 Volume {idx_int} finalizado ({len(full_content_str):,} caracteres)")


def _finalize_consolidation(paths_dict: Dict[str, str], name_str: str, idx_int: int, content_str: str, meta_list: List[Dict[str, str]], state_dict: Dict[str, Any]) -> None:
    """
    Salva o último volume (se não vazio) e persiste o estado final.
    
    POR QUE ISSO É NECESSÁRIO?
    Quando o loop acaba, pode ser que o último volume ainda não esteja cheio. 
    Não podemos esquecer de salvá-lo! Também limpamos as listas de IDs para 
    garantir que não haja duplicatas antes de gravar o JSON de estado.
    """
    if content_str:
        header_only_str: str = generate_volume_header(name_str, get_channel_url(name_str))
        # Só salva se tiver algo além do cabeçalho
        if content_str.strip() != header_only_str.strip():
            _save_volume(paths_dict, name_str, idx_int, content_str, meta_list)
            state_dict["last_volume"] = idx_int
            state_dict["last_volume_size"] = len(content_str)
            
    # Remove duplicatas e ordena as listas antes de salvar
    state_dict["processed_files"] = sorted(list(set(state_dict["processed_files"])))
    state_dict["processed_ids"] = sorted(list(set(state_dict["processed_ids"])))
    save_state(paths_dict["state"], state_dict)


def _print_lexis_banner(reset_mode_bool: bool, base_dir_path_str: str) -> None:
    """
    Imprime o cabeçalho visual de execução.
    
    EXPLICAÇÃO PARA JUNIORES:
    É sempre bom dar um feedback visual para o usuário saber exatamente 
    o que o programa está fazendo e em qual pasta ele está trabalhando.
    """
    mode_label_str: str = "RESET (reprocessando tudo)" if reset_mode_bool else "INCREMENTAL"
    print(f"\n{'='*50}")
    print(f"  LEXIS-JOIN — Modo: {mode_label_str}")
    print(f"  Diretório Base: {os.path.abspath(base_dir_path_str)}")
    print(f"{'='*50}")


def _scan_for_channel_files(dir_path_str: str) -> List[str]:
    """
    Busca arquivos de vídeo/transcrição que indicam que uma pasta é um canal.
    
    POR QUE ISSO É NECESSÁRIO?
    O Lexis pode ser rodado em uma pasta que tem vários canais dentro, 
    ou diretamente na pasta de um canal só. Esta função ajuda a identificar 
    se estamos 'dentro' da casa de um canal.
    """
    dir_name_str: str = os.path.basename(os.path.abspath(dir_path_str))
    return [
        f for f in os.listdir(dir_path_str) 
        if f.endswith(('.txt', '.srt', '.md')) and 
        not re.match(rf"^{re.escape(dir_name_str)}-v\d{{3}}\.txt$", f)
    ]


def _has_archived_files(dir_path_str: str) -> bool:
    """Verifica se existem arquivos na pasta de archive."""
    archive_path_str: str = os.path.join(dir_path_str, ARCHIVE_DIR_NAME)
    if not os.path.exists(archive_path_str):
        return False
    return any(f.endswith(('.txt', '.srt', '.md')) for f in os.listdir(archive_path_str))


def _process_subdirectories(base_path_str: str, reset_mode_bool: bool) -> None:
    """
    Itera e processa subpastas como canais individuais.
    
    EXPLICAÇÃO PARA JUNIORES:
    Se você rodar o Lexis na sua pasta principal de 'scripts', ele vai 
    olhar cada subpasta e, se achar transcrições lá, vai processar uma a uma.
    """
    ignore_set: Set[str] = {ARCHIVE_DIR_NAME, 'volumes_notebooklm', '__pycache__', '.venv', '.git'}
    subdirs_list: List[str] = [
        d for d in os.listdir(base_path_str) 
        if os.path.isdir(os.path.join(base_path_str, d)) and d not in ignore_set
    ]
    for channel_name_str in sorted(subdirs_list):
        process_channel(os.path.join(base_path_str, channel_name_str), channel_name_str, reset_mode=reset_mode_bool)


def consolidate_by_channel(base_dir_path_str: str, reset_mode_bool: bool = False) -> None:
    """
    Orquestra a consolidação de transcrições em volumes para um ou mais canais.
    
    POR QUE ISSO É NECESSÁRIO?
    Este é o ponto de entrada principal da lógica. Ele decide se vai 
    processar apenas a pasta atual ou se vai mergulhar nas subpastas.
    """
    if not os.path.exists(base_dir_path_str):
        print_err(f"O diretório '{base_dir_path_str}' não existe.")
        return

    _print_lexis_banner(reset_mode_bool, base_dir_path_str)
    
    files_list: List[str] = _scan_for_channel_files(base_dir_path_str)
    has_archives_bool: bool = _has_archived_files(base_dir_path_str)

    # Se a pasta atual tem arquivos ou um arquivo morto, processa ela como canal
    if files_list or has_archives_bool:
        channel_name_str: str = os.path.basename(os.path.abspath(base_dir_path_str))
        process_channel(base_dir_path_str, channel_name_str, reset_mode=reset_mode_bool)
    else:
        # Caso contrário, tenta processar cada subpasta
        _process_subdirectories(base_dir_path_str, reset_mode_bool)
    
    print(f"\n{'='*50}")
    print(f"  ✅ Concluído!")
    print(f"{'='*50}\n")


def main() -> None:
    """
    Entry point para execução standalone do lexis.py.
    
    EXPLICAÇÃO PARA JUNIORES:
    Aqui é onde a mágica começa quando você digita 'python lexis.py'. 
    Nós usamos o 'argparse' para entender o que o usuário quer 
    (ex: se ele passou uma pasta específica ou se quer usar o --reset).
    """
    parser = argparse.ArgumentParser(description="LEXIS: Consolidador de Transcrições")
    parser.add_argument("path", nargs="?", default=".", help="Caminho da pasta a processar")
    parser.add_argument("--reset", action="store_true", help="Reseta estado e volumes")
    args = parser.parse_args()
    
    consolidate_by_channel(args.path, reset_mode_bool=args.reset)


if __name__ == "__main__":
    main()
