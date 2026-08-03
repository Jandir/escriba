#!/usr/bin/env python3
"""
convert_all_bases.py (Escriba v2.8.0)
─────────────────────────────────────────────────────────────────────────────
Script de conversão e atualização massiva para todas as bases e canais.

O que este script faz:
  1. Varre automaticamente diretórios de downloads (ex: ~/Documents/youtubedownloads
     e pastas locais) identificando todas as pastas de canais ativas.
  2. Regenera todos os arquivos .md a partir das legendas .srt aplicando o
     motor v2.8.0:
       - Restauração Local de Pontuação Gramatical (., ,, ? e maiúsculas).
       - Garantia de Divisão por Capítulos (mínimo de 3 a 8 capítulos via vales TF-IDF).
       - Hierarquia estrita Markdown H1 -> H2 -> H3.
  3. Re-executa a consolidação do Lexis (--reset) para cada canal:
       - Gera novos volumes de 1.0MB (~200k tokens) em volumes_notebooklm.
       - Aplica tags <article class="video-entry"> e Frontmatter YAML sem duplicação de título.
       - Atualiza a Tabela de Índice (Volume Index) no rodapé.

Uso:
  python convert_all_bases.py [caminho_opcional]

Exemplo:
  python convert_all_bases.py C:\\Users\\Jandir\\Documents\\youtubedownloads
─────────────────────────────────────────────────────────────────────────────
"""

import sys
import os
import re
import glob
from pathlib import Path

# Ajusta o path para importar módulos do Escriba
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from escriba import srt_to_md, print_header, VERSION
from lexis import process_channel
from utils import print_ok, print_info, print_warn, print_section, print_err, extract_video_id


DEFAULT_SEARCH_PATHS = [
    os.path.expanduser("~/Documents/youtubedownloads"),
    str(SCRIPT_DIR.parent), # c:\Users\Jandir\scripts
]


def find_channel_directories(base_paths: list[str]) -> list[Path]:
    """Identifica pastas que contêm bases ou legendas de canais do Escriba."""
    channel_dirs: set[Path] = set()

    for base_path_str in base_paths:
        base_path = Path(base_path_str)
        if not base_path.exists():
            continue

        # Procura por pastas contendo escriba_*.json ou subpasta archive / volumes_notebooklm
        for root, dirs, files in os.walk(base_path):
            root_path = Path(root)
            if root_path.name in ("archive", "volumes_notebooklm", ".git", ".venv", "scratch", "tests", "transcripts_tmp"):
                continue
            
            # Se encontrar arquivo de estado escriba_*.json ou pasta archive com srt/md
            has_escriba_json = any(f.startswith("escriba_") and f.endswith(".json") for f in files)
            has_archive = "archive" in dirs
            has_volumes = "volumes_notebooklm" in dirs

            if has_escriba_json or has_archive or has_volumes:
                channel_dirs.add(root_path)

    return sorted(list(channel_dirs))


def process_single_channel_directory(channel_dir: Path):
    """Atualiza todas as legendas .md e regera os volumes NotebookLM de um canal."""
    channel_name = channel_dir.name
    print_section(f"Processando Canal: {channel_name} ({channel_dir})")

    # 1. Localizar todas as legendas .srt (no diretório do canal ou na pasta archive)
    srt_files = list(channel_dir.glob("*.srt")) + list(channel_dir.glob("archive/*.srt"))
    print_info(f"Encontrados {len(srt_files)} arquivos de legenda .srt para regeneração.")

    converted_md_count = 0
    for srt_path in srt_files:
        vid_id = extract_video_id(srt_path.name) or srt_path.stem
        # Tenta inferir o título a partir do nome do arquivo
        clean_title = srt_path.stem.replace(f"-{vid_id}", "").replace("-pt", "").replace("-en", "").replace("_", " ").title()
        
        try:
            res = srt_to_md(srt_path, vid_id, clean_title, indentation_prefix_str="  ")
            if res:
                converted_md_count += 1
        except Exception as e:
            print_warn(f"Falha ao re-converter {srt_path.name}: {e}")

    print_ok(f"{converted_md_count} arquivos .md atualizados com pontuação v2.8.0 e capítulos.")

    # 2. Re-executar o Lexis com --reset para regerar os volumes NotebookLM
    print_info(f"Re-gerando volumes NotebookLM (1.0MB) para {channel_name}...")
    try:
        process_channel(str(channel_dir), channel_name, reset_mode_bool=True)
        print_ok(f"Volumes do canal '{channel_name}' regerados com sucesso em volumes_notebooklm!")
    except Exception as e:
        print_err(f"Erro ao consolidar canal {channel_name}: {e}")


def main():
    print_header(VERSION)
    print_info("Script de Conversão Massiva v2.8.0 - Escriba & Lexis")

    target_paths = DEFAULT_SEARCH_PATHS
    if len(sys.argv) > 1:
        target_paths = [os.path.abspath(sys.argv[1])]

    print_info(f"Buscando bases de canais nos caminhos: {target_paths}")
    channel_dirs = find_channel_directories(target_paths)

    if not channel_dirs:
        print_warn("Nenhuma pasta de canal do Escriba foi encontrada nos locais pesquisados.")
        return

    print_ok(f"Encontradas {len(channel_dirs)} pasta(s) de canais para atualizar:\n")
    for d in channel_dirs:
        print(f"  • {d}")
    print()

    for channel_dir in channel_dirs:
        process_single_channel_directory(channel_dir)

    print("\n" + "=" * 60)
    print_ok("🎉 CONVERSÃO DE TODAS AS BASES CONCLUÍDA COM SUCESSO!")
    print("=" * 60)


if __name__ == "__main__":
    main()
