#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_channel_duplicates.py
===========================
Varre todos os bancos de dados JSON (escriba_*.json e lista_*.json) a partir da pasta
'youtubedownloads' no diretório de Documentos do usuário.
Carrega cada banco de dados, limpa duplicatas na lista de canais usando a nova lógica
de deduplicação centralizada em history.py, e salva o JSON atualizado.
"""

import sys
from pathlib import Path
import json

# Adiciona o diretório raiz do escriba ao path para podermos importar de history.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from history import _deduplicate_channel_list

def main():
    base_dir = Path("C:/Users/Jandir/Documents/youtubedownloads")
    if not base_dir.exists():
        print(f"Erro: Pasta base não encontrada em {base_dir}")
        sys.exit(1)
        
    print(f"Iniciando a limpeza e deduplicação de canais em: {base_dir}")
    
    # Encontra todos os arquivos de banco de dados
    db_paths = sorted(
        list(base_dir.glob("**/escriba_*.json")) + 
        list(base_dir.glob("**/lista_*.json"))
    )
    
    db_paths = sorted(list(set(db_paths)))
    
    print(f"Encontrados {len(db_paths)} arquivos de banco de dados para examinar.\n")
    
    cleaned_count = 0
    for idx, db_path in enumerate(db_paths, 1):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            if not isinstance(data, dict):
                continue
                
            modified = False
            for key_str in ["youtube_channels", "vimeo_channels"]:
                if key_str in data:
                    original_list = data[key_str]
                    if isinstance(original_list, list) and original_list:
                        cleaned_list = _deduplicate_channel_list(original_list)
                        if len(cleaned_list) != len(original_list):
                            data[key_str] = cleaned_list
                            modified = True
            
            if modified:
                # Salva o arquivo de volta com as modificações
                with open(db_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                print(f"[{idx}/{len(db_paths)}] {db_path.name}: Limpo com sucesso (lista de canais deduplicada).")
                cleaned_count += 1
            else:
                # Sem alterações necessárias
                pass
                
        except Exception as e:
            print(f"[{idx}/{len(db_paths)}] Erro ao processar {db_path.name}: {e}")
            
    print("\n" + "=" * 80)
    print(f"Limpeza concluída! Total de bancos de dados corrigidos: {cleaned_count}/{len(db_paths)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
