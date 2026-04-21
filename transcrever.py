#!/usr/bin/env python3
"""
================================================================================
TRANSCREVER.PY - Transcrição de Áudio para Texto usando Whisper
================================================================================

 Olá! Este script transforma arquivos de áudio (MP3, WAV, M4A, etc) em texto.
 Ele usa o modelo Whisper da OpenAI, mas com a implementação "faster-whisper"
 que é muito mais rápida e eficiente em memória.

 Como usar:
     python transcrever.py audio.mp3                              # Transcreve audio.mp3
     python transcrever.py --model small --language pt audio.mp3 # Força modelo pequeno e português
     python transcrever.py -o resultado.txt audio.mp3           # Salva em arquivo específico

================================================================================
"""

# ================================================================================
# IMPORTS - O que precisamos importar?
# ================================================================================
# Suprimir warnings chatos de dependências
import warnings
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported version")

# argparse: Biblioteca padrão do Python para criar interfaces de linha de comando.
#           Permite que o usuário passe argumentos como --model, --language, etc.
from argparse import ArgumentParser

# pathlib.Path: Uma forma moderna e orientado a objetos de lidar com caminhos de
#               arquivos. Substitui o uso antigo de os.path.
from pathlib import Path

# faster_whisper: A implementação otimizada do Whisper. É типа o Whisper original,
#                mas rewritten em C/Cython para ser muito mais rápido.
#                Suporta quantization (int8) para rodar em CPUs normais.
from faster_whisper import WhisperModel

# time: Para calcular o tempo de execução e estimado.
import time as time_module

# sys: Para flush da saída e controle do terminal.
import sys


# ================================================================================
# FUNÇÕES AUXILIARES
# ================================================================================

def format_time(seconds):
    """
    Formata segundos em formato legível: HH:MM:SS ou MM:SS.
    Se for menos de 1 minuto, mostra só segundos.
    """
    if seconds < 0:
        return "--:--"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def format_time_estimate(elapsed_seconds, progress):
    """
    Estima o tempo total baseado no progresso atual.
    Se já passou 10 segundos e está em 50%, estima 20 segundos total.
    """
    if progress <= 0:
        return "--:--"
    
    total_estimate = elapsed_seconds / progress
    remaining = total_estimate - elapsed_seconds
    
    if remaining < 0 or remaining > 3600 * 10:  # Se estimada > 10 horas, algo errado
        return "--:--"
    
    return format_time(remaining)


def get_audio_duration(file_path):
    """
    Tenta obter a duração do áudio usando várias méthodes.
    Retorna None se não conseguir.
    """
    # Método 1: Usar ffprobe (mais preciso)
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    
    # Método 2: Usar mutagen (já instalado no projeto)
    try:
        from mutagen import File
        audio = File(str(file_path))
        if audio and hasattr(audio.info, 'length'):
            return audio.info.length
    except Exception:
        pass
    
    return None


# ================================================================================
# MAIN - A função principal
# ================================================================================
# Toda a lógica do script está aqui. Separar em funções menores é bom para
# códigos grandes, mas aqui tudo cabe bem em uma função só.
def main():
    # -------------------------------------------------------------------------
    # PARTE 1: Configurar os argumentos da linha de comando
    # -------------------------------------------------------------------------
    # ArgumentParser é tipo um formulário: você define quais campos (argumentos)
    # o usuário pode preencher, e ele faz a validação automática.
    #
    # description: Texto de ajuda que aparece quando o usuário digita --help
    parser = ArgumentParser(
        description="Transcreve arquivos de áudio para texto usando Whisper"
    )

    # add_argument: Define um argumento que o usuário pode passar.
    # O primeiro argumento ("audio") não tem "--" na frente, então é obrigatório.
    # É o arquivo de áudio que queremos transcrever.
    parser.add_argument("audio", help="Arquivo de áudio (mp3, wav, m4a, etc)")

    # --model ou -m: Permite escolher qual modelo do Whisper usar.
    # choices: Limita as opções possíveis (evita erros de digitação).
    # default="base": Se o usuário não escolher nada, usa "base" por padrão.
    # Os modelos variam em tamanho e qualidade:
    #   - tiny:   Mais rápido, menos preciso (~75MB)
    #   - base:   Bom equilíbrio (padrão que usamos) (~150MB)
    #   - small:  Melhor qualidade, mais lento (~500MB)
    #   - medium: Muito bom, requer mais RAM (~1.5GB)
    #   - large:  O melhor, precisa de máquina potente (~3GB)
    parser.add_argument(
        "--model", "-m",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        help="Modelo Whisper a usar (padrão: base)"
    )

    # --language ou -l: Permite forçar o idioma da transcrição.
    # Se não informado, o Whisper detecta automaticamente.
    # Códigos comuns: "pt" (português), "en" (inglês), "es" (espanhol), etc.
    parser.add_argument(
        "--language", "-l",
        help="Idioma forçado (pt, en, es, fr, de, etc)"
    )

    # --output ou -o: Define onde salvar o resultado.
    # Se não informado, vamos gerar automaticamente: audio.mp3 -> audio.txt
    parser.add_argument(
        "--output", "-o",
        help="Arquivo de saída (padrão: audio.txt)"
    )

    # parse_args(): Agora sim, processa tudo que o usuário digitou!
    args = parser.parse_args()

    # -------------------------------------------------------------------------
    # PARTE 2: Validar o arquivo de entrada
    # -------------------------------------------------------------------------
    # Path() é uma forma de criar um objeto que representa um caminho de arquivo.
    # Isso nos dá métodos úteis como .exists() para verificar se o arquivo existe.
    audio_path = Path(args.audio)

    # Sempre valide inputs! Se o arquivo não existe, melhor avisar o usuário
    # logo no início do que deixar o programa crashar depois.
    if not audio_path.exists():
        print(f"Erro: Arquivo não encontrado: {args.audio}")
        return 1  # 1 = código de erro (algo deu errado)

    # -------------------------------------------------------------------------
    # PARTE 3: Obter duração do áudio (para calcular progresso)
    # -------------------------------------------------------------------------
    # Vamos tentar descobrir quanto tempo tem o áudio para mostrar uma barra
    # de progresso decente. Se não conseguir, vamos mostrar só tempo corrido.
    print(f"Analisando arquivo de áudio...")
    audio_duration = get_audio_duration(audio_path)
    
    if audio_duration:
        print(f"Duração do áudio: {format_time(audio_duration)}")
    else:
        print("Aviso: Não foi possível detectar a duração do áudio.")

    # -------------------------------------------------------------------------
    # PARTE 4: Carregar o modelo Whisper
    # -------------------------------------------------------------------------
    # WhisperModel() carrega o modelo na memória.
    # compute_type="int8": Isso é importante! Significa que o modelo usa
    # quantization de 8 bits, o que reduz o uso de RAM pela metade sem perder
    # muita precisão. Perfeito para rodar em CPUs de notebooks/desktop.
    print(f"Carregando modelo {args.model}...")
    model = WhisperModel(args.model, compute_type="int8")

    # -------------------------------------------------------------------------
    # PARTE 5: Transcrever o áudio
    # -------------------------------------------------------------------------
    print(f"Transcrevendo {audio_path.name}...")
    print("-" * 50)

    # Se o usuário passou --language, passamos para o transcribe.
    # Se não passou, o Whisper detecta automaticamente (None).
    transcribe_args = {"language": args.language} if args.language else {}

    # Iniciar cronômetro para medir o tempo de execução
    start_time = time_module.time()

    # model.transcribe() retorna duas coisas:
    # - segments: um iterador com cada pedaço de texto transcrito
    # - info: informações sobre a transcrição (idioma detectado, etc)
    segments, info = model.transcribe(str(audio_path), **transcribe_args)

    # info.language nos diz qual idioma foi detectado (ou forçado).
    # language_probability é a confiança do modelo (0 a 1).
    if info.language:
        lang = info.language
        prob = info.language_probability
        # Verificar se são strings ou float (varia conforme versão)
        if isinstance(lang, str):
            if prob is not None:
                try:
                    prob_val = float(prob)
                    print(f"Idioma detectado: {lang} (prob: {prob_val:.2f})")
                except (ValueError, TypeError):
                    print(f"Idioma detectado: {lang}")
            else:
                print(f"Idioma detectado: {lang}")

    # -------------------------------------------------------------------------
    # PARTE 6: Montar o texto final COM MOSTRADOR DE PROGRESSO
    # -------------------------------------------------------------------------
    # O Whisper retorna segmentos separados (por exemplo, um a cada frase).
    # Precisamos juntar todos em um único texto.
    # .text contém o texto daquele segmento.
    # .strip() remove espaços extras no início/fim.
    
    # Vamos mostrar uma barra de progresso enquanto processa os segmentos.
    # Isso dá feedback visual ao usuário, especialmente para áudios longos.
    texto_segments = []
    segment_count = 0
    
    # last_update controla com que frequência atualizamos a tela.
    # Atualizar a cada caractere é muito rápido, então делаем a cada 0.1s.
    last_update = 0
    
    for segment in segments:
        texto_segments.append(segment.text.strip())
        segment_count += 1
        
        # Calcular tempo corrido
        elapsed = time_module.time() - start_time
        
        # Calcular progresso (se temos duração do áudio)
        if audio_duration and segment.end:
            progress = segment.end / audio_duration
        else:
            # Se não temos duração, usamos contagem de segmentos como proxy
            progress = 0  # Modo "trabalhando"
        
        # Atualizar显示 a cada 0.2 segundos (5 atualizações por segundo no máx)
        current_time = time_module.time()
        if current_time - last_update > 0.2:
            # Tempo estimado: se temos 30%done em 10s, total = 10/0.3 = 33s
            if progress > 0:
                time_remaining = format_time_estimate(elapsed, progress)
            else:
                time_remaining = "--:--"
            
            # Montar a mensagem de progresso
            elapsed_str = format_time(elapsed)
            
            if audio_duration and segment.end:
                # Mostrar barra de progresso com percentage
                bar_width = 30
                filled = int(bar_width * progress)
                bar = "█" * filled + "░" * (bar_width - filled)
                pct = progress * 100
                
                # Linha de progresso: [████████████░░░░░░░░░░░░░░░░] 45% | ⏱ 00:15 / ⏳ 00:18
                progress_line = f"\r[{bar}] {pct:5.1f}% | ⏱ {elapsed_str} / ⏳ {time_remaining}"
            else:
                # Sem duração: só mostra tempo corrido e contagem de segmentos
                progress_line = f"\rProcessando segmento {segment_count}... | ⏱ {elapsed_str}"
            
            # Escrever sem newline (\r volta ao início da linha)
            sys.stdout.write(progress_line)
            sys.stdout.flush()
            
            last_update = current_time

    # Terminar a linha de progresso com newline
    elapsed_total = time_module.time() - start_time
    sys.stdout.write("\n")
    sys.stdout.flush()
    
    print(f"Transcrição concluída em {format_time(elapsed_total)}")

    # " ".join() junta todos os segmentos com um espaço entre eles.
    # É mais eficiente que usar += em loops (que cria strings novas a cada iteração).
    texto = " ".join(texto_segments)

    # -------------------------------------------------------------------------
    # PARTE 7: Salvar o resultado
    # -------------------------------------------------------------------------
    # Se o usuário passou --output, usa esse caminho.
    # Se não, gera automático: audio.mp3 -> audio.txt
    if not texto:
        print("Nenhum texto transcrito.")
        return 1

    output_path = Path(args.output) if args.output else audio_path.with_suffix(".txt")

    # .write_text() é o método mais simples para escrever texto em arquivo.
    # encoding="utf-8" garante que caracteres especiais (ç, á, ã, etc) ficam certos.
    output_path.write_text(texto, encoding="utf-8")

    print(f"Salvo em: {output_path}")
    print(f"Caracteres transcritos: {len(texto)}")

    return 0  # 0 = tudo certo, sem erros!


# ================================================================================
# PONTO DE ENTRADA
# ================================================================================
# Python executa tudo que está no nível do arquivo quando roda o script.
# O bloco "if __name__ == '__main__'" é uma convenção que significa:
# "só execute main() se este arquivo for rodado diretamente, não importado".
if __name__ == "__main__":
    # exit(main()) garante que o programa termina com o código de retorno correto.
    # main() pode retornar 0 (sucesso) ou 1 (erro), e exit() passa isso para o SO.
    exit(main())
