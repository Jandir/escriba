from pathlib import Path

def inspect_files():
    archive_dir = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell/archive")
    search_terms = ['z9-w_', 'haDjk', '2_vm', '6iZn', 'VWwp', 'jZ3w', 'q-KR', 'prU6', 'johnmaxwell']
    
    print("Files matching search terms in archive:")
    print("=" * 80)
    for file_path in archive_dir.glob("*.md"):
        filename = file_path.name
        for term in search_terms:
            if term in filename:
                print(f"Match for '{term}': {filename} (Size: {file_path.stat().st_size})")

if __name__ == "__main__":
    inspect_files()
