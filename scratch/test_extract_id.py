import re
import sys
from pathlib import Path

# Add current workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import extract_video_id

def test():
    filenames = [
        "johnmaxwell-2_vmXK06-Iw-en.md",
        "johnmaxwell-6iZnXLFh-yI-en.md",
        "johnmaxwell-haDjkPhV-lc-en.md",
        "johnmaxwell-prU6DNyX-vI-en.md",
        "johnmaxwell-q-KRwmwq-qE-en.md",
        "johnmaxwell-VWwptuyk-aY-en.md"
    ]
    
    print("Testing extract_video_id:")
    print("=" * 80)
    for f in filenames:
        extracted = extract_video_id(f)
        print(f"File: {f} -> Extracted ID: '{extracted}'")
        
    print("\nTesting regex patterns:")
    _YT_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{11}$')
    print(f"Does 'VWwptuyk-aY' match _YT_ID_PATTERN? {_YT_ID_PATTERN.match('VWwptuyk-aY') is not None}")

if __name__ == "__main__":
    test()
