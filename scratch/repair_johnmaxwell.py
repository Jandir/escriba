import json
import shutil
from pathlib import Path

def repair_database():
    channel_dir = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell")
    db_path = channel_dir / "escriba_johnmaxwell.json"
    backup_path = channel_dir / "escriba_johnmaxwell.json.bak"

    print("=" * 80)
    print("REPAIRING JOHN MAXWELL DATABASE")
    print("=" * 80)

    # 1. Backup the database
    print(f"Creating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)
    print("[OK] Backup created successfully.")

    # 2. Truncate the file at offset 123068
    print("Truncating corrupted trailing NUL bytes and leftover data...")
    with open(db_path, "r", encoding="utf-8") as f:
        text_content = f.read()
        
    valid_json_part = text_content[:123068]
    
    # 3. Parse JSON
    try:
        data = json.loads(valid_json_part)
        print("[OK] Truncated partition parsed successfully.")
    except Exception as e:
        print(f"[X] Failed to parse truncated partition: {e}")
        return

    # 4. Correct the mismatched/truncated IDs
    id_mapping = {
        "ll-2_vmXK06": "2_vmXK06-Iw",
        "ll-6iZnXLFh": "6iZnXLFh-yI",
        "ll-haDjkPhV": "haDjkPhV-lc",
        "ll-prU6DNyX": "prU6DNyX-vI",
        "ll-q-KRwmwq": "q-KRwmwq-qE",
        "ll-VWwptuyk": "VWwptuyk-aY"
    }

    videos = data.get("videos", [])
    new_videos = []
    
    removed_fake = False
    corrected_count = 0

    for video in videos:
        vid = video.get("video_id") or video.get("id")
        
        # Remove fake ID
        if vid == "johnmaxwell":
            removed_fake = True
            print("- Removed fake video entry: 'johnmaxwell'")
            continue
            
        # Fix truncated IDs
        if vid in id_mapping:
            old_vid = vid
            new_vid = id_mapping[old_vid]
            video["video_id"] = new_vid
            corrected_count += 1
            print(f"- Corrected video ID: '{old_vid}' -> '{new_vid}'")
            
        new_videos.append(video)

    # 5. Add missing IDs that are in the archive
    missing_ids = ["z9-w_OlrF-8", "jZ3wFLqjCcM"]
    for m_id in missing_ids:
        # Check if already exists (should not, but just in case)
        if not any(v.get("video_id") == m_id for v in new_videos):
            new_videos.append({
                "video_id": m_id,
                "consolidated_notebooklm": True
            })
            print(f"- Added missing archived video entry: '{m_id}'")

    data["videos"] = new_videos

    # 6. Save the repaired database
    print(f"Writing repaired database to: {db_path}")
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("[OK] Repaired database saved successfully!")
    print("=" * 80)

if __name__ == "__main__":
    repair_database()
