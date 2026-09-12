#!/usr/bin/env python3
"""
reprocessar_md_monoliticos.py (Escriba Utility)
─────────────────────────────────────────────────────────────────────────────
Utilitário para identificar e reestruturar arquivos Markdown (.md) monolíticos
que foram gerados sem quebra de tópicos ou com blocos únicos de parágrafos.

O que este script faz:
  1. Varre o diretório indicado procurando por arquivos .md com apenas 1 tópico
     ou parágrafos excessivamente longos (> 2.000 caracteres).
  2. Detecta o idioma real do texto (EN/PT) e ajusta as stopwords e o Frontmatter.
  3. Re-segmenta o texto em parágrafos legíveis (60s a 120s / 500 a 1.200 chars).
  4. Extrai tópicos e palavras-chave semânticas via TF-IDF (scikit-learn).
  5. Gera uma estrutura completa H1 -> H2 (Sumário e Capítulos) -> H3 (Tópicos).

Uso:
  python reprocessar_md_monoliticos.py [caminho_pasta_ou_arquivo] [--dry-run] [--rename-orig]
─────────────────────────────────────────────────────────────────────────────
"""

import sys
import os
import re
import argparse
from pathlib import Path
from typing import Any, List, Dict, Tuple

# Garante acesso aos módulos do Escriba
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from escriba import (
    get_merged_stopwords,
    _calc_total_seconds,
    _smart_ts,
    generate_md_header,
    VERSION,
)
from utils import print_ok, print_info, print_warn, print_section, print_err


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """Separa o YAML frontmatter do corpo do arquivo markdown."""
    metadata = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2].strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    metadata[k.strip()] = v.strip().strip('"').strip("'")
    return metadata, body


def parse_duration_seconds(dur_str: str) -> int:
    """Converte string de duração (HH:MM:SS ou MM:SS) em segundos totais."""
    if not dur_str:
        return 0
    parts = dur_str.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            return int(parts[0])
    except ValueError:
        pass
    return 0


def detect_dominant_language(text: str, current_lang: str = "pt") -> str:
    """Detecta se o texto é predominantemente inglês ou português via vocabulário básico."""
    sample = text[:3000].lower()
    en_markers = {"the", "and", "is", "of", "to", "in", "that", "we", "you", "this", "with", "for"}
    pt_markers = {"que", "de", "não", "um", "uma", "para", "com", "os", "as", "em", "por", "isso"}

    words = set(re.findall(r"\b[a-z]{2,}\b", sample))
    en_score = len(words & en_markers)
    pt_score = len(words & pt_markers)

    if en_score > pt_score:
        return "en"
    if pt_score > en_score:
        return "pt"
    return current_lang if current_lang in ("en", "pt") else "en"


def partition_into_paragraphs(raw_body: str, total_seconds: int) -> List[Tuple[int, str]]:
    """Divide um corpo de texto longo em parágrafos pontuados com timestamps estimados."""
    # 1. Limpa títulos markdown, sumários pré-existentes, blockquotes e marcadores
    cleaned = re.sub(r"^\s*#+.*$", "", raw_body, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*>.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\*\s+`?\[?\d{2}:\d{2}(?::\d{2})?\]?`?.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[\d{2}:\d{2}(?::\d{2})?\]", "", cleaned)
    # Converte marcadores de falante '>>' em quebras de frase naturais
    cleaned = re.sub(r">>+", ". ", cleaned)
    cleaned = " ".join(cleaned.split())

    if not cleaned:
        return []

    # 2. Divide em frases onde houver pontuação
    sentence_end_re = re.compile(r'([.!?]["\']?\s+)')
    tokens = sentence_end_re.split(cleaned)
    raw_sentences = []
    for i in range(0, len(tokens) - 1, 2):
        raw_sentences.append(tokens[i] + tokens[i + 1])
    if len(tokens) % 2 == 1 and tokens[-1].strip():
        raw_sentences.append(tokens[-1])

    # Se alguma frase for excessivamente longa (comum em legendas sem pontuação), fatia a cada ~50 palavras
    sentences = []
    for s in raw_sentences:
        words = s.split()
        if len(words) > 80:
            chunk_size = 50
            for w_idx in range(0, len(words), chunk_size):
                chunk = " ".join(words[w_idx:w_idx + chunk_size])
                if not chunk.endswith((".", "!", "?")):
                    chunk += "."
                sentences.append(chunk)
        else:
            sentences.append(s)

    # 3. Agrupa frases em parágrafos de tamanho confortável (~700 a 1.200 caracteres)
    paragraphs = []
    curr_para = []
    curr_len = 0

    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        curr_para.append(s_clean)
        curr_len += len(s_clean)
        if curr_len >= 800:
            paragraphs.append(" ".join(curr_para))
            curr_para = []
            curr_len = 0

    if curr_para:
        paragraphs.append(" ".join(curr_para))

    if not paragraphs:
        paragraphs = [cleaned]

    # Distribui timestamps proporcionais ao longo do tempo total
    num_p = len(paragraphs)
    result = []
    for idx, p in enumerate(paragraphs):
        sec = int((idx / max(1, num_p)) * total_seconds)
        result.append((sec, p))

    return result


def extract_topic_keywords(paragraphs: List[str], lang_code: str, num_topics: int = 5) -> List[str]:
    """Usa TF-IDF para extrair tópicos/palavras-chave representativos."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np

    stopwords = list(get_merged_stopwords(lang_code))
    vectorizer = TfidfVectorizer(stop_words=stopwords, min_df=1, max_features=500)

    try:
        tfidf_mat = vectorizer.fit_transform(paragraphs)
        features = vectorizer.get_feature_names_out()
    except Exception:
        return [f"Tópico {i+1}" for i in range(num_topics)]

    chunk_size = max(1, len(paragraphs) // num_topics)
    labels = []

    for i in range(num_topics):
        start_idx = i * chunk_size
        end_idx = (i + 1) * chunk_size if i < num_topics - 1 else len(paragraphs)
        if start_idx >= len(paragraphs):
            break

        sub_mat = tfidf_mat[start_idx:end_idx, :]
        seg_vector = np.asarray(sub_mat.sum(axis=0)).flatten()
        top_indices = seg_vector.argsort()[::-1]

        kw = [features[idx] for idx in top_indices if len(features[idx]) > 2][:3]
        if i == 0:
            labels.append("Introdução")
        elif kw:
            labels.append(" · ".join(kw))
        else:
            labels.append(f"Tópico {i+1}")

    return labels


def format_timestamp(seconds: int) -> str:
    """Formata segundos em HH:MM:SS ou MM:SS."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def is_monolithic_md(content: str) -> bool:
    """Verifica se um arquivo .md carece de quebra de tópicos ou tem parágrafos monstruosos."""
    # Menos de 2 tópicos H3 de transcrição
    h3_topics = re.findall(r"^###\s+\[", content, flags=re.MULTILINE)
    if len(h3_topics) <= 1:
        return True

    # Parágrafo contínuo gigante (> 3.000 chars sem quebra de linha)
    lines = content.splitlines()
    for l in lines:
        if len(l.strip()) > 3000:
            return True

    return False


def restructure_md_file(file_path: Path, dry_run: bool = False, rename_orig: bool = False) -> bool:
    """Reestrutura um arquivo MD monolítico para torná-lo particionado e legível."""
    try:
        content = file_path.read_text(encoding="utf-8-sig")
    except Exception as e:
        print_err(f"Erro ao ler {file_path.name}: {e}")
        return False

    if not is_monolithic_md(content):
        return False

    meta, raw_body = parse_frontmatter(content)
    title = meta.get("title", file_path.stem)
    video_id = meta.get("video_id", file_path.stem)
    date_str = meta.get("date", "Desconhecida")
    dur_str = meta.get("duration", "00:00")
    total_sec = parse_duration_seconds(dur_str)

    # Detecta o idioma correto
    detected_lang = detect_dominant_language(raw_body, meta.get("language", "pt"))

    # Particiona o corpo em parágrafos com timestamps
    paras_with_ts = partition_into_paragraphs(raw_body, total_sec)
    if not paras_with_ts:
        return False

    # Determina o número de tópicos com base na duração (3 a 8 tópicos)
    if total_sec < 1800:
        num_topics = 3
    elif total_sec < 3600:
        num_topics = 5
    else:
        num_topics = 8

    just_paras = [p[1] for p in paras_with_ts]
    topic_labels = extract_topic_keywords(just_paras, detected_lang, num_topics=num_topics)

    # Agrupa parágrafos em tópicos
    chunk_p_size = max(1, len(paras_with_ts) // len(topic_labels))
    segments = []
    for t_idx, label in enumerate(topic_labels):
        p_start = t_idx * chunk_p_size
        p_end = (t_idx + 1) * chunk_p_size if t_idx < len(topic_labels) - 1 else len(paras_with_ts)
        seg_paras = paras_with_ts[p_start:p_end]
        if seg_paras:
            seg_start_ts = format_timestamp(seg_paras[0][0])
            segments.append((seg_start_ts, label, seg_paras))

    # Monta novo conteúdo estruturado
    new_lines = []
    # 1. Cabeçalho YAML
    new_lines.extend(generate_md_header(title, video_id, date_str, dur_str, detected_lang, VERSION))
    
    # 2. Sumário
    new_lines.append("## Sumário e Tópicos (Timestamps)\n")
    for seg_ts, label, _ in segments:
        new_lines.append(f"* `[{seg_ts}]` **{label}**\n")
    new_lines.append("\n## Transcrição Estruturada por Capítulos\n")

    # 3. Capítulos e Parágrafos
    for seg_ts, label, seg_paras in segments:
        new_lines.append(f"### [{seg_ts}] - Tópico: {label}\n\n")
        for p_sec, p_text in seg_paras:
            p_ts = format_timestamp(p_sec)
            new_lines.append(f"[{p_ts}] {p_text}\n\n")

    full_output = "".join(new_lines)

    target_path = file_path
    if rename_orig and file_path.name.endswith("-orig.md"):
        new_name = file_path.name[:-8] + ".md"
        target_path = file_path.parent / new_name

    if dry_run:
        print_info(f"[DRY-RUN] Reestruturaria {file_path.name} -> {len(segments)} tópicos, {len(paras_with_ts)} parágrafos, idioma: {detected_lang}")
        return True

    try:
        # Se for renomear, salva no novo caminho e exclui o antigo
        target_path.write_text(full_output, encoding="utf-8-sig")
        if rename_orig and target_path != file_path:
            file_path.unlink()
        print_ok(f"Reestruturado com sucesso: {target_path.name} ({len(segments)} tópicos, idioma: {detected_lang})")
        return True
    except OSError as e:
        print_err(f"Falha ao gravar {target_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Reestruturador de arquivos .md monolíticos do Escriba.")
    parser.add_argument("target", nargs="?", default=r"C:\Users\Jandir\Documents\youtubedownloads\michaelheiser\archive", help="Caminho para arquivo .md ou pasta com arquivos.")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula a reestruturação sem alterar os arquivos.")
    parser.add_argument("--rename-orig", action="store_true", help="Remove o sufixo -orig.md ao gravar.")
    args = parser.parse_args()

    target_path = Path(args.target)
    if not target_path.exists():
        print_err(f"Caminho não encontrado: {target_path}")
        return

    files_to_process = []
    if target_path.is_file():
        if target_path.suffix.lower() == ".md":
            files_to_process.append(target_path)
    else:
        files_to_process = sorted(list(target_path.glob("*.md")))

    print_section(f"Varredura de Arquivos Monolíticos ({len(files_to_process)} arquivos)")

    reprocessed = 0
    for f in files_to_process:
        if is_monolithic_md(f.read_text(encoding="utf-8-sig", errors="ignore")):
            success = restructure_md_file(f, dry_run=args.dry_run, rename_orig=args.rename_orig)
            if success:
                reprocessed += 1

    print_section("Resultado do Reprocessamento")
    print_ok(f"Processamento concluído: {reprocessed} arquivo(s) monolíticos foram tratados.")


if __name__ == "__main__":
    main()
