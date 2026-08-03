import os
import json
import re
import sys
from pathlib import Path

def format_size(num_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} TB"

def run_integrity_check():
    channel_dir = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell")
    db_path = channel_dir / "escriba_johnmaxwell.json"
    archive_dir = channel_dir / "archive"

    print("=" * 80)
    print("INSPECTING JOHN MAXWELL DATABASE INTEGRITY")
    print("=" * 80)
    print(f"Channel Folder: {channel_dir}")
    print(f"Database File:  {db_path}")
    print(f"Archive Folder: {archive_dir}")
    print("-" * 80)

    # 1. Check Directory and Files Existence
    if not channel_dir.exists():
        print(f"ERROR: Channel directory {channel_dir} does not exist!")
        return

    if not db_path.exists():
        print(f"ERROR: Database file {db_path} does not exist!")
        return

    # Check database file size
    db_size = db_path.stat().st_size
    print(f"Database Size: {format_size(db_size)}")

    # 2. Try Parsing JSON
    db_data = None
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            db_data = json.load(f)
        print("[OK] JSON Parsing: SUCCESS (Valid JSON Syntax)")
    except json.JSONDecodeError as jde:
        print(f"[X] JSON Parsing: FAILED (Corrupted JSON Syntax)")
        print(f"  Error message: {jde.msg}")
        print(f"  Line: {jde.lineno}, Column: {jde.colno}, Char: {jde.pos}")
        return
    except Exception as e:
        print(f"[X] JSON Parsing: FAILED with unexpected error: {e}")
        return

    # 3. Schema & Types Verification
    print("-" * 80)
    print("DATABASE SCHEMA & STRUCTURE VERIFICATION")
    print("-" * 80)
    
    errors = []
    warnings = []

    if not isinstance(db_data, dict):
        errors.append(f"Root elements must be a dictionary, got: {type(db_data).__name__}")
        print(f"[X] Root object: FAILED (is a {type(db_data).__name__}, expected dict)")
        return
    else:
        print("[OK] Root object: SUCCESS (dictionary)")

    # Check top-level keys
    print("Top-level keys found:", list(db_data.keys()))
    
    videos_list = None
    if "videos" not in db_data:
        errors.append("Missing 'videos' key at root level.")
        print("[X] Key 'videos': FAILED (missing)")
    else:
        videos_list = db_data["videos"]
        if not isinstance(videos_list, list):
            errors.append(f"'videos' key must be a list, got: {type(videos_list).__name__}")
            print(f"[X] 'videos' type: FAILED (got {type(videos_list).__name__}, expected list)")
            videos_list = None
        else:
            print(f"[OK] Key 'videos': SUCCESS (contains {len(videos_list)} entries)")

    # 4. Entry-Level Data Validation
    if videos_list is not None:
        print("\nValidating individual video entries...")
        
        youtube_id_pattern = re.compile(r"^[A-Za-z0-9_-]{11}$")
        vimeo_id_pattern = re.compile(r"^\d{7,12}$")
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        seen_ids = {}
        empty_titles = 0
        invalid_ids = []
        invalid_dates = []

        for idx, video in enumerate(videos_list):
            if not isinstance(video, dict):
                errors.append(f"Video entry at index {idx} is not a dictionary: {type(video).__name__}")
                continue

            video_id = video.get("video_id") or video.get("id")
            
            # Check ID
            if not video_id:
                errors.append(f"Video entry at index {idx} is missing a video ID (keys: {list(video.keys())})")
                continue

            # Track duplicates
            if video_id in seen_ids:
                seen_ids[video_id].append(idx)
            else:
                seen_ids[video_id] = [idx]

            # Validate ID format
            is_youtube = youtube_id_pattern.match(str(video_id))
            is_vimeo = vimeo_id_pattern.match(str(video_id))
            if not (is_youtube or is_vimeo):
                invalid_ids.append((video_id, idx))

            # Validate Title
            title = video.get("title")
            # Note: Lexis state files might only have video_id and consolidated_notebooklm
            if "title" in video:
                if not title or str(title).strip() in ["", "N/A", "Avulso"]:
                    empty_titles += 1

            # Validate Date format
            pub_date = video.get("publish_date")
            if pub_date:
                if str(pub_date) in ["N/A", "Desconhecida", ""]:
                    pass
                elif not date_pattern.match(str(pub_date)):
                    invalid_dates.append((video_id, pub_date, idx))

        # Print detailed report on video entries
        print(f"  Processed {len(videos_list)} video entries.")
        
        # Report duplicates
        duplicates = {k: v for k, v in seen_ids.items() if len(v) > 1}
        if duplicates:
            warnings.append(f"Found {len(duplicates)} duplicate video IDs in the database.")
            print(f"  [!] Duplicates: {len(duplicates)} IDs appear multiple times!")
            for vid, indices in list(duplicates.items())[:5]:
                print(f"    - ID '{vid}' appears at indices: {indices}")
        else:
            print("  [OK] Duplicates: None found")

        # Report invalid IDs
        if invalid_ids:
            errors.append(f"Found {len(invalid_ids)} video entries with invalid ID formats.")
            print(f"  [X] Invalid IDs: {len(invalid_ids)} found!")
            for vid, idx in invalid_ids[:5]:
                print(f"    - Index {idx}: '{vid}'")
        else:
            print("  [OK] ID Formats: All valid")

        # Report empty/placeholder titles
        if empty_titles:
            warnings.append(f"Found {empty_titles} video entries with missing/placeholder titles.")
            print(f"  [!] Titles: {empty_titles} entries have empty/placeholder titles.")
        else:
            print("  [OK] Titles: All entries have valid titles (where titles exist)")

        # Report invalid dates
        if invalid_dates:
            warnings.append(f"Found {len(invalid_dates)} video entries with invalid date formats.")
            print(f"  [!] Date Format: {len(invalid_dates)} entries have invalid formats.")
        else:
            print("  [OK] Date Formats: All valid (where dates exist)")

    # 5. Archive Folder Synchronization Audit
    print("-" * 80)
    print("ARCHIVE FILES SYNCHRONIZATION AUDIT")
    print("-" * 80)
    
    if not archive_dir.exists():
        warnings.append(f"Archive folder '{archive_dir}' does not exist.")
        print(f"[!] Archive folder does not exist at: {archive_dir}")
    else:
        md_files = list(archive_dir.glob("*.md"))
        print(f"Files found in archive: {len(md_files)} .md files")

        # Extract IDs from archive files
        archive_ids = set()
        filename_id_regex = re.compile(r"johnmaxwell-([A-Za-z0-9_-]{11})-.*\.md$")
        vimeo_filename_id_regex = re.compile(r"johnmaxwell-(\d{7,12})-.*\.md$")
        
        for file_path in md_files:
            filename = file_path.name
            m = filename_id_regex.match(filename)
            if not m:
                m = vimeo_filename_id_regex.match(filename)
                
            if m:
                video_id = m.group(1)
                archive_ids.add(video_id)
            else:
                warnings.append(f"Could not extract video ID from archive filename: {filename}")
                print(f"  [!] Filename Pattern Match Failed: {filename}")
                continue

        db_ids = set(seen_ids.keys()) if videos_list is not None else set()

        # Database entries without archive files (Orphan DB Entries)
        db_only_ids = db_ids - archive_ids
        if db_only_ids:
            warnings.append(f"{len(db_only_ids)} database entries do not have a matching .md in the archive.")
            print(f"  [!] Orphan DB Entries: {len(db_only_ids)} entries in JSON have no matching .md file in /archive")
            for vid in list(db_only_ids)[:5]:
                print(f"    - ID: {vid}")
        else:
            print("  [OK] DB-to-Archive Sync: All DB entries have matching archive files")

        # Archive files without DB entries (Orphan Archive Files)
        archive_only_ids = archive_ids - db_ids
        if archive_only_ids:
            warnings.append(f"{len(archive_only_ids)} archive files are not registered in the database.")
            print(f"  [!] Orphan Archive Files: {len(archive_only_ids)} .md files are not registered in the JSON database")
            for vid in list(archive_only_ids)[:5]:
                print(f"    - ID: {vid}")
        else:
            print("  [OK] Archive-to-DB Sync: All archive files are registered in the DB")

    # 6. Overall Verdict
    print("=" * 80)
    print("SUMMARY VERDICT")
    print("=" * 80)
    print(f"Errors:   {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    print("-" * 80)
    
    if errors:
        print("STATUS: [X] CRITICAL INTEGRITY ERRORS FOUND")
        for err in errors:
            print(f" - ERROR: {err}")
    elif warnings:
        print("STATUS: [!] STABILITY WARNINGS FOUND (Database is readable, but needs optimization/repair)")
        for wrn in warnings:
            print(f" - WARNING: {wrn}")
    else:
        print("STATUS: [OK] INTEGRITY VERIFICATION PASSED (Database is fully healthy)")
    print("=" * 80)

if __name__ == "__main__":
    run_integrity_check()
