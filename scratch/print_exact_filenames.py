from pathlib import Path

def print_exact_filenames():
    archive_dir = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell/archive")
    targets = ['haDjkPhV', 'VWwptuyk', '2_vmXK06', '6iZnXLFh', 'q-KRwmwq', 'prU6DNyX']
    
    print("Exact filenames in archive matching targets:")
    print("=" * 80)
    for file_path in archive_dir.glob("*.md"):
        filename = file_path.name
        for target in targets:
            if target in filename:
                print(f"Target '{target}': {filename}")

if __name__ == "__main__":
    print_exact_filenames()
