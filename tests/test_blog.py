import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

# Adiciona diretório raiz no path para import
sys.path.insert(0, str(Path(__file__).parent.parent))

import blog
from blog import (
    DownloadResult,
    convert_html_to_clean_markdown,
    detect_language,
    discover_feed_url,
    download_video,
    generate_fast_list_json,
    is_blog_url,
    make_post_id,
)
from escriba import get_provider, parse_input_type


def test_make_post_id_deterministic():
    """Garante que make_post_id gera IDs determinísticos iniciados por art_."""
    url = "https://meublog.com/artigo-1"
    id1 = make_post_id(url)
    id2 = make_post_id(url)
    assert id1 == id2
    assert id1.startswith("art_")
    assert len(id1) == 16  # 'art_' + 12 hex chars


def test_is_blog_url():
    """Valida detecção de URLs de blogs e exclusão de YouTube/Vimeo."""
    assert is_blog_url("https://meublog.com/feed") is True
    assert is_blog_url("https://dev.to/post/123") is True
    assert is_blog_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is False
    assert is_blog_url("https://vimeo.com/123456789") is False
    assert is_blog_url("") is False


def test_get_provider_routing():
    """Valida se get_provider identifica blog, vimeo e youtube corretamente."""
    assert get_provider("https://meublog.com/feed.xml") == "blog"
    assert get_provider("art_1234567890ab") == "blog"
    assert get_provider("https://vimeo.com/123456789") == "vimeo"
    assert get_provider("123456789") == "vimeo"
    assert get_provider("https://youtube.com/watch?v=dQw4w9WgXcQ") == "youtube"
    assert get_provider("@canal_youtube") == "youtube"


def test_parse_input_type_blog():
    """Valida se parse_input_type aceita URLs de blog e IDs de artigo."""
    url, itype, vid = parse_input_type("https://meublog.com/posts")
    assert itype == "channel"
    assert url == "https://meublog.com/posts"

    url_art, itype_art, vid_art = parse_input_type("art_1234567890ab")
    assert itype_art == "video"
    assert vid_art == "art_1234567890ab"


def test_convert_html_to_clean_markdown():
    """Garante que a conversão HTML -> Markdown gera o cabeçalho YAML esperado e remove ruído."""
    html_raw = """
    <html>
        <body>
            <header><nav><a href="/">Home</a></nav></header>
            <article>
                <h1>O Poder da Graça</h1>
                <p>Este é o primeiro parágrafo sobre a fé.</p>
                <div class="sidebar">Anúncio aqui</div>
            </article>
            <footer>Todos os direitos reservados</footer>
        </body>
    </html>
    """
    md_result = convert_html_to_clean_markdown(
        html_content_str=html_raw,
        article_title_str="O Poder da Graça",
        post_id_str="art_test123456",
        article_url_str="https://meublog.com/graca",
        publish_date_str="2026-03-26",
        lang_str="pt",
    )

    assert "---" in md_result
    assert 'title: "O Poder da Graça"' in md_result
    assert 'video_id: "art_test123456"' in md_result
    assert 'url: "https://meublog.com/graca"' in md_result
    assert 'date: "2026-03-26"' in md_result
    assert 'source: "Escriba v2.8.1 (Blog)"' in md_result
    assert "# O Poder da Graça" in md_result
    assert "Este é o primeiro parágrafo sobre a fé." in md_result
    # Confirma que tags limpas não vazam
    assert "Anúncio aqui" not in md_result


def test_generate_fast_list_json_rss_feed():
    """Valida varredura de feed RSS com extração e Smart Sync."""
    fake_feed = MagicMock()
    fake_feed.entries = [
        {
            "id": "guid-post-1",
            "link": "https://meublog.com/post-1",
            "title": "Primeiro Post",
            "published_parsed": (2026, 3, 20, 10, 0, 0, 0, 0, 0),
        },
        {
            "id": "guid-post-2",
            "link": "https://meublog.com/post-2",
            "title": "Segundo Post",
            "published": "Mon, 16 Mar 2026 12:00:00 GMT",
        },
    ]

    with patch("feedparser.parse", return_value=fake_feed), \
         patch("blog.discover_feed_url", return_value="https://meublog.com/feed"):

        articles = generate_fast_list_json(
            yt_dlp_cmd_list=[],
            cookie_args_list=[],
            channel_url_str="https://meublog.com",
        )

        assert len(articles) == 2
        assert articles[0]["title"] == "Primeiro Post"
        assert articles[0]["publish_date"] == "2026-03-20"
        assert articles[0]["video_id"].startswith("art_")
        assert articles[1]["title"] == "Segundo Post"
        assert articles[1]["publish_date"] == "2026-03-16"


def test_download_video_blog_article(tmp_path):
    """Testa download e geração de arquivo Markdown e info.json simulado."""
    post_id = "art_testblog99"
    article_url = "https://meublog.com/artigo-vida"
    sample_html = "<html><body><article><h1>Vida Cristã</h1><p>Conteúdo profundo.</p></article></body></html>"

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = sample_html

    with patch("requests.Session.get", return_value=fake_response), \
         patch("pathlib.Path.cwd", return_value=tmp_path):

        exit_code = download_video(
            yt_dlp_cmd_list=[],
            cookie_args_list=[],
            video_id_str=post_id,
            lang_filter_str="pt",
            folder_name_str="meublog",
            article_url_str=article_url,
            title_str="Vida Cristã",
            publish_date_str="2026-03-25",
        )

        assert exit_code == int(DownloadResult.SUCCESS)

        md_file = tmp_path / f"meublog-{post_id}.md"
        assert md_file.exists()
        md_content = md_file.read_text(encoding="utf-8")
        assert 'title: "Vida Cristã"' in md_content
        assert "Conteúdo profundo." in md_content

        info_file = tmp_path / f"meublog-{post_id}.info.json"
        assert info_file.exists()
        info_data = json.loads(info_file.read_text(encoding="utf-8"))
        assert info_data["id"] == post_id
        assert info_data["title"] == "Vida Cristã"
        assert info_data["extractor"] == "blog"


def test_detect_language_blog():
    """Valida detecção de idioma de feed no blog."""
    fake_feed = {
        "feed": {
            "language": "pt-BR"
        }
    }
    with patch("blog.discover_feed_url", return_value="https://meublog.com/feed"), \
         patch("feedparser.parse", return_value=fake_feed):
        lang = detect_language([], [], "https://meublog.com")
        assert lang == "^pt.*"
