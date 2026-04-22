import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from utils import print_ok, print_err, print_info, print_warn, print_section, BOLD, RESET

"""
MÓDULO HISTORY: A Memória do Escriba
-----------------------------------
Este módulo funciona como o 'cérebro' persistente do projeto. Ele é responsável por:
1. Saber quais vídeos já foram processados para não gastar banda e tempo repetindo o trabalho.
2. Migrar dados de versões antigas do script (que usavam arquivos .txt) para o novo formato JSON.
3. Garantir que, se o computador desligar no meio de um salvamento, o banco de dados não seja corrompido.
"""


def _find_legacy_databases(cwd_path: Path) -> List[Path]:
    """
    Busca arquivos JSON de versões anteriores (prefixo 'lista_').
    
    Por que fazemos isso?
    O projeto evoluiu e mudou o nome dos arquivos (de 'lista_' para 'escriba_').
    Para que o usuário não perca seu histórico, procuramos por esses nomes antigos.
    """
    patterns = ["escriba_*.json", "lista_*.json"]
    found = []
    for p in patterns:
        found.extend(list(cwd_path.glob(p)))
    
    # Ordenamos pelo mais recente (data de modificação) para garantir que pegamos a info mais atual.
    return sorted(found, key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)

def get_latest_json_path(cwd_path: Path) -> Path:
    """
    Decide qual arquivo .json é o banco de dados oficial desta pasta.
    Prioriza o nome novo 'escriba_[nome_da_pasta].json'.
    """
    official = cwd_path / f"escriba_{cwd_path.name}.json"
    if official.exists():
        return official
    legacies = _find_legacy_databases(cwd_path)
    return legacies[0] if legacies else official


def _get_history_search_dirs(cwd_path: Path) -> List[Path]:
    """Retorna lista de diretórios para buscar histórico (atual + subpastas)."""
    try:
        ignore = {".git", ".venv", "__pycache__"}
        return [cwd_path] + [d for d in cwd_path.iterdir() if d.is_dir() and d.name not in ignore]
    except Exception:
        return [cwd_path]

def load_all_local_history(cwd_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Lê todos os dados de vídeos já processados que encontrar na pasta.
    
    O 'history_map' é um dicionário onde a CHAVE é o ID do vídeo (ex: dQw4w9WgXcQ)
    e o VALOR é um objeto com as informações daquele vídeo.
    Isso permite buscas instantâneas (chamadas de O(1)) durante a execução.
    """
    history_map: Dict[str, Dict[str, Any]] = {}
    blacklist = {"package.json", "package-lock.json", "requirements.json", "env.json"}
    video_id_regex = re.compile(r"([A-Za-z0-9_-]{11})(?=\.info\.json$)")
    for directory in _get_history_search_dirs(cwd_path):
        _scan_directory_for_history(directory, blacklist, video_id_regex, history_map)
    return history_map


def _scan_directory_for_history(directory: Path, blacklist: set, vid_regex: re.Pattern, history_map: Dict[str, Dict[str, Any]]) -> None:
    """Varre um único diretório procurando arquivos JSON com dados de vídeos."""
    try:
        for jf in directory.glob("*.json"):
            if jf.name in blacklist: continue
            if jf.name.startswith(("escriba_", "lista_")):
                _parse_master_json(jf, history_map)
                continue
            match = vid_regex.search(jf.name)
            if match:
                _parse_video_metadata_json(jf, match.group(1), history_map)
    except Exception:
        pass


def _parse_master_json(jf: Path, history_map: Dict[str, Dict[str, Any]]) -> None:
    """Lê o banco de dados principal e preenche o history_map."""
    try:
        with open(jf, "r", encoding="utf-8") as fd:
            json_data = json.load(fd)
            v_list = _get_video_list_from_json(json_data)
            if isinstance(v_list, list):
                _populate_history_from_list(v_list, history_map)
    except Exception:
        pass

def _get_video_list_from_json(json_data: Any) -> Any:
    """Extrai a lista de vídeos de um dicionário (moderno) ou retorna a própria lista (legado)."""
    if isinstance(json_data, dict) and "videos" in json_data:
        return json_data["videos"]
    return json_data

def _populate_history_from_list(v_list: List[Dict[str, Any]], history_map: Dict[str, Dict[str, Any]]) -> None:
    """Itera sobre uma lista de vídeos e os mescla no mapa de histórico."""
    for v in v_list:
        vid_id = v.get("video_id") or v.get("id")
        if vid_id:
            _merge_video_data(history_map, vid_id, v)


def _parse_video_metadata_json(jf: Path, vid_id: str, history_map: Dict[str, Dict[str, Any]]) -> None:
    """Extrai metadados de um arquivo .info.json avulso."""
    try:
        with open(jf, "r", encoding="utf-8") as fd:
            meta = json.load(fd)
            if not isinstance(meta, dict):
                return
            
            upload_date = _extract_upload_date(meta)
            real_vid_id = meta.get("id") or meta.get("display_id") or vid_id
            v_data = _build_video_metadata_dict(meta, real_vid_id, upload_date)
            _merge_video_data(history_map, real_vid_id, v_data)
    except Exception:
        pass

def _extract_upload_date(meta: Dict[str, Any]) -> str:
    """Extrai e formata a data de upload de um dicionário de metadados."""
    raw_date = meta.get("upload_date") or meta.get("publish_date") or meta.get("date")
    if raw_date and len(str(raw_date)) == 8 and str(raw_date).isdigit():
        s = str(raw_date)
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return raw_date or "N/A"

def _build_video_metadata_dict(meta: Dict[str, Any], vid_id: str, upload_date: str) -> Dict[str, Any]:
    """Constrói o dicionário padronizado de dados do vídeo."""
    return {
        "video_id": vid_id,
        "title": meta.get("title") or meta.get("fulltitle") or "Avulso",
        "publish_date": upload_date,
        "subtitle_downloaded": meta.get("subtitle_downloaded", False),
        "info_downloaded": True if upload_date != "N/A" else False,
        "channel_id": meta.get("channel_id") or meta.get("uploader_id"),
        "uploader": meta.get("uploader") or meta.get("channel"),
        "uploader_id": meta.get("uploader_id") or meta.get("channel_id")
    }


def _merge_video_data(history_map: Dict[str, Dict[str, Any]], vid_id: str, new_data: Dict[str, Any]) -> None:
    """Combina dados de um vídeo de múltiplas fontes sem perder informações."""
    if vid_id not in history_map:
        history_map[vid_id] = new_data.copy()
        return
    _merge_fields_inline(history_map[vid_id], new_data)

def _merge_fields_inline(existing: Dict[str, Any], new_data: Dict[str, Any]) -> None:
    """Mescla campos individuais de dados de vídeo in-place."""
    _merge_text_field(existing, new_data, "publish_date", ["N/A"])
    _merge_text_field(existing, new_data, "title", ["N/A", "", "Avulso"])
    
    for flag in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
        if new_data.get(flag):
            existing[flag] = True
            
    if new_data.get("source_channel") and not existing.get("source_channel"):
        existing["source_channel"] = new_data["source_channel"]

def _merge_text_field(existing: Dict[str, Any], new: Dict[str, Any], field: str, placeholders: List[str]) -> None:
    """Mescla um campo de texto se o novo valor for válido e o antigo for placeholder."""
    val = new.get(field)
    if val and val not in placeholders:
        if not existing.get(field) or existing[field] in placeholders:
            existing[field] = val


def save_channel_state_json(json_path: Optional[Path], videos_list: List[Dict[str, Any]], channel_handle: Optional[str] = None, detected_language: Optional[str] = None, youtube_channel: Optional[str] = None) -> None:
    """Salva o banco de dados JSON do canal no disco de forma segura."""
    if not json_path: return
    
    final_videos = _deduplicate_videos(videos_list)
    existing_data = _load_existing_json_safely(json_path)
    
    output_data = {
        "folder_repository": json_path.stem.replace("escriba_", ""),
        "videos": final_videos
    }
    
    _populate_output_metadata(output_data, existing_data, channel_handle, detected_language, youtube_channel)
    _write_json_atomically(json_path, output_data)

def _deduplicate_videos(videos_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove entradas duplicadas do mesmo video_id, mesclando-as."""
    dedup_map: Dict[str, Dict[str, Any]] = {}
    for v in videos_list:
        vid_id = v.get("video_id") or v.get("id")
        if not vid_id: continue
        if vid_id not in dedup_map:
            dedup_map[vid_id] = v.copy()
        else:
            _merge_duplicate_inline(dedup_map[vid_id], v)
    return list(dedup_map.values())

def _load_existing_json_safely(json_path: Path) -> Dict[str, Any]:
    """Tenta carregar o JSON existente, retornando um dict vazio em caso de erro."""
    if not json_path.exists(): return {}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _populate_output_metadata(output_data: Dict[str, Any], existing: Dict[str, Any], handle: Optional[str], lang: Optional[str], url: Optional[str]) -> None:
    """Preenche metadados no dicionário de saída, preservando dados existentes."""
    existing_channels = existing.get("youtube_channels", [])
    if isinstance(existing_channels, list) and existing_channels:
        output_data["youtube_channels"] = existing_channels
    
    context = handle or existing.get("channel_context")
    if context: output_data["channel_context"] = context
    if lang: output_data["detected_language"] = lang
    if url: output_data["youtube_channel"] = url


def _merge_duplicate_inline(existing: Dict[str, Any], new: Dict[str, Any]) -> None:
    """Mescla duas entradas do mesmo video_id dentro do processo de salvamento."""
    _merge_fields_inline(existing, new)
    if "playlists" in new:
        _merge_playlists(existing, new["playlists"])

def _merge_playlists(existing: Dict[str, Any], new_playlists: List[str]) -> None:
    """Une listas de playlists sem duplicar itens."""
    if "playlists" not in existing:
        existing["playlists"] = []
    for p in new_playlists:
        if p not in existing["playlists"]:
            existing["playlists"].append(p)


def _write_json_atomically(json_path: Path, output_data: Dict[str, Any]) -> None:
    """
    Grava o arquivo JSON usando a técnica de 'Escrita Atômica'.
    
    Como funciona:
    1. Escrevemos em um arquivo temporário (.tmp).
    2. Se a escrita terminar com sucesso, RENOMEAMOS o temporário para o nome oficial.
    
    Por que?
    Se o script travar durante a escrita, o arquivo original continua intacto. 
    Isso evita que o banco de dados seja corrompido e você perca todo o seu histórico.
    """
    target_write_path = _get_target_write_path(json_path)
    temp_path = target_write_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as fd:
            json.dump(output_data, fd, indent=4, ensure_ascii=False)
        temp_path.replace(target_write_path)
        _cleanup_legacy_json(json_path, target_write_path)
    except Exception as e:
        print_warn(f"Erro ao salvar histórico: {e}")

def _get_target_write_path(json_path: Path) -> Path:
    """Retorna o caminho de escrita, convertendo prefixos legados."""
    if json_path.name.startswith("lista_"):
        return json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    return json_path

def _cleanup_legacy_json(original_path: Path, target_path: Path) -> None:
    """Remove o arquivo legado se ele foi migrado para um novo nome."""
    if original_path != target_path and original_path.exists():
        original_path.unlink(missing_ok=True)


def filter_state_list(full_state_list: List[Dict[str, Any]], date_limit_filter: str) -> List[Dict[str, Any]]:
    """Filtra a lista de vídeos para retornar apenas os publicados a partir de uma data."""
    if not full_state_list: return []
    if not date_limit_filter: return list(full_state_list)
    
    normalized_limit = _normalize_date_limit(date_limit_filter)
    return [v for v in full_state_list if _is_video_after_date(v, normalized_limit)]

def _normalize_date_limit(date_limit_filter: str) -> str:
    """Normaliza o filtro de data usando o DateRange do yt-dlp."""
    try:
        from yt_dlp.utils import DateRange
        parsed = DateRange.day(date_limit_filter).start
        return parsed.replace("-", "") if parsed else date_limit_filter
    except Exception:
        return date_limit_filter

def _is_video_after_date(video: Dict[str, Any], date_limit: str) -> bool:
    """Verifica se um vídeo foi publicado após a data limite."""
    d_str = video.get("publish_date", "N/A")
    if not d_str or d_str == "N/A": return False
    return d_str.replace("-", "") >= date_limit


def auto_migrate_legacy_files(cwd_path: Path, state_list: List[Dict[str, Any]]) -> bool:
    """Migra dados de arquivos de texto antigos para o formato JSON atual."""
    legacy_data = _collect_legacy_ids(cwd_path)
    if not any(legacy_data): return False

    updated_count = _apply_legacy_migration(state_list, legacy_data)
    _backup_legacy_files(cwd_path)
    
    if updated_count > 0:
        print_ok(f"Migração de arquivos legacy concluída ({updated_count} updates no JSON).")
    return True

def _collect_legacy_ids(cwd_path: Path) -> Tuple[set, set, set]:
    """Coleta IDs de todos os arquivos legados."""
    return (
        _read_legacy_id_file(cwd_path / "historico.txt", "youtube "),
        _read_legacy_id_file(cwd_path / "historico-info.txt", "youtube "),
        _read_legacy_nosub_file(cwd_path / "videos_sem_legenda.txt")
    )

def _apply_legacy_migration(state_list: List[Dict[str, Any]], legacy_data: Tuple[set, set, set]) -> int:
    """Aplica as flags migratórias na lista de estados."""
    h_ids, i_ids, n_ids = legacy_data
    count = 0
    for item in state_list:
        vid_id = item.get("video_id")
        if not vid_id: continue
        count += _update_flags_from_legacy(item, vid_id, h_ids, i_ids, n_ids)
    return count

def _update_flags_from_legacy(item: Dict[str, Any], vid_id: str, h_ids: set, i_ids: set, n_ids: set) -> int:
    """Atualiza flags individuais para um vídeo a partir dos dados legados."""
    updates = 0
    mapping = [("subtitle_downloaded", h_ids), ("info_downloaded", i_ids), ("has_no_subtitle", n_ids)]
    for key, id_set in mapping:
        if vid_id in id_set and not item.get(key):
            item[key] = True; updates = 1
    return updates

def _backup_legacy_files(cwd_path: Path) -> None:
    """Renomeia arquivos legados para .bak."""
    files = ["historico.txt", "historico-info.txt", "videos_sem_legenda.txt"]
    for f in files:
        p = cwd_path / f
        if p.is_file(): p.rename(p.with_suffix(".txt.bak"))


def _read_legacy_id_file(path: Path, prefix: str) -> set:
    """Lê um arquivo de histórico legado no formato de linhas com prefixo."""
    ids: set = set()
    if not path.is_file(): return ids
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(prefix):
                ids.add(stripped[len(prefix):])
    return ids


def _read_legacy_nosub_file(path: Path) -> set:
    """Lê o arquivo legado de vídeos sem legenda disponível."""
    ids: set = set()
    if not path.is_file(): return ids
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if "watch?v=" in line:
                vid = line.strip().split("watch?v=")[-1].strip()
                if vid: ids.add(vid)
    return ids


def migrate_all_databases(cwd_path: Path) -> None:
    """Atualiza todos os bancos de dados JSON da pasta para o formato mais recente."""
    json_files = list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json"))
    if not json_files:
        print_info("Nenhum banco de dados compatível encontrado para migração.")
        return

    print_section("Migração de Banco de Dados")
    print_info(f"Verificando {len(json_files)} arquivo(s) para adaptação...")
    migrated_count = sum(1 for jp in json_files if _migrate_single_database(jp))

    if migrated_count > 0:
        print_ok(f"Migração concluída! {BOLD}{migrated_count}{RESET} arquivo(s) adaptados.")
    else:
        print_info("Todos os bancos de dados já estão na versão mais recente.")


def _migrate_single_database(json_path: Path) -> bool:
    """Analisa e migra um único arquivo JSON para o formato atual."""
    try:
        data = _load_existing_json_safely(json_path)
        if not data: return False

        migrated_fields = _migrate_database_fields(data)
        is_legacy_name = json_path.name.startswith("lista_")

        if migrated_fields or is_legacy_name:
            print_info(f"Adaptando: {BOLD}{json_path.name}{RESET}...")
            save_channel_state_json(json_path, data.get("videos", []), 
                                   channel_handle=data.get("channel_context"),
                                   detected_language=data.get("detected_language"),
                                   youtube_channel=data.get("youtube_channel"))
            _cleanup_legacy_migration_file(json_path, is_legacy_name)
            return True
    except Exception as e:
        print_err(f"Falha ao migrar {json_path.name}: {e}")
    return False

def _migrate_database_fields(data: Dict[str, Any]) -> bool:
    """Renomeia campos desatualizados no dicionário de dados."""
    if "youtube_channel" in data: return False
    field = "channel" if "channel" in data else ("channel_context" if "channel_context" in data else None)
    if field:
        data["youtube_channel"] = data[field]
        return True
    return False

def _cleanup_legacy_migration_file(json_path: Path, is_legacy_name: bool) -> None:
    """Remove arquivo original se o novo nome foi criado."""
    if not is_legacy_name: return
    new_path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    if new_path.exists() and new_path != json_path:
        json_path.unlink()


def register_channel_in_json(json_path: Path, channel_handle: str) -> Tuple[bool, bool]:
    """Verifica se um canal do YouTube já foi registrado no banco de dados JSON."""
    if not channel_handle: return False, False
    
    handle_normalized = _normalize_handle(channel_handle)
    data = _load_existing_json_safely(json_path)
    
    channels = data.get("youtube_channels", [])
    if not isinstance(channels, list): channels = []

    if _is_handle_registered(handle_normalized, channels):
        return False, True

    channels.append(handle_normalized)
    data["youtube_channels"] = channels
    success = _atomic_json_dump(json_path, data)
    return True, success

def _normalize_handle(handle: str) -> str:
    """Padroniza o handle para sempre ter o prefixo @."""
    if not handle.startswith(("http", "@")):
        return f"@{handle}"
    return handle

def _is_handle_registered(handle: str, channels: List[str]) -> bool:
    """Verifica se um handle já está na lista de canais (case-insensitive)."""
    target = handle.lstrip("@").lower()
    return any(c.lstrip("@").lower() == target for c in channels)

def _atomic_json_dump(path: Path, data: Dict[str, Any]) -> bool:
    """Realiza um dump JSON atômico e retorna sucesso."""
    temp = path.with_suffix(".tmp")
    try:
        with open(temp, "w", encoding="utf-8") as fd:
            json.dump(data, fd, indent=4, ensure_ascii=False)
        temp.replace(path)
        print_ok(f"Canal registrado no banco de dados.")
        return True
    except Exception as e:
        print_warn(f"Falha ao persistir novo canal no JSON: {e}")
        temp.unlink(missing_ok=True)
        return False
