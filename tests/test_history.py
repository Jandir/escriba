"""
Testes automatizados para history.py
=====================================

Cada função do módulo history.py tem ao menos um teste aqui.
Os testes usam tmp_path (fixture do pytest) para criar arquivos
temporários que são apagados automaticamente após cada teste.

Para rodar: pytest tests/test_history.py -v
"""

import json
import sys
import time
from pathlib import Path

import pytest

# Garante que o diretório raiz do projeto está no path de importação
sys.path.insert(0, str(Path(__file__).parent.parent))

from history import (
    get_latest_json_path,
    load_all_local_history,
    save_channel_state_json,
    filter_state_list,
    register_channel_in_json,
    auto_migrate_legacy_files,
    migrate_all_databases,
    _merge_video_data,
    _merge_duplicate_inline,
    _parse_master_json,
    _parse_video_metadata_json,
    _read_legacy_id_file,
    _read_legacy_nosub_file,
)


# ─── Fixtures reutilizáveis ────────────────────────────────────────────────────

@pytest.fixture
def sample_videos():
    """Lista de vídeos de exemplo reutilizável nos testes."""
    return [
        {"video_id": "AAAbbbCCC11", "title": "Vídeo Um", "publish_date": "2024-01-01"},
        {"video_id": "ZZZyyyXXX22", "title": "Vídeo Dois", "publish_date": "2023-06-15"},
    ]


# ─── get_latest_json_path ─────────────────────────────────────────────────────

class TestGetLatestJsonPath:
    """
    Testa a detecção correta do arquivo JSON de banco de dados.
    O padrão oficial é escriba_<NomeDaPasta>.json.
    """

    def test_retorna_oficial_quando_existe(self, tmp_path):
        """Se o arquivo oficial existe, deve ser retornado diretamente."""
        oficial = tmp_path / f"escriba_{tmp_path.name}.json"
        oficial.write_text("{}")
        assert get_latest_json_path(tmp_path) == oficial

    def test_retorna_legado_quando_oficial_ausente(self, tmp_path):
        """Sem o oficial, deve retornar o legado mais recente (escriba_*)."""
        legado = tmp_path / "escriba_canalantigo.json"
        legado.write_text("{}")
        result = get_latest_json_path(tmp_path)
        assert result == legado

    def test_retorna_lista_legada_quando_unica_opcao(self, tmp_path):
        """Deve aceitar o formato ainda mais antigo lista_*.json."""
        lista = tmp_path / "lista_foo.json"
        lista.write_text("{}")
        result = get_latest_json_path(tmp_path)
        assert result == lista

    def test_retorna_mais_recente_entre_multiplos_legados(self, tmp_path):
        """Com múltiplos legados, deve retornar o modificado mais recentemente."""
        old = tmp_path / "escriba_antigo.json"
        old.write_text("{}")
        time.sleep(0.01)  # Garante diferença de timestamp
        new = tmp_path / "escriba_novo.json"
        new.write_text("{}")
        result = get_latest_json_path(tmp_path)
        assert result == new

    def test_retorna_caminho_oficial_quando_nenhum_json_existe(self, tmp_path):
        """Se não existir nenhum JSON, retorna o caminho do oficial (que ainda será criado)."""
        result = get_latest_json_path(tmp_path)
        assert result.name == f"escriba_{tmp_path.name}.json"
        assert not result.exists()  # Ainda não foi criado


# ─── _merge_video_data ────────────────────────────────────────────────────────

class TestMergeVideoData:
    """
    Testa as regras de merge entre dados de um mesmo vídeo vindos de fontes diferentes.
    """

    def test_adiciona_nova_entrada(self):
        """Vídeo novo deve ser inserido diretamente no mapa."""
        history = {}
        _merge_video_data(history, "vid001", {"title": "Título", "publish_date": "2024-01-01"})
        assert "vid001" in history
        assert history["vid001"]["title"] == "Título"

    def test_titulo_real_substitui_placeholder(self):
        """'Avulso' e '' devem ser substituídos por um título real."""
        history = {"v": {"title": "Avulso", "publish_date": "N/A"}}
        _merge_video_data(history, "v", {"title": "Título Real", "publish_date": "2024-03-01"})
        assert history["v"]["title"] == "Título Real"

    def test_titulo_real_nao_e_sobrescrito_por_placeholder(self):
        """Um título já válido não deve ser sobrescrito por 'Avulso'."""
        history = {"v": {"title": "Título Real", "publish_date": "2024-01-01"}}
        _merge_video_data(history, "v", {"title": "Avulso"})
        assert history["v"]["title"] == "Título Real"

    def test_data_real_substitui_na(self):
        """Uma data válida deve substituir 'N/A'."""
        history = {"v": {"publish_date": "N/A"}}
        _merge_video_data(history, "v", {"publish_date": "2024-05-10"})
        assert history["v"]["publish_date"] == "2024-05-10"

    def test_flag_true_nao_e_revertida(self):
        """Uma flag booleana True jamais deve voltar para False."""
        history = {"v": {"subtitle_downloaded": True}}
        _merge_video_data(history, "v", {"subtitle_downloaded": False})
        assert history["v"]["subtitle_downloaded"] is True

    def test_flags_acumulam_progresso(self):
        """Flags False devem ser atualizadas para True quando a nova fonte traz True."""
        history = {"v": {"subtitle_downloaded": False, "info_downloaded": False}}
        _merge_video_data(history, "v", {"subtitle_downloaded": True, "info_downloaded": True})
        assert history["v"]["subtitle_downloaded"] is True
        assert history["v"]["info_downloaded"] is True

    def test_source_channel_preenchido_uma_vez(self):
        """source_channel deve ser preenchido na primeira ocorrência e nunca sobrescrito."""
        history = {"v": {"source_channel": "@CanalA"}}
        _merge_video_data(history, "v", {"source_channel": "@CanalB"})
        assert history["v"]["source_channel"] == "@CanalA"


# ─── _merge_duplicate_inline ──────────────────────────────────────────────────

class TestMergeDuplicateInline:
    """
    Testa a mesclagem de entradas duplicadas durante o salvamento do JSON.
    """

    def test_playlists_sao_unidas_sem_duplicar(self):
        existing = {"playlists": ["PL001"]}
        new = {"playlists": ["PL001", "PL002"]}
        _merge_duplicate_inline(existing, new)
        assert existing["playlists"] == ["PL001", "PL002"]

    def test_playlists_criadas_se_ausentes(self):
        existing = {}
        new = {"playlists": ["PL999"]}
        _merge_duplicate_inline(existing, new)
        assert "playlists" in existing
        assert "PL999" in existing["playlists"]

    def test_flag_subtitle_downloaded_acumula(self):
        existing = {"subtitle_downloaded": False}
        _merge_duplicate_inline(existing, {"subtitle_downloaded": True})
        assert existing["subtitle_downloaded"] is True


# ─── _parse_master_json ───────────────────────────────────────────────────────

class TestParseMasterJson:
    """
    Testa a leitura de bancos de dados principais (formato moderno e legado).
    """

    def test_le_formato_moderno(self, tmp_path):
        """Formato moderno: dict com chave 'videos'."""
        jf = tmp_path / "escriba_test.json"
        jf.write_text(json.dumps({"videos": [{"video_id": "V001", "title": "Aula"}]}))
        history_map = {}
        _parse_master_json(jf, history_map)
        assert "V001" in history_map

    def test_le_formato_legado_lista_pura(self, tmp_path):
        """Formato legado: lista direta de vídeos sem wrapper."""
        jf = tmp_path / "lista_old.json"
        jf.write_text(json.dumps([{"id": "V002", "title": "Palestra"}]))
        history_map = {}
        _parse_master_json(jf, history_map)
        assert "V002" in history_map

    def test_ignora_arquivo_corrompido(self, tmp_path):
        """JSON inválido não deve lançar exceção — apenas ignorado."""
        jf = tmp_path / "escriba_bad.json"
        jf.write_text("ISSO NAO EH JSON {{{")
        history_map = {}
        _parse_master_json(jf, history_map)  # Não deve lançar
        assert history_map == {}


# ─── _parse_video_metadata_json ───────────────────────────────────────────────

class TestParseVideoMetadataJson:
    """
    Testa a extração de metadados de .info.json avulsos gerados pelo yt-dlp.
    """

    def test_converte_data_yyyymmdd(self, tmp_path):
        """Data no formato 20240115 deve ser convertida para 2024-01-15."""
        jf = tmp_path / "video-AbCdEfGhIjK.info.json"
        jf.write_text(json.dumps({"title": "Vídeo X", "upload_date": "20240115"}))
        history_map = {}
        _parse_video_metadata_json(jf, "AbCdEfGhIjK", history_map)
        assert history_map["AbCdEfGhIjK"]["publish_date"] == "2024-01-15"

    def test_usa_fulltitle_como_fallback(self, tmp_path):
        """Se não houver 'title', deve usar 'fulltitle'."""
        jf = tmp_path / "video-AbCdEfGhIjK.info.json"
        jf.write_text(json.dumps({"fulltitle": "Título Completo", "upload_date": "20240101"}))
        history_map = {}
        _parse_video_metadata_json(jf, "AbCdEfGhIjK", history_map)
        assert history_map["AbCdEfGhIjK"]["title"] == "Título Completo"

    def test_ignora_nao_dict(self, tmp_path):
        """Se o arquivo contiver uma lista em vez de dict, deve ser ignorado."""
        jf = tmp_path / "video-AbCdEfGhIjK.info.json"
        jf.write_text("[]")
        history_map = {}
        _parse_video_metadata_json(jf, "AbCdEfGhIjK", history_map)
        assert "AbCdEfGhIjK" not in history_map


# ─── save_channel_state_json ──────────────────────────────────────────────────

class TestSaveChannelStateJson:
    """
    Testa o salvamento do banco de dados — incluindo deduplicação,
    preservação de youtube_channels e escrita atômica.
    """

    def test_cria_arquivo_json_valido(self, tmp_path, sample_videos):
        """O arquivo salvo deve ser JSON válido com a chave 'videos'."""
        json_path = tmp_path / "escriba_test.json"
        save_channel_state_json(json_path, sample_videos)
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "videos" in data
        assert len(data["videos"]) == 2

    def test_salva_detected_language(self, tmp_path):
        """Campo detected_language deve estar presente quando informado."""
        json_path = tmp_path / "escriba_test.json"
        save_channel_state_json(json_path, [], detected_language="pt")
        data = json.loads(json_path.read_text())
        assert data.get("detected_language") == "pt"

    def test_deduplica_videos_com_mesmo_id(self, tmp_path):
        """Dois registros com o mesmo video_id devem ser mesclados em um só."""
        videos = [
            {"video_id": "duplo", "title": "Avulso", "subtitle_downloaded": False},
            {"video_id": "duplo", "title": "Título Real", "subtitle_downloaded": True},
        ]
        json_path = tmp_path / "escriba_dup.json"
        save_channel_state_json(json_path, videos)
        data = json.loads(json_path.read_text())
        assert len(data["videos"]) == 1
        assert data["videos"][0]["title"] == "Título Real"
        assert data["videos"][0]["subtitle_downloaded"] is True

    def test_preserva_youtube_channels_existente(self, tmp_path):
        """
        REGRESSÃO: save_channel_state_json não deve apagar youtube_channels
        que já estão no arquivo. Este foi o bug relatado pelo usuário.
        """
        json_path = tmp_path / "escriba_multi.json"

        # Simula: usuário rodou com @CanalNovo primeiro e ele foi registrado
        json_path.write_text(json.dumps({
            "youtube_channels": ["@CanalNovo"],
            "videos": []
        }))

        # Agora process_videos() de @CanalOriginal chama save_channel_state_json()
        # Esse save NÃO deve apagar @CanalNovo da lista
        save_channel_state_json(json_path, [], youtube_channel="https://youtube.com/@CanalOriginal")

        data = json.loads(json_path.read_text())
        assert "youtube_channels" in data
        assert "@CanalNovo" in data["youtube_channels"], (
            "BUG: save_channel_state_json apagou @CanalNovo da lista youtube_channels!"
        )

    def test_preserva_multiplos_canais_apos_saves_sequenciais(self, tmp_path):
        """
        Simula o fluxo completo: dois canais registrados + dois saves sequenciais.
        Ambos devem permanecer no JSON ao final.
        """
        json_path = tmp_path / "escriba_seq.json"

        # Registra dois canais
        json_path.write_text(json.dumps({
            "youtube_channels": ["@CanalA", "@CanalB"],
            "videos": []
        }))

        # Primeiro save (processando @CanalA)
        save_channel_state_json(json_path, [{"video_id": "v1", "title": "A"}],
                                youtube_channel="https://youtube.com/@CanalA")
        data = json.loads(json_path.read_text())
        assert "@CanalA" in data["youtube_channels"]
        assert "@CanalB" in data["youtube_channels"]

        # Segundo save (processando @CanalB)
        save_channel_state_json(json_path, [{"video_id": "v2", "title": "B"}],
                                youtube_channel="https://youtube.com/@CanalB")
        data = json.loads(json_path.read_text())
        assert "@CanalA" in data["youtube_channels"]
        assert "@CanalB" in data["youtube_channels"]
        assert len(data["videos"]) == 1  # Cada save traz apenas os vídeos do seu canal

    def test_noop_quando_json_path_e_none(self):
        """Não deve lançar exceção quando json_path é None."""
        save_channel_state_json(None, [])  # Não deve explodir


# ─── register_channel_in_json ─────────────────────────────────────────────────

class TestRegisterChannelInJson:
    """
    Testa o registro de novos canais no banco de dados.
    Cobre detecção de canal novo, idempotência e normalização de handle.
    """

    def test_registra_canal_novo_em_json_existente(self, tmp_path):
        """Canal não cadastrado deve ser adicionado e is_new=True retornado."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"youtube_channels": ["@CanalA"], "videos": []}))

        is_new, registered = register_channel_in_json(json_path, "@CanalB")

        assert is_new is True
        assert registered is True
        data = json.loads(json_path.read_text())
        assert "@CanalB" in data["youtube_channels"]

    def test_canal_ja_existente_nao_e_duplicado(self, tmp_path):
        """Canal já cadastrado deve retornar is_new=False sem modificar o arquivo."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"youtube_channels": ["@CanalA"], "videos": []}))

        is_new, registered = register_channel_in_json(json_path, "@CanalA")

        assert is_new is False
        data = json.loads(json_path.read_text())
        assert data["youtube_channels"].count("@CanalA") == 1  # Não duplicou

    def test_comparacao_case_insensitive(self, tmp_path):
        """@MeuCanal e @meucanal devem ser tratados como o mesmo canal."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"youtube_channels": ["@MeuCanal"], "videos": []}))

        is_new, _ = register_channel_in_json(json_path, "@meucanal")

        assert is_new is False

    def test_normaliza_handle_sem_arroba(self, tmp_path):
        """Um handle sem @ deve receber o prefixo automaticamente."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"youtube_channels": [], "videos": []}))

        register_channel_in_json(json_path, "CanalSemArroba")

        data = json.loads(json_path.read_text())
        assert "@CanalSemArroba" in data["youtube_channels"]

    def test_url_completa_mantida_como_esta(self, tmp_path):
        """URLs completas (http...) não recebem prefixo @ e são armazenadas como estão."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"youtube_channels": [], "videos": []}))

        url = "https://www.youtube.com/@MeuCanal"
        register_channel_in_json(json_path, url)

        data = json.loads(json_path.read_text())
        assert url in data["youtube_channels"]

    def test_cria_lista_de_canais_se_ausente(self, tmp_path):
        """Se o JSON não tiver youtube_channels ainda, deve criar a chave."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"videos": []}))  # Sem youtube_channels

        is_new, _ = register_channel_in_json(json_path, "@Novo")

        assert is_new is True
        data = json.loads(json_path.read_text())
        assert "@Novo" in data["youtube_channels"]

    def test_retorna_false_false_para_handle_vazio(self, tmp_path):
        """String vazia deve retornar (False, False) sem modificar nada."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"videos": []}))

        is_new, registered = register_channel_in_json(json_path, "")

        assert is_new is False
        assert registered is False

    def test_acumula_varios_canais_sequencialmente(self, tmp_path):
        """Registros sequenciais devem acumular todos os canais sem perder nenhum."""
        json_path = tmp_path / "escriba_test.json"
        json_path.write_text(json.dumps({"videos": []}))

        register_channel_in_json(json_path, "@Canal1")
        register_channel_in_json(json_path, "@Canal2")
        register_channel_in_json(json_path, "@Canal3")

        data = json.loads(json_path.read_text())
        canais = data["youtube_channels"]
        assert "@Canal1" in canais
        assert "@Canal2" in canais
        assert "@Canal3" in canais
        assert len(canais) == 3

    def test_json_path_inexistente_cria_arquivo(self, tmp_path):
        """Se o arquivo ainda não existe, deve ser criado com o canal."""
        json_path = tmp_path / "escriba_novo.json"
        assert not json_path.exists()

        is_new, registered = register_channel_in_json(json_path, "@PrimeiroCanal")

        assert is_new is True
        assert registered is True
        assert json_path.exists()


# ─── Integração: register + save não perde canais ─────────────────────────────

class TestIntegracaoRegisterSave:
    """
    Testa o fluxo completo que causou o bug original:
    register_channel_in_json() seguido de save_channel_state_json()
    não deve apagar os canais registrados.
    """

    def test_fluxo_novo_canal_depois_do_original(self, tmp_path):
        """
        Reproduz o cenário do bug reportado pelo usuário:
          1. escriba.py @CanalNovo   → registra e processa
          2. escriba.py @CanalOriginal → o save não deve apagar @CanalNovo
        """
        json_path = tmp_path / "escriba_pasta.json"

        # Passo 1: @CanalOriginal está cadastrado no banco
        json_path.write_text(json.dumps({
            "youtube_channels": ["@CanalOriginal"],
            "videos": [{"video_id": "v_orig", "title": "Original"}]
        }))

        # Passo 2: usuário roda com @CanalNovo — register detecta novo canal
        is_new, _ = register_channel_in_json(json_path, "@CanalNovo")
        assert is_new is True

        # Passo 3: process_videos() de @CanalNovo chama save ao final
        save_channel_state_json(
            json_path,
            [{"video_id": "v_novo", "title": "Novo"}],
            youtube_channel="https://youtube.com/@CanalNovo"
        )

        data = json.loads(json_path.read_text())

        # Ambos os canais devem estar presentes
        assert "@CanalOriginal" in data["youtube_channels"], \
            "BUG: @CanalOriginal foi apagado após processar @CanalNovo!"
        assert "@CanalNovo" in data["youtube_channels"], \
            "BUG: @CanalNovo desapareceu após o save!"


# ─── filter_state_list ────────────────────────────────────────────────────────

class TestFilterStateList:
    """
    Testa a filtragem de vídeos por data de publicação.
    """

    def test_sem_filtro_retorna_todos(self):
        """Sem filtro de data, retorna a lista completa."""
        videos = [
            {"video_id": "a", "publish_date": "2023-01-01"},
            {"video_id": "b", "publish_date": "2022-05-15"},
        ]
        assert len(filter_state_list(videos, "")) == 2

    def test_com_filtro_remove_datas_antigas(self):
        """Vídeos anteriores à data-limite não devem aparecer no resultado."""
        videos = [
            {"video_id": "a", "publish_date": "20240601"},
            {"video_id": "b", "publish_date": "20220101"},
            {"video_id": "c", "publish_date": "N/A"},
        ]
        result = filter_state_list(videos, "20240101")
        ids = [v["video_id"] for v in result]
        assert "a" in ids
        assert "b" not in ids  # anterior ao filtro
        assert "c" not in ids  # sem data válida

    def test_lista_vazia_retorna_vazia(self):
        assert filter_state_list([], "20240101") == []

    def test_todos_sem_data_retornam_vazio(self):
        """Vídeos sem data válida nunca passam pelo filtro de data."""
        videos = [{"video_id": "x", "publish_date": "N/A"}]
        assert filter_state_list(videos, "20240101") == []


# ─── auto_migrate_legacy_files ────────────────────────────────────────────────

class TestAutoMigateLegacyFiles:
    """
    Testa a migração de arquivos .txt legados para flags no JSON.
    """

    def test_migra_subtitle_downloaded_do_historico_txt(self, tmp_path):
        """IDs no historico.txt devem ter subtitle_downloaded=True no JSON."""
        (tmp_path / "historico.txt").write_text("youtube V1234567890\n")
        state = [{"video_id": "V1234567890", "subtitle_downloaded": False}]
        auto_migrate_legacy_files(tmp_path, state)
        assert state[0]["subtitle_downloaded"] is True

    def test_renomeia_arquivos_legados_para_bak(self, tmp_path):
        """Após migração, os .txt devem ser renomeados para .bak."""
        hist = tmp_path / "historico.txt"
        hist.write_text("youtube V1234567890\n")
        auto_migrate_legacy_files(tmp_path, [{"video_id": "V1234567890"}])
        assert not hist.exists()
        assert (tmp_path / "historico.txt.bak").exists()

    def test_retorna_false_sem_arquivos_legados(self, tmp_path):
        """Se não há arquivos legados, retorna False."""
        result = auto_migrate_legacy_files(tmp_path, [])
        assert result is False


# ─── _read_legacy_id_file ────────────────────────────────────────────────────

class TestReadLegacyIdFile:
    """
    Testa a leitura de IDs de arquivos de histórico legados com prefixo.
    """

    def test_le_ids_com_prefixo(self, tmp_path):
        f = tmp_path / "historico.txt"
        f.write_text("youtube V1234567890\nyoutube ZZZyyyXXX22\n")
        ids = _read_legacy_id_file(f, "youtube ")
        assert "V1234567890" in ids
        assert "ZZZyyyXXX22" in ids

    def test_ignora_linhas_sem_prefixo(self, tmp_path):
        f = tmp_path / "historico.txt"
        f.write_text("# comentario\nyoutube V1234567890\n")
        ids = _read_legacy_id_file(f, "youtube ")
        assert len(ids) == 1

    def test_retorna_set_vazio_se_arquivo_ausente(self, tmp_path):
        ids = _read_legacy_id_file(tmp_path / "nao_existe.txt", "youtube ")
        assert ids == set()


# ─── _read_legacy_nosub_file ─────────────────────────────────────────────────

class TestReadLegacyNosubFile:
    """
    Testa a extração de IDs de vídeos sem legenda do arquivo legado.
    """

    def test_extrai_id_da_url(self, tmp_path):
        f = tmp_path / "videos_sem_legenda.txt"
        f.write_text("https://www.youtube.com/watch?v=dQw4w9WgXcQ\n")
        ids = _read_legacy_nosub_file(f)
        assert "dQw4w9WgXcQ" in ids

    def test_ignora_linhas_sem_watch_v(self, tmp_path):
        f = tmp_path / "videos_sem_legenda.txt"
        f.write_text("linha sem url\nhttps://www.youtube.com/watch?v=AbCdEfGhIjK\n")
        ids = _read_legacy_nosub_file(f)
        assert len(ids) == 1

    def test_retorna_vazio_se_arquivo_ausente(self, tmp_path):
        ids = _read_legacy_nosub_file(tmp_path / "nao_existe.txt")
        assert ids == set()


# ─── load_all_local_history ──────────────────────────────────────────────────

class TestLoadAllLocalHistory:
    """
    Testa o carregamento e consolidação do histórico de toda a pasta.
    """

    def test_le_banco_principal_moderno(self, tmp_path):
        jf = tmp_path / "escriba_canal.json"
        jf.write_text(json.dumps({"videos": [{"video_id": "V001", "title": "Test"}]}))
        history = load_all_local_history(tmp_path)
        assert "V001" in history

    def test_le_info_json_avulso(self, tmp_path):
        """
        Arquivo .info.json avulso com ID no nome deve ser detectado.

        O regex em _scan_directory_for_history() extrai o PRIMEIRO bloco de
        exatamente 11 chars alfanuméricos+_- encontrado no nome do arquivo.
        Por isso usamos um nome cujo único bloco de 11 chars é o ID do vídeo.
        """
        jf = tmp_path / "AbCdEfGhIjK.info.json"  # ID sozinho no stem
        jf.write_text(json.dumps({"title": "Título Avulso", "upload_date": "20240301"}))
        history = load_all_local_history(tmp_path)
        assert "AbCdEfGhIjK" in history

    def test_ignora_package_json(self, tmp_path):
        """package.json e similares da blacklist devem ser ignorados."""
        (tmp_path / "package.json").write_text('{"name": "app"}')
        history = load_all_local_history(tmp_path)
        assert history == {}

    def test_consolida_banco_e_avulso(self, tmp_path):
        """
        Dados do banco principal e do .info.json avulso do mesmo vídeo
        devem ser mesclados em uma única entrada com dados mais ricos.

        O regex extrai o primeiro bloco de 11 chars alfanuméricos+_- do nome.
        Usamos o ID sozinho no stem para garantir que o regex o capture corretamente.
        """
        banco = tmp_path / "escriba_canal.json"
        banco.write_text(json.dumps({
            "videos": [{"video_id": "AbCdEfGhIjK", "title": "Avulso", "publish_date": "N/A"}]
        }))
        # Nome com ID isolado como primeiro bloco de 11 chars no stem
        avulso = tmp_path / "AbCdEfGhIjK.info.json"
        avulso.write_text(json.dumps({"title": "Título Real", "upload_date": "20240115"}))

        history = load_all_local_history(tmp_path)

        assert history["AbCdEfGhIjK"]["title"] == "Título Real"
        assert history["AbCdEfGhIjK"]["publish_date"] == "2024-01-15"

