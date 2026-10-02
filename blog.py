"""
MÓDULO BLOG: Extração de Artigos e Feeds RSS/Atom
-------------------------------------------------
Este módulo implementa o provedor de Blog para o Escriba.
Permite extrair postagens de blogs via RSS/Atom feeds ou diretamente de URLs de artigos,
convertendo o conteúdo HTML em Markdown limpo para o NotebookLM,
com suporte a Smart Sync e rastreamento incremental no histórico JSON.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from enum import IntEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import feedparser
import html2text
import requests

from rules import clean_ekklezia_terms, restore_punctuation_heuristics, fix_sentence_capitalization
from utils import (
    BCYAN,
    BOLD,
    DIM,
    RESET,
    format_date,
    print_err,
    print_info,
    print_ok,
    print_warn,
)


class DownloadResult(IntEnum):
    """Códigos de retorno padronizados para operações de download."""
    SUCCESS = 0
    SKIPPED = 1
    FAILED = 2


DEFAULT_LANGUAGE_FALLBACK: str = "pt"
REQUEST_TIMEOUT_SECONDS: int = 20
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Padrões comuns para localização de feeds RSS/Atom
COMMON_FEED_PATHS: list[str] = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss/",
    "/rss.xml",
    "/atom.xml",
    "/feed.xml",
    "/index.xml",
]


def make_post_id(url_or_guid_str: str) -> str:
    """Gera um ID único determinístico baseado em hash MD5 (12 caracteres)."""
    clean_val_str: str = url_or_guid_str.strip()
    return f"art_{hashlib.md5(clean_val_str.encode('utf-8')).hexdigest()[:12]}"


def is_blog_url(url_str: str) -> bool:
    """Detecta se uma URL corresponde a um blog, feed RSS ou artigo da web."""
    if not url_str or not (url_str.startswith("http://") or url_str.startswith("https://")):
        return False
    lower_url_str: str = url_str.lower()
    if "youtube.com" in lower_url_str or "youtu.be" in lower_url_str or "vimeo.com" in lower_url_str:
        return False
    if any(lower_url_str.endswith(ext) for ext in [".xml", ".rss", "/feed", "/feed/", "/rss", "/rss/"]):
        return True
    return True


def _get_request_session() -> requests.Session:
    """Cria uma sessão HTTP pré-configurada com headers comuns."""
    session_obj: requests.Session = requests.Session()
    session_obj.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    return session_obj


def discover_feed_url(target_url_str: str) -> str | None:
    """
    Tenta descobrir a URL do feed RSS/Atom a partir da URL do blog/site.
    1. Se a própria URL já for um feed válido, retorna ela mesma.
    2. Procura tags <link rel="alternate" type="application/rss+xml" ...> no HTML.
    3. Tenta caminhos comuns (/feed, /rss, etc.).
    """
    target_clean_str: str = target_url_str.strip()
    session_obj = _get_request_session()

    # 1. Verifica se a própria URL já é um feed RSS/Atom
    try:
        parsed_feed = feedparser.parse(target_clean_str)
        if parsed_feed.entries:
            return target_clean_str
    except Exception:
        pass

    # 2. Faz fetch do HTML da página inicial ou seção
    try:
        response_obj = session_obj.get(target_clean_str, timeout=REQUEST_TIMEOUT_SECONDS)
        if response_obj.status_code == 200:
            soup_obj = BeautifulSoup(response_obj.text, "html.parser")
            feed_links = soup_obj.find_all(
                "link",
                rel=lambda r: r and "alternate" in r.lower() if isinstance(r, str) else (r and "alternate" in [x.lower() for x in r]),
                type=lambda t: t and ("rss" in t.lower() or "atom" in t.lower() or "xml" in t.lower()) if isinstance(t, str) else False,
            )
            for link_tag in feed_links:
                href_str = link_tag.get("href")
                if href_str:
                    full_feed_url_str: str = urljoin(target_clean_str, href_str)
                    check_parsed = feedparser.parse(full_feed_url_str)
                    if check_parsed.entries:
                        return full_feed_url_str
    except Exception:
        pass

    # 3. Tenta caminhos padrão conhecidos
    parsed_base = urlparse(target_clean_str)
    base_origin_str: str = f"{parsed_base.scheme}://{parsed_base.netloc}"
    for path_candidate_str in COMMON_FEED_PATHS:
        candidate_url_str: str = urljoin(base_origin_str, path_candidate_str)
        try:
            feed_candidate = feedparser.parse(candidate_url_str)
            if feed_candidate.entries:
                return candidate_url_str
        except Exception:
            continue

    return None


def _parse_entry_date(entry_data_dict: dict[str, Any]) -> str:
    """Extrai e padroniza a data de publicação no formato YYYY-MM-DD."""
    if "published_parsed" in entry_data_dict and entry_data_dict["published_parsed"]:
        try:
            dt_obj = datetime(*entry_data_dict["published_parsed"][:6])
            return dt_obj.strftime("%Y-%m-%d")
        except Exception:
            pass

    for date_field_str in ["published", "updated", "created", "pubDate"]:
        raw_val_str = entry_data_dict.get(date_field_str)
        if raw_val_str:
            try:
                dt_obj = parsedate_to_datetime(raw_val_str)
                return dt_obj.strftime("%Y-%m-%d")
            except Exception:
                pass
            res_formatted = format_date(raw_val_str)
            if res_formatted != "Desconhecida":
                return res_formatted

    return "Desconhecida"


def _extract_single_article_info(article_url_str: str) -> dict[str, Any]:
    """Extrai metadados e conteúdo de um artigo direto quando não há feed."""
    session_obj = _get_request_session()
    post_id_str: str = make_post_id(article_url_str)
    try:
        response_obj = session_obj.get(article_url_str, timeout=REQUEST_TIMEOUT_SECONDS)
        if response_obj.status_code != 200:
            return {
                "video_id": post_id_str,
                "title": "Artigo sem título",
                "publish_date": "Desconhecida",
                "source_channel": article_url_str,
                "url": article_url_str,
                "subtitle_downloaded": False,
                "info_downloaded": False,
                "has_no_subtitle": False,
            }

        soup_obj = BeautifulSoup(response_obj.text, "html.parser")
        title_tag = soup_obj.find("meta", property="og:title") or soup_obj.find("title")
        title_str: str = title_tag.get("content") if title_tag and title_tag.get("content") else (title_tag.text.strip() if title_tag else "Artigo")

        date_tag = (
            soup_obj.find("meta", property="article:published_time")
            or soup_obj.find("meta", attrs={"name": "publication_date"})
            or soup_obj.find("time")
        )
        raw_date_str = ""
        if date_tag:
            raw_date_str = date_tag.get("content") or date_tag.get("datetime") or date_tag.text.strip()
        pub_date_str = format_date(raw_date_str) if raw_date_str else "Desconhecida"

        return {
            "video_id": post_id_str,
            "title": title_str,
            "publish_date": pub_date_str,
            "source_channel": article_url_str,
            "url": article_url_str,
            "subtitle_downloaded": False,
            "info_downloaded": False,
            "has_no_subtitle": False,
        }
    except Exception as e_obj:
        print_warn(f"Erro ao obter artigo único ({article_url_str}): {e_obj}")
        return {
            "video_id": post_id_str,
            "title": "Artigo",
            "publish_date": "Desconhecida",
            "source_channel": article_url_str,
            "url": article_url_str,
            "subtitle_downloaded": False,
            "info_downloaded": False,
            "has_no_subtitle": False,
        }


def generate_fast_list_json(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    channel_url_str: str,
    history_dict: dict[str, Any] | None = None,
    stop_at_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Varre os artigos do blog via Feed RSS/Atom ou URL direta com Smart Sync.
    Retorna uma lista de registros padronizados para o Escriba.
    """
    print_info("Fase 1: Mapeando artigos do Blog/Feed...")
    feed_url_str: str | None = discover_feed_url(channel_url_str)

    if not feed_url_str:
        print_info(f"Nenhum feed RSS/Atom descoberto para {channel_url_str}. Tratando como artigo individual...")
        single_record = _extract_single_article_info(channel_url_str)
        return [single_record]

    print_ok(f"Feed RSS/Atom localizado: {BOLD}{feed_url_str}{RESET}")
    parsed_feed = feedparser.parse(feed_url_str)
    entries_list = parsed_feed.entries or []
    print_info(f"Artigos encontrados no feed: {len(entries_list)}")

    articles_found_list: list[dict[str, Any]] = []
    consecutive_known_count_int: int = 0
    max_consecutive_known: int = 10

    for entry_obj in entries_list:
        link_str: str = entry_obj.get("link") or ""
        guid_str: str = entry_obj.get("id") or link_str
        if not guid_str and not link_str:
            continue

        post_id_str: str = make_post_id(guid_str or link_str)
        title_str: str = entry_obj.get("title", "Sem Título").strip()
        pub_date_str: str = _parse_entry_date(entry_obj)

        if history_dict and post_id_str in history_dict:
            existing_entry = history_dict[post_id_str]
            if pub_date_str == "Desconhecida":
                pub_date_str = existing_entry.get("publish_date", "Desconhecida")
            if not title_str or title_str == "Sem Título":
                title_str = existing_entry.get("title", "Sem Título")

        # Smart Sync: parar cedo se já conhecemos os últimos artigos consecutivos
        if stop_at_ids and post_id_str in stop_at_ids:
            consecutive_known_count_int += 1
            if consecutive_known_count_int >= max_consecutive_known:
                print_ok(f"Smart Sync: {max_consecutive_known} artigos consecutivos já conhecidos. Finalizando varredura cedo!")
                break
        else:
            consecutive_known_count_int = 0

        articles_found_list.append({
            "video_id": post_id_str,
            "title": title_str,
            "publish_date": pub_date_str,
            "source_channel": channel_url_str,
            "url": link_str,
            "subtitle_downloaded": False,
            "info_downloaded": False,
            "has_no_subtitle": False,
        })

    return articles_found_list


def detect_language(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    channel_url_str: str,
    cached_lang_str: str | None = None,
) -> str:
    """Detecta o idioma principal do blog a partir do feed ou cabeçalhos HTML."""
    if cached_lang_str and cached_lang_str != "N/A":
        return cached_lang_str

    try:
        feed_url_str = discover_feed_url(channel_url_str)
        if feed_url_str:
            parsed = feedparser.parse(feed_url_str)
            feed_meta = parsed.get("feed", {})
            feed_lang = feed_meta.get("language")
            if feed_lang:
                base_lang = feed_lang.split("-")[0].split("_")[0].lower()
                return f"^{base_lang}.*"
    except Exception:
        pass

    return f"^{DEFAULT_LANGUAGE_FALLBACK}.*"


def _clean_html_article_body(soup_obj: BeautifulSoup) -> str:
    """
    Remove tags ruidosas (scripts, estilos, menus, rodapés, anúncios)
    e extrai o elemento principal do artigo.
    """
    # Remove elementos indesejados
    for tag_name in ["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header", "aside", "form"]:
        for el in soup_obj.find_all(tag_name):
            el.decompose()

    # Remove elementos comuns de navegação e widgets
    for el in soup_obj.find_all(class_=re.compile(r"(sidebar|comment|menu|nav|footer|ad-|advertisement|social|share)", re.IGNORECASE)):
        if el.name not in ["body", "main", "article", "html"]:
            el.decompose()

    # Prioriza seletores de conteúdo de artigo
    content_element = (
        soup_obj.find("article")
        or soup_obj.find(attrs={"role": "main"})
        or soup_obj.find("main")
        or soup_obj.find(class_=re.compile(r"(post-content|entry-content|article-content|content-area|blog-post)", re.IGNORECASE))
        or soup_obj.find("body")
        or soup_obj
    )

    return str(content_element)


def convert_html_to_clean_markdown(
    html_content_str: str,
    article_title_str: str,
    post_id_str: str,
    article_url_str: str,
    publish_date_str: str,
    lang_str: str = "pt",
    version_str: str = "2.8.1",
) -> str:
    """
    Converte o HTML do artigo para Markdown limpo com cabeçalho YAML padronizado
    e regras de limpeza de termos (Ekklezia).
    """
    # Limpa o HTML se for documento ou fragmento HTML
    if "<" in html_content_str and ">" in html_content_str:
        soup_obj = BeautifulSoup(html_content_str, "html.parser")
        cleaned_html_str = _clean_html_article_body(soup_obj)
    else:
        cleaned_html_str = html_content_str

    h2t = html2text.HTML2Text()
    h2t.ignore_links = False
    h2t.ignore_images = False
    h2t.ignore_tables = False
    h2t.body_width = 0

    markdown_text_str: str = h2t.handle(cleaned_html_str).strip()

    # Aplica regras Ekklezia de substituição e pontuação
    markdown_text_str = clean_ekklezia_terms(markdown_text_str)
    markdown_text_str = restore_punctuation_heuristics(markdown_text_str)
    markdown_text_str = fix_sentence_capitalization(markdown_text_str)

    # Monta cabeçalho YAML padronizado idêntico ao NotebookLM do Escriba
    safe_title_str = article_title_str.replace('"', '\\"')
    yaml_header_str: str = f"""---
title: "{safe_title_str}"
video_id: "{post_id_str}"
url: "{article_url_str}"
date: "{publish_date_str}"
duration: "N/A"
language: "{lang_str.strip('^$.*')}"
source: "Escriba v{version_str} (Blog)"
---

# {article_title_str}

> **Data:** {publish_date_str} · **Idioma:** {lang_str.strip('^$.*')}  
> 🔗 [{article_url_str}]({article_url_str})

{markdown_text_str}
"""
    return yaml_header_str


def download_video(
    yt_dlp_cmd_list: list[str],
    cookie_args_list: list[str],
    video_id_str: str,
    lang_filter_str: str,
    folder_name_str: str,
    download_video_only_hd: bool = False,
    article_url_str: str = "",
    title_str: str = "",
    publish_date_str: str = "Desconhecida",
) -> int:
    """
    Interface de download unificada com o Escriba.
    Para blogs, faz o fetch do artigo HTML, extrai o texto, salva o .md direto
    e opcionalmente um info.json simulado para consistência com o pipeline.
    """
    target_url_str: str = article_url_str
    if not target_url_str:
        print_err(f"URL do artigo não fornecida para o ID {video_id_str}")
        return int(DownloadResult.FAILED)

    try:
        session_obj = _get_request_session()
        response_obj = session_obj.get(target_url_str, timeout=REQUEST_TIMEOUT_SECONDS)
        if response_obj.status_code != 200:
            print_err(f"Erro HTTP {response_obj.status_code} ao baixar artigo: {target_url_str}")
            return int(DownloadResult.FAILED)

        soup_obj = BeautifulSoup(response_obj.text, "html.parser")

        # Recupera título se não fornecido
        if not title_str or title_str == "Sem Título":
            t_tag = soup_obj.find("title") or soup_obj.find("h1")
            title_str = t_tag.text.strip() if t_tag else "Artigo"

        # Extrai e limpa corpo do artigo
        article_html_str: str = _clean_html_article_body(soup_obj)
        clean_md_str: str = convert_html_to_clean_markdown(
            html_content_str=article_html_str,
            article_title_str=title_str,
            post_id_str=video_id_str,
            article_url_str=target_url_str,
            publish_date_str=publish_date_str,
            lang_str=lang_filter_str,
        )

        cwd_path = Path.cwd()
        md_file_path = cwd_path / f"{folder_name_str}-{video_id_str}.md"
        with open(md_file_path, "w", encoding="utf-8") as f_md:
            f_md.write(clean_md_str)

        # Salva info.json simulado para alimentar harvest_and_delete_info_json
        info_json_path = cwd_path / f"{folder_name_str}-{video_id_str}.info.json"
        info_data_dict = {
            "id": video_id_str,
            "title": title_str,
            "upload_date": publish_date_str.replace("-", "") if publish_date_str != "Desconhecida" else "",
            "webpage_url": target_url_str,
            "extractor": "blog",
        }
        with open(info_json_path, "w", encoding="utf-8") as f_info:
            json.dump(info_data_dict, f_info, ensure_ascii=False, indent=2)

        return int(DownloadResult.SUCCESS)

    except Exception as error_obj:
        print_err(f"Erro ao processar artigo {video_id_str} ({target_url_str}): {error_obj}")
        return int(DownloadResult.FAILED)
