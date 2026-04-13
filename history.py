import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from utils import print_ok, print_err, print_info, print_warn, print_section, BOLD, RESET

def get_latest_json_path(cwd_path: Path) -> Path:
    """
    Retorna o banco de dados JSON da pasta.
    Se o oficial não existe, busca versões legadas para auto-detecção.
    """
    folder_name: str = cwd_path.name
    official_path: Path = cwd_path / f"escriba_{folder_name}.json"
    if official_path.exists():
        return official_path
        
    legacies: List[Path] = sorted(
        list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json")),
        key=lambda x: x.stat().st_mtime if x.exists() else 0,
        reverse=True
    )
    return legacies[0] if legacies else official_path

def load_all_local_history(cwd_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Escaneia a pasta local em busca de dados de vídeos já processados anteriormente.
    """
    history_map: Dict[str, Dict[str, Any]] = {}
    blacklist: set = {"package.json", "package-lock.json", "requirements.json", "env.json"}
    video_id_regex: re.Pattern = re.compile(r"([A-Za-z0-9_-]{11})")
    
    try:
        search_dirs: List[Path] = [cwd_path] + [d for d in cwd_path.iterdir() if d.is_dir() and d.name not in (".git", ".venv", "__pycache__")]
    except Exception:
        search_dirs = [cwd_path]
    
    for directory in search_dirs:
        _scan_directory_for_history(directory, blacklist, video_id_regex, history_map)

    return history_map

def _scan_directory_for_history(directory: Path, blacklist: set, video_id_regex: re.Pattern, history_map: Dict[str, Dict[str, Any]]) -> None:
    """Extraído para reduzir tamanho do loop de scan iterativo."""
    try:
        for jf in directory.glob("*.json"):
            if jf.name in blacklist:
                continue
            
            if jf.name.startswith(("escriba_", "lista_")):
                _parse_master_json(jf, history_map)
                continue

            match = video_id_regex.search(jf.name)
            if match:
                _parse_video_metadata_json(jf, match.group(1), history_map)
    except Exception:
        pass

def _parse_master_json(jf: Path, history_map: Dict[str, Dict[str, Any]]) -> None:
    """Extrai informações do JSON principal legado ou moderno."""
    try:
        with open(jf, "r", encoding="utf-8") as fd:
            json_data = json.load(fd)
            v_list = json_data["videos"] if isinstance(json_data, dict) and "videos" in json_data else json_data
            if isinstance(v_list, list):
                for v in v_list:
                    vid_id = v.get("video_id") or v.get("id")
                    if vid_id:
                        _merge_video_data(history_map, vid_id, v)
    except Exception:
        pass

def _parse_video_metadata_json(jf: Path, vid_id: str, history_map: Dict[str, Dict[str, Any]]) -> None:
    """Extrai informações de .info.json avulsos."""
    try:
        with open(jf, "r", encoding="utf-8") as fd:
            meta = json.load(fd)
            if not isinstance(meta, dict):
                return
                
            upload_date = meta.get("upload_date") or meta.get("publish_date") or meta.get("date")
            if upload_date and len(str(upload_date)) == 8 and str(upload_date).isdigit():
                s_date = str(upload_date)
                upload_date = f"{s_date[:4]}-{s_date[4:6]}-{s_date[6:]}"
            
            v_data = {
                "video_id": vid_id,
                "title": meta.get("title") or meta.get("fulltitle") or meta.get("video_title") or "Avulso",
                "publish_date": upload_date or "N/A",
                "subtitle_downloaded": meta.get("subtitle_downloaded", False),
                "info_downloaded": True if upload_date else False,
                "channel_id": meta.get("channel_id") or meta.get("uploader_id"),
                "uploader": meta.get("uploader") or meta.get("channel"),
                "uploader_id": meta.get("uploader_id") or meta.get("channel_id")
            }
            _merge_video_data(history_map, vid_id, v_data)
    except Exception:
        pass

def _merge_video_data(history_map: Dict[str, Dict[str, Any]], vid_id: str, new_data: Dict[str, Any]) -> None:
    """Combina dados de vídeos de múltiplas fontes com prioridades de strings/flags"""
    if vid_id not in history_map:
        history_map[vid_id] = new_data.copy()
        return
        
    existing = history_map[vid_id]
    if new_data.get("publish_date") and new_data["publish_date"] != "N/A":
        if not existing.get("publish_date") or existing["publish_date"] == "N/A":
            existing["publish_date"] = new_data["publish_date"]
    if new_data.get("title") and new_data["title"] not in ("N/A", "", "Avulso"):
        if not existing.get("title") or existing["title"] in ("N/A", "", "Avulso"):
            existing["title"] = new_data["title"]
            
    for flag in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
        if new_data.get(flag):
            existing[flag] = True
            
    if new_data.get("source_channel") and not existing.get("source_channel"):
        existing["source_channel"] = new_data["source_channel"]

def save_channel_state_json(
    json_path: Optional[Path], 
    videos_list: List[Dict[str, Any]], 
    channel_handle: Optional[str] = None, 
    detected_language: Optional[str] = None, 
    youtube_channel: Optional[str] = None
) -> None:
    """Salva o banco de dados JSON de forma atômica."""
    if not json_path:
        return
        
    dedup_map: Dict[str, Dict[str, Any]] = {}
    for v in videos_list:
        vid_id = v.get("video_id") or v.get("id")
        if not vid_id:
            continue
        if vid_id not in dedup_map:
            dedup_map[vid_id] = v.copy()
        else:
            _merge_duplicate_inline(dedup_map[vid_id], v)

    final_videos = list(dedup_map.values())
    
    if not channel_handle and json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                channel_handle = json.load(f).get("channel_context")
        except Exception:
            pass
            
    output_data: Dict[str, Any] = {
        "folder_repository": json_path.stem.replace("escriba_", ""),
        "videos": final_videos
    }
    if channel_handle:
        output_data["channel_context"] = channel_handle
    if detected_language:
        output_data["detected_language"] = detected_language
    if youtube_channel:
        output_data["youtube_channel"] = youtube_channel
        
    _write_json_atomically(json_path, output_data)

def _merge_duplicate_inline(existing: Dict[str, Any], new: Dict[str, Any]) -> None:
    """Extraído para manter modularidade"""
    for flag in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
        if new.get(flag):
            existing[flag] = True
    
    if new.get("publish_date") and new["publish_date"] != "N/A":
        if not existing.get("publish_date") or existing["publish_date"] == "N/A":
            existing["publish_date"] = new["publish_date"]
    if new.get("title") and new["title"] not in ("N/A", "Avulso", ""):
        if not existing.get("title") or existing["title"] in ("N/A", "Avulso", ""):
            existing["title"] = new["title"]
            
    if "playlists" in new:
        if "playlists" not in existing:
            existing["playlists"] = []
        for p in new["playlists"]:
            if p not in existing["playlists"]:
                existing["playlists"].append(p)

def _write_json_atomically(json_path: Path, output_data: Dict[str, Any]) -> None:
    """Gerencia a escrita temporária e atomicidade."""
    target_write_path = json_path
    if json_path.name.startswith("lista_"):
        target_write_path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    
    temp_path = target_write_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as file_descriptor:
            json.dump(output_data, file_descriptor, indent=4, ensure_ascii=False)
        temp_path.replace(target_write_path)
        
        if json_path.name.startswith("lista_") and json_path.exists():
            json_path.unlink(missing_ok=True)
    except Exception as e:
        print_warn(f"Ignorando erro ao salvar JSON de state: {e}")

def filter_state_list(full_state_list: List[Dict[str, Any]], date_limit_filter: str) -> List[Dict[str, Any]]:
    if not full_state_list:
        return []

    if date_limit_filter:
        try:
            from yt_dlp.utils import DateRange
            parsed_date_str = DateRange.day(date_limit_filter).start
            if parsed_date_str:
                date_limit_filter = parsed_date_str.replace("-", "")
        except Exception:
            pass 
            
        filtered_list = []
        for v_dict in full_state_list:
            d_str = v_dict.get("publish_date", "N/A")
            if d_str and d_str != "N/A":
                d_str_clean = d_str.replace("-", "")
                if d_str_clean >= date_limit_filter:
                    filtered_list.append(v_dict)
        return filtered_list
        
    return list(full_state_list)


def auto_migrate_legacy_files(cwd_path: Path, state_list: List[Dict[str, Any]]) -> bool:
    """
    Migra dados de arquivos texto antigos (historico.txt, videos_sem_legenda.txt)
    para o novo formato JSON. Renomeia os arquivos originais para .bak após migração.
    """
    historico_ids: set = _read_legacy_id_file(cwd_path / "historico.txt", prefix="youtube ")
    info_ids: set = _read_legacy_id_file(cwd_path / "historico-info.txt", prefix="youtube ")
    no_sub_ids: set = _read_legacy_nosub_file(cwd_path / "videos_sem_legenda.txt")

    if not historico_ids and not info_ids and not no_sub_ids:
        return False

    migrated_count: int = 0
    for item in state_list:
        video_id = item.get("video_id")
        if not video_id:
            continue
        if video_id in historico_ids and not item.get("subtitle_downloaded"):
            item["subtitle_downloaded"] = True
            migrated_count += 1
        if video_id in info_ids and not item.get("info_downloaded"):
            item["info_downloaded"] = True
            migrated_count += 1
        if video_id in no_sub_ids and not item.get("has_no_subtitle"):
            item["has_no_subtitle"] = True
            migrated_count += 1

    for legacy_path in [cwd_path / "historico.txt", cwd_path / "historico-info.txt", cwd_path / "videos_sem_legenda.txt"]:
        if legacy_path.is_file():
            legacy_path.rename(legacy_path.with_suffix(".txt.bak"))

    if migrated_count > 0:
        print_ok(f"Migração de arquivos legacy concluída ({migrated_count} updates no JSON).")
    return True


def _read_legacy_id_file(path: Path, prefix: str) -> set:
    """Lê IDs de um arquivo de histórico legado com prefixo."""
    ids: set = set()
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(prefix):
                    ids.add(line[len(prefix):])
    return ids


def _read_legacy_nosub_file(path: Path) -> set:
    """Lê IDs de vídeos sem legenda do arquivo legado."""
    ids: set = set()
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if "watch?v=" in line:
                    vid = line.strip().split("watch?v=")[-1].strip()
                    if vid:
                        ids.add(vid)
    return ids


def migrate_all_databases(cwd_path: Path) -> None:
    """
    Varre a pasta em busca de JSONs escriba_*/lista_* e os adapta para
    a versão atual (adicionando youtube_channel e padronizando nomes).
    """
    json_files: List[Path] = list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json"))
    if not json_files:
        print_info("Nenhum banco de dados compatível encontrado para migração.")
        return

    print_section("Migração de Banco de Dados")
    print_info(f"Verificando {len(json_files)} arquivo(s) para adaptação...")
    migrated_count: int = 0

    for json_path in json_files:
        if _migrate_single_database(json_path):
            migrated_count += 1

    if migrated_count > 0:
        print_ok(f"Migração concluída! {BOLD}{migrated_count}{RESET} arquivo(s) adaptados.")
    else:
        print_info("Todos os bancos de dados já estão na versão mais recente.")


def _migrate_single_database(json_path: Path) -> bool:
    """Migra um único arquivo JSON para o formato atual. Retorna True se houve mudança."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return False

        needs_migration = False
        if "youtube_channel" not in data:
            if "channel" in data:
                data["youtube_channel"] = data["channel"]
                needs_migration = True
            elif "channel_context" in data:
                data["youtube_channel"] = data["channel_context"]
                needs_migration = True

        is_legacy_name = json_path.name.startswith("lista_")

        if needs_migration or is_legacy_name:
            print_info(f"Adaptando: {BOLD}{json_path.name}{RESET}...")
            save_channel_state_json(
                json_path,
                data.get("videos", []),
                channel_handle=data.get("channel_context"),
                detected_language=data.get("detected_language"),
                youtube_channel=data.get("youtube_channel")
            )
            if is_legacy_name:
                new_path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))
                if new_path.exists() and new_path != json_path:
                    json_path.unlink()
            return True
    except Exception as e:
        print_err(f"Falha ao migrar {json_path.name}: {e}")
    return False
