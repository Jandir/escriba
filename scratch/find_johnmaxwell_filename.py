from pathlib import Path

def find_file():
    archive_dir = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell/archive")
    for file_path in archive_dir.glob("*.md"):
        filename = file_path.name
        if "johnmaxwell-johnmaxwell" in filename:
            print(f"FOUND: {filename} (Size: {file_path.stat().st_size})")

if __name__ == "__main__":
    find_file()
