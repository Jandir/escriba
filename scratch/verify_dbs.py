#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_dbs.py
=============
Varre todos os bancos de dados JSON (escriba_*.json e lista_*.json) a partir da pasta
'youtubedownloads' no diretório de Documentos do usuário.
Realiza verificações de integridade sintática, conformidade com o esquema, consistência
de metadados dos vídeos, duplicidade e sincronização com arquivos locais (legendas e transcrições).
Gera um relatório detalhado em console e salva um relatório Markdown nos artefatos.
"""

import os
import json
import re
import sys
from pathlib import Path
from datetime import datetime

# Configurações de cores para o terminal
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"

def is_likely_youtube_id(seg: str) -> bool:
    if not re.match(r"^[A-Za-z0-9_-]{11}$", seg):
        return False
    # Filtra palavras do dicionário de 11 caracteres (ex: "association", "development")
    # Um ID válido do YouTube é aleatório e geralmente contém números/símbolos ou mistura de maiúsculas/minúsculas
    has_digit_or_symbol = any(c.isdigit() or c in '_-' for c in seg)
    has_upper = any(c.isupper() for c in seg)
    has_lower = any(c.islower() for c in seg)
    return has_digit_or_symbol or (has_upper and has_lower)

def is_valid_vimeo_id(seg: str) -> bool:
    return bool(re.match(r"^\d{7,12}$", seg))

def extract_video_id_from_filename(filename: str) -> str | None:
    # Remove as extensões
    name = filename
    while '.' in name:
        name = name.rsplit('.', 1)[0]
    
    # Divide por hífen e analisa os segmentos
    segments = name.split('-')
    for seg in segments:
        if is_likely_youtube_id(seg):
            return seg
        if is_valid_vimeo_id(seg):
            return seg
    return None

def format_size(num_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} TB"

def run_verification():
    base_dir = Path("C:/Users/Jandir/Documents/youtubedownloads")
    if not base_dir.exists():
        print(f"{RED}{BOLD}Erro: Pasta base não encontrada em {base_dir}{RESET}")
        sys.exit(1)
        
    print(f"{BLUE}{BOLD}Iniciando verificação dos bancos de dados JSON em:{RESET} {base_dir}")
    
    # Encontra todos os arquivos de banco de dados
    db_paths = sorted(
        list(base_dir.glob("**/escriba_*.json")) + 
        list(base_dir.glob("**/lista_*.json"))
    )
    
    # Remove duplicatas se o glob pegou o mesmo arquivo (caminhos absolutos evitam isso, mas é bom garantir)
    db_paths = sorted(list(set(db_paths)))
    
    print(f"{CYAN}Encontrados {len(db_paths)} arquivos de banco de dados para analisar.{RESET}\n")
    
    results = {}
    total_errors = 0
    total_warnings = 0
    corrupt_files_count = 0
    
    youtube_id_pattern = re.compile(r"^[A-Za-z0-9_-]{11}$")
    vimeo_id_pattern = re.compile(r"^\d{7,12}$")
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    
    for idx, db_path in enumerate(db_paths, 1):
        channel_name = db_path.parent.name
        db_filename = db_path.name
        db_size = db_path.stat().st_size
        
        print(f"[{idx}/{len(db_paths)}] Analisando {BOLD}{channel_name}{RESET} ({db_filename})... ", end="", flush=True)
        
        channel_report = {
            "path": db_path,
            "filename": db_filename,
            "size": db_size,
            "errors": [],
            "warnings": [],
            "videos_count": 0,
            "status": "OK"
        }
        
        # 1. Carregamento e Sintaxe JSON
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as jde:
            channel_report["errors"].append(
                f"Sintaxe JSON corrompida: {jde.msg} (Linha {jde.lineno}, Coluna {jde.colno})"
            )
            channel_report["status"] = "CORRUPT"
            results[channel_name] = channel_report
            total_errors += 1
            corrupt_files_count += 1
            print(f"{RED}ERRO DE SINTAXE{RESET}")
            continue
        except Exception as e:
            channel_report["errors"].append(f"Erro inesperado ao abrir arquivo: {e}")
            channel_report["status"] = "ERROR"
            results[channel_name] = channel_report
            total_errors += 1
            print(f"{RED}ERRO DE LEITURA{RESET}")
            continue
            
        # 2. Estrutura e Esquema
        videos_list = None
        if isinstance(data, list):
            # Formato legado de lista pura
            channel_report["warnings"].append("Banco de dados no formato legado (lista pura). Recomenda-se migrar.")
            videos_list = data
        elif isinstance(data, dict):
            if "videos" not in data:
                channel_report["errors"].append("Esquema inválido: chave 'videos' não encontrada na raiz.")
            else:
                videos_list = data["videos"]
                if not isinstance(videos_list, list):
                    channel_report["errors"].append(f"Esquema inválido: a chave 'videos' deve ser uma lista, mas é {type(videos_list).__name__}.")
                    videos_list = None
        else:
            channel_report["errors"].append(f"Esquema inválido: objeto raiz deve ser dict ou list, mas é {type(data).__name__}.")
            
        if channel_report["errors"]:
            channel_report["status"] = "ERROR"
            results[channel_name] = channel_report
            total_errors += len(channel_report["errors"])
            print(f"{RED}ERRO DE ESQUEMA{RESET}")
            continue
            
        channel_report["videos_count"] = len(videos_list) if videos_list else 0
        
        # 3. Validação dos Vídeos
        seen_ids = {}
        empty_titles = 0
        invalid_ids = []
        invalid_dates = []
        invalid_types = []
        
        if videos_list:
            for v_idx, video in enumerate(videos_list):
                if not isinstance(video, dict):
                    channel_report["errors"].append(f"Entrada de vídeo no índice {v_idx} não é um objeto/dicionário (tipo: {type(video).__name__}).")
                    continue
                    
                video_id = video.get("video_id") or video.get("id")
                
                # Validação do ID
                if not video_id:
                    channel_report["errors"].append(f"Entrada no índice {v_idx} está sem ID de vídeo. Chaves disponíveis: {list(video.keys())}")
                    continue
                
                # Duplicados
                if video_id in seen_ids:
                    seen_ids[video_id].append(v_idx)
                else:
                    seen_ids[video_id] = [v_idx]
                    
                # Formato de ID
                is_youtube = youtube_id_pattern.match(str(video_id))
                is_vimeo = vimeo_id_pattern.match(str(video_id))
                if not (is_youtube or is_vimeo):
                    invalid_ids.append((video_id, v_idx))
                    
                # Título
                title = video.get("title")
                if "title" in video:
                    if not title or str(title).strip() in ["", "N/A", "Avulso"]:
                        empty_titles += 1
                        
                # Data de publicação
                pub_date = video.get("publish_date")
                if pub_date:
                    if str(pub_date) not in ["N/A", "Desconhecida", ""]:
                        if not date_pattern.match(str(pub_date)):
                            invalid_dates.append((video_id, pub_date, v_idx))
                            
                # Tipos de dados das flags
                for flag in ["subtitle_downloaded", "info_downloaded", "has_no_subtitle"]:
                    if flag in video and not isinstance(video[flag], bool):
                        invalid_types.append((video_id, flag, type(video[flag]).__name__, v_idx))
                        
            # Consolida problemas de vídeo no relatório
            duplicates = {k: v for k, v in seen_ids.items() if len(v) > 1}
            if duplicates:
                channel_report["warnings"].append(
                    f"Encontrados {len(duplicates)} IDs de vídeo duplicados: " + 
                    ", ".join([f"'{k}' em {v}" for k, v in list(duplicates.items())[:3]]) + 
                    (f" e mais {len(duplicates)-3}..." if len(duplicates) > 3 else "")
                )
            if invalid_ids:
                channel_report["errors"].append(
                    f"Encontrados {len(invalid_ids)} IDs com formato inválido: " + 
                    ", ".join([f"'{v[0]}' no índice {v[1]}" for v in invalid_ids[:3]]) + 
                    (f" e mais {len(invalid_ids)-3}..." if len(invalid_ids) > 3 else "")
                )
            if empty_titles:
                channel_report["warnings"].append(f"Existem {empty_titles} vídeos com títulos vazios ou placeholders ('N/A', 'Avulso').")
                
            if invalid_dates:
                channel_report["warnings"].append(
                    f"Existem {len(invalid_dates)} vídeos com formato de data inválido (esperado YYYY-MM-DD): " + 
                    ", ".join([f"ID '{v[0]}': '{v[1]}' no índice {v[2]}" for v in invalid_dates[:3]]) + 
                    (f" e mais {len(invalid_dates)-3}..." if len(invalid_dates) > 3 else "")
                )
            if invalid_types:
                channel_report["warnings"].append(
                    f"Existem {len(invalid_types)} flags com tipo incorreto (esperado bool): " + 
                    ", ".join([f"ID '{v[0]}': {v[1]} é {v[2]} no índice {v[3]}" for v in invalid_types[:3]]) + 
                    (f" e mais {len(invalid_types)-3}..." if len(invalid_types) > 3 else "")
                )

        # 4. Auditoria de Sincronização Local (Orphans Audit)
        channel_dir = db_path.parent
        archive_dirs = [channel_dir / "archive", channel_dir / "archives", channel_dir]
        
        # Mapeia arquivos físicos para IDs detectados
        local_files_by_id = {} # video_id -> list of file paths
        all_local_files = []
        
        for arch_dir in archive_dirs:
            if arch_dir.exists() and arch_dir.is_dir():
                for f in arch_dir.iterdir():
                    if f.is_file() and f.suffix in ['.srt', '.vtt', '.md', '.txt', '.info.json']:
                        # Ignora arquivos globais do sistema ou scripts
                        if f.name in ['cookies.txt', 'README.md', 'escriba.py', 'history.py'] or f.name.startswith('escriba_'):
                            continue
                        all_local_files.append(f)
                        vid_id = extract_video_id_from_filename(f.name)
                        if vid_id:
                            if vid_id not in local_files_by_id:
                                local_files_by_id[vid_id] = []
                            local_files_by_id[vid_id].append(f)
                            
        # A. Entradas de banco sem arquivos locais (Orphan DB Entries)
        db_ids = set(seen_ids.keys())
        local_ids = set(local_files_by_id.keys())
        
        orphan_db_ids = db_ids - local_ids
        if orphan_db_ids:
            channel_report["warnings"].append(
                f"{len(orphan_db_ids)} registros no JSON não possuem nenhum arquivo correspondente (.srt, .vtt, .md) local. Ex: " + 
                ", ".join(list(orphan_db_ids)[:3]) + 
                (f" e mais {len(orphan_db_ids)-3}..." if len(orphan_db_ids) > 3 else "")
            )
            
        # B. Arquivos locais sem registro no banco (Orphan Local Files)
        orphan_local_ids = local_ids - db_ids
        if orphan_local_ids:
            channel_report["warnings"].append(
                f"{len(orphan_local_ids)} vídeos locais possuem arquivos no disco mas NÃO estão registrados no JSON. Ex: " + 
                ", ".join(list(orphan_local_ids)[:3]) + 
                (f" e mais {len(orphan_local_ids)-3}..." if len(orphan_local_ids) > 3 else "")
            )
            
        # C. Verificação de Legendas Baixadas
        subtitle_missing_ids = []
        if videos_list:
            for video in videos_list:
                video_id = video.get("video_id") or video.get("id")
                if video.get("subtitle_downloaded") is True:
                    # Verifica se existe arquivo .srt ou .vtt correspondente
                    files = local_files_by_id.get(video_id, [])
                    has_sub = any(f.suffix in ['.srt', '.vtt'] for f in files)
                    if not has_sub:
                        subtitle_missing_ids.append(video_id)
                        
        if subtitle_missing_ids:
            channel_report["warnings"].append(
                f"{len(subtitle_missing_ids)} vídeos marcados com legenda baixada no banco não têm arquivo .srt/.vtt local. Ex: " + 
                ", ".join(subtitle_missing_ids[:3]) + 
                (f" e mais {len(subtitle_missing_ids)-3}..." if len(subtitle_missing_ids) > 3 else "")
            )
            
        # Atualiza o status geral do canal
        if channel_report["errors"]:
            channel_report["status"] = "ERROR"
            total_errors += len(channel_report["errors"])
            print(f"{RED}ERRO ({len(channel_report['errors'])} erros, {len(channel_report['warnings'])} avisos){RESET}")
        elif channel_report["warnings"]:
            channel_report["status"] = "WARNING"
            total_warnings += len(channel_report["warnings"])
            print(f"{YELLOW}AVISO ({len(channel_report['warnings'])} avisos){RESET}")
        else:
            channel_report["status"] = "OK"
            print(f"{GREEN}OK ({channel_report['videos_count']} vídeos){RESET}")
            
        results[channel_name] = channel_report
        
    # Exibe resumo final no terminal
    print("\n" + "=" * 80)
    print(f"{BOLD}RESUMO DA VERIFICAÇÃO DE INTEGRIDADE{RESET}")
    print("=" * 80)
    print(f"Total de bancos analisados: {len(db_paths)}")
    print(f"Bancos com Erro Crítico:   {sum(1 for r in results.values() if r['status'] in ['ERROR', 'CORRUPT'])}")
    print(f"Bancos com Avisos:         {sum(1 for r in results.values() if r['status'] == 'WARNING')}")
    print(f"Bancos 100% Saudáveis:     {sum(1 for r in results.values() if r['status'] == 'OK')}")
    print("-" * 80)
    print(f"Total de Erros Críticos:   {total_errors}")
    print(f"Total de Avisos/Alertas:   {total_warnings}")
    print("=" * 80)
    
    # Gera relatório Markdown nos artefatos
    generate_markdown_report(results, base_dir, total_errors, total_warnings)

def generate_markdown_report(results: dict, base_dir: Path, total_errors: int, total_warnings: int):
    artifact_dir = Path("C:/Users/Jandir/.gemini/antigravity/brain/ebc75b90-49b0-4ca8-bf0f-1497ef02cf29")
    if not artifact_dir.exists():
        artifact_dir.mkdir(parents=True, exist_ok=True)
        
    report_path = artifact_dir / "relatorio_verificacao.md"
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Relatório de Integridade dos Bancos de Dados JSON\n\n")
        f.write(f"**Data da Auditoria:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write(f"**Diretório Analisado:** `{base_dir}`\n\n")
        
        # Resumo executivo em tabela
        f.write("## Resumo Executivo\n\n")
        f.write("| Métrica | Valor |\n")
        f.write("| :--- | :--- |\n")
        f.write(f"| **Total de Bancos Analisados** | {len(results)} |\n")
        f.write(f"| **Bancos 100% Saudáveis (OK)** | {sum(1 for r in results.values() if r['status'] == 'OK')} |\n")
        f.write(f"| **Bancos com Avisos (WARNING)** | {sum(1 for r in results.values() if r['status'] == 'WARNING')} |\n")
        f.write(f"| **Bancos com Erros Críticos (ERROR)** | {sum(1 for r in results.values() if r['status'] in ['ERROR', 'CORRUPT'])} |\n")
        f.write(f"| **Total de Erros Críticos** | {total_errors} |\n")
        f.write(f"| **Total de Avisos/Alertas** | {total_warnings} |\n\n")
        
        # Tabela consolidada de canais
        f.write("## Tabela Geral de Status\n\n")
        f.write("| Canal | Arquivo Banco | Tamanho | Vídeos | Status | Erros | Avisos |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        
        for channel, report in sorted(results.items()):
            status_emoji = "✅ OK"
            if report["status"] == "CORRUPT":
                status_emoji = "💥 CORROMPIDO"
            elif report["status"] == "ERROR":
                status_emoji = "❌ ERRO"
            elif report["status"] == "WARNING":
                status_emoji = "⚠️ AVISO"
                
            f.write(f"| **{channel}** | `{report['filename']}` | {format_size(report['size'])} | {report['videos_count']} | {status_emoji} | {len(report['errors'])} | {len(report['warnings'])} |\n")
            
        f.write("\n---\n\n")
        f.write("## Detalhamento de Inconsistências por Canal\n\n")
        
        # Lista detalhada de canais problemáticos
        has_problems = False
        for channel, report in sorted(results.items()):
            if report["status"] == "OK":
                continue
            has_problems = True
            
            status_text = "ERRO CRÍTICO" if report["status"] in ["ERROR", "CORRUPT"] else "AVISO"
            
            f.write(f"### 📁 Canal: {channel} ({status_text})\n")
            f.write(f"- **Arquivo:** `{report['path'].as_posix()}`\n")
            f.write(f"- **Tamanho:** {format_size(report['size'])} | **Vídeos:** {report['videos_count']}\n\n")
            
            if report["errors"]:
                f.write("#### ❌ Erros Críticos\n")
                for err in report["errors"]:
                    f.write(f"- {err}\n")
                f.write("\n")
                
            if report["warnings"]:
                f.write("#### ⚠️ Avisos e Inconsistências\n")
                for wrn in report["warnings"]:
                    f.write(f"- {wrn}\n")
                f.write("\n")
                
            f.write("---\n\n")
            
        if not has_problems:
            f.write("> [!NOTE]\n")
            f.write("> Todos os bancos de dados estão 100% saudáveis e sincronizados com os arquivos locais! Nenhuma irregularidade foi detectada.\n")
            
    print(f"\n{GREEN}{BOLD}Relatório Markdown gerado com sucesso em:{RESET} {report_path}")

if __name__ == "__main__":
    run_verification()
