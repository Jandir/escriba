import sys
import os
from pathlib import Path
import pytest
from unittest.mock import MagicMock

# Adiciona diretório pai no path para facilitar import local
sys.path.insert(0, str(Path(__file__).parent.parent))

# Patch escriba because it has SyntaxError on python 3.12 due to t""
sys.modules['escriba'] = MagicMock()
# lexiz depends on escriba, and maybe has its own syntax errors if we do this, let's just mock it
sys.modules['lexis'] = MagicMock()

from convert_all_bases import find_channel_directories

def test_find_channel_directories_non_existent_path(tmp_path):
    """Should safely ignore non-existent base paths."""
    base_paths = [str(tmp_path / "does_not_exist")]
    result = find_channel_directories(base_paths)
    assert result == []

def test_find_channel_directories_with_escriba_json(tmp_path):
    """Should discover channels that contain escriba_*.json files."""
    channel_dir = tmp_path / "MyChannel"
    channel_dir.mkdir()
    (channel_dir / "escriba_state.json").touch()

    result = find_channel_directories([str(tmp_path)])
    assert len(result) == 1
    assert result[0] == channel_dir

def test_find_channel_directories_with_archive_dir(tmp_path):
    """Should discover channels that contain an 'archive' directory."""
    channel_dir = tmp_path / "ChannelWithArchive"
    channel_dir.mkdir()
    (channel_dir / "archive").mkdir()

    result = find_channel_directories([str(tmp_path)])
    assert len(result) == 1
    assert result[0] == channel_dir

def test_find_channel_directories_with_volumes_dir(tmp_path):
    """Should discover channels that contain a 'volumes_notebooklm' directory."""
    channel_dir = tmp_path / "ChannelWithVolumes"
    channel_dir.mkdir()
    (channel_dir / "volumes_notebooklm").mkdir()

    result = find_channel_directories([str(tmp_path)])
    assert len(result) == 1
    assert result[0] == channel_dir

def test_find_channel_directories_excluded_directories(tmp_path):
    """Should ignore internal/ignored directories like .git or tests."""
    # Create an invalid channel named .git with an archive
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "archive").mkdir()

    # Create a valid channel containing a .git dir
    valid_channel = tmp_path / "ValidChannel"
    valid_channel.mkdir()
    (valid_channel / "archive").mkdir()
    (valid_channel / ".git").mkdir()

    result = find_channel_directories([str(tmp_path)])

    # Should only find ValidChannel, not .git
    assert result == sorted([valid_channel])

def test_find_channel_directories_multiple_paths_and_sorting(tmp_path):
    """Should handle multiple base paths, deduplicate, and sort the result."""
    base1 = tmp_path / "base1"
    base1.mkdir()
    base2 = tmp_path / "base2"
    base2.mkdir()

    channel_b = base1 / "ChannelB"
    channel_b.mkdir()
    (channel_b / "escriba_123.json").touch()

    channel_a = base2 / "ChannelA"
    channel_a.mkdir()
    (channel_a / "archive").mkdir()

    # Using the same path twice to test deduplication
    result = find_channel_directories([str(base1), str(base2), str(base1)])

    assert len(result) == 2
    assert result == sorted([channel_a, channel_b])  # Sorted alphabetically
