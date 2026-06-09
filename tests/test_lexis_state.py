import pytest
import os
import json
import sys
from pathlib import Path
from typing import Dict, Any

# Adiciona o diretório pai ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lexis import load_state, save_state, _clear_lexis_state, _get_default_state


def test_load_state_legacy_only(tmp_path):
    """Garante que a lista de processed_ids do formato legado é carregada corretamente."""
    state_file = tmp_path / "escriba_legacy.json"
    legacy_data = {
        "lexis_state": {
            "processed_files": ["file1.txt"],
            "processed_ids": ["ABC12345678", "XYZ87654321"],
            "last_volume": 2,
            "last_volume_size": 1000
        }
    }
    state_file.write_text(json.dumps(legacy_data), encoding="utf-8")
    
    state_dict = load_state(str(state_file))
    
    assert state_dict["processed_ids"] == ["ABC12345678", "XYZ87654321"]
    assert state_dict["processed_files"] == ["file1.txt"]
    assert state_dict["last_volume"] == 2
    assert state_dict["last_volume_size"] == 1000


def test_load_state_new_format_only(tmp_path):
    """Garante que processed_ids é reconstruído a partir do flag nos vídeos do JSON."""
    state_file = tmp_path / "escriba_new.json"
    new_data = {
        "videos": [
            {"video_id": "ABC12345678", "consolidated_notebooklm": True, "title": "Vídeo A"},
            {"id": "XYZ87654321", "consolidated": True, "title": "Vídeo B"},
            {"video_id": "NOTCONSOLIDA", "subtitle_downloaded": True, "title": "Vídeo C"}
        ],
        "lexis_state": {
            "processed_files": ["file2.txt"],
            "last_volume": 1,
            "last_volume_size": 500
        }
    }
    state_file.write_text(json.dumps(new_data), encoding="utf-8")
    
    state_dict = load_state(str(state_file))
    
    # Deve encontrar e mesclar ABC12345678 e XYZ87654321
    assert "ABC12345678" in state_dict["processed_ids"]
    assert "XYZ87654321" in state_dict["processed_ids"]
    assert "NOTCONSOLIDA" not in state_dict["processed_ids"]
    assert len(state_dict["processed_ids"]) == 2


def test_load_state_legacy_and_new_merged(tmp_path):
    """Garante que processed_ids mescla IDs do lexis_state legado com os dos vídeos novos."""
    state_file = tmp_path / "escriba_merged.json"
    merged_data = {
        "videos": [
            {"video_id": "NEWVIDEO111", "consolidated_notebooklm": True}
        ],
        "lexis_state": {
            "processed_ids": ["LEGACY22222"]
        }
    }
    state_file.write_text(json.dumps(merged_data), encoding="utf-8")
    
    state_dict = load_state(str(state_file))
    
    assert sorted(state_dict["processed_ids"]) == ["LEGACY22222", "NEWVIDEO111"]


def test_save_state_migrates_to_videos(tmp_path):
    """Garante que save_state grava flags nos vídeos, cria faltantes e remove processed_ids do JSON final."""
    state_file = tmp_path / "escriba_save.json"
    initial_data = {
        "videos": [
            {"video_id": "EXISTING111", "title": "Já Existente"},
            {"id": "OTHER222222", "title": "Outro"}
        ]
    }
    state_file.write_text(json.dumps(initial_data), encoding="utf-8")
    
    state_dict = {
        "processed_files": ["f.txt"],
        "processed_ids": ["EXISTING111", "NEW33333333"],
        "last_volume": 3,
        "last_volume_size": 2000
    }
    
    save_state(str(state_file), state_dict)
    
    # Recarrega o JSON bruto do arquivo para auditar a estrutura exata salva
    with open(state_file, 'r', encoding='utf-8') as f:
        saved_raw = json.load(f)
        
    # 1. Verifica se "processed_ids" NÃO está no "lexis_state" serializado
    assert "processed_ids" not in saved_raw["lexis_state"]
    assert saved_raw["lexis_state"]["processed_files"] == ["f.txt"]
    assert saved_raw["lexis_state"]["last_volume"] == 3
    
    # 2. Verifica se a lista de vídeos foi atualizada corretamente
    videos = saved_raw["videos"]
    assert len(videos) == 3 # O original tinha 2, + 1 placeholder criado para "NEW33333333"
    
    video_map = {v.get("video_id") or v.get("id"): v for v in videos}
    
    assert video_map["EXISTING111"]["consolidated_notebooklm"] is True
    assert video_map["EXISTING111"]["title"] == "Já Existente"
    
    assert video_map["NEW33333333"]["consolidated_notebooklm"] is True
    assert "title" not in video_map["NEW33333333"] # Criado como placeholder
    
    assert "consolidated_notebooklm" not in video_map["OTHER222222"]


def test_clear_lexis_state_removes_flags_from_videos(tmp_path):
    """Garante que _clear_lexis_state apaga a chave lexis_state e limpa as flags de consolidação."""
    state_file = tmp_path / "escriba_reset.json"
    initial_data = {
        "videos": [
            {"video_id": "ABC111", "consolidated_notebooklm": True, "title": "A"},
            {"id": "XYZ222", "consolidated": True, "title": "B"},
            {"video_id": "NOT_TOUCHED", "title": "C"}
        ],
        "lexis_state": {
            "processed_files": ["f.txt"]
        }
    }
    state_file.write_text(json.dumps(initial_data), encoding="utf-8")
    
    _clear_lexis_state(str(state_file))
    
    with open(state_file, 'r', encoding='utf-8') as f:
        saved_raw = json.load(f)
        
    assert "lexis_state" not in saved_raw
    
    videos = saved_raw["videos"]
    for v in videos:
        assert "consolidated_notebooklm" not in v
        assert "consolidated" not in v
        assert "title" in v # Garante que as outras chaves do vídeo não foram removidas


def test_migrate_all_databases_converts_lexis_state(tmp_path):
    """Garante que a função migrate_all_databases também converte e limpa a estrutura lexis_state."""
    from history import migrate_all_databases
    
    state_file = tmp_path / "escriba_meucanal.json"
    initial_data = {
        "folder_repository": "meucanal",
        "videos": [
            {"video_id": "ABC111", "title": "A"}
        ],
        "lexis_state": {
            "processed_files": ["f.txt"],
            "processed_ids": ["ABC111", "XYZ222"]
        }
    }
    state_file.write_text(json.dumps(initial_data), encoding="utf-8")
    
    # Executa a migração
    migrate_all_databases(tmp_path)
    
    # Recarrega o arquivo
    with open(state_file, 'r', encoding='utf-8') as f:
        migrated_raw = json.load(f)
        
    # Verifica se processed_ids sumiu do lexis_state
    assert "processed_ids" not in migrated_raw["lexis_state"]
    
    # Verifica se as flags foram adicionadas aos vídeos correspondentes
    videos = migrated_raw["videos"]
    video_map = {v.get("video_id") or v.get("id"): v for v in videos}
    
    assert video_map["ABC111"]["consolidated_notebooklm"] is True
    assert video_map["XYZ222"]["consolidated_notebooklm"] is True
