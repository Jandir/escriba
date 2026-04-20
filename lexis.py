#!/usr/bin/env python3
"""
=============================================================================
=============================================================================
LEXIS: Consolidador de Transcrições para NotebookLM
=============================================================================

SUMÁRIO DO MÓDULO:
Módulo nativo do Escriba para processar arquivos de transcrições 
(.md, .txt) e legendas (.srt) e consolidá-los em volumes balanceados 
(~1.8MB) otimizados para a janela de contexto de IAs como o NotebookLM.

Principais Funcionalidades:
1. Priorização de Formatos: Quando existem múltiplos arquivos para o mesmo
   vídeo, prioriza .md > .txt > .srt, arquivando os excedentes.
2. Limpeza e Desduplicação: Remove tags HTML, formatações de tempo e 
   desduplica trechos de "roll-up" automático de legendas do YouTube.
3. Ingestão de Metadados: Avalia arquivos `.info.json` e o banco de dados
   `escriba_[canal].json` para preencher metadados do RAG.
4. Processamento Incremental: O estado de controle (arquivos processados,
   volume atual) é salvo como chave `lexis_state` dentro do próprio
   `escriba_[canal].json`, unificando os bancos de dados.
5. Índice por Volume: Gera um índice detalhado (ID, Data, Título) ao 
   final de cada volume para referência rápida.
6. Organização do Sistema de Arquivos: Move arquivos originais processados 
   ou duplicados para a pasta "archive". Volumes gerados são guardados 
   na subpasta "volumes_notebooklm".

Modos de Operação:
- Incremental (padrão): Processa apenas arquivos novos, retomando o
  último volume em aberto.
- Reset (--lexis-reset): Apaga volumes gerados, descarta o estado lexis
  do JSON, restaura os originais da pasta archive e reprocessa tudo.
===============================================================================================================
"""

import argparse
import os
import re
import shutil
import json
from datetime import datetime
from utils import print_ok, print_err, print_warn, print_info, print_section, BOLD, RESET, DIM

# Pasta de Arquivo morto das .srt originais baixadas do Youtube
# O usuário fica responsável por apagar essa pasta quando quiser.
ARCHIVE_DIR_NAME = "archive" 

# Configurações de Limite
# 1.8MB (aprox. 1.8 * 1024 * 1024 caracteres) é considerado o ponto ideal de performance
# e janela de contexto estendida ao integrar esses volumes de texto puro no NotebookLM.
MAX_FILE_SIZE_MB = 1.8
MAX_CHARS = MAX_FILE_SIZE_MB * 1024 * 1024 

def clean_srt_content(subtitle_content):
    """
    Função principal: 
    Remove formatações HTML, limpa timestamps e desduplica linhas repetitivas 
    decrustadas pelo efeito de "roll-up" automático de legendas do YouTube.
    Isso otimiza e encurta vastamente o tamanho do arquivo destino para a IA processar.
    
    Processo de desduplicação:
    - O Youtube envia blocos encadeados tipo:
      Bloco N: "Palavra 1"
      Bloco N+1: "Palavra 1 \n Palavra 2", etc.
    - Essa técnica varre os arrays sobrepostos para capturar puramente strings inéditas de cada linha de tempo.
    """
    # Normaliza quebras de linha
    subtitle_content = subtitle_content.replace('\r\n', '\n')
    
    # Regex para identificar blocos de legenda:
    # Número
    # Timestamp --> Timestamp
    # Texto... (pode ter várias linhas)
    # \n (linha em branco separadora)
    
    subtitle_block_pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:(?!\n\n).)*?)(?=\n\n|$)', re.DOTALL)
    
    subtitle_blocks_list = []
    for regex_match_result in subtitle_block_pattern.finditer(subtitle_content):
        subtitle_text_block = regex_match_result.group(4).strip()
        
        # Limpa tags HTML
        subtitle_text_block = re.sub(r'<[^>]*>', '', subtitle_text_block)
        
        # Quebra em linhas e remove vazias
        current_lines_list = [line.strip() for line in subtitle_text_block.split('\n') if line.strip()]
        
        if not current_lines_list:
            continue
            
        if not subtitle_blocks_list:
            subtitle_blocks_list.append(current_lines_list)
        else:
            previous_lines_list = subtitle_blocks_list[-1]
            
            # Lógica de desduplicação:
            # Se a última linha do bloco anterior for o início deste bloco,
            # ou se este bloco for uma sub-sequência do anterior ampliada.
            # Ex: Prev=["A", "B"], Curr=["A", "B", "C"] -> Adiciona apenas "C"
            
            start_idx = 0
            # Caso 1: A última linha do anterior é repetida aqui
            if previous_lines_list and current_lines_list[0] == previous_lines_list[-1]:
                start_idx = 1
            # Caso 2: O bloco anterior inteiro está contido no início deste (mais comum no roll-up)
            elif len(previous_lines_list) < len(current_lines_list) and current_lines_list[:len(previous_lines_list)] == previous_lines_list:
                start_idx = len(previous_lines_list)
                
            if start_idx < len(current_lines_list):
                subtitle_blocks_list.append(current_lines_list[start_idx:])

    # Aplana a lista de blocos em uma única string
    cleaned_lines_list = []
    for block in subtitle_blocks_list:
        cleaned_lines_list.extend(block)
        
    return ' '.join(cleaned_lines_list)

def get_metadata(srt_file_path):
    """
    Função principal:
    Lê atributos do arquivo `.info.json` para preencher os Metadados do RAG (Data, Título e ID).
    Aceita arquivos .md, .txt ou .srt como entrada.
    
    Lógica:
    Como os downloads podem gerar artefatos terminados com sufixos diferentes ex: 'nomedovideo.pt.srt',
    o script itera descobrindo qual foi o prefixo literal original extraindo hífenes e pontos 
    até casar com a formatação exata do arquivo `.info.json`.
    """
    base_name = os.path.splitext(srt_file_path)[0]
    
    candidate_json_paths_list = [base_name + ".info.json"]
    
    temporary_filename = base_name
    while '.' in temporary_filename:
        temporary_filename = temporary_filename.rsplit('.', 1)[0]
        if temporary_filename:
            candidate_json_paths_list.append(temporary_filename + ".info.json")

    temporary_filename = base_name
    while '-' in temporary_filename:
        temporary_filename = temporary_filename.rsplit('-', 1)[0]
        if temporary_filename:
             candidate_json_paths_list.append(temporary_filename + ".info.json")
    
    candidate_json_paths_list = list(dict.fromkeys(candidate_json_paths_list))

    for json_file_path in candidate_json_paths_list:
        if os.path.exists(json_file_path):
            try:
                with open(json_file_path, 'r', encoding='utf-8') as file_descriptor:
                    json_parsed_data = json.load(file_descriptor)
                    return {
                        "date": json_parsed_data.get('upload_date', 'Desconhecida'),
                        "title": json_parsed_data.get('title', 'Sem Título'),
                        "id": json_parsed_data.get('id', 'Sem ID')
                    }
            except Exception:
                pass
    
    # Fallback: Extrair ID do nome do arquivo (Padrão: Canal--ID.ext ou Canal-ID-lang.ext)
    try:
        base_name_only = os.path.basename(srt_file_path).rsplit('.', 1)[0]
        # Regex para capturar o ID (caracteres alfanuméricos, hifens e underscores)
        # O ID do Youtube geralmente tem 11 caracteres.
        # Tentamos capturar o bloco que se pareça com um ID entre hifens ou no fim.
        parts = base_name_only.split('-')
        for part in reversed(parts):
            if 9 <= len(part) <= 15 and re.match(r"^[A-Za-z0-9_-]+$", part):
                return {
                    "date": "Desconhecida",
                    "title": "Sem Título",
                    "id": part
                }
    except:
        pass

    return {
        "date": "Desconhecida",
        "title": "Sem Título",
        "id": "Sem ID"
    }

def process_content(subtitle_content, transcription_filename, full_file_path, metadata_dict=None):
    """
    Função principal:
    Ingere a string bruta de um vídeo (seja .srt de download ou um .txt gerado previamente),
    parseia o bloco original e reestrutura esse payload acoplando os metadados mais legíveis 
    para alimentar como Volume consolidado no NotebookLM.
    
    Retorno:
    Tupla de 3 itens sendo o 1º a "Formatação Consolidada" e o 2º item o "Texto Crú" contíguo da transcrição.
    A extração do Resumo (3º item) foi desativada desta listagem mas mantido o parse reverso 
    para segurança de compatibilidade com modelos antigos de .txt.
    """
    cleaned_transcription = ""
    extracted_summary_text = ""
    
    # Tenta detectar se é um arquivo consolidado antigo ou um Lexis-Chunk
    if "TRANSCRIÇÃO INTEGRAL:" in subtitle_content:
        try:
            cleaned_transcription = subtitle_content.split("TRANSCRIÇÃO INTEGRAL:")[1].strip()
        except:
            cleaned_transcription = subtitle_content
    elif transcription_filename.endswith('.srt'):
        cleaned_transcription = clean_srt_content(subtitle_content)
    elif transcription_filename.endswith('.md'):
        # Arquivos .md do Escriba possuem cabeçalho estruturado.
        # Formato novo (v2.5+): YAML frontmatter + # H1 + blockquote de metadados
        # Formato antigo:       ## H2 + **URL:** / **Data:** / **Duração:**
        #
        # Estratégia: extrair o bloco de metadados do cabeçalho e prefixar no
        # corpo da transcrição, garantindo que o volume Lexis não perca a âncora
        # semântica (título, data, URL, duração) de cada vídeo.
        content = subtitle_content.strip()
        header_block = ""

        # ── Extração de cabeçalho: formato novo (YAML frontmatter + # H1) ──────
        # Remove o bloco YAML (--- ... ---) e captura o H1 + blockquote logo após
        yaml_stripped = re.sub(r"^---\n.*?\n---\n?", "", content, count=1, flags=re.DOTALL).strip()

        # Captura bloco H1 + blockquote (> **Data:** ... / > 🔗 ...)
        h1_match = re.match(
            r"^(#\s+.+?\n(?:\n?>.*\n)*)",
            yaml_stripped,
            re.MULTILINE,
        )
        if h1_match:
            header_block = h1_match.group(1).strip() + "\n\n"
            content_to_slice = yaml_stripped
        else:
            # ── Fallback: formato antigo (## H2 + **URL:** / **Data:**) ─────────
            h2_match = re.match(
                r"^(##\s+.+?\n(?:\*\*.+?\*\*.*\n)*)",
                content,
                re.MULTILINE,
            )
            if h2_match:
                header_block = h2_match.group(1).strip() + "\n\n"
            content_to_slice = content

        # ── Fatia o corpo a partir da primeira seção real ──────────────────────
        if "### Segmentos de Tópicos" in content_to_slice:
            body = content_to_slice.split("### Segmentos de Tópicos", 1)[1]
            cleaned_transcription = header_block + "### Segmentos de Tópicos" + body
        elif "### Transcrição Estruturada" in content_to_slice:
            body = content_to_slice.split("### Transcrição Estruturada", 1)[1]
            cleaned_transcription = header_block + "### Transcrição Estruturada" + body
        else:
            cleaned_transcription = content_to_slice
    else:
        cleaned_transcription = subtitle_content.strip()

    if metadata_dict is None:
        metadata_dict = get_metadata(full_file_path)
    
    # Remoção de mensagens de intervalo (ex: [Pulo de tempo: ...], [Intervalo: ...])
    # Essas mensagens são geradas pelo Escriba em formatos MD/TXT e podem poluir o RAG
    cleaned_transcription = re.sub(r'\[(?:Pulo de tempo|Intervalo|Gap|Pulo):?.*?\]', '', cleaned_transcription, flags=re.IGNORECASE)
    # Remove espaços extras gerados pela remoção
    cleaned_transcription = re.sub(r'\n{3,}', '\n\n', cleaned_transcription)
    cleaned_transcription = cleaned_transcription.strip()

    # Formatação Estética para NotebookLM
    formatted_transcription_block = f"\n{'='*60}\n"
    formatted_transcription_block += f"ARQUIVO: {transcription_filename}\n"
    formatted_transcription_block += f"ID: {metadata_dict['id']}\n"
    formatted_transcription_block += f"DATA: {metadata_dict['date']}\n"
    formatted_transcription_block += f"TITULO: {metadata_dict['title']}\n"
    formatted_transcription_block += f"{'-'*60}\n"
    formatted_transcription_block += f"{cleaned_transcription}\n"
    formatted_transcription_block += f"{'='*60}\n"

    return formatted_transcription_block, cleaned_transcription, extracted_summary_text

def _migrate_legacy_state(channel_dir_path: str, state_file_path: str) -> None:
    """
    Migração única: importa o .lexis-join-state.json legado para dentro do
    escriba_[canal].json (chave `lexis_state`) e apaga o arquivo antigo.
    """
    legacy_path = os.path.join(channel_dir_path, ".lexis-join-state.json")
    if not os.path.exists(legacy_path):
        return
    try:
        with open(legacy_path, 'r', encoding='utf-8') as f:
            legacy_state = json.load(f)

        # Só migra se ainda não houver lexis_state no arquivo destino
        dest_data = {}
        if os.path.exists(state_file_path):
            with open(state_file_path, 'r', encoding='utf-8') as f:
                dest_data = json.load(f)

        if "lexis_state" not in dest_data:
            dest_data["lexis_state"] = legacy_state
            with open(state_file_path, 'w', encoding='utf-8') as f:
                json.dump(dest_data, f, ensure_ascii=False, indent=2)
            print_info(f"🔀 Estado legado migrado de .lexis-join-state.json → {os.path.basename(state_file_path)}", "  ")

        os.remove(legacy_path)
        print_info("🗑  .lexis-join-state.json legado removido.", "  ")
    except Exception as e:
        print_warn(f"Falha ao migrar estado legado: {e}", "  ")


def load_state(state_file_path):
    if os.path.exists(state_file_path):
        try:
            with open(state_file_path, 'r', encoding='utf-8') as file_descriptor:
                data = json.load(file_descriptor)
                return data.get("lexis_state", {"processed_files": [], "processed_ids": [], "last_volume": 1, "last_volume_size": 0})
        except Exception:
            return {"processed_files": [], "processed_ids": [], "last_volume": 1, "last_volume_size": 0}
    return {"processed_files": [], "processed_ids": [], "last_volume": 1, "last_volume_size": 0}

def save_state(state_file_path, state_dict):
    data = {}
    if os.path.exists(state_file_path):
        try:
            with open(state_file_path, 'r', encoding='utf-8') as file_descriptor:
                data = json.load(file_descriptor)
        except Exception:
            pass
    data["lexis_state"] = state_dict
    with open(state_file_path, 'w', encoding='utf-8') as file_descriptor:
        json.dump(data, file_descriptor, ensure_ascii=False, indent=2)
    print_info(f"💾 Estado Lexis salvo em {os.path.basename(state_file_path)}", "  ")

def get_channel_url(channel_dir_path, channel_name):
    """
    Retorna a URL completa do canal no formato https://youtube.com/@[channel_name].
    """
    # Aumentando a precisão: se o channel_name já começa com @, não duplicamos
    handle = channel_name
    if not handle.startswith("@"):
        handle = f"@{handle}"
    
    return f"https://youtube.com/{handle}"

def generate_volume_header(channel_name, channel_url):
    """Gera o cabeçalho de metadados do volume."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"{'='*60}\n"
    header += f"METADADOS DO VOLUME\n"
    header += f"CANAL: {channel_name}\n"
    header += f"URL: {channel_url}\n"
    header += f"DATA DE CRIAÇÃO: {now}\n"
    header += f"{'='*60}\n\n"
    return header

def extract_metadata_from_volume(volume_content: str) -> list[dict]:
    """
    Lê um volume de texto já existente (que foi retomado) e extrai os metadados
    dos vídeos que já estão inseridos no arquivo para repopular o índice no final.
    """
    recovered_metadata = []
    
    # Busca blocos no formato:
    # ID: ...
    # DATA: ...
    # TITULO: ...
    # ------------------------------------------------------------
    pattern = re.compile(
        r"ID:\s*(.*?)\nDATA:\s*(.*?)\nTITULO:\s*(.*?)\n-{" + str(60) + "}",
        re.MULTILINE
    )
    
    for match in pattern.finditer(volume_content):
        vid_id = match.group(1).strip()
        date = match.group(2).strip()
        title = match.group(3).strip()
        
        recovered_metadata.append({
            "id": vid_id,
            "date": date,
            "title": title
        })
        
    return recovered_metadata

def generate_volume_index(video_metadata_list):
    """Gera um índice detalhado de vídeos contidos no volume (ID | Data | Título)."""
    if not video_metadata_list:
        return ""
    
    # Remove duplicatas mantendo a ordem (pode haver o mesmo vídeo se houver múltiplos arquivos dele, o que é raro mas possível)
    seen_ids = set()
    unique_metadata = []
    for meta in video_metadata_list:
        vid_id = meta.get("id", "Sem ID")
        if vid_id not in seen_ids:
            unique_metadata.append(meta)
            seen_ids.add(vid_id)
            
    # Ordena por data (se disponível) ou título
    unique_metadata.sort(key=lambda x: (x.get("date", ""), x.get("title", "")))
    
    index_text = f"\n\n{'='*60}\n"
    index_text += f"ÍNDICE DE VÍDEOS NESTE VOLUME (Detalhamento):\n"
    index_text += f"{'-'*60}\n"
    index_text += f"{'ID':<15} | {'DATA':<10} | {'TÍTULO'}\n"
    index_text += f"{'-'*60}\n"
    
    for meta in unique_metadata:
        vid_id = meta.get("id", "Sem ID")
        date = meta.get("date", "Desconhecida")
        title = meta.get("title", "Sem Título")
        # Truncar título se for muito longo para uma linha de índice? (Opcional, mas melhor manter limpo)
        if len(title) > 60:
            title = title[:57] + "..."
        index_text += f"{vid_id:<15} | {date:<10} | {title}\n"
        
    index_text += f"{'='*60}\n"
    return index_text

def scan_volumes_for_files(output_dir_path, channel_name):
    """
    Varre os volumes .txt existentes para detectar quais arquivos já foram consolidados.
    Retorna (set de arquivos encontrados, set de IDs encontrados, maior_volume, tamanho_maior_volume).
    """
    found_files_set = set()
    found_ids_set = set()
    recovered_max_volume_idx = 0
    recovered_volume_bytes = 0
    
    if not os.path.exists(output_dir_path):
        return found_files_set, found_ids_set, 0, 0
        
    volume_filename_pattern = re.compile(rf"^{re.escape(channel_name)}-v(\d{{3}})\.txt$")
    for volume_filename in os.listdir(output_dir_path):
        regex_match_result = volume_filename_pattern.match(volume_filename)
        if regex_match_result:
            volume_index = int(regex_match_result.group(1))
            volume_file_path = os.path.join(output_dir_path, volume_filename)
            
            # Se for o maior volume encontrado até agora, guarda dados para retomada
            volume_file_bytes = os.path.getsize(volume_file_path)
            if volume_index > recovered_max_volume_idx:
                recovered_max_volume_idx = volume_index
                recovered_volume_bytes = volume_file_bytes
            
            try:
                with open(volume_file_path, 'r', encoding='utf-8') as file_descriptor:
                    for line in file_descriptor:
                        if line.startswith("ARQUIVO: "):
                            transcription_filename = line.strip().replace("ARQUIVO: ", "")
                            found_files_set.add(transcription_filename)
                        elif line.startswith("ID: "):
                            video_id = line.strip().replace("ID: ", "")
                            if video_id and video_id != "Sem ID":
                                found_ids_set.add(video_id)
            except Exception:
                pass
                
    return found_files_set, found_ids_set, recovered_max_volume_idx, recovered_volume_bytes

def process_channel(channel_dir_path, channel_name, reset_mode=False):
    """
    Função principal:
    Agrupa vídeos soltos e consolida seus textos lado a lado iterativamente
    como uma fita cassete. Uma vez que o payload em texto acumulado estourar MAX_CHARS (ex: +1.8MB),
    o limite é acionado para cortar o volume, persistí-lo para .txt na subpasta designada, e reiniciar a esteira volumétrica com ID+1.
    
    Priorização de formatos (.md > .txt > .srt):
    Quando existem múltiplos arquivos para o mesmo vídeo (identificados pelo ID),
    o script seleciona o melhor formato e arquiva os excedentes automaticamente.
    Esta lógica se aplica a ambos os modos de operação.
    
    Modos de operação:
    - Incremental (padrão): Processa apenas arquivos novos, retomando o último volume aberto.
    - Reset (--reset): Restaura arquivos da pasta archive e reprocessa tudo do zero.
    """
    state_file_path = os.path.join(channel_dir_path, f"escriba_{channel_name}.json")
    output_dir_path = os.path.join(channel_dir_path, "volumes_notebooklm")
    archive_dir_path = os.path.join(channel_dir_path, ARCHIVE_DIR_NAME)

    # Migra .lexis-join-state.json legado para dentro do escriba_[canal].json (execução única)
    _migrate_legacy_state(channel_dir_path, state_file_path)

    # Valida estrutura de nomenclaturas do Youtube do canal selecionado em seu escopo de arquivos no diretório:
    # Match Regex exige o padrão de prefixo: "[NOME DO CANAL]-[ID DE 9-15 CARACTERES].extensão"
    # Extensões aceitas: .md (preferido), .txt, .srt — a priorização ocorre na etapa de seleção.
    channel_file_regex_pattern = re.compile(rf"^{re.escape(channel_name)}[-]+[A-Za-z0-9_-]{{9,15}}(?:-[a-zA-Z0-9-]+)?\.(txt|srt|md)$")
    
    # --- Modo Reset: apaga volumes, manifesto e restaura arquivos ---
    if reset_mode:
        print(f"\n🔄 Resetando Canal: {channel_name}")
        # Apaga volumes existentes do canal
        if os.path.exists(output_dir_path):
            volume_filename_pattern = re.compile(rf"^{re.escape(channel_name)}-v\d{{3}}\.txt$")
            for volume_filename in os.listdir(output_dir_path):
                if volume_filename_pattern.match(volume_filename):
                    volume_file_path = os.path.join(output_dir_path, volume_filename)
                    os.remove(volume_file_path)
                    print_info(f"  🗑 Removido: {volume_file_path}"[4:])
        # Apaga manifesto lexis_state mas preserva database escriba
        if os.path.exists(state_file_path):
            try:
                with open(state_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if "lexis_state" in data:
                    del data["lexis_state"]
                    with open(state_file_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print_info(f"🗑 Estado do Lexis removido de {os.path.basename(state_file_path)}", "  ")
            except Exception:
                pass
            
        # Restaura arquivos da pasta archive
        if os.path.exists(archive_dir_path):
            restored_files_count = 0
            for archive_filename in os.listdir(archive_dir_path):
                if channel_file_regex_pattern.match(archive_filename) or archive_filename.endswith(".info.json"):
                    source_file_path = os.path.join(archive_dir_path, archive_filename)
                    destination_file_path = os.path.join(channel_dir_path, archive_filename)
                    shutil.move(source_file_path, destination_file_path)
                    restored_files_count += 1
            if restored_files_count > 0:
                print_ok(f"  📦 Restaurados {restored_files_count} arquivos do archive."[5:])

    # Busca arquivos APÓS possível restauração do reset
    all_channel_files_list = [f for f in os.listdir(channel_dir_path) 
             if channel_file_regex_pattern.match(f) and not re.match(rf"^{re.escape(channel_name)}-v\d{{3}}\.txt$", f)]
    if not all_channel_files_list:
        return

    # Ordena arquivos para garantir ordem determinística na priorização e processamento
    all_channel_files_list.sort()
    
    if reset_mode:
        # Reprocessa tudo do zero
        processed_files_set = set()
        processed_ids_set = set()
        current_volume_content = ""
        current_volume_idx = 1
        current_state_dict = {}
        recovered_max_volume_idx = 1
    else:
        # --- Modo Incremental: filtra arquivos já processados ---
        current_state_dict = load_state(state_file_path)
        processed_files_set = set(current_state_dict.get("processed_files", []))
        processed_ids_set = set(current_state_dict.get("processed_ids", []))
        
        # Fallback: varre volumes existentes para detectar IDs já consolidados
        # (proteção contra manifesto apagado/corrompido)
        # O manifesto só deve conter arquivos que de fato constam nos volumes.
        volume_files_set, volume_ids_set, recovered_max_volume_idx, recovered_volume_bytes = scan_volumes_for_files(output_dir_path, channel_name)
        
        needs_state_update = False
        if volume_files_set - processed_files_set or volume_ids_set - processed_ids_set:
            recovered_files_count = len(volume_files_set - processed_files_set)
            recovered_ids_count = len(volume_ids_set - processed_ids_set)
            print_info(f"  🔍 Recuperados {recovered_files_count} arquivo(s) e {recovered_ids_count} ID(s) dos volumes (manifesto incompletos)"[5:])
            processed_files_set |= volume_files_set
            processed_ids_set |= volume_ids_set
            needs_state_update = True
            
        # Sincroniza volume/tamanho se o estado atual estiver zerado/desatualizado
        if current_state_dict.get("last_volume", 0) == 0 and recovered_max_volume_idx > 0:
            current_state_dict["last_volume"] = recovered_max_volume_idx
            current_state_dict["last_volume_size"] = recovered_volume_bytes
            needs_state_update = True

        if needs_state_update:
            # Persiste o manifesto corrigido imediatamente para não perder a recuperação
            corrected_state_dict = {
                "processed_files": sorted(list(processed_files_set)),
                "processed_ids": sorted(list(processed_ids_set)),
                "last_volume": current_state_dict.get("last_volume", 1),
                "last_volume_size": current_state_dict.get("last_volume_size", 0)
            }
            save_state(state_file_path, corrected_state_dict)
        
    # --- Priorização de Arquivos (.md > .txt > .srt) ---
    # Aplica-se a ambos os modos: Reset e Incremental
    id_to_files_dict = {}
    for transcription_filename in all_channel_files_list:
        if transcription_filename in processed_files_set:
            continue
        
        full_path = os.path.join(channel_dir_path, transcription_filename)
        meta = get_metadata(full_path)
        v_id = meta.get("id", "Sem ID")
        
        if v_id == "Sem ID":
            # Se não tem ID, usamos o próprio nome do arquivo/extensão para não perder
            v_id = f"FILE_{transcription_filename}"
        
        if v_id not in id_to_files_dict:
            id_to_files_dict[v_id] = []
        id_to_files_dict[v_id].append(transcription_filename)

    files_to_process_list = []
    archived_duplicates_count = 0
    archive_dir_path = os.path.join(channel_dir_path, ARCHIVE_DIR_NAME)
    os.makedirs(archive_dir_path, exist_ok=True)

    for v_id, files_list in id_to_files_dict.items():
        # Critério de desempate: preferir .md, depois .txt, depois .srt
        # Ordenamos por peso da extensão
        def ext_priority(fname):
            ext = os.path.splitext(fname)[1].lower()
            if ext == '.md': return 0
            if ext == '.txt': return 1
            if ext == '.srt': return 2
            return 3
        
        sorted_files = sorted(files_list, key=ext_priority)
        best_file = sorted_files[0]
        
        # Se v_id for um ID real e já foi processado, arquiva todos
        is_real_id = not v_id.startswith("FILE_")
        if is_real_id and v_id in processed_ids_set:
            for f in files_list:
                shutil.move(os.path.join(channel_dir_path, f), os.path.join(archive_dir_path, f))
                # Move .info.json
                json_f = f.rsplit('.', 1)[0] + ".info.json"
                json_p = os.path.join(channel_dir_path, json_f)
                if os.path.exists(json_p):
                    shutil.move(json_p, os.path.join(archive_dir_path, json_f))
                archived_duplicates_count += 1
            continue
        
        files_to_process_list.append(best_file)
        
        # Arquiva os excedentes do mesmo ID
        for i in range(1, len(sorted_files)):
            f_extra = sorted_files[i]
            shutil.move(os.path.join(channel_dir_path, f_extra), os.path.join(archive_dir_path, f_extra))
            # Move .info.json
            json_f = f_extra.rsplit('.', 1)[0] + ".info.json"
            json_p = os.path.join(channel_dir_path, json_f)
            if os.path.exists(json_p):
                shutil.move(json_p, os.path.join(archive_dir_path, json_f))
            archived_duplicates_count += 1
        
    if archived_duplicates_count > 0:
        print_info(f"  🧹 {archived_duplicates_count} arquivo(s) duplicado(s) por ID extra foram arquivados sem reprocessamento."[5:])
    
    if reset_mode:
        print_section(f"--- Processando Canal: {channel_name} (reset: {len(files_to_process_list)} arquivos únicos) ---"[4:-4])
    else:
        if not files_to_process_list:
            print_ok(f"\n✅ Canal: {channel_name} — nenhum arquivo novo. ({len(processed_files_set)} já processados)"[3:])
            return
    
    # Sempre verifica o MAIOR volume registrado no disco ou no estado para retomada
    current_volume_idx = max(recovered_max_volume_idx, current_state_dict.get("last_volume", 1), 1)
        
    # Tenta carregar o conteúdo do último volume existente para continuar preenchendo
    if not reset_mode:
        last_volume_file_path = os.path.join(output_dir_path, f"{channel_name}-v{current_volume_idx:03d}.txt")
        current_volume_content = ""
        if os.path.exists(last_volume_file_path):
            with open(last_volume_file_path, 'r', encoding='utf-8') as last_volume_file_descriptor:
                current_volume_content = last_volume_file_descriptor.read()
            last_volume_bytes = len(current_volume_content)
            
            if last_volume_bytes < MAX_CHARS:
                print_info(f"\n📂 Retomando Volume {current_volume_idx} ({last_volume_bytes:,} chars)"[3:])
                # Remove o índice anterior caso exista para não duplicar
                index_marker = f"\n\n{'='*60}\nÍNDICE DE VÍDEOS NESTE VOLUME"
                if index_marker in current_volume_content:
                    current_volume_content = current_volume_content.split(index_marker)[0]
                    print_warn(f"  ✂️ Índice anterior removido para atualização."[5:])
            else:
                current_volume_idx += 1  # Último volume estava cheio, começa um novo
                current_volume_content = ""
        else:
            current_volume_idx = max(current_volume_idx, 1)
        
        print_section(f"--- Processando Canal: {channel_name} (incremental: {len(files_to_process_list)} novos, {len(processed_files_set)} já processados) ---"[4:-4])

    # Obtém URL do canal para o cabeçalho
    channel_url = get_channel_url(channel_dir_path, channel_name)
    iteration_volume_metadata = [] # Metadados adicionados ao volume atual na memória

    # Se um volume foi retomado, tenta extrair metadados antigos para o índice
    if current_volume_content:
        recovered = extract_metadata_from_volume(current_volume_content)
        iteration_volume_metadata.extend(recovered)
        if recovered:
            print_info(f"  🔍 {len(recovered)} vídeo(s) detectado(s) no volume retomado."[5:])
    
    # Carrega base de metadados do escriba se disponível para fallback de títulos/datas
    # No modo RESET, ignoramos a base global para forçar reprocessamento limpo
    global_metadata_lookup = {}
    if not reset_mode:
        escriba_json_path = os.path.join(os.path.dirname(channel_dir_path), f"escriba_{channel_name}.json")
        if not os.path.exists(escriba_json_path):
            escriba_json_path = os.path.join(channel_dir_path, f"escriba_{channel_name}.json")
            
        if os.path.exists(escriba_json_path):
            try:
                with open(escriba_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for v in data.get("videos", []):
                        if "id" in v:
                            global_metadata_lookup[v["id"]] = v
            except:
                pass
    else:
        print_warn(f"  ℹ️  Modo RESET ativo: ignorando base global de metadados (escriba_{channel_name}.json)."[6:])

    # Lista acumulativa de arquivos processados nesta execução
    iteration_processed_files_list = []
    iteration_processed_ids_list = []
    
    # Cria pasta de output se não existir
    os.makedirs(output_dir_path, exist_ok=True)
    # Cria pasta de arquivo morto
    archive_dir_path = os.path.join(channel_dir_path, ARCHIVE_DIR_NAME)
    os.makedirs(archive_dir_path, exist_ok=True)

    for i, transcription_filename in enumerate(files_to_process_list):
        full_file_path = os.path.join(channel_dir_path, transcription_filename)
        
        try:
            with open(full_file_path, 'r', encoding='utf-8', errors='replace') as file_descriptor:
                subtitle_content = file_descriptor.read()
            
            metadata_dict = get_metadata(full_file_path)
            
            # Se for fallback "Sem ID" ou "Sem Título", tenta buscar na base global do escriba
            if metadata_dict["id"] != "Sem ID" and (metadata_dict["title"] == "Sem Título" or metadata_dict["date"] == "Desconhecida"):
                if metadata_dict["id"] in global_metadata_lookup:
                    v_meta = global_metadata_lookup[metadata_dict["id"]]
                    metadata_dict["title"] = v_meta.get("title", metadata_dict["title"])
                    metadata_dict["date"] = v_meta.get("upload_date", metadata_dict["date"])

            formatted_transcription_block, _, _ = process_content(subtitle_content, transcription_filename, full_file_path, metadata_dict=metadata_dict)

            video_id = metadata_dict.get("id", "")
            
            # Se o volume está vazio, adiciona o cabeçalho
            if not current_volume_content:
                current_volume_content = generate_volume_header(channel_name, channel_url)
                iteration_volume_metadata = []

            # Se adicionar este texto estourar o limite, fecha o volume atual
            if len(current_volume_content) + len(formatted_transcription_block) > MAX_CHARS and current_volume_content:
                # Adiciona o índice antes de salvar
                current_volume_content += generate_volume_index(iteration_volume_metadata)
                
                output_volume_filename = f"{channel_name}-v{current_volume_idx:03d}.txt"
                output_volume_file_path = os.path.join(output_dir_path, output_volume_filename)
                
                with open(output_volume_file_path, 'w', encoding='utf-8') as output_file_descriptor:
                    output_file_descriptor.write(current_volume_content)
                
                print_ok(f"  📦 Volume {current_volume_idx} finalizado: {output_volume_filename} ({len(current_volume_content):,} caracteres)"[5:])
                
                # Salva estado intermediário para segurança
                intermediate_state_dict = {
                    "processed_files": sorted(list(processed_files_set | set(iteration_processed_files_list))),
                    "processed_ids": sorted(list(processed_ids_set | set(iteration_processed_ids_list))),
                    "last_volume": current_volume_idx,
                    "last_volume_size": len(current_volume_content)
                }
                save_state(state_file_path, intermediate_state_dict)
                
                # Reseta para o próximo volume
                current_volume_idx += 1
                current_volume_content = generate_volume_header(channel_name, channel_url)
                iteration_volume_metadata = []
            
            current_volume_content += formatted_transcription_block
            iteration_processed_files_list.append(transcription_filename)
            
            # Adiciona ao índice independente de ter ID formatado ou não (usa fallback se necessário)
            iteration_processed_ids_list.append(video_id if video_id != "Sem ID" else transcription_filename)
            iteration_volume_metadata.append(metadata_dict)
            
            # Move arquivo original para a pasta archive
            shutil.move(full_file_path, os.path.join(archive_dir_path, transcription_filename))
            # Move também o .info.json se existir
            json_filename = transcription_filename.rsplit('.', 1)[0] + ".info.json"
            json_file_path = os.path.join(channel_dir_path, json_filename)
            if os.path.exists(json_file_path):
                shutil.move(json_file_path, os.path.join(archive_dir_path, json_filename))
            
            print(f"  [{(i+1):03d}/{len(files_to_process_list):03d}] Adicionado: {transcription_filename}")

        except Exception as e:
            print_err(f"  ❌ Erro ao processar {transcription_filename}: {str(e)}"[5:])

    # Salva o volume final (ou atual se incompleto)
    if current_volume_content:
        # Se o conteúdo for apenas o cabeçalho (nenhum vídeo adicionado), não salva
        header_only = generate_volume_header(channel_name, channel_url)
        if current_volume_content.strip() != header_only.strip():
            # Adiciona o índice antes de salvar
            current_volume_content += generate_volume_index(iteration_volume_metadata)
            
            output_volume_filename = f"{channel_name}-v{current_volume_idx:03d}.txt"
            output_volume_file_path = os.path.join(output_dir_path, output_volume_filename)
            with open(output_volume_file_path, 'w', encoding='utf-8') as output_file_descriptor:
                output_file_descriptor.write(current_volume_content)
            print_ok(f"  📦 Volume {current_volume_idx} salvo ({len(current_volume_content):,} caracteres)"[5:])
        
        # Salva estado final
        final_state_dict = {
            "processed_files": sorted(list(processed_files_set | set(iteration_processed_files_list))),
            "processed_ids": sorted(list(processed_ids_set | set(iteration_processed_ids_list))),
            "last_volume": current_volume_idx,
            "last_volume_size": len(current_volume_content)
        }
    else:
        final_state_dict = {
            "processed_files": sorted(list(processed_files_set)),
            "processed_ids": sorted(list(processed_ids_set)),
            "last_volume": current_volume_idx,
            "last_volume_size": len(current_volume_content)
        }
    save_state(state_file_path, final_state_dict)

def consolidate_by_channel(base_dir_path, reset_mode=False):
    """
    Função principal:
    Entry-point do lexis-join que varre recursivamente a pasta base buscando
    vídeos na raiz que compõe um canal base, para então chamar subdiretórios 
    (assumindo diretório/pasta = nome de canal distinto) acionando a função iteradora process_channel(subpasta).
    
    Parâmetros:
    - reset_mode: Se True, apaga volumes e manifesto e reprocessa tudo do zero.
    """
    if not os.path.exists(base_dir_path):
        print_err(f"❌ Erro: O diretório '{base_dir_path}' não existe."[3:])
        return

    execution_mode_label = "RESET (reprocessando tudo)" if reset_mode else "INCREMENTAL"
    print(f"\n{'='*50}")
    print(f"  LEXIS-JOIN — Modo: {execution_mode_label}")
    print(f"  Diretório Base: {os.path.abspath(base_dir_path)}")
    print(f"{'='*50}")
    
    # 1. Busca vídeos avulsos espalhados no diretório base.
    base_dir_name = os.path.basename(os.path.abspath(base_dir_path))
    base_dir_files_list = [f for f in os.listdir(base_dir_path) 
                  if f.endswith(('.txt', '.srt', '.md')) and not re.match(rf"^{re.escape(base_dir_name)}-v\d{{3}}\.txt$", f)]
    
    # Também considera se há arquivos nas pastas de archive do próprio diretório base
    archived_files = []
    if os.path.exists(os.path.join(base_dir_path, ARCHIVE_DIR_NAME)):
        archived_files = [f for f in os.listdir(os.path.join(base_dir_path, ARCHIVE_DIR_NAME)) if f.endswith(('.txt', '.srt', '.md'))]

    if base_dir_files_list or archived_files:
        process_channel(base_dir_path, base_dir_name, reset_mode=reset_mode)

    # 2. Se o base_dir NÃO for um canal, itera pelos subdiretórios assumindo que eles são os canais.
    if not (base_dir_files_list or archived_files):
        subdirs_list = [channel_dir_name for channel_dir_name in os.listdir(base_dir_path) 
                if os.path.isdir(os.path.join(base_dir_path, channel_dir_name)) and channel_dir_name not in (ARCHIVE_DIR_NAME, 'volumes_notebooklm', '__pycache__', '.venv', '.git')]
        for channel_dir_name in subdirs_list:
            process_channel(os.path.join(base_dir_path, channel_dir_name), channel_dir_name, reset_mode=reset_mode)
    
    print(f"\n{'='*50}")
    print(f"  ✅ Concluído!")
    print(f"{'='*50}\n")

