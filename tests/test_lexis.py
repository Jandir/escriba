import pytest
import sys
import os
from pathlib import Path
from typing import List, Set, Dict

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

from lexis import (
    _get_deduplication_start_index, 
    clean_srt_content, 
    _get_ext_priority, 
    _generate_json_candidates,
    _process_subtitle_block,
    _parse_volume_manifest,
    _format_lexis_block,
    _enrich_metadata
)

# EXPLICAÇÃO PARA JUNIORES:
# O módulo Lexis lida com a organização de grandes volumes de texto.
# Testamos aqui se a detecção de duplicatas (deduplicação) e a extração
# de metadados estão funcionando, para garantir que o NotebookLM receba
# dados limpos e bem estruturados.

def test_get_deduplication_start_index_exact_match():
    """Verifica se o índice de início é detectado corretamente em match exato."""
    prev_str_list: List[str] = ["Hello", "World"]
    curr_str_list: List[str] = ["World", "New"]
    # Deve retornar 1 pois curr_str_list[0] == prev_str_list[-1]
    assert _get_deduplication_start_index(prev_str_list, curr_str_list) == 1

def test_get_deduplication_start_index_contained():
    """Verifica se o índice de início ignora blocos que já existem integralmente."""
    prev_str_list: List[str] = ["A", "B"]
    curr_str_list: List[str] = ["A", "B", "C"]
    # Deve retornar 2 pois curr_str_list começa exatamente com prev_str_list
    assert _get_deduplication_start_index(prev_str_list, curr_str_list) == 2

def test_get_deduplication_start_index_no_match():
    """Verifica se retorna 0 quando não há sobreposição entre os blocos."""
    prev_str_list: List[str] = ["A", "B"]
    curr_str_list: List[str] = ["X", "Y"]
    assert _get_deduplication_start_index(prev_str_list, curr_str_list) == 0

def test_clean_srt_content():
    """Verifica a limpeza de arquivos SRT para texto fluido."""
    srt_content_str: str = """1
00:00:01,000 --> 00:00:03,000
Hello

2
00:00:03,000 --> 00:00:05,000
World
"""
    result_str: str = clean_srt_content(srt_content_str)
    assert "Hello World" in result_str

def test_process_subtitle_block_deduplication():
    """Testa a lógica de remoção de repetições (roll-up) em legendas SRT."""
    subtitle_blocks_list: List[List[str]] = [["Olá", "tudo"]]
    new_text_str: str = "Olá\ntudo\nbem"
    
    # Ao processar "Olá tudo bem", ele deve detectar que "Olá tudo" já existe
    # e adicionar apenas "bem".
    _process_subtitle_block(new_text_str, subtitle_blocks_list)
    
    assert len(subtitle_blocks_list) == 2
    assert subtitle_blocks_list[1] == ["bem"]

def test_ext_priority():
    """Verifica a ordem de prioridade de extensões (Markdown > Texto > Legenda)."""
    assert _get_ext_priority("file.md") == 0
    assert _get_ext_priority("file.txt") == 1
    assert _get_ext_priority("file.srt") == 2
    assert _get_ext_priority("file.jpg") == 3

def test_generate_json_candidates():
    """Verifica a geração de nomes de arquivos .info.json para busca de metadados."""
    candidates_list: List[str] = _generate_json_candidates("Channel--ID.pt-br.txt")
    assert "Channel--ID.pt-br.info.json" in candidates_list
    assert "Channel--ID.info.json" in candidates_list

def test_format_lexis_block():
    """Verifica se o bloco formatado para o volume contém as etiquetas de identificação."""
    text_str: str = "Conteúdo do vídeo"
    filename_str: str = "video.md"
    metadata_dict: Dict[str, str] = {"id": "VID123", "title": "Título Legal", "date": "2024-01-01"}
    
    formatted_str: str = _format_lexis_block(text_str, filename_str, metadata_dict)
    
    assert "ARQUIVO: video.md" in formatted_str
    assert "ID: VID123" in formatted_str
    assert "Título Legal" in formatted_str
    assert "2024-01-01" in formatted_str

def test_parse_volume_manifest(tmp_path):
    """Verifica se conseguimos recuperar o estado a partir de um arquivo de volume físico."""
    volume_file_path = tmp_path / "Volume_1.txt"
    volume_content_str: str = (
        "ARQUIVO: video_orig.md\n"
        "ID: XYZ789\n"
        "Algum texto aqui...\n"
        "ARQUIVO: outro.txt\n"
        "ID: ABC123\n"
    )
    volume_file_path.write_text(volume_content_str, encoding="utf-8")
    
    files_set: Set[str] = set()
    ids_set: Set[str] = set()
    
    _parse_volume_manifest(str(volume_file_path), files_set, ids_set)
    
    assert "video_orig.md" in files_set
    assert "outro.txt" in files_set
    assert "XYZ789" in ids_set
    assert "ABC123" in ids_set

def test_enrich_metadata():
    """Verifica o preenchimento de metadados faltantes usando a base global."""
    meta_dict: Dict[str, str] = {"id": "V1", "title": "Sem Título", "date": "Desconhecida"}
    global_dict: Dict[str, Any] = {
        "V1": {"title": "Título Global", "upload_date": "2023-12-25"}
    }
    
    _enrich_metadata(meta_dict, global_dict.get("V1", {}))
    
    assert meta_dict["title"] == "Título Global"
    assert meta_dict["date"] == "2023-12-25"
