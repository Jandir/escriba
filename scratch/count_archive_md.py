import os
import json
import re
from pathlib import Path

def count_archive_md():
    channel_dir = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell")
    db_path = channel_dir / "escriba_johnmaxwell.json"
    archive_dir = channel_dir / "archive"

    # Read partition
    with open(db_path, "r", encoding="utf-8") as f:
        text = f.read()
    part = text[:123068]
    data = json.loads(part)
    db_ids = {v.get("video_id") or v.get("id") for v in data.get("videos", []) if v.get("video_id") or v.get("id")}
    print(f"Number of video entries in recovered JSON: {len(db_ids)}")

    if not archive_dir.exists():
        print("Archive directory does not exist!")
        return

    md_files = list(archive_dir.glob("*.md"))
    print(f"Total .md files in archive: {len(md_files)}")

    # Extract IDs from .md files
    # Format is johnmaxwell-<video_id>-en.md or johnmaxwell-<video_id>-en-orig.md
    archive_ids = set()
    filename_id_regex = re.compile(r"johnmaxwell-([A-Za-z0-9_-]{11})-.*\.md$")
    vimeo_filename_id_regex = re.compile(r"johnmaxwell-(\d{7,12})-.*\.md$")

    for file_path in md_files:
        filename = file_path.name
        m = filename_id_regex.match(filename)
        if not m:
            m = vimeo_filename_id_regex.match(filename)
        if m:
            archive_ids.add(m.group(1))
        else:
            # Fallback check
            print(f"Failed to extract ID from filename: {filename}")

    print(f"Number of unique video IDs in archive (.md): {len(archive_ids)}")

    # Check differences
    missing_in_db = archive_ids - db_ids
    missing_in_archive = db_ids - archive_ids

    print(f"IDs in archive (.md) but missing in DB: {len(missing_in_db)}")
    if missing_in_db:
        print("First 10 missing in DB:")
        print(list(missing_in_db)[:10])

    print(f"IDs in DB but missing in archive (.md): {len(missing_in_archive)}")
    if missing_in_archive:
        print("First 10 missing in archive (.md):")
        print(list(missing_in_archive)[:10])

if __name__ == "__main__":
    count_archive_md()
