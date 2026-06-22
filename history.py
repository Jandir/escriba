import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from utils import print_ok, print_err, print_info, print_warn, print_section, BOLD, RESET, format_date

"""
MÓDULO HISTORY: A Memória do Escriba
-----------------------------------
Este módulo funciona como o 'cérebro' persistente do projeto. Ele é responsável por:
1. Saber quais vídeos já foram processados para não gastar banda e tempo repetindo o trabalho (ETL incremental).
2. Migrar dados de versões antigas do script (que usavam arquivos .txt) para o novo formato JSON.
3. Garantir que, se o computador desligar no meio de um salvamento, o banco de dados não seja corrompido (Escrita Atômica).

Explicação para Iniciantes (Sufixos de Tipagem / Convenções Ekklezia):
Neste arquivo, todas as variáveis possuem sufixos que indicam seu tipo (ex: _str, _list, _path, _dict).
Esta é uma convenção muito útil em projetos dinâmicos (onde não usamos checagem de tipos estática rígida)
pois ajuda você, programador júnior, a saber exatamente o que está manipulando de imediato:
- `x_path` é um objeto do Pathlib.
- `x_str` é uma string clássica.
- `x_dict` é um dicionário chave-valor.
- `x_list` é uma lista indexada.
"""


def _find_legacy_databases(cwd_path: Path) -> List[Path]:
    """
    Busca arquivos JSON de bancos de dados antigos ou da versão atual no diretório.
    
    Explicação para Iniciantes:
    - O projeto evoluiu e mudou o nome dos arquivos (de 'lista_[canal].json' para 'escriba_[canal].json').
      Para que o usuário não perca seu histórico, procuramos por esses nomes antigos.
    - Usamos o método `.glob()` da biblioteca Pathlib para buscar arquivos que seguem um padrão de texto.
    - O '*' no padrão 'lista_*.json' é um caractere curinga (wildcard) que significa 'qualquer texto aqui'.
    - Ordenamos pelo mais recente (data de modificação de arquivo no disco) para garantir que
      o sistema priorize o arquivo que foi salvo por último.
    - O comando `x_path.stat().st_mtime` nos dá a data e segundo exatos em formato de 'timestamp Epoch'
      em que o arquivo foi modificado pelo sistema operacional.
    """
    patterns_list: List[str] = ["escriba_*.json", "lista_*.json"]
    found_paths_list: List[Path] = []
    
    for pattern_str in patterns_list:
        found_paths_list.extend(list(cwd_path.glob(pattern_str)))
    
    # Lambda é uma função anônima de uma única linha. Aqui ela diz ao 'sorted': 
    # "Ordene esta lista de caminhos comparando o tempo de modificação do arquivo".
    return sorted(found_paths_list, key=lambda x_path: x_path.stat().st_mtime if x_path.exists() else 0, reverse=True)


def get_latest_json_path(cwd_path: Path) -> Path:
    """
    Decide qual arquivo .json é o banco de dados oficial desta pasta de execução.
    Prioriza o nome novo 'escriba_[nome_da_pasta].json'.
    
    Explicação para Iniciantes:
    Buscamos um arquivo que represente a pasta atual. Se ela se chama 'casais',
    o arquivo oficial será 'escriba_casais.json'. Caso ele não exista,
    procuramos se existe algum outro legado disponível para reuso antes de criar um do zero.
    """
    official_json_path: Path = cwd_path / f"escriba_{cwd_path.name}.json"
    
    if official_json_path.exists():
        return official_json_path
        
    legacy_json_paths_list: List[Path] = _find_legacy_databases(cwd_path)
    # Retorna o primeiro legado encontrado (que é o mais recente devido à ordenação no find)
    # ou, se não houver nenhum, retorna o caminho do arquivo oficial que será criado futuramente.
    return legacy_json_paths_list[0] if legacy_json_paths_list else official_json_path


def _get_history_search_dirs(cwd_path: Path) -> List[Path]:
    """
    Retorna uma lista de diretórios onde o histórico local deve ser pesquisado
    (incluindo a pasta atual e subpastas válidas do canal).
    
    Explicação para Iniciantes:
    Filtramos pastas de controle como '.git' (onde o Git salva o histórico do repositório),
    '.venv' (ambiente virtual do Python) e '__pycache__' (bytecode compilado do Python).
    Não faz sentido varrer essas pastas porque elas contêm arquivos binários do sistema
    e varrê-las tornaria o processo incrivelmente lento.
    """
    try:
        ignore_names_set: set[str] = {".git", ".venv", "__pycache__"}
        # List Comprehension: Cria uma lista filtrando pastas no disco que não estejam no conjunto ignorado.
        return [cwd_path] + [d_path for d_path in cwd_path.iterdir() if d_path.is_dir() and d_path.name not in ignore_names_set]
    except Exception:
        # Se ocorrer erro de permissão ao ler alguma pasta, retorna apenas a pasta principal (cwd)
        return [cwd_path]


def load_all_local_history(cwd_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Lê todos os dados de vídeos já processados que encontrar na pasta.
    
    Explicação para Iniciantes:
    - O 'history_map_dict' é um dicionário em que a CHAVE é o ID do vídeo (ex: dQw4w9WgXcQ)
      e o VALOR é um objeto de metadados daquele vídeo.
      Usar um mapa/dicionário chaveado por ID permite buscas instantâneas durante a execução.
      Em termos de ciência da computação, dizemos que a busca tem complexidade O(1) (Tempo Constante),
      enquanto buscar em uma lista exigiria percorrer item por item (O(N) - Tempo Linear).
    """
    history_map_dict: Dict[str, Dict[str, Any]] = {}
    blacklist_names_set: set[str] = {"package.json", "package-lock.json", "requirements.json", "env.json"}
    
    # Regex para identificar IDs de vídeo em arquivos .info.json (gerados pelo yt-dlp)
    # O padrão `(?=\.info\.json$)` é um 'lookahead positivo'. Ele garante que o nome do arquivo
    # termina com '.info.json', mas não inclui essa extensão no texto capturado pelo grupo de correspondência.
    video_id_regex_obj: re.Pattern = re.compile(r"([A-Za-z0-9_-]{11}|\d+)(?=\.info\.json$)")
    
    for directory_path in _get_history_search_dirs(cwd_path):
        _scan_directory_for_history(directory_path, blacklist_names_set, video_id_regex_obj, history_map_dict)
        
    return history_map_dict


def _scan_directory_for_history(
    directory_path: Path, 
    blacklist_names_set: set[str], 
    vid_regex_obj: re.Pattern, 
    history_map_dict: Dict[str, Dict[str, Any]]
) -> None:
    """
    Varre um único diretório procurando arquivos JSON com dados de vídeos.
    Dividido em duas etapas para garantir integridade e performance de leitura.
    """
    try:
        json_files_list: List[Path] = list(directory_path.glob("*.json"))
        
        # 1. Primeiro processamos os bancos de dados mestre (escriba_ ou lista_)
        # Isso garante que history_map_dict já contenha a maior base de dados conhecida em memória rápida.
        for json_file_path in json_files_list:
            if json_file_path.name in blacklist_names_set: 
                continue
            if json_file_path.name.startswith(("escriba_", "lista_")):
                _parse_master_json(json_file_path, history_map_dict)
                
        # 2. Depois processamos os arquivos avulsos (.info.json),
        # pulando os que já estão completos no banco de dados mestre para acelerar drasticamente a leitura do disco.
        for json_file_path in json_files_list:
            if json_file_path.name in blacklist_names_set: 
                continue
            if json_file_path.name.startswith(("escriba_", "lista_")):
                continue
                
            match_obj: Optional[re.Match] = vid_regex_obj.search(json_file_path.name)
            if match_obj:
                video_id_str: str = match_obj.group(1)
                existing_data: Optional[Dict[str, Any]] = history_map_dict.get(video_id_str)
                
                # Otimização crucial: se já temos o vídeo com data e a flag 'info_downloaded',
                # não precisamos abrir e decodificar o arquivo .info.json individual do disco (I/O lento).
                if existing_data and existing_data.get("info_downloaded") and existing_data.get("publish_date") not in ["N/A", "Desconhecida", ""]:
                    continue
                    
                _parse_video_metadata_json(json_file_path, video_id_str, history_map_dict)
    except Exception:
        # Falhas de leitura individuais de arquivos corrompidos não devem travar o pipeline.
        pass


def _parse_master_json(json_file_path: Path, history_map_dict: Dict[str, Dict[str, Any]]) -> None:
    """Lê o banco de dados principal e preenche o mapa de histórico."""
    try:
        with open(json_file_path, "r", encoding="utf-8") as file_descriptor_obj:
            json_data_any: Any = json.load(file_descriptor_obj)
            video_list: Any = _get_video_list_from_json(json_data_any)
            
            if isinstance(video_list, list):
                _populate_history_from_list(video_list, history_map_dict)
    except Exception:
        pass


def _get_video_list_from_json(json_data_any: Any) -> Any:
    """
    Extrai a lista de vídeos de um dicionário estructurado (versão moderna do Escriba)
    ou retorna a própria lista se o JSON for legado (antigo formato de lista pura).
    """
    if isinstance(json_data_any, dict) and "videos" in json_data_any:
        return json_data_any["videos"]
    return json_data_any


def _populate_history_from_list(video_list: List[Dict[str, Any]], history_map_dict: Dict[str, Dict[str, Any]]) -> None:
    """Itera sobre uma lista de vídeos extraída do JSON e os mescla no mapa de histórico."""
    for video_dict in video_list:
        video_id_str: Optional[str] = video_dict.get("video_id") or video_dict.get("id")
        if video_id_str:
            _merge_video_data(history_map_dict, video_id_str, video_dict)


def _parse_video_metadata_json(
    json_file_path: Path, 
    video_id_str: str, 
    history_map_dict: Dict[str, Dict[str, Any]]
) -> None:
    """Extrai os metadados brutos de um arquivo .info.json individual e os salva."""
    try:
        with open(json_file_path, "r", encoding="utf-8") as file_descriptor_obj:
            metadata_dict: Any = json.load(file_descriptor_obj)
            if not isinstance(metadata_dict, dict):
                return
            
            upload_date_str: str = _extract_upload_date(metadata_dict)
            # Prioridade de ID do vídeo: Campo 'id' do JSON -> 'display_id' -> o ID extraído do nome do arquivo
            real_video_id_str: str = metadata_dict.get("id") or metadata_dict.get("display_id") or video_id_str
            
            video_data_dict: Dict[str, Any] = _build_video_metadata_dict(metadata_dict, real_video_id_str, upload_date_str)
            _merge_video_data(history_map_dict, real_video_id_str, video_data_dict)
    except Exception:
        pass


def _extract_upload_date(metadata_dict: Dict[str, Any]) -> str:
    """
    Extrai e formata a data de upload de um dicionário de metadados.
    Retorna no formato padronizado YYYY-MM-DD.
    """
    raw_date_any: Any = metadata_dict.get("upload_date") or metadata_dict.get("publish_date") or metadata_dict.get("date")
    return format_date(raw_date_any)


def _build_video_metadata_dict(metadata_dict: Dict[str, Any], video_id_str: str, upload_date_str: str) -> Dict[str, Any]:
    """
    Constrói um dicionário padronizado do vídeo contendo as chaves que o Escriba precisa.
    Normaliza diferenças entre campos que o YouTube e o Vimeo geram no arquivo info.json.
    """
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
    Combina dados de um vídeo vindos de múltiplos arquivos diferentes sem perder informações.
    
    Explicação para Iniciantes (O Processo de Merge):
    - Se o vídeo nunca foi visto antes, simplesmente fazemos uma cópia dos novos dados e adicionamos ao mapa.
    - Se o vídeo já existe na base de dados, não podemos sobrescrever cega ou destrutivamente.
      Usamos a função `_merge_fields_inline` para mesclar apenas os dados vazios ou incompletos.
    """
    if video_id_str not in history_map_dict:
        history_map_dict[video_id_str] = new_data_dict.copy()
        return
    _merge_fields_inline(history_map_dict[video_id_str], new_data_dict)


def _merge_fields_inline(existing_data_dict: Dict[str, Any], new_data_dict: Dict[str, Any]) -> None:
    """
    Mescla campos individuais de dados de vídeo alterando a estrutura 'in-place' (direto na memória).
    
    Explicação para Iniciantes:
    - O termo 'in-place' significa que não criamos um novo dicionário na memória,
      nós modificamos diretamente o dicionário que já existe dentro do mapa `history_map_dict`.
    - Isso economiza memória e processamento.
    - Para as chaves booleanas (verdadeiro/falso), aplicamos uma lógica de disjunção:
      Se pelo menos um dos registros disser que a legenda foi baixada (`True`), o registro final será `True`.
    """
    _merge_text_field(existing_data_dict, new_data_dict, "publish_date", ["N/A", "Desconhecida", ""])
    _merge_text_field(existing_data_dict, new_data_dict, "title", ["N/A", "", "Avulso"])
    
    # Flags Booleanas: Se o novo dado for True, definimos o campo como True no original
    for flag_name_str in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
        if new_data_dict.get(flag_name_str):
            existing_data_dict[flag_name_str] = True
            
    if new_data_dict.get("source_channel") and not existing_data_dict.get("source_channel"):
        existing_data_dict["source_channel"] = new_data_dict["source_channel"]


def _merge_text_field(existing_dict: Dict[str, Any], new_dict: Dict[str, Any], field_name_str: str, placeholders_list: List[str]) -> None:
    """Mescla um campo de texto se o novo valor for válido e o valor existente for genérico/placeholder."""
    new_value_any: Any = new_dict.get(field_name_str)
    if new_value_any and new_value_any not in placeholders_list:
        if not existing_dict.get(field_name_str) or existing_dict[field_name_str] in placeholders_list:
            existing_dict[field_name_str] = new_value_any


def save_channel_state_json(
    json_path: Optional[Path], 
    videos_list: List[Dict[str, Any]], 
    channel_handle_str: Optional[str] = None, 
    detected_language_str: Optional[str] = None, 
    channel_url_str: Optional[str] = None,
    youtube_channel_url_str: Optional[str] = None
) -> None:
    """
    Orquestra a escrita segura do banco de dados JSON do canal de volta ao disco rígido.
    
    Explicação para Iniciantes:
    1. Removemos registros duplicados na lista de vídeos antes de salvar.
    2. Lemos o arquivo existente de forma segura para não perder configurações paralelas.
    3. Montamos o dicionário unificado e o gravamos de forma 'atômica'.
    """
    if youtube_channel_url_str is not None:
        channel_url_str = youtube_channel_url_str
    if not json_path: 
        return
    
    final_videos_list: List[Dict[str, Any]] = _deduplicate_videos(videos_list)
    existing_data_dict: Dict[str, Any] = _load_existing_json_safely(json_path)
    
    output_data_dict: Dict[str, Any] = {
        "folder_repository": json_path.stem.replace("escriba_", ""),
        "videos": final_videos_list
    }
    
    _populate_output_metadata(output_data_dict, existing_data_dict, channel_handle_str, detected_language_str, channel_url_str)
    _write_json_atomically(json_path, output_data_dict)


def _deduplicate_videos(videos_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicatas indesejadas da lista base, mesclando dados duplicados por ID de vídeo."""
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
    """Carrega o JSON existente e evita falhas de sintaxe se o arquivo estiver corrompido ou vazio."""
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
    """Preenche metadados de controle do canal no dicionário final de salvamento, preservando listas de canais."""
    # Preservar listas de canais para YouTube e Vimeo salvos de execuções anteriores
    for key_str in ["youtube_channels", "vimeo_channels"]:
        existing_list = existing_dict.get(key_str, [])
        if isinstance(existing_list, list) and existing_list:
            output_data_dict[key_str] = existing_list
            
    # Identifica o provedor de vídeo com base na URL
    provider_str = "vimeo" if url_str and "vimeo.com" in url_str else "youtube"
    channels_key_str = f"{provider_str}_channels"
    url_key_str = f"{provider_str}_channel"
    
    context_str: Optional[str] = handle_str or existing_dict.get("channel_context")
    if context_str: 
        output_data_dict["channel_context"] = context_str
    
    lang_val_str: Optional[str] = lang_str or existing_dict.get("detected_language")
    if lang_val_str: 
        output_data_dict["detected_language"] = lang_val_str
        
    final_url_str: Optional[str] = url_str or existing_dict.get(url_key_str) or existing_dict.get("youtube_channel") or existing_dict.get("channel")
    if final_url_str: 
        output_data_dict[url_key_str] = final_url_str


def _merge_duplicate_inline(existing_dict: Dict[str, Any], new_dict: Dict[str, Any]) -> None:
    """Mescla duas chaves de dicionários duplicados in-place durante o salvamento."""
    _merge_fields_inline(existing_dict, new_dict)
    if "playlists" in new_dict:
        _merge_playlists(existing_dict, new_dict["playlists"])


def _merge_playlists(existing_dict: Dict[str, Any], new_playlists_list: List[str]) -> None:
    """Mescla listas de playlists sem duplicar registros."""
    if "playlists" not in existing_dict:
        existing_dict["playlists"] = []
    for playlist_id_str in new_playlists_list:
        if playlist_id_str not in existing_dict["playlists"]:
            existing_dict["playlists"].append(playlist_id_str)


def _safe_replace(temp_path: Path, target_path: Path, max_retries: int = 5, delay: float = 0.2) -> None:
    """Substitui o arquivo de destino pelo temporário de forma segura com retentativas no Windows."""
    import time
    for attempt in range(1, max_retries + 1):
        try:
            temp_path.replace(target_path)
            return
        except (PermissionError, OSError) as e:
            if attempt == max_retries:
                raise e
            time.sleep(delay)


def _write_json_atomically(json_path: Path, output_data_dict: Dict[str, Any]) -> None:
    """
    Grava o arquivo JSON usando a técnica clássica de 'Escrita Atômica'.
    
    Explicação para Iniciantes:
    Q: O que é Escrita Atômica e por que precisamos dela?
    A: Se usarmos 'open(arquivo, "w")' diretamente, o Python limpa o arquivo no disco
       e começa a escrever os novos caracteres aos poucos. Se o seu computador desligar
       ou acabar a bateria bem no meio desse processo (que dura milissegundos), o arquivo
       original fica danificado (corrompido/metade vazio), perdendo todo o banco de dados.
    
    A Solução:
    1. Escrevemos em um arquivo temporário ao lado do original (`.tmp`).
    2. Somente se o arquivo for escrito por completo e com sucesso no HD, usamos o método `.replace()`
       do sistema operacional para substituir o arquivo antigo pelo novo de forma instantânea.
    3. Em sistemas operacionais modernos, a substituição de ponteiros de arquivo é uma operação
       'atômica' (ou acontece 100% ou não acontece nada, sem meio termo).
    """
    target_write_path: Path = _get_target_write_path(json_path)
    temp_file_path: Path = target_write_path.with_suffix(".tmp")
    
    try:
        # Grava os dados completos no arquivo temporário
        with open(temp_file_path, "w", encoding="utf-8") as file_descriptor_obj:
            json.dump(output_data_dict, file_descriptor_obj, indent=4, ensure_ascii=False)
            
        # Faz a troca atômica no sistema de arquivos
        _safe_replace(temp_file_path, target_write_path)
        _cleanup_legacy_json(json_path, target_write_path)
    except Exception as error_obj:
        print_warn(f"Erro ao salvar histórico de forma segura: {error_obj}")


def _get_target_write_path(json_path: Path) -> Path:
    """Normaliza o caminho de escrita trocando os prefixos legados 'lista_' pelo oficial 'escriba_'."""
    if json_path.name.startswith("lista_"):
        return json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    return json_path


def _cleanup_legacy_json(original_path: Path, target_path: Path) -> None:
    """Remove o banco de dados antigo se o arquivo foi migrado com sucesso para um novo nome."""
    if original_path != target_path and original_path.exists():
        original_path.unlink(missing_ok=True)


def filter_state_list(full_state_list: List[Dict[str, Any]], date_limit_filter_str: str) -> List[Dict[str, Any]]:
    """
    Filtra a lista de vídeos cadastrados mantendo apenas os publicados a partir de uma data limite.
    
    Explicação para Iniciantes:
    - Se passarmos a flag `--date 20260101`, ignoramos vídeos antigos anteriores a 2026.
    - Usamos list comprehension para filtrar de forma performática.
    - Chamamos a função de comparação `_is_video_after_date`.
    """
    if not full_state_list: 
        return []
    if not date_limit_filter_str: 
        return list(full_state_list)
    
    # Converte datas como "20260101" para formato de comparação simples
    # removendo hífens das strings de data para comparação numérica de strings.
    normalized_limit_str: str = _normalize_date_limit(date_limit_filter_str)
    return [video_dict for video_dict in full_state_list if _is_video_after_date(video_dict, normalized_limit_str)]


def _normalize_date_limit(date_limit_filter_str: str) -> str:
    """Normaliza a string de filtro de data utilizando o parser DateRange interno do yt-dlp."""
    try:
        from yt_dlp.utils import DateRange
        parsed_date_str: Optional[str] = DateRange.day(date_limit_filter_str).start
        return parsed_date_str.replace("-", "") if parsed_date_str else date_limit_filter_str
    except Exception:
        return date_limit_filter_str


def _is_video_after_date(video_dict: Dict[str, Any], date_limit_str: str) -> bool:
    """
    Retorna verdadeiro se a data de publicação do vídeo for igual ou posterior ao limite numérico.
    Exemplo: "2026-03-16" virá "20260316" e se o limite for "20260101", "20260316" >= "20260101" é True.
    """
    publish_date_str: str = video_dict.get("publish_date", "Desconhecida")
    if not publish_date_str or publish_date_str in ("N/A", "Desconhecida", ""): 
        return False
    return publish_date_str.replace("-", "") >= date_limit_str


def auto_migrate_legacy_files(cwd_path: Path, state_list: List[Dict[str, Any]]) -> bool:
    """
    Lê os arquivos legados do Escriba (.txt de histórico) e injeta no banco de dados JSON moderno.
    
    Explicação para Iniciantes (Evolução de Arquitetura):
    Nas primeiras versões, o Escriba anotava em arquivos de texto comuns como "historico.txt"
    quais vídeos ele já havia baixado. Essa abordagem era ruim porque ler arquivos de texto avulsos
    é lento e difícil de manter metadados ricos (como título, durações e canais).
    Hoje usamos um banco de dados centralizado em formato JSON. Esta função lê os .txt antigos
    para que o usuário não tenha que rebaixar canais inteiros de novo, gerando retrocompatibilidade automática.
    """
    legacy_data_tuple: Tuple[set, set, set] = _collect_legacy_ids(cwd_path)
    # Se não encontrar nenhum arquivo legado, encerra sem fazer nada
    if not any(legacy_data_tuple): 
        return False

    updated_count_int: int = _apply_legacy_migration(state_list, legacy_data_tuple)
    _backup_legacy_files(cwd_path)
    
    if updated_count_int > 0:
        print_ok(f"Migração de arquivos legacy concluída ({updated_count_int} updates no JSON).")
    return True


def _collect_legacy_ids(cwd_path: Path) -> Tuple[set, set, set]:
    """Busca e extrai IDs dos arquivos de texto legados."""
    return (
        _read_legacy_id_file(cwd_path / "historico.txt", "youtube "),
        _read_legacy_id_file(cwd_path / "historico-info.txt", "youtube "),
        _read_legacy_nosub_file(cwd_path / "videos_sem_legenda.txt")
    )


def _apply_legacy_migration(state_list: List[Dict[str, Any]], legacy_data_tuple: Tuple[set, set, set]) -> int:
    """Atualiza as flags correspondentes na lista de estados de vídeos."""
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
    """Define flags True para chaves que estavam nos arquivos legados e incrementa o contador."""
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
    """Renomeia os arquivos legados de texto para o sufixo '.bak' (backup) para que não sejam relidos."""
    legacy_files_list: List[str] = ["historico.txt", "historico-info.txt", "videos_sem_legenda.txt"]
    for file_name_str in legacy_files_list:
        file_path: Path = cwd_path / file_name_str
        if file_path.is_file(): 
            file_path.rename(file_path.with_suffix(".txt.bak"))


def _read_legacy_id_file(file_path: Path, prefix_str: str) -> set[str]:
    """Lê um arquivo legado de texto e isola a string do ID do vídeo (removendo prefixos de provedor)."""
    ids_set: set = set()
    if not file_path.is_file(): 
        return ids_set
        
    with open(file_path, "r", encoding="utf-8") as file_descriptor_obj:
        for raw_line_str in file_descriptor_obj:
            clean_line_str: str = raw_line_str.strip()
            if clean_line_str.startswith(prefix_str):
                # Isola o ID após o espaço do prefixo (ex: "youtube ID_VIDEO" -> "ID_VIDEO")
                ids_set.add(clean_line_str[len(prefix_str):])
                
    return ids_set


def _read_legacy_nosub_file(file_path: Path) -> set[str]:
    """Lê o arquivo legado que lista links de vídeos sem legenda e extrai seus IDs de vídeo."""
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
    """Executa a varredura completa de atualização estrutural em todos os JSONs da pasta."""
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
        print_info("Todos os bancos de dados já estão na versão mais recente.")


def _migrate_single_database(json_path: Path) -> bool:
    """
    Analisa e migra um único arquivo JSON para o formato estrutural mais atual do Escriba.
    Garante também a importação de estados consolidados do Lexis (processed_ids).
    """
    try:
        data_dict: Dict[str, Any] = _load_existing_json_safely(json_path)
        if not data_dict: 
            return False

        migrated_fields_bool: bool = _migrate_database_fields(data_dict)
        is_legacy_name_bool: bool = json_path.name.startswith("lista_")

        # Verifica se precisamos migrar a estrutura do lexis_state (processed_ids para os vídeos)
        has_legacy_lexis_state_bool: bool = False
        if "lexis_state" in data_dict and isinstance(data_dict["lexis_state"], dict):
            if "processed_ids" in data_dict["lexis_state"]:
                has_legacy_lexis_state_bool = True

        if migrated_fields_bool or is_legacy_name_bool or has_legacy_lexis_state_bool:
            print_info(f"Adaptando: {BOLD}{json_path.name}{RESET}...")
            
            # Carrega o estado antigo do Lexis antes que save_channel_state_json remova chaves desnecessárias
            state_dict: Optional[Dict[str, Any]] = None
            if has_legacy_lexis_state_bool:
                from lexis import load_state
                state_dict = load_state(str(json_path))
                
            # Salva o arquivo no formato novo
            save_channel_state_json(
                json_path, 
                data_dict.get("videos", []), 
                channel_handle_str=data_dict.get("channel_context"),
                detected_language_str=data_dict.get("detected_language"),
                youtube_channel_url_str=data_dict.get("youtube_channel")
            )
            
            # Grava o estado consolidado do Lexis na nova modelagem de dados do vídeo
            if state_dict is not None:
                from lexis import save_state
                save_state(str(json_path), state_dict)
                
            # Deleta arquivos antigos físicos se o nome mudou para 'escriba_'
            _cleanup_legacy_migration_file(json_path, is_legacy_name_bool)
            return True
    except Exception as error_obj:
        print_err(f"Falha ao migrar {json_path.name}: {error_obj}")
        
    return False


def _migrate_database_fields(data_dict: Dict[str, Any]) -> bool:
    """Renomeia chaves desatualizadas do JSON (ex: 'channel' para 'youtube_channel')."""
    if "youtube_channel" in data_dict: 
        return False
        
    field_name_str: Optional[str] = "channel" if "channel" in data_dict else ("channel_context" if "channel_context" in data_dict else None)
    if field_name_str:
        data_dict["youtube_channel"] = data_dict[field_name_str]
        return True
        
    return False


def _cleanup_legacy_migration_file(json_path: Path, is_legacy_name_bool: bool) -> None:
    """Remove fisicamente o arquivo original antigo após a criação do arquivo com prefixo 'escriba_'."""
    if not is_legacy_name_bool: 
        return
        
    new_json_path: Path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))
    if new_json_path.exists() and new_json_path != json_path:
        json_path.unlink()


def register_channel_in_json(json_path: Path, handle_str: str, provider_str: str = "youtube") -> Tuple[bool, bool]:
    """
    Registra dinamicamente um handle de canal na lista de metadados do JSON se ainda não estiver cadastrado.
    Isso ajuda a unificar canais que compartilham a mesma pasta.
    """
    if not handle_str: 
        return False, False
        
    final_handle = handle_str
    if provider_str == "youtube":
        final_handle = _normalize_handle(handle_str)
        
    data_dict: Dict[str, Any] = _load_existing_json_safely(json_path)
    
    channels_key_str = f"{provider_str}_channels"
    channels_list: List[str] = data_dict.get(channels_key_str, [])
    
    if not isinstance(channels_list, list): 
        channels_list = []
        
    if _is_handle_registered(final_handle, channels_list):
        return False, True
        
    channels_list.append(final_handle)
    data_dict[channels_key_str] = channels_list
    success_bool = _atomic_json_dump(json_path, data_dict)
    
    return True, success_bool


def _normalize_handle(handle_str: str) -> str:
    """Garante que o identificador/handle do canal no YouTube possua sempre o prefixo '@' (ex: @Canal)."""
    if not handle_str.startswith(("http", "@")):
        return f"@{handle_str}"
    return handle_str


def _is_handle_registered(handle_str: str, channels_list: List[str]) -> bool:
    """Checa se o canal já foi cadastrado na lista (fazendo comparação case-insensitive)."""
    target_str: str = handle_str.lstrip("@").lower()
    return any(c_str.lstrip("@").lower() == target_str for c_str in channels_list)


def _atomic_json_dump(json_path: Path, data_dict: Dict[str, Any]) -> bool:
    """Executa a escrita atômica do JSON e retorna sucesso (True) ou falha (False)."""
    temp_file_path: Path = json_path.with_suffix(".tmp")
    try:
        with open(temp_file_path, "w", encoding="utf-8") as file_descriptor_obj:
            json.dump(data_dict, file_descriptor_obj, indent=4, ensure_ascii=False)
            
        _safe_replace(temp_file_path, json_path)
        print_ok(f"Canal registrado no banco de dados.")
        return True
    except Exception as error_obj:
        print_warn(f"Falha ao persistir novo canal no JSON: {error_obj}")
        temp_file_path.unlink(missing_ok=True)
        return False
