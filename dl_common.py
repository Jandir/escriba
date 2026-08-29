import re
import sys
import yt_dlp
from typing import List, Callable, Optional, Any
from pathlib import Path
from utils import print_err, print_warn, print_info

def escriba_progress_hook(d):
    """Callback invocado periodicamente pelo yt-dlp durante o download de arquivos."""
    import sys
    if getattr(sys, "_escriba_interrupted", False):
        raise KeyboardInterrupt

def _normalize_lang_pattern(lang_str: str) -> str:
    if not lang_str:
        return ""
    if lang_str.startswith("^") or lang_str.endswith(".*"):
        return lang_str
    if "*" not in lang_str and "." not in lang_str:
        return f"^{lang_str}.*"
    return lang_str

def _download_video_common(
    video_id_str: str,
    url: str,
    yt_dlp_cmd_list: List[str],
    cookie_args_list: List[str],
    download_args: List[str],
    extra_dl_args: List[str],
    lang_filter_str: str,
    output_template_str: str,
    patterns_to_try: List[tuple],
    refresh_cookies_func: Callable[[Path, Path], List[str]],
    is_vimeo: bool = False
) -> int:
    lang_pattern = _normalize_lang_pattern(lang_filter_str)
    lang_regex = re.compile(lang_pattern, re.IGNORECASE)

    current_cookies = list(cookie_args_list)

    while True:
        base_args = yt_dlp_cmd_list[3:] + current_cookies + [
            "--ignore-no-formats-error",
            "--write-info-json",
            "--restrict-filenames",
        ]
        base_args.extend(download_args)
        base_args.extend(extra_dl_args)

        try:
            parsed_opts = yt_dlp.parse_options(base_args)[3]

            extract_opts = dict(parsed_opts)
            extract_opts.update({
                'skip_download': True,
                'quiet': True,
                'no_warnings': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
            })

            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if info is None:
                raise ValueError("Não foi possível extrair informações do vídeo (info é None)")

            subtitles = info.get('subtitles') or {}
            auto_captions = info.get('automatic_captions') or {}

            chosen_lang = None
            is_auto = False

            if is_vimeo:
                for pat_str, want_auto in patterns_to_try:
                    if not pat_str:
                        continue
                    normalized_pat = _normalize_lang_pattern(pat_str)
                    regex = re.compile(normalized_pat, re.IGNORECASE)

                    source_dict = auto_captions if want_auto else subtitles

                    for lang_code in source_dict.keys():
                        if regex.match(lang_code):
                            chosen_lang = lang_code
                            is_auto = want_auto
                            break
                    if chosen_lang:
                        break
            else:
                for lang_code in subtitles.keys():
                    if lang_regex.match(lang_code):
                        chosen_lang = lang_code
                        is_auto = False
                        break

                if not chosen_lang:
                    for lang_code in auto_captions.keys():
                        if lang_regex.match(lang_code):
                            chosen_lang = lang_code
                            is_auto = True
                            break

            download_opts = dict(parsed_opts)
            download_opts['progress_hooks'] = [escriba_progress_hook]

            if chosen_lang:
                download_opts.update({
                    'writesubtitles': not is_auto,
                    'writeautomaticsub': is_auto,
                    'subtitleslangs': [chosen_lang],
                })

                source_dict = auto_captions if is_auto else subtitles
                formats = source_dict.get(chosen_lang, [])
                if formats:
                    selected_format = next((f for f in formats if f.get('ext') == 'vtt'), formats[0])
                    info['requested_subtitles'] = {
                        chosen_lang: {
                            'ext': selected_format.get('ext'),
                            'data': selected_format.get('data'),
                            'url': selected_format.get('url'),
                        }
                    }
                else:
                    info['requested_subtitles'] = {}
            else:
                download_opts.update({
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                    'subtitleslangs': [],
                })
                info['requested_subtitles'] = {}

            with yt_dlp.YoutubeDL(download_opts) as ydl_dl:
                ydl_dl.process_info(info)

            return 0
        except Exception as error_obj:
            if getattr(sys, "_escriba_interrupted", False):
                raise KeyboardInterrupt

            error_str = str(error_obj)
            is_429 = "429" in error_str or "too many requests" in error_str.lower()

            if not is_vimeo and is_429:
                print_warn(f"\n⚠ [HTTP 429] Limite de requisições excedido no vídeo {video_id_str}.")
                print_warn("O YouTube bloqueou temporariamente este IP ou sessão (Too Many Requests).")
                print_warn("Por favor, realize os seguintes passos para liberação:")
                print_warn("  1. Abra o YouTube no navegador Google Chrome desta máquina.")
                print_warn("  2. Reproduza qualquer vídeo para verificar/resolver CAPTCHAs.")
                print_warn("  3. Caso o IP esteja bloqueado, altere a VPN ou mude sua conexão.")
                print_info("Pressione ENTER para renovar os cookies e tentar novamente, digite 'p' + ENTER para pular este vídeo, ou Ctrl+C para abortar...")
                try:
                    if not sys.stdin.isatty():
                        print_warn("Ambiente não-interativo detectado. Pulando vídeo automaticamente devido a erro HTTP 429.")
                        return 1
                    user_input = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print_err("\nProcesso interrompido pelo usuário.")
                    raise KeyboardInterrupt

                if user_input == "p":
                    print_warn(f"Vídeo {video_id_str} pulado pelo usuário devido a limite de requisições.")
                    return 1

                try:
                    current_cookies = refresh_cookies_func(
                        Path.cwd(), Path(__file__).parent.resolve()
                    )
                except Exception as e:
                    print_warn(f"Erro ao renovar cookies: {e}")
                continue

            print_warn(f"Erro ao baixar vídeo {video_id_str}: {error_obj}. Tentando renovar cookies do navegador...")
            try:
                new_cookies_args_list: List[str] = refresh_cookies_func(
                    Path.cwd(), Path(__file__).parent.resolve()
                )

                base_args_retry = yt_dlp_cmd_list[3:] + new_cookies_args_list + [
                    "--ignore-no-formats-error",
                    "--write-info-json",
                    "--restrict-filenames",
                ] + download_args + extra_dl_args

                parsed_opts_retry = yt_dlp.parse_options(base_args_retry)[3]
                extract_opts_retry = dict(parsed_opts_retry)
                extract_opts_retry.update({
                    'skip_download': True,
                    'quiet': True,
                    'no_warnings': True,
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                })

                with yt_dlp.YoutubeDL(extract_opts_retry) as ydl:
                    info = ydl.extract_info(url, download=False)

                if info is None:
                    raise ValueError("Não foi possível extrair informações do vídeo após renovação de cookies (info é None)")

                subtitles = info.get('subtitles') or {}
                auto_captions = info.get('automatic_captions') or {}

                chosen_lang = None
                is_auto = False

                if is_vimeo:
                    for pat_str, want_auto in patterns_to_try:
                        if not pat_str:
                            continue
                        normalized_pat = _normalize_lang_pattern(pat_str)
                        regex = re.compile(normalized_pat, re.IGNORECASE)
                        source_dict = auto_captions if want_auto else subtitles
                        for lang_code in source_dict.keys():
                            if regex.match(lang_code):
                                chosen_lang = lang_code
                                is_auto = want_auto
                                break
                        if chosen_lang:
                            break
                else:
                    for lang_code in subtitles.keys():
                        if lang_regex.match(lang_code):
                            chosen_lang = lang_code
                            is_auto = False
                            break
                    if not chosen_lang:
                        for lang_code in auto_captions.keys():
                            if lang_regex.match(lang_code):
                                chosen_lang = lang_code
                                is_auto = True
                                break

                download_opts_retry = dict(parsed_opts_retry)
                download_opts_retry['progress_hooks'] = [escriba_progress_hook]
                if chosen_lang:
                    download_opts_retry.update({
                        'writesubtitles': not is_auto,
                        'writeautomaticsub': is_auto,
                        'subtitleslangs': [chosen_lang],
                    })
                    source_dict = auto_captions if is_auto else subtitles
                    formats = source_dict.get(chosen_lang, [])
                    if formats:
                        selected_format = next((f for f in formats if f.get('ext') == 'vtt'), formats[0])
                        info['requested_subtitles'] = {
                            chosen_lang: {
                                'ext': selected_format.get('ext'),
                                'data': selected_format.get('data'),
                                'url': selected_format.get('url'),
                            }
                        }
                    else:
                        info['requested_subtitles'] = {}
                else:
                    download_opts_retry.update({
                        'writesubtitles': False,
                        'writeautomaticsub': False,
                        'subtitleslangs': [],
                    })
                    info['requested_subtitles'] = {}

                with yt_dlp.YoutubeDL(download_opts_retry) as ydl_dl:
                    ydl_dl.process_info(info)
                return 0
            except Exception as retry_error:
                if getattr(sys, "_escriba_interrupted", False):
                    raise KeyboardInterrupt

                retry_str = str(retry_error)
                if not is_vimeo and ("429" in retry_str or "too many requests" in retry_str.lower()):
                    print_warn(f"\n⚠ [HTTP 429] Limite de requisições excedido no vídeo {video_id_str} após tentativa de correção automática.")
                    print_warn("Por favor, realize os seguintes passos para liberação:")
                    print_warn("  1. Abra o YouTube no navegador Google Chrome desta máquina.")
                    print_warn("  2. Reproduza qualquer vídeo para verificar/resolver CAPTCHAs.")
                    print_warn("  3. Caso o IP esteja bloqueado, altere a VPN ou mude sua conexão.")
                    print_info("Pressione ENTER para renovar os cookies e tentar novamente, digite 'p' + ENTER para pular este vídeo, ou Ctrl+C para abortar...")
                    try:
                        if not sys.stdin.isatty():
                            print_warn("Ambiente não-interativo detectado. Pulando vídeo automaticamente devido a erro HTTP 429.")
                            return 1
                        user_input = input().strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print_err("\nProcesso interrompido pelo usuário.")
                        raise KeyboardInterrupt

                    if user_input == "p":
                        print_warn(f"Vídeo {video_id_str} pulado pelo usuário devido a limite de requisições.")
                        return 1

                    try:
                        current_cookies = refresh_cookies_func(
                            Path.cwd(), Path(__file__).parent.resolve()
                        )
                    except Exception as e:
                        print_warn(f"Erro ao renovar cookies: {e}")
                    continue

                print_err(f"Erro crítico após renovar cookies no vídeo {video_id_str}: {retry_error}")
                return 2
