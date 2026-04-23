import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from utils import print_ok, print_err, print_info, print_warn, print_section, BOLD, RESET, format_date

"""
MÓDULO HISTORY: A Memória do Escriba
-----------------------------------
Este módulo funciona como o 'cérebro' persistente do projeto. Ele é responsável por:
1. Saber quais vídeos já foram processados para não gastar banda e tempo repetindo o trabalho.
2. Migrar dados de versões antigas do script (que usavam arquivos .txt) para o novo formato JSON.
3. Garantir que, se o computador desligar no meio de um salvamento, o banco de dados não seja corrompido.

PADRÃO EKKLEZIA:
Neste arquivo, todas as variáveis possuem sufixos que indicam seu tipo (ex: _str, _list, _path).
Isso ajuda você, programador júnior, a saber exatamente o que está manipulando sem precisar 
subir o código para ver a definição da variável.
"""


def _find_legacy_databases(cwd_path: Path) -> List[Path]:
    """
    Busca arquivos JSON de versões anteriores (prefixo 'lista_').
    
    Explicação para Juniores:
    O projeto evoluiu e mudou o nome dos arquivos (de 'lista_' para 'escriba_').
    Para que o usuário não perca seu histórico, procuramos por esses nomes antigos.
    Usamos o método .glob() da biblioteca Pathlib para buscar arquivos que seguem um padrão.
    O '*' no padrão 'lista_*.json' é um caractere curinga (wildcard) que significa 'qualquer coisa'.
    """
    patterns_list: List[str] = ["escriba_*.json", "lista_*.json"]
    found_paths_list: List[Path] = []
    
    for pattern_str in patterns_list:
        found_paths_list.extend(list(cwd_path.glob(pattern_str)))
    
    # Ordenamos pelo mais recente (data de modificação) para garantir que pegamos a info mais atual.
    # O comando .stat().st_mtime nos dá o "segundo exato" em que o arquivo foi salvo.
    return sorted(found_paths_list, key=lambda x_path: x_path.stat().st_mtime if x_path.exists() else 0, reverse=True)


def get_latest_json_path(cwd_path: Path) -> Path:
    """
    Decide qual arquivo .json é o banco de dados oficial desta pasta.
    Prioriza o nome novo 'escriba_[nome_da_pasta].json'.
    """
    official_json_path: Path = cwd_path / f"escriba_{cwd_path.name}.json"
    
    if official_json_path.exists():
        return official_json_path
        
    legacy_json_paths_list: List[Path] = _find_legacy_databases(cwd_path)
    return legacy_json_paths_list[0] if legacy_json_paths_list else official_json_path


def _get_history_search_dirs(cwd_path: Path) -> List[Path]:
    """Retorna lista de diretórios para buscar histórico (atual + subpastas)."""
    try:
        ignore_names_set: set[str] = {".git", ".venv", "__pycache__"}
        # List Comprehension: Cria uma lista filtrando pastas que não estão no ignore_names_set.
        return [cwd_path] + [d_path for d_path in cwd_path.iterdir() if d_path.is_dir() and d_path.name not in ignore_names_set]
    except Exception:
        return [cwd_path]


def load_all_local_history(cwd_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Lê todos os dados de vídeos já processados que encontrar na pasta.
    
    O 'history_map_dict' é um dicionário onde a CHAVE é o ID do vídeo (ex: dQw4w9WgXcQ)
    e o VALOR é um objeto com as informações daquele vídeo.
    Isso permite buscas instantâneas (chamadas de O(1)) durante a execução.
    """
    history_map_dict: Dict[str, Dict[str, Any]] = {}
    blacklist_names_set: set[str] = {"package.json", "package-lock.json", "requirements.json", "env.json"}
    
    # Regex para identificar IDs de vídeo em arquivos .info.json (padrão do yt-dlp)
    video_id_regex_obj: re.Pattern = re.compile(r"([A-Za-z0-9_-]{11})(?=\.info\.json$)")
    
    for directory_path in _get_history_search_dirs(cwd_path):
        _scan_directory_for_history(directory_path, blacklist_names_set, video_id_regex_obj, history_map_dict)
        
    return history_map_dict


def _scan_directory_for_history(
    directory_path: Path, 
    blacklist_names_set: set[str], 
    vid_regex_obj: re.Pattern, 
    history_map_dict: Dict[str, Dict[str, Any]]
) -> None:
    """Varre um único diretório procurando arquivos JSON com dados de vídeos."""
    try:
        for json_file_path in directory_path.glob("*.json"):
            if json_file_path.name in blacklist_names_set: 
                continue
                
            # Se o arquivo começa com escriba_ ou lista_, ele é um banco de dados mestre.
            if json_file_path.name.startswith(("escriba_", "lista_")):
                _parse_master_json(json_file_path, history_map_dict)
                continue
                
            # Caso contrário, pode ser um .info.json de um vídeo específico.
            match_obj: Optional[re.Match] = vid_regex_obj.search(json_file_path.name)
            if match_obj:
                _parse_video_metadata_json(json_file_path, match_obj.group(1), history_map_dict)
    except Exception:
        pass


def _parse_master_json(json_file_path: Path, history_map_dict: Dict[str, Dict[str, Any]]) -> None:
    """Lê o banco de dados principal e preenche o history_map_dict."""
    try:
        with open(json_file_path, "r", encoding="utf-8") as file_descriptor_obj:
            json_data_any: Any = json.load(file_descriptor_obj)
            video_list: Any = _get_video_list_from_json(json_data_any)
            
            if isinstance(video_list, list):
                _populate_history_from_list(video_list, history_map_dict)
    except Exception:
        pass


def _get_video_list_from_json(json_data_any: Any) -> Any:
    """Extrai a lista de vídeos de um dicionário (moderno) ou retorna a própria lista (legado)."""
    if isinstance(json_data_any, dict) and "videos" in json_data_any:
        return json_data_any["videos"]
    return json_data_any


def _populate_history_from_list(video_list: List[Dict[str, Any]], history_map_dict: Dict[str, Dict[str, Any]]) -> None:
    """Itera sobre uma lista de vídeos e os mescla no mapa de histórico."""
    for video_dict in video_list:
        video_id_str: Optional[str] = video_dict.get("video_id") or video_dict.get("id")
        if video_id_str:
            _merge_video_data(history_map_dict, video_id_str, video_dict)


def _parse_video_metadata_json(
    json_file_path: Path, 
    video_id_str: str, 
    history_map_dict: Dict[str, Dict[str, Any]]
) -> None:
    """Extrai metadados de um arquivo .info.json avulso."""
    try:
        with open(json_file_path, "r", encoding="utf-8") as file_descriptor_obj:
            metadata_dict: Any = json.load(file_descriptor_obj)
            if not isinstance(metadata_dict, dict):
                return
            
            upload_date_str: str = _extract_upload_date(metadata_dict)
            # Prioridade de ID: campo 'id' -> campo 'display_id' -> o que veio do nome do arquivo
            real_video_id_str: str = metadata_dict.get("id") or metadata_dict.get("display_id") or video_id_str
            
            video_data_dict: Dict[str, Any] = _build_video_metadata_dict(metadata_dict, real_video_id_str, upload_date_str)
            _merge_video_data(history_map_dict, real_video_id_str, video_data_dict)
    except Exception:
        pass


def _extract_upload_date(metadata_dict: Dict[str, Any]) -> str:
    """
    Extrai e formata a data de upload de um dicionário de metadados.
    
    Explicação para Juniores:
    O YouTube entrega datas como '20231225'. Nós queremos '2023-12-25' para facilitar a leitura.
    Usamos o f-string para fatiar (slice) a string original nas posições corretas.
    Exemplo: date_str[:4] pega os primeiros 4 caracteres ('2023').
    """
    raw_date_any: Any = metadata_dict.get("upload_date") or metadata_dict.get("publish_date") or metadata_dict.get("date")
    return format_date(raw_date_any)


def _build_video_metadata_dict(metadata_dict: Dict[str, Any], video_id_str: str, upload_date_str: str) -> Dict[str, Any]:
    """Constrói o dicionário padronizado de dados do vídeo."""
    return {
        "video_id": video_id_str,
        "title": metadata_dict.get("title") or metadata_dict.get("fulltitle") or "Avulso",
        "publish_date": upload_date_str,
        "subtitle_downloaded": metadata_dict.get("subtitle_downloaded", False),
        "info_downloaded": True if upload_date_str != "Desconhecida" else False,
        "channel_id": metadata_dict.get("channel_id") or metadata_dict.get("uploader_id"),
        "uploader": metadata_dict.get("uploader") or metadata_dict.get("channel"),
        "uploader_id": metadata_dict.get("uploader_id") or metadata_dict.get("channel_id")
    }


def _merge_video_data(history_map_dict: Dict[str, Dict[str, Any]], video_id_str: str, new_data_dict: Dict[str, Any]) -> None:
    """
    Combina dados de um vídeo de múltiplas fontes sem perder informações.
    
    Explicação para Juniores:
    Às vezes encontramos informações de um vídeo em dois lugares diferentes (ex: no banco de dados
    e em um arquivo .info.json avulso). Em vez de um apagar o outro, usamos o 'merge' (mesclar).
    Se já temos o vídeo, apenas atualizamos os campos que estão faltando ou que são mais completos.
    """
    if video_id_str not in history_map_dict:
        history_map_dict[video_id_str] = new_data_dict.copy()
        return
    _merge_fields_inline(history_map_dict[video_id_str], new_data_dict)


def _merge_fields_inline(existing_data_dict: Dict[str, Any], new_data_dict: Dict[str, Any]) -> None:
    """Mescla campos individuais de dados de vídeo in-place (direto na memória)."""
    _merge_text_field(existing_data_dict, new_data_dict, "publish_date", ["N/A", "Desconhecida", ""])
    _merge_text_field(existing_data_dict, new_data_dict, "title", ["N/A", "", "Avulso"])
    
    # Flags Booleanas: se o novo dado diz True, mantemos True.
    for flag_name_str in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
        if new_data_dict.get(flag_name_str):
            existing_data_dict[flag_name_str] = True
            
    if new_data_dict.get("source_channel") and not existing_data_dict.get("source_channel"):
        existing_data_dict["source_channel"] = new_data_dict["source_channel"]


def _merge_text_field(existing_dict: Dict[str, Any], new_dict: Dict[str, Any], field_name_str: str, placeholders_list: List[str]) -> None:
    """Mescla um campo de texto se o novo valor for válido e o antigo for placeholder."""
    new_value_any: Any = new_dict.get(field_name_str)
    if new_value_any and new_value_any not in placeholders_list:
        if not existing_dict.get(field_name_str) or existing_dict[field_name_str] in placeholders_list:
            existing_dict[field_name_str] = new_value_any


def save_channel_state_json(
    json_path: Optional[Path], 
    videos_list: List[Dict[str, Any]], 
    channel_handle_str: Optional[str] = None, 
    detected_language_str: Optional[str] = None, 
    youtube_channel_url_str: Optional[str] = None
) -> None:
    """Salva o banco de dados JSON do canal no disco de forma segura."""
    if not json_path: 
        return
    
    final_videos_list: List[Dict[str, Any]] = _deduplicate_videos(videos_list)
    existing_data_dict: Dict[str, Any] = _load_existing_json_safely(json_path)
    
    output_data_dict: Dict[str, Any] = {
        "folder_repository": json_path.stem.replace("escriba_", ""),
        "videos": final_videos_list
    }
    
    _populate_output_metadata(output_data_dict, existing_data_dict, channel_handle_str, detected_language_str, youtube_channel_url_str)
    _write_json_atomically(json_path, output_data_dict)


def _deduplicate_videos(videos_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove entradas duplicadas do mesmo video_id, mesclando-as."""
    dedup_map_dict: Dict[str, Dict[str, Any]] = {}
    for video_dict in videos_list:
        video_id_str: Optional[str] = video_dict.get("video_id") or video_dict.get("id")
        if not video_id_str: 
            continue
            
        if video_id_str not in dedup_map_dict:
            dedup_map_dict[video_id_str] = video_dict.copy()
        else:
            _merge_duplicate_inline(dedup_map_dict[video_id_str], video_dict)
            
    return list(dedup_map_dict.values())


def _load_existing_json_safely(json_path: Path) -> Dict[str, Any]:
    """Tenta carregar o JSON existente, retornando um dict vazio em caso de erro."""
    if not json_path.exists(): 
        return {}
    try:
        with open(json_path, "r", encoding="utf-8") as file_descriptor_obj:
            data_any: Any = json.load(file_descriptor_obj)
            return data_any if isinstance(data_any, dict) else {}
    except Exception:
        return {}


def _populate_output_metadata(
    output_data_dict: Dict[str, Any], 
    existing_dict: Dict[str, Any], 
    handle_str: Optional[str], 
    lang_str: Optional[str], 
    url_str: Optional[str]
) -> None:
    """Preenche metadados no dicionário de saída, preservando dados existentes."""
    existing_channels_list: Any = existing_dict.get("youtube_channels", [])
    if isinstance(existing_channels_list, list) and existing_channels_list:
        output_data_dict["youtube_channels"] = existing_channels_list
    
    context_str: Optional[str] = handle_str or existing_dict.get("channel_context")
    if context_str: 
        output_data_dict["channel_context"] = context_str
    if lang_str: 
        output_data_dict["detected_language"] = lang_str
    if url_str: 
        output_data_dict["youtube_channel"] = url_str


def _merge_duplicate_inline(existing_dict: Dict[str, Any], new_dict: Dict[str, Any]) -> None:
    """Mescla duas entradas do mesmo video_id dentro do processo de salvamento."""
    _merge_fields_inline(existing_dict, new_dict)
    if "playlists" in new_dict:
        _merge_playlists(existing_dict, new_dict["playlists"])


def _merge_playlists(existing_dict: Dict[str, Any], new_playlists_list: List[str]) -> None:
    """Une listas de playlists sem duplicar itens."""
    if "playlists" not in existing_dict:
        existing_dict["playlists"] = []
    for playlist_id_str in new_playlists_list:
        if playlist_id_str not in existing_dict["playlists"]:
            existing_dict["playlists"].append(playlist_id_str)


def _write_json_atomically(json_path: Path, output_data_dict: Dict[str, Any]) -> None:
    """
    Grava o arquivo JSON usando a técnica de 'Escrita Atômica'.
    
    Explicação para Juniores:
    1. Escrevemos em um arquivo temporário (.tmp).
    2. Se a escrita terminar com sucesso, RENOMEAMOS o temporário para o nome oficial.
    
    Por que?
    Se o computador desligar bem na hora que o Python está escrevendo no HD, o arquivo
    pode ficar cortado pela metade (corrompido). Com o arquivo temporário, se algo 
    der errado, o arquivo original continua seguro.
    """
    target_write_path: Path = _get_target_write_path(json_path)
    temp_file_path: Path = target_write_path.with_suffix(".tmp")
    
    try:
        with open(temp_file_path, "w", encoding="utf-8") as file_descriptor_obj:
            json.dump(output_data_dict, file_descriptor_obj, indent=4, ensure_ascii=False)
            
        temp_file_path.replace(target_write_path)
        _cleanup_legacy_json(json_path, target_write_path)
    except Exception as error_obj:
        print_warn(f"Erro ao salvar histórico: {error_obj}")


def _get_target_write_path(json_path: Path) -> Path:
    """Retorna o caminho de escrita, convertendo prefixos legados."""
    if json_path.name.startswith("lista_"):
        return json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    return json_path


def _cleanup_legacy_json(original_path: Path, target_path: Path) -> None:
    """Remove o arquivo legado se ele foi migrado para um novo nome."""
    if original_path != target_path and original_path.exists():
        original_path.unlink(missing_ok=True)


def filter_state_list(full_state_list: List[Dict[str, Any]], date_limit_filter_str: str) -> List[Dict[str, Any]]:
    """
    Filtra a lista de vídeos para retornar apenas os publicados a partir de uma data.
    
    Explicação para Juniores:
    Se o usuário quer ver apenas vídeos de 2024 em diante, passamos a data limite aqui.
    O filtro percorre toda a lista (usando List Comprehension) e mantém apenas os vídeos 
    cuja 'publish_date' seja maior ou igual ao limite.
    """
    if not full_state_list: 
        return []
    if not date_limit_filter_str: 
        return list(full_state_list)
    
    normalized_limit_str: str = _normalize_date_limit(date_limit_filter_str)
    return [video_dict for video_dict in full_state_list if _is_video_after_date(video_dict, normalized_limit_str)]


def _normalize_date_limit(date_limit_filter_str: str) -> str:
    """Normaliza o filtro de data usando o DateRange do yt-dlp."""
    try:
        from yt_dlp.utils import DateRange
        parsed_date_str: Optional[str] = DateRange.day(date_limit_filter_str).start
        return parsed_date_str.replace("-", "") if parsed_date_str else date_limit_filter_str
    except Exception:
        return date_limit_filter_str


def _is_video_after_date(video_dict: Dict[str, Any], date_limit_str: str) -> bool:
    """Verifica se um vídeo foi publicado após a data limite."""
    publish_date_str: str = video_dict.get("publish_date", "Desconhecida")
    if not publish_date_str or publish_date_str in ("N/A", "Desconhecida", ""): 
        return False
    return publish_date_str.replace("-", "") >= date_limit_str


def auto_migrate_legacy_files(cwd_path: Path, state_list: List[Dict[str, Any]]) -> bool:
    """
    Migra dados de arquivos de texto antigos para o formato JSON atual.
    
    Explicação para Juniores:
    Antigamente, o Escriba salvava tudo em arquivos .txt soltos. Hoje usamos JSON porque é
    mais organizado e fácil de ler via código. Esta função garante que, se o usuário
    tinha dados nos .txt antigos, eles sejam movidos automaticamente para o novo sistema.
    """
    legacy_data_tuple: Tuple[set, set, set] = _collect_legacy_ids(cwd_path)
    if not any(legacy_data_tuple): 
        return False

    updated_count_int: int = _apply_legacy_migration(state_list, legacy_data_tuple)
    _backup_legacy_files(cwd_path)
    
    if updated_count_int > 0:
        print_ok(f"Migração de arquivos legacy concluída ({updated_count_int} updates no JSON).")
    return True


def _collect_legacy_ids(cwd_path: Path) -> Tuple[set, set, set]:
    """Coleta IDs de todos os arquivos legados."""
    return (
        _read_legacy_id_file(cwd_path / "historico.txt", "youtube "),
        _read_legacy_id_file(cwd_path / "historico-info.txt", "youtube "),
        _read_legacy_nosub_file(cwd_path / "videos_sem_legenda.txt")
    )


def _apply_legacy_migration(state_list: List[Dict[str, Any]], legacy_data_tuple: Tuple[set, set, set]) -> int:
    """Aplica as flags migratórias na lista de estados."""
    history_ids_set, info_ids_set, nosub_ids_set = legacy_data_tuple
    count_int: int = 0
    for video_dict in state_list:
        video_id_str: Optional[str] = video_dict.get("video_id")
        if not video_id_str: 
            continue
        count_int += _update_flags_from_legacy(video_dict, video_id_str, history_ids_set, info_ids_set, nosub_ids_set)
    return count_int


def _update_flags_from_legacy(
    video_dict: Dict[str, Any], 
    video_id_str: str, 
    history_ids_set: set, 
    info_ids_set: set, 
    nosub_ids_set: set
) -> int:
    """Atualiza flags individuais para um vídeo a partir dos dados legados."""
    updates_int: int = 0
    mapping_list: List[Tuple[str, set]] = [
        ("subtitle_downloaded", history_ids_set), 
        ("info_downloaded", info_ids_set), 
        ("has_no_subtitle", nosub_ids_set)
    ]
    
    for flag_name_str, ids_set in mapping_list:
        if video_id_str in ids_set and not video_dict.get(flag_name_str):
            video_dict[flag_name_str] = True
            updates_int = 1
            
    return updates_int


def _backup_legacy_files(cwd_path: Path) -> None:
    """Renomeia arquivos legados para .bak."""
    legacy_files_list: List[str] = ["historico.txt", "historico-info.txt", "videos_sem_legenda.txt"]
    for file_name_str in legacy_files_list:
        file_path: Path = cwd_path / file_name_str
        if file_path.is_file(): 
            file_path.rename(file_path.with_suffix(".txt.bak"))


def _read_legacy_id_file(file_path: Path, prefix_str: str) -> set[str]:
    """Lê um arquivo de histórico legado no formato de linhas com prefixo."""
    ids_set: set = set()
    if not file_path.is_file(): 
        return ids_set
        
    with open(file_path, "r", encoding="utf-8") as file_descriptor_obj:
        for raw_line_str in file_descriptor_obj:
            clean_line_str: str = raw_line_str.strip()
            if clean_line_str.startswith(prefix_str):
                ids_set.add(clean_line_str[len(prefix_str):])
                
    return ids_set


def _read_legacy_nosub_file(file_path: Path) -> set[str]:
    """Lê o arquivo legado de vídeos sem legenda disponível."""
    ids_set: set = set()
    if not file_path.is_file(): 
        return ids_set
        
    with open(file_path, "r", encoding="utf-8") as file_descriptor_obj:
        for raw_line_str in file_descriptor_obj:
            if "watch?v=" in raw_line_str:
                video_id_str: str = raw_line_str.strip().split("watch?v=")[-1].strip()
                if video_id_str: 
                    ids_set.add(video_id_str)
                    
    return ids_set


def migrate_all_databases(cwd_path: Path) -> None:
    """Atualiza todos os bancos de dados JSON da pasta para o formato mais recente."""
    json_paths_list: List[Path] = list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json"))
    if not json_paths_list:
        print_info("Nenhum banco de dados compatível encontrado para migração.")
        return

    print_section("Migração de Banco de Dados")
    print_info(f"Verificando {len(json_paths_list)} arquivo(s) para adaptação...")
    
    migrated_count_int: int = sum(1 for json_path in json_paths_list if _migrate_single_database(json_path))

    if migrated_count_int > 0:
        print_ok(f"Migração concluída! {BOLD}{migrated_count_int}{RESET} arquivo(s) adaptados.")
    else:
        print_info("Todos os bancos de dados já estão na version mais recente.")


def _migrate_single_database(json_path: Path) -> bool:
    """Analisa e migra um único arquivo JSON para o formato atual."""
    try:
        data_dict: Dict[str, Any] = _load_existing_json_safely(json_path)
        if not data_dict: 
            return False

        migrated_fields_bool: bool = _migrate_database_fields(data_dict)
        is_legacy_name_bool: bool = json_path.name.startswith("lista_")

        if migrated_fields_bool or is_legacy_name_bool:
            print_info(f"Adaptando: {BOLD}{json_path.name}{RESET}...")
            save_channel_state_json(
                json_path, 
                data_dict.get("videos", []), 
                channel_handle_str=data_dict.get("channel_context"),
                detected_language_str=data_dict.get("detected_language"),
                youtube_channel_url_str=data_dict.get("youtube_channel")
            )
            _cleanup_legacy_migration_file(json_path, is_legacy_name_bool)
            return True
    except Exception as error_obj:
        print_err(f"Falha ao migrar {json_path.name}: {error_obj}")
        
    return False


def _migrate_database_fields(data_dict: Dict[str, Any]) -> bool:
    """Renomeia campos desatualizados no dicionário de dados."""
    if "youtube_channel" in data_dict: 
        return False
        
    field_name_str: Optional[str] = "channel" if "channel" in data_dict else ("channel_context" if "channel_context" in data_dict else None)
    if field_name_str:
        data_dict["youtube_channel"] = data_dict[field_name_str]
        return True
        
    return False


def _cleanup_legacy_migration_file(json_path: Path, is_legacy_name_bool: bool) -> None:
    """Remove arquivo original se o novo nome foi criado."""
    if not is_legacy_name_bool: 
        return
        
    new_json_path: Path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    if new_json_path.exists() and new_json_path != json_path:
        json_path.unlink()


def register_channel_in_json(json_path: Path, channel_handle_str: str) -> Tuple[bool, bool]:
    """Verifica se um canal do YouTube já foi registrado no banco de dados JSON."""
    if not channel_handle_str: 
        return False, False
    
    handle_normalized_str: str = _normalize_handle(channel_handle_str)
    data_dict: Dict[str, Any] = _load_existing_json_safely(json_path)
    
    channels_list: Any = data_dict.get("youtube_channels", [])
    if not isinstance(channels_list, list): 
        channels_list = []

    if _is_handle_registered(handle_normalized_str, channels_list):
        return False, True

    channels_list.append(handle_normalized_str)
    data_dict["youtube_channels"] = channels_list
    success_bool: bool = _atomic_json_dump(json_path, data_dict)
    
    return True, success_bool


def _normalize_handle(handle_str: str) -> str:
    """Padroniza o handle para sempre ter o prefixo @."""
    if not handle_str.startswith(("http", "@")):
        return f"@{handle_str}"
    return handle_str


def _is_handle_registered(handle_str: str, channels_list: List[str]) -> bool:
    """Verifica se um handle já está na lista de canais (case-insensitive)."""
    target_str: str = handle_str.lstrip("@").lower()
    return any(c_str.lstrip("@").lower() == target_str for c_str in channels_list)


def _atomic_json_dump(json_path: Path, data_dict: Dict[str, Any]) -> bool:
    """Realiza um dump JSON atômico e retorna sucesso."""
    temp_file_path: Path = json_path.with_suffix(".tmp")
    try:
        with open(temp_file_path, "w", encoding="utf-8") as file_descriptor_obj:
            json.dump(data_dict, file_descriptor_obj, indent=4, ensure_ascii=False)
            
        temp_file_path.replace(json_path)
        print_ok(f"Canal registrado no banco de dados.")
        return True
    except Exception as error_obj:
        print_warn(f"Falha ao persistir novo canal no JSON: {error_obj}")
        temp_file_path.unlink(missing_ok=True)
        return False

