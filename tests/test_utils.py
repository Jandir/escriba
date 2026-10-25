import pytest
from unittest.mock import patch

from utils import (
    extract_video_id,
    format_date,
    print_ok,
    print_err,
    print_warn,
    print_info,
    print_skip,
    print_dl,
    print_section,
    print_header,
    print_countdown,
    ICON_OK,
    ICON_ERR,
    ICON_WARN,
    ICON_INFO,
    ICON_SKIP,
    ICON_DL,
    GREEN,
    BRED,
    YELLOW,
    DIM,
    BCYAN,
    BOLD,
    BWHITE,
    RESET,
)

def test_extract_video_id_happy_path():
    assert extract_video_id("video-abc123DEF45.info.json") == "abc123DEF45"
    assert extract_video_id("canal-12345678901.pt.srt") == "12345678901"
    assert extract_video_id("/path/to/my_video-ZHbX0yoC8uo.info.json") == "ZHbX0yoC8uo"
    assert extract_video_id("ZHbX0yoC8uo") == "ZHbX0yoC8uo"

def test_extract_video_id_with_suffixes():
    assert extract_video_id("video-abc123DEF45-orig.md") == "abc123DEF45"
    assert extract_video_id("video-abc123DEF45.pt-br.srt") == "abc123DEF45"
    assert extract_video_id("video-abc123DEF45.en.vtt") == "abc123DEF45"
    assert extract_video_id("video-abc123DEF45-en.txt") == "abc123DEF45"

def test_extract_video_id_embedded():
    # If the ID is embedded somewhere, it requires boundary characters that do not match the ID pattern,
    # or the fallback pattern `([A-Za-z0-9_-]{11})` could pick an unintended 11-char sequence if there are
    # valid adjacent characters. We must use a boundary to test it properly, for example spaces or special chars.
    # We provide a clear boundary '!' that is not in `_YT_ID_CHAR_PATTERN` to ensure the regex matches exactly the 11 chars.
    assert extract_video_id("prefix!abc123DEF45!suffix.mp4") == "abc123DEF45"

def test_extract_video_id_not_found():
    assert extract_video_id("no_id_here.mp4") == "Sem ID"
    assert extract_video_id("short.mp4") == "Sem ID"
    assert extract_video_id("") == "Sem ID"

def test_format_date_happy_path():
    assert format_date("20260316") == "2026-03-16"
    assert format_date(20260316) == "2026-03-16"
    assert format_date("2023-12-25") == "2023-12-25"

def test_format_date_edge_cases():
    assert format_date("  20230101  ") == "2023-01-01"
    assert format_date("Unexpected Date") == "Unexpected Date"

def test_format_date_error_conditions():
    assert format_date(None) == "Desconhecida"
    assert format_date("") == "Desconhecida"
    assert format_date("None") == "Desconhecida"
    assert format_date("N/A") == "Desconhecida"

def test_print_ok(capsys):
    print_ok("Test OK")
    captured = capsys.readouterr()
    assert captured.out == f"{ICON_OK}  {GREEN}Test OK{RESET}\n"

def test_print_err(capsys):
    print_err("Test Error")
    captured = capsys.readouterr()
    assert captured.out == f"{ICON_ERR}  {BRED}Test Error{RESET}\n"

def test_print_warn(capsys):
    print_warn("Test Warning")
    captured = capsys.readouterr()
    assert captured.out == f"{ICON_WARN}  {YELLOW}Test Warning{RESET}\n"

def test_print_info(capsys):
    print_info("Test Info")
    captured = capsys.readouterr()
    assert captured.out == f"{ICON_INFO}  {DIM}Test Info{RESET}\n"

def test_print_skip(capsys):
    print_skip("Test Skip")
    captured = capsys.readouterr()
    assert captured.out == f"{ICON_SKIP}  {DIM}Test Skip{RESET}\n"

def test_print_dl(capsys):
    print_dl("Test DL")
    captured = capsys.readouterr()
    assert captured.out == f"{ICON_DL}  {BCYAN}Test DL{RESET}\n"

def test_print_section(capsys):
    print_section("Test Section")
    captured = capsys.readouterr()
    assert captured.out == f"\n{BOLD}{BWHITE}Test Section{RESET}\n\n"

def test_print_header(capsys):
    print_header("1.0.0")
    captured = capsys.readouterr()
    assert captured.out == f"\n{BOLD}{BCYAN}Escriba v1.0.0{RESET}\n\n"

@patch('time.sleep')
def test_print_countdown(mock_sleep, capsys):
    print_countdown(2, "Waiting")
    captured = capsys.readouterr()
    assert mock_sleep.call_count == 2
    # Verify the last carriage return and clear line was emitted
    assert "\r\x1b[K" in captured.out

@patch('time.sleep')
def test_print_countdown_keyboard_interrupt(mock_sleep, capsys):
    mock_sleep.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        print_countdown(2, "Waiting")
    captured = capsys.readouterr()
    # Verify the terminal is cleared properly on interrupt
    assert "\r\x1b[K" in captured.out
