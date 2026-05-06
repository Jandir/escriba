import re
from pathlib import Path

# Mock functions from escriba.py
def get_provider(url: str) -> str:
    """Retorna 'vimeo' ou 'youtube' baseado na URL."""
    if not url: return "youtube"
    # Logic from the latest escriba.py update
    if "vimeo.com" in url or re.match(r"^\d+$", url):
        return "vimeo"
    return "youtube"

def test_get_provider():
    test_cases = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("dQw4w9WgXcQ", "youtube"),
        ("https://vimeo.com/22439234", "vimeo"),
        ("22439234", "vimeo"),
        ("", "youtube"),
        ("random_string", "youtube"),
    ]
    for url, expected in test_cases:
        actual = get_provider(url)
        assert actual == expected, f"Failed for {url}: expected {expected}, got {actual}"
    print("get_provider tests passed!")

def test_disk_cache_regex():
    # Logic from process_videos in escriba.py
    prefix = "MyChannel-"
    
    # Files to test
    files = [
        "MyChannel-dQw4w9WgXcQ.en.srt",      # YouTube
        "MyChannel-22439234.pt.srt",         # Vimeo
        "MyChannel-invalid.txt",             # Invalid ID format
        "OtherChannel-22439234.srt",         # Wrong prefix
    ]
    
    cache = {}
    
    regex_pattern = fr"^{re.escape(prefix)}([A-Za-z0-9_-]{{11}}|\d+)"
    
    for filename in files:
        if filename.startswith(prefix):
            match = re.search(regex_pattern, filename)
            if match:
                vid_id = match.group(1)
                if vid_id not in cache: cache[vid_id] = []
                cache[vid_id].append(filename)
                
    assert "dQw4w9WgXcQ" in cache
    assert "22439234" in cache
    assert "invalid" not in cache
    assert len(cache) == 2
    print("disk_cache_regex tests passed!")

if __name__ == "__main__":
    test_get_provider()
    test_disk_cache_regex()
