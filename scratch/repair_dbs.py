#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_dbs.py
=============
Tenta reparar os bancos de dados JSON corrompidos truncando o conteúdo extra no ponto
onde o parser JSON indica "Extra data" (o que ocorre quando o arquivo não foi truncado corretamente
durante uma escrita anterior).
"""

import json
from pathlib import Path

def repair_json_file(file_path: Path) -> tuple[bool, str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return False, f"Erro ao ler o arquivo: {e}"

    try:
        json.loads(content)
        return True, "O arquivo já é um JSON válido. Nenhuma ação necessária."
    except json.JSONDecodeError as e:
        if "Extra data" in e.msg:
            # Ponto onde o JSON extra começa
            pos = e.pos
            valid_part = content[:pos].strip()
            try:
                # Valida se a parte truncada é um JSON válido
                parsed_data = json.loads(valid_part)
                
                # Faz o backup do arquivo corrompido
                backup_path = file_path.with_suffix(".json.bak")
                if backup_path.exists():
                    backup_path.unlink()
                file_path.rename(backup_path)
                
                # Salva o JSON corrigido de forma limpa (truncando o arquivo antigo)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(parsed_data, f, indent=4, ensure_ascii=False)
                    
                return True, f"Reparado com sucesso! Arquivo truncado na posição {pos}. Backup salvo em {backup_path.name}"
            except Exception as ex:
                return False, f"Falha ao validar parte truncada: {ex}"
        else:
            return False, f"Erro de JSON não é 'Extra data': {e.msg} na linha {e.lineno}"

def main():
    base_dir = Path("C:/Users/Jandir/Documents/youtubedownloads")
    corrupted_paths = [
        base_dir / "ComofazerSEO/escriba_ComofazerSEO.json",
        base_dir / "EWKenyonTeachings/escriba_EWKenyonTeachings.json",
        base_dir / "andrewwommackmin/escriba_andrewwommackmin.json",
        base_dir / "arthurbrooks/escriba_arthurbrooks.json",
        base_dir / "danmartell/escriba_danmartell.json",
        base_dir / "jenniferlaclaire/escriba_jenniferlaclaire.json",
        base_dir / "jerrysavelle/escriba_jerrysavelle.json",
        base_dir / "josuegoncalves/escriba_josuegoncalves.json",
    ]
    
    print("Iniciando reparação dos bancos de dados JSON corrompidos...")
    print("=" * 80)
    
    repaired_count = 0
    for path in corrupted_paths:
        if not path.exists():
            print(f"[!] Arquivo não encontrado: {path.name}")
            continue
            
        print(f"Analisando {path.name}... ", end="")
        success, message = repair_json_file(path)
        if success:
            repaired_count += 1
            print(f"[OK] {message}")
        else:
            print(f"[FALHA] {message}")
            
    print("=" * 80)
    print(f"Processo concluído. Total de arquivos reparados: {repaired_count}/{len(corrupted_paths)}")

if __name__ == "__main__":
    main()
