import pytest
import os
import shutil
from pathlib import Path
from typing import List

# Adiciona diretório pai no path para facilitar import local
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from lexis import _get_eligible_files, ARCHIVE_DIR_NAME

def test_get_eligible_files_with_archive(tmp_path):
    """
    Verifica se o Lexis encontra arquivos tanto na pasta principal quanto no archive.
    """
    # 1. Prepara a estrutura de pastas
    channel_path = tmp_path / "meucanal"
    channel_path.mkdir()
    archive_path = channel_path / ARCHIVE_DIR_NAME
    archive_path.mkdir()
    
    # 2. Cria arquivos fictícios
    # Padrão: [Canal]--[ID].[ext]
    # IDs do YouTube têm 11 caracteres.
    f1 = channel_path / "meucanal--ABC12345678.txt"
    f1.write_text("conteudo 1")
    
    f2 = archive_path / "meucanal--XYZ12345678.md"
    f2.write_text("conteudo 2")
    
    # Arquivo que NÃO deve ser pego (sem padrão de canal)
    f3 = channel_path / "aleatorio.txt"
    f3.write_text("ignore")

    # 3. Executa a função
    eligible_files = _get_eligible_files(str(channel_path), "meucanal")
    
    # 4. Validações
    assert "meucanal--ABC12345678.txt" in eligible_files
    assert os.path.join(ARCHIVE_DIR_NAME, "meucanal--XYZ12345678.md") in eligible_files
    assert "aleatorio.txt" not in eligible_files
    assert len(eligible_files) == 2

def test_get_eligible_files_only_main(tmp_path):
    """Verifica se funciona apenas com a pasta principal (sem archive)."""
    channel_path = tmp_path / "canal2"
    channel_path.mkdir()
    
    f1 = channel_path / "canal2--12345678901.srt"
    f1.write_text("legenda")
    
    eligible_files = _get_eligible_files(str(channel_path), "canal2")
    
    assert len(eligible_files) == 1
    assert "canal2--12345678901.srt" in eligible_files

def test_get_eligible_files_sorting(tmp_path):
    """Verifica se a lista retornada está ordenada (importante para determinismo)."""
    channel_path = tmp_path / "canal_sort"
    channel_path.mkdir()
    
    (channel_path / "canal_sort--ZZZZZZZZZZZ.txt").write_text("z")
    (channel_path / "canal_sort--AAAAAAAAAAA.txt").write_text("a")
    
    eligible_files = _get_eligible_files(str(channel_path), "canal_sort")
    
    assert eligible_files == ["canal_sort--AAAAAAAAAAA.txt", "canal_sort--ZZZZZZZZZZZ.txt"]

from lexis import _restore_from_archive

def test_restore_from_archive(tmp_path):
    """Verifica se os arquivos são movidos do archive de volta para a pasta principal."""
    channel_path = tmp_path / "canal_reset"
    channel_path.mkdir()
    archive_path = channel_path / ARCHIVE_DIR_NAME
    archive_path.mkdir()
    
    f1 = archive_path / "arquivo1.txt"
    f1.write_text("conteudo")
    
    _restore_from_archive(str(archive_path), str(channel_path))
    
    assert (channel_path / "arquivo1.txt").exists()
    assert not (archive_path / "arquivo1.txt").exists()
