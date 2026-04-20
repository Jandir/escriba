import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from utils import print_ok, print_err, print_info, print_warn, print_section, BOLD, RESET


def get_latest_json_path(cwd_path: Path) -> Path:
    """
    Descobre qual arquivo JSON usar como banco de dados desta pasta.

    O Escriba sempre tenta usar o arquivo "oficial", que segue o padrão:
        escriba_<NomeDaPasta>.json
    Por exemplo, se você está em uma pasta chamada "Filosofia", o banco
    esperado é "escriba_Filosofia.json".

    Mas e se esse arquivo ainda não existir? Isso pode acontecer em duas situações:
      1. É a primeira vez que o Escriba roda nessa pasta (banco ainda não foi criado).
      2. A pasta tem arquivos antigos com nomes diferentes (formato legado).

    Quando o oficial não existe, a função busca arquivos com padrões antigos
    como "escriba_*.json" ou "lista_*.json", e retorna o mais recente deles.
    Se nenhum for encontrado, retorna o caminho do oficial (que será criado depois).

    Args:
        cwd_path: O diretório de trabalho atual (a pasta do canal).

    Returns:
        O Path do banco de dados a ser usado.
    """
    folder_name: str = cwd_path.name
    official_path: Path = cwd_path / f"escriba_{folder_name}.json"

    # Se o arquivo oficial existe, perfeito — usamos ele diretamente
    if official_path.exists():
        return official_path

    # Caso contrário, pesquisamos por arquivos no formato legado.
    # sorted(..., reverse=True) ordena do mais recente para o mais antigo
    # para que legacies[0] seja sempre o arquivo mais atualizado disponível.
    legacies: List[Path] = sorted(
        list(cwd_path.glob("escriba_*.json")) + list(cwd_path.glob("lista_*.json")),
        key=lambda x: x.stat().st_mtime if x.exists() else 0,
        reverse=True
    )

    # Se achou algum legado, usa ele. Se não achou nada, retorna o caminho oficial
    # (que não existe ainda, mas será criado quando salvarmos pela primeira vez).
    return legacies[0] if legacies else official_path


def load_all_local_history(cwd_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Lê todos os dados de vídeos já processados que existem na pasta local.

    Por que isso existe?
    O Escriba pode ter vídeos registrados em múltiplos lugares:
      - No banco principal (escriba_*.json)
      - Em arquivos .info.json avulsos gerados pelo yt-dlp
      - Em subpastas (ex: archive/)

    Esta função varre tudo isso e consolida em um único dicionário chamado
    history_map, onde a chave é o video_id (ex: "dQw4w9WgXcQ") e o valor
    é um dicionário com os metadados daquele vídeo.

    O objetivo é ter uma visão completa do que já foi baixado, para evitar
    re-baixar o que já existe.

    Args:
        cwd_path: O diretório de trabalho atual (a pasta do canal).

    Returns:
        Um dicionário {video_id: dados_do_video} com todo o histórico encontrado.
    """
    history_map: Dict[str, Dict[str, Any]] = {}

    # Lista de arquivos JSON que não são bancos de dados de vídeos e devem ser ignorados
    blacklist: set = {"package.json", "package-lock.json", "requirements.json", "env.json"}

    # Regex para encontrar IDs de vídeo do YouTube: exatamente 11 caracteres alfanuméricos + _ e -
    # Como o arquivo é no padrão [NomeDaPasta]-[VideoID].info.json,
    # procuramos o ID posicionado no final do nome do arquivo.
    video_id_regex: re.Pattern = re.compile(r"([A-Za-z0-9_-]{11})(?=\.info\.json$)")

    # Montamos a lista de diretórios para varrer: a pasta atual + subpastas relevantes.
    # Ignoramos pastas de ferramentas que nunca terão dados de vídeos (.git, .venv, __pycache__).
    try:
        search_dirs: List[Path] = [cwd_path] + [
            d for d in cwd_path.iterdir()
            if d.is_dir() and d.name not in (".git", ".venv", "__pycache__")
        ]
    except Exception:
        # Se não conseguir listar subpastas (ex: problema de permissão), usamos só a pasta atual
        search_dirs = [cwd_path]

    for directory in search_dirs:
        _scan_directory_for_history(directory, blacklist, video_id_regex, history_map)

    return history_map


def _scan_directory_for_history(
    directory: Path,
    blacklist: set,
    video_id_regex: re.Pattern,
    history_map: Dict[str, Dict[str, Any]]
) -> None:
    """
    Varre um único diretório procurando arquivos JSON com dados de vídeos.

    Esta função foi separada de load_all_local_history() para manter o código
    organizado (cada função faz uma coisa só — princípio de responsabilidade única).

    Ela classifica cada arquivo JSON encontrado em dois tipos:
      1. Banco principal (começa com "escriba_" ou "lista_") → lido por _parse_master_json()
      2. Metadados avulsos (nome contém um ID de vídeo) → lido por _parse_video_metadata_json()

    Args:
        directory:       A pasta a ser varrida.
        blacklist:       Nomes de arquivos a ignorar completamente.
        video_id_regex:  Padrão regex para detectar IDs de vídeo em nomes de arquivo.
        history_map:     Dicionário acumulador que será preenchido com os dados encontrados.
    """
    try:
        for jf in directory.glob("*.json"):
            # Ignora arquivos que não têm nada a ver com vídeos do YouTube
            if jf.name in blacklist:
                continue

            # Banco de dados principal → processa como lista de vídeos estruturada
            if jf.name.startswith(("escriba_", "lista_")):
                _parse_master_json(jf, history_map)
                continue

            # Arquivo avulso (ex: "titulo-do-video-dQw4w9WgXcQ.info.json")
            # Se o nome contém um ID de vídeo de 11 caracteres, processamos como metadados
            match = video_id_regex.search(jf.name)
            if match:
                _parse_video_metadata_json(jf, match.group(1), history_map)
    except Exception:
        # Se algum arquivo causar erro (corrompido, sem permissão etc.), simplesmente
        # ignoramos e continuamos — um arquivo com problema não deve parar tudo.
        pass


def _parse_master_json(jf: Path, history_map: Dict[str, Dict[str, Any]]) -> None:
    """
    Lê o banco de dados principal (escriba_*.json ou lista_*.json) e adiciona
    cada vídeo encontrado ao history_map.

    O banco principal pode estar em dois formatos:
      - Formato moderno: {"videos": [...], "folder_repository": "...", ...}
      - Formato legado: diretamente uma lista [...] de objetos de vídeo

    Por isso verificamos se json_data é um dicionário com chave "videos"
    ou se é diretamente uma lista.

    Args:
        jf:           Caminho do arquivo JSON do banco principal.
        history_map:  Dicionário acumulador a ser preenchido.
    """
    try:
        with open(jf, "r", encoding="utf-8") as fd:
            json_data = json.load(fd)

            # Suporte aos dois formatos: moderno (dict com "videos") e legado (lista pura)
            v_list = json_data["videos"] if isinstance(json_data, dict) and "videos" in json_data else json_data

            if isinstance(v_list, list):
                for v in v_list:
                    # Cada vídeo pode ter o ID na chave "video_id" (moderno) ou "id" (legado)
                    vid_id = v.get("video_id") or v.get("id")
                    if vid_id:
                        _merge_video_data(history_map, vid_id, v)
    except Exception:
        # Arquivo corrompido ou com formato inesperado → ignoramos silenciosamente
        pass


def _parse_video_metadata_json(jf: Path, vid_id: str, history_map: Dict[str, Dict[str, Any]]) -> None:
    """
    Lê um arquivo .info.json avulso gerado pelo yt-dlp e extrai os metadados do vídeo.

    Quando o yt-dlp baixa um vídeo, ele pode gerar um arquivo .info.json com
    dezenas de campos sobre aquele vídeo (título, canal, data de upload etc.).
    Esta função lê esse arquivo e extrai apenas o que o Escriba precisa.

    Uma particularidade: o yt-dlp salva a data de upload no formato YYYYMMDD
    (ex: "20230415"), mas o Escriba usa o formato YYYY-MM-DD (ex: "2023-04-15").
    Por isso fazemos a conversão se a data tiver exatamente 8 dígitos.

    Args:
        jf:           Caminho do arquivo .info.json avulso.
        vid_id:       O ID do vídeo extraído do nome do arquivo.
        history_map:  Dicionário acumulador a ser preenchido.
    """
    try:
        with open(jf, "r", encoding="utf-8") as fd:
            meta = json.load(fd)

            # .info.json sempre deve ser um dicionário — se não for, ignoramos
            if not isinstance(meta, dict):
                return

            # O campo de data de upload pode ter nomes diferentes dependendo
            # da versão do yt-dlp. Tentamos os três mais comuns em ordem de preferência.
            upload_date = meta.get("upload_date") or meta.get("publish_date") or meta.get("date")

            # Converte "20230415" → "2023-04-15" para padronização interna
            if upload_date and len(str(upload_date)) == 8 and str(upload_date).isdigit():
                s_date = str(upload_date)
                upload_date = f"{s_date[:4]}-{s_date[4:6]}-{s_date[6:]}"

            # O ID real do vídeo presente dentro do JSON dita a verdade
            real_vid_id = meta.get("id") or meta.get("display_id") or vid_id

            # Montamos o dicionário de dados do vídeo.
            # Usamos "or" para tentar múltiplos nomes de campo — o yt-dlp muda
            # os nomes entre versões, então cobrir alternativas é uma boa prática.
            v_data = {
                "video_id": real_vid_id,
                "title": meta.get("title") or meta.get("fulltitle") or meta.get("video_title") or "Avulso",
                "publish_date": upload_date or "N/A",
                "subtitle_downloaded": meta.get("subtitle_downloaded", False),
                "info_downloaded": True if upload_date else False,  # Só marcamos como baixado se temos a data
                "channel_id": meta.get("channel_id") or meta.get("uploader_id"),
                "uploader": meta.get("uploader") or meta.get("channel"),
                "uploader_id": meta.get("uploader_id") or meta.get("channel_id")
            }
            _merge_video_data(history_map, real_vid_id, v_data)
    except Exception:
        # Arquivo corrompido ou inesperado → ignoramos para não travar o scan
        pass


def _merge_video_data(
    history_map: Dict[str, Dict[str, Any]],
    vid_id: str,
    new_data: Dict[str, Any]
) -> None:
    """
    Combina dados de um vídeo de múltiplas fontes sem perder informações.

    Por que isso é necessário?
    O mesmo vídeo pode aparecer em vários arquivos (banco principal + .info.json avulso).
    Cada fonte pode ter informações diferentes ou mais completas que a outra.

    Estratégia de merge (dados mais ricos ganham):
      - Campos de texto (título, data): o valor não-vazio substitui o "N/A" ou vazio.
      - Flags booleanas (subtitle_downloaded etc.): uma vez True, sempre True.
        Isso garante que um vídeo marcado como baixado nunca "regride" para não-baixado.
      - source_channel: preenchido uma vez e nunca sobrescrito.

    Args:
        history_map:  O dicionário acumulador de histórico.
        vid_id:       O ID do vídeo a ser mesclado.
        new_data:     Os novos dados encontrados para esse vídeo.
    """
    # Se o vídeo ainda não está no mapa, simplesmente adicionamos uma cópia dos dados
    if vid_id not in history_map:
        history_map[vid_id] = new_data.copy()
        return

    # Vídeo já existe: mesclamos com prioridade para dados mais ricos
    existing = history_map[vid_id]

    # Data de publicação: atualiza apenas se o valor atual é inválido ("N/A") e o novo é válido
    if new_data.get("publish_date") and new_data["publish_date"] != "N/A":
        if not existing.get("publish_date") or existing["publish_date"] == "N/A":
            existing["publish_date"] = new_data["publish_date"]

    # Título: atualiza apenas se o atual é um placeholder e o novo é real
    if new_data.get("title") and new_data["title"] not in ("N/A", "", "Avulso"):
        if not existing.get("title") or existing["title"] in ("N/A", "", "Avulso"):
            existing["title"] = new_data["title"]

    # Flags booleanas: uma vez marcadas como True, nunca voltam para False.
    # Isso evita que um arquivo menos completo "apague" o histórico de um download concluído.
    for flag in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
        if new_data.get(flag):
            existing[flag] = True

    # Canal de origem: preenchido apenas uma vez (quem veio primeiro fica)
    if new_data.get("source_channel") and not existing.get("source_channel"):
        existing["source_channel"] = new_data["source_channel"]


def save_channel_state_json(
    json_path: Optional[Path],
    videos_list: List[Dict[str, Any]],
    channel_handle: Optional[str] = None,
    detected_language: Optional[str] = None,
    youtube_channel: Optional[str] = None
) -> None:
    """
    Salva o banco de dados JSON do canal no disco de forma segura.

    Esta é a função de persistência central do Escriba. Ela é chamada sempre
    que o estado dos vídeos muda (novo download, novo metadado etc.).

    O processo de salvamento tem três etapas:
      1. Deduplicação: remove entradas duplicadas do mesmo video_id, mesclando-as.
      2. Montagem: constrói o dicionário final a ser salvo (com vídeos + metadados do canal).
      3. Escrita atômica: salva primeiro em .tmp, depois renomeia — assim nunca
         corrompemos o arquivo original caso algo dê errado no meio do processo.

    Args:
        json_path:         Onde salvar o arquivo JSON.
        videos_list:       A lista de vídeos com seus estados atuais.
        channel_handle:    Handle do canal (ex: "@Filosofia") para preservar no banco.
        detected_language: Idioma detectado das legendas (ex: "pt") para cache.
        youtube_channel:   URL do canal no YouTube para referência futura.
    """
    # Se não temos um caminho definido, não há nada para salvar
    if not json_path:
        return

    # Etapa 1: Deduplicação — consolida entradas com o mesmo video_id em uma só.
    # Isso pode acontecer se a mesma URL for processada mais de uma vez.
    dedup_map: Dict[str, Dict[str, Any]] = {}
    for v in videos_list:
        vid_id = v.get("video_id") or v.get("id")
        if not vid_id:
            continue  # Entrada sem ID é inválida e descartável
        if vid_id not in dedup_map:
            dedup_map[vid_id] = v.copy()
        else:
            # Já existe uma entrada para este ID → mesclamos em vez de sobrescrever
            _merge_duplicate_inline(dedup_map[vid_id], v)

    final_videos = list(dedup_map.values())

    # Lemos o JSON existente para recuperar campos que não chegam como argumento.
    # IMPORTANTE: lemos TODO o conteúdo atual de uma vez para poder preservar
    # campos que esta função não gerencia diretamente — especialmente youtube_channels.
    # Se fizéssemos leituras separadas por campo, correríamos o risco de sobrescrever
    # a lista de canais toda vez que alguém chamasse save_channel_state_json(),
    # pois o output_data seria montado do zero sem ela.
    existing_json_data: Dict[str, Any] = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                existing_json_data = json.load(f)
                if not isinstance(existing_json_data, dict):
                    existing_json_data = {}
        except Exception:
            pass  # JSON corrompido ou inacessível → começamos do zero, sem drama

    # Recupera channel_handle do arquivo caso não tenha sido informado como argumento
    if not channel_handle:
        channel_handle = existing_json_data.get("channel_context")

    # Etapa 2: Montar o dicionário final que será gravado no arquivo.
    # Começamos preservando todos os campos do JSON atual que não são gerenciados
    # diretamente aqui (ex: youtube_channels, campos customizados futuros).
    # Isso garante que nenhum dado seja perdido silenciosamente entre salvamentos.
    output_data: Dict[str, Any] = {
        "folder_repository": json_path.stem.replace("escriba_", ""),  # Ex: "escriba_Filosofia" → "Filosofia"
        "videos": final_videos
    }

    # Preserva a lista acumulada de canais registrados nesta pasta.
    # Sem isso, cada chamada a save_channel_state_json() apagaria a lista,
    # e o usuário perderia os canais cadastrados anteriormente via register_channel_in_json().
    existing_channels: List[str] = existing_json_data.get("youtube_channels", [])
    if isinstance(existing_channels, list) and existing_channels:
        output_data["youtube_channels"] = existing_channels

    # Campos opcionais: só incluímos se tiverem valor definido
    if channel_handle:
        output_data["channel_context"] = channel_handle
    if detected_language:
        output_data["detected_language"] = detected_language
    if youtube_channel:
        output_data["youtube_channel"] = youtube_channel

    # Etapa 3: Escrita segura em disco (função auxiliar abaixo)
    _write_json_atomically(json_path, output_data)


def _merge_duplicate_inline(existing: Dict[str, Any], new: Dict[str, Any]) -> None:
    """
    Mescla duas entradas do mesmo video_id dentro do processo de salvamento.

    Esta função é chamada quando detectamos dois registros com o mesmo ID
    durante a deduplicação em save_channel_state_json().

    As regras de mesclagem são as mesmas de _merge_video_data():
      - Flags booleanas acumulam (True prevalece sobre False)
      - Campos de texto: valor real/completo substitui placeholder
      - Playlists: unimos as listas sem duplicar

    Args:
        existing: O registro já existente no dedup_map (será modificado in-place).
        new:      O registro duplicado recém-encontrado.
    """
    # Flags de estado: uma vez True, não voltam — garantia de progresso incremental
    for flag in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
        if new.get(flag):
            existing[flag] = True

    # Data de publicação: prefere o valor real sobre "N/A"
    if new.get("publish_date") and new["publish_date"] != "N/A":
        if not existing.get("publish_date") or existing["publish_date"] == "N/A":
            existing["publish_date"] = new["publish_date"]

    # Título: prefere o valor real sobre placeholders
    if new.get("title") and new["title"] not in ("N/A", "Avulso", ""):
        if not existing.get("title") or existing["title"] in ("N/A", "Avulso", ""):
            existing["title"] = new["title"]

    # Playlists: une as duas listas sem duplicar itens
    if "playlists" in new:
        if "playlists" not in existing:
            existing["playlists"] = []
        for p in new["playlists"]:
            if p not in existing["playlists"]:
                existing["playlists"].append(p)


def _write_json_atomically(json_path: Path, output_data: Dict[str, Any]) -> None:
    """
    Salva um dicionário em disco como JSON de forma segura (escrita atômica).

    O que é escrita atômica?
    Em vez de escrever direto no arquivo final, escrevemos em um arquivo
    temporário (.tmp). Só depois que a escrita terminar com sucesso é que
    renomeamos o .tmp para o nome definitivo.

    Por que isso importa?
    Se o computador travar, a luz acabar ou o processo for interrompido
    no meio da escrita, o arquivo final nunca fica pela metade ou corrompido.
    O .tmp é descartado e o arquivo original permanece intacto.

    Também cuida da migração de nome: arquivos antigos no formato "lista_*.json"
    são salvos com o novo nome "escriba_*.json" e o arquivo antigo é removido.

    Args:
        json_path:    Caminho-alvo final do arquivo JSON.
        output_data:  O dicionário Python a ser serializado como JSON.
    """
    # Migração de nome legado: "lista_Canal.json" → "escriba_Canal.json"
    target_write_path = json_path
    if json_path.name.startswith("lista_"):
        target_write_path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))

    # Cria o arquivo temporário com o mesmo nome mas extensão .tmp
    temp_path = target_write_path.with_suffix(".tmp")
    try:
        # Escrevemos no .tmp (se algo der errado aqui, o .json original não é afetado)
        with open(temp_path, "w", encoding="utf-8") as file_descriptor:
            json.dump(output_data, file_descriptor, indent=4, ensure_ascii=False)

        # Substituição atômica: renomeia .tmp → .json de uma vez só
        temp_path.replace(target_write_path)

        # Se era um arquivo legado "lista_", apaga o original agora que o novo já exists
        if json_path.name.startswith("lista_") and json_path.exists():
            json_path.unlink(missing_ok=True)
    except Exception as e:
        print_warn(f"Ignorando erro ao salvar JSON de state: {e}")


def filter_state_list(
    full_state_list: List[Dict[str, Any]],
    date_limit_filter: str
) -> List[Dict[str, Any]]:
    """
    Filtra a lista de vídeos para retornar apenas os publicados a partir de uma data.

    Útil quando o usuário passa --date para processar apenas vídeos recentes.
    Por exemplo, com --date "2024-01-01", só vídeos de 2024 em diante são processados.

    O filtro aceita vários formatos de data graças ao parser do yt-dlp (DateRange),
    que reconhece formatos como "20240101", "2024-01-01", "last_month" etc.

    Se date_limit_filter for vazio ou None, retorna a lista completa sem filtro.

    Args:
        full_state_list:   Lista completa de vídeos do banco de dados.
        date_limit_filter: String com a data mínima (ex: "2024-01-01") ou vazia.

    Returns:
        Lista de vídeos filtrada (ou a lista original se nenhum filtro for aplicado).
    """
    # Lista vazia → nada para filtrar
    if not full_state_list:
        return []

    if date_limit_filter:
        # Tentamos usar o parser de datas do próprio yt-dlp para normalizar a entrada.
        # Isso deixa o filtro mais robusto e compatível com os formatos que o usuário usa.
        try:
            from yt_dlp.utils import DateRange
            parsed_date_str = DateRange.day(date_limit_filter).start
            if parsed_date_str:
                # Converte "2024-01-01" → "20240101" para comparação por string
                date_limit_filter = parsed_date_str.replace("-", "")
        except Exception:
            pass  # Se o parser falhar, usamos a string original como está

        filtered_list = []
        for v_dict in full_state_list:
            d_str = v_dict.get("publish_date", "N/A")
            if d_str and d_str != "N/A":
                # Remove hífens para comparação uniforme: "2024-01-15" → "20240115"
                # Comparação por string funciona corretamente para datas no formato YYYYMMDD
                d_str_clean = d_str.replace("-", "")
                if d_str_clean >= date_limit_filter:
                    filtered_list.append(v_dict)
        return filtered_list

    # Sem filtro de data → retorna cópia da lista completa
    return list(full_state_list)


def auto_migrate_legacy_files(cwd_path: Path, state_list: List[Dict[str, Any]]) -> bool:
    """
    Migra dados de arquivos de texto antigos para o formato JSON atual.

    O Escriba usava arquivos .txt simples para registrar o histórico:
      - historico.txt         → IDs de vídeos com legenda baixada
      - historico-info.txt    → IDs de vídeos com metadados baixados
      - videos_sem_legenda.txt → IDs de vídeos sem legenda disponível

    Esses formatos foram substituídos pelo banco JSON, que é muito mais rico e
    fácil de manipular. Esta função faz a transição:
      1. Lê os IDs dos arquivos antigos
      2. Atualiza as flags correspondentes na state_list (JSON)
      3. Renomeia os .txt para .bak (como backup, sem apagar)

    Args:
        cwd_path:    O diretório de trabalho atual.
        state_list:  A lista de vídeos carregada do banco JSON (será modificada in-place).

    Returns:
        True se havia arquivos legados para migrar, False se já estava tudo atualizado.
    """
    # Lemos os IDs de cada arquivo legado. Se o arquivo não existir, retornamos um set vazio.
    historico_ids: set = _read_legacy_id_file(cwd_path / "historico.txt", prefix="youtube ")
    info_ids: set = _read_legacy_id_file(cwd_path / "historico-info.txt", prefix="youtube ")
    no_sub_ids: set = _read_legacy_nosub_file(cwd_path / "videos_sem_legenda.txt")

    # Se nenhum arquivo legado foi encontrado, não há nada para migrar
    if not historico_ids and not info_ids and not no_sub_ids:
        return False

    migrated_count: int = 0
    for item in state_list:
        video_id = item.get("video_id")
        if not video_id:
            continue

        # Para cada vídeo nos arquivos antigos, marcamos a flag correspondente no JSON
        if video_id in historico_ids and not item.get("subtitle_downloaded"):
            item["subtitle_downloaded"] = True
            migrated_count += 1
        if video_id in info_ids and not item.get("info_downloaded"):
            item["info_downloaded"] = True
            migrated_count += 1
        if video_id in no_sub_ids and not item.get("has_no_subtitle"):
            item["has_no_subtitle"] = True
            migrated_count += 1

    # Renomeia os arquivos legados para .bak — preservamos como backup, não apagamos
    for legacy_path in [
        cwd_path / "historico.txt",
        cwd_path / "historico-info.txt",
        cwd_path / "videos_sem_legenda.txt"
    ]:
        if legacy_path.is_file():
            legacy_path.rename(legacy_path.with_suffix(".txt.bak"))

    if migrated_count > 0:
        print_ok(f"Migração de arquivos legacy concluída ({migrated_count} updates no JSON).")
    return True


def _read_legacy_id_file(path: Path, prefix: str) -> set:
    """
    Lê um arquivo de histórico legado no formato de linhas com prefixo.

    O formato antigo era simples: cada linha tinha "youtube <ID_DO_VIDEO>".
    Exemplo de conteúdo do historico.txt:
        youtube dQw4w9WgXcQ
        youtube xvFZjo5PgG0

    Esta função extrai apenas os IDs (sem o prefixo) e os retorna como um set.
    Usar set em vez de list garante que não haja IDs duplicados.

    Args:
        path:    Caminho do arquivo legado.
        prefix:  O prefixo a ser removido de cada linha (ex: "youtube ").

    Returns:
        Um conjunto (set) com os IDs encontrados. Vazio se o arquivo não existir.
    """
    ids: set = set()
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Só processa linhas que começam com o prefixo esperado
                if line.startswith(prefix):
                    ids.add(line[len(prefix):])  # Remove o prefixo e guarda só o ID
    return ids


def _read_legacy_nosub_file(path: Path) -> set:
    """
    Lê o arquivo legado de vídeos sem legenda disponível.

    O formato era uma URL por linha, como:
        https://www.youtube.com/watch?v=dQw4w9WgXcQ

    Extraímos o ID do vídeo da URL (a parte após "watch?v=").

    Args:
        path: Caminho do arquivo videos_sem_legenda.txt legado.

    Returns:
        Um conjunto (set) com os IDs dos vídeos sem legenda. Vazio se não existir.
    """
    ids: set = set()
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                # Só processa linhas que contêm uma URL do YouTube com watch?v=
                if "watch?v=" in line:
                    vid = line.strip().split("watch?v=")[-1].strip()
                    if vid:
                        ids.add(vid)
    return ids


def migrate_all_databases(cwd_path: Path) -> None:
    """
    Atualiza todos os bancos de dados JSON da pasta para o formato mais recente.

    Com o tempo, o formato do JSON do Escriba evoluiu. Esta função detecta
    bancos de dados desatualizados e os adapta automaticamente, sem perda de dados.

    Mudanças tratadas aqui:
      - Campos renomeados: "channel" → "youtube_channel"
      - Nomes de arquivo legados: "lista_*.json" → "escriba_*.json"

    Quando usar? Rode "python escriba.py --migrate" na pasta do canal.

    Args:
        cwd_path: O diretório de trabalho atual onde os JSONs estão.
    """
    # Busca todos os bancos de dados nesta pasta (formatos atual e legado)
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
    """
    Analisa e migra um único arquivo JSON para o formato atual.

    Verifica dois tipos de desatualização:
      1. Campos antigos: "channel" ou "channel_context" precisam virar "youtube_channel"
      2. Nome legado: "lista_*.json" precisa virar "escriba_*.json"

    Se qualquer um deles for detectado, o arquivo é resalvo no novo formato.

    Args:
        json_path: Caminho do arquivo JSON a ser verificado.

    Returns:
        True se o arquivo foi modificado (havia algo para migrar).
        False se já estava atualizado ou se ocorreu um erro.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # JSONs de estado sempre devem ser dicionários — listas são formato inválido
        if not isinstance(data, dict):
            return False

        # Verifica se precisa renomear campos desatualizados
        needs_migration = False
        if "youtube_channel" not in data:
            if "channel" in data:
                # Campo antigo "channel" → novo padrão "youtube_channel"
                data["youtube_channel"] = data["channel"]
                needs_migration = True
            elif "channel_context" in data:
                # Campo intermediário "channel_context" → novo padrão "youtube_channel"
                data["youtube_channel"] = data["channel_context"]
                needs_migration = True

        # Verifica se o nome do arquivo segue o padrão legado "lista_"
        is_legacy_name = json_path.name.startswith("lista_")

        if needs_migration or is_legacy_name:
            print_info(f"Adaptando: {BOLD}{json_path.name}{RESET}...")
            # Resalvamos usando save_channel_state_json(), que já cuida da
            # renomeação de arquivo e da escrita atômica
            save_channel_state_json(
                json_path,
                data.get("videos", []),
                channel_handle=data.get("channel_context"),
                detected_language=data.get("detected_language"),
                youtube_channel=data.get("youtube_channel")
            )
            # Se era um arquivo legado e o novo já existe, removemos o antigo
            if is_legacy_name:
                new_path = json_path.with_name(json_path.name.replace("lista_", "escriba_"))
                if new_path.exists() and new_path != json_path:
                    json_path.unlink()
            return True
    except Exception as e:
        print_err(f"Falha ao migrar {json_path.name}: {e}")
    return False


def register_channel_in_json(json_path: Path, channel_handle: str) -> Tuple[bool, bool]:
    """
    Verifica se um canal do YouTube já foi registrado no banco de dados JSON
    desta pasta. Se não estiver, adiciona e salva o arquivo.

    Por que isso importa?
    O Escriba mantém uma lista de canais em cada pasta de trabalho.
    Quando o usuário digita um @Canal pela primeira vez, precisamos:
      1. Saber se ele já está cadastrado (para não duplicar)
      2. Registrá-lo no JSON se for novidade
      3. Processar apenas ele, sem re-baixar os outros canais da pasta

    Args:
        json_path:       Caminho do arquivo JSON desta pasta (ex: escriba_MinhaPasta.json)
        channel_handle:  O canal informado pelo usuário (ex: "@CanalXYZ" ou URL completa)

    Returns:
        Uma tupla com dois booleanos: (is_new, was_registered)
        - is_new:          True quando o canal não existia antes → é uma novidade
        - was_registered:  True quando o banco foi atualizado com sucesso
    """
    # Proteção: se o usuário passou uma string vazia, não há nada para fazer
    if not channel_handle:
        return False, False

    # Padronizamos o handle para sempre ter o prefixo @.
    # Isso evita cadastros duplicados como "MeuCanal" e "@MeuCanal".
    # URLs completas (http...) são mantidas como estão — o YouTube aceita os dois formatos.
    handle_normalized = channel_handle
    if not handle_normalized.startswith(("http", "@")):
        handle_normalized = f"@{handle_normalized}"

    # Lemos o JSON para saber quais canais já estão cadastrados.
    # Se o arquivo não existir ainda, começamos com um dicionário vazio
    # e ele será criado do zero ao salvar.
    data: Dict[str, Any] = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as fd:
                data = json.load(fd)
        except Exception as e:
            # Se o arquivo está corrompido ou inacessível, avisamos e paramos.
            # É mais seguro abortar do que sobrescrever dados que não conseguimos ler.
            print_warn(f"Não foi possível ler {json_path.name} para verificar canais: {e}")
            return False, False

    # Garantia defensiva: o JSON pode ter sido salvo de forma inesperada
    # (ex: como lista em vez de dicionário). Se isso acontecer, recomeçamos do zero.
    if not isinstance(data, dict):
        data = {}

    # Recupera a lista de canais já cadastrados, ou uma lista vazia se for a primeira vez.
    channels: List[str] = data.get("youtube_channels", [])
    if not isinstance(channels, list):
        channels = []  # Proteção extra caso o campo exista mas não seja uma lista

    # Comparamos removendo o @ e convertendo para minúsculas.
    # Assim, "@MeuCanal", "meucanal" e "@meucanal" são tratados como o mesmo canal,
    # evitando duplicatas causadas por diferenças de digitação.
    handle_bare = handle_normalized.lstrip("@").lower()
    for existing in channels:
        existing_bare = existing.lstrip("@").lower()
        if existing_bare == handle_bare:
            # Canal já existe no banco → não é novidade, não precisa salvar nada
            return False, True

    # Se chegamos até aqui, o canal é novo para esta pasta.
    # Adicionamos à lista e atualizamos o dicionário principal.
    channels.append(handle_normalized)
    data["youtube_channels"] = channels

    # Escrevemos em um arquivo temporário (.tmp) primeiro, só depois renomeamos.
    # Por quê? Se o programa travar ou der erro no meio da escrita,
    # o arquivo original continua intacto — o .tmp é descartado sozinho.
    # Essa técnica se chama "escrita atômica" e é uma boa prática de segurança de dados.
    temp_path = json_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as fd:
            json.dump(data, fd, indent=4, ensure_ascii=False)
        temp_path.replace(json_path)  # Substituição atômica: tudo ou nada
        print_ok(f"Canal {BOLD}{handle_normalized}{RESET} registrado no banco de dados.")
        return True, True
    except Exception as e:
        # Algo deu errado ao salvar. Removemos o .tmp para não deixar lixo no disco.
        print_warn(f"Falha ao persistir novo canal no JSON: {e}")
        temp_path.unlink(missing_ok=True)  # missing_ok=True: não dá erro se o .tmp nem chegou a ser criado
        return True, False  # is_new=True porque o canal é novo, mas was_registered=False (falhou ao salvar)
