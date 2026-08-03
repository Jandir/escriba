import sys
from pathlib import Path

# Add current workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import extract_video_id

def find_files():
    archive_dir = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell/archive")
    print("Files resulting in ID 'johnmaxwell':")
    print("=" * 80)
    
    found = False
    for file_path in archive_dir.glob("*.md"):
        filename = file_path.name
        extracted = extract_video_id(filename)
        if extracted == "johnmaxwell":
            print(f"File: {filename} (Size: {file_path.stat().st_size})")
            found = True
            
    if not found:
        print("No files in the archive parse to the ID 'johnmaxwell'!")

if __name__ == "__main__":
    find_files()
