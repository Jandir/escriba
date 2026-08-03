import json
from pathlib import Path

def inspect_mismatched():
    db_path = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell/escriba_johnmaxwell.json")
    with open(db_path, "r", encoding="utf-8") as f:
        text = f.read()
    part = text[:123068]
    data = json.loads(part)
    videos = data.get("videos", [])
    
    mismatched_db_ids = ['johnmaxwell', 'll-VWwptuyk', 'll-haDjkPhV', 'll-q-KRwmwq', 'll-2_vmXK06', 'll-prU6DNyX', 'll-6iZnXLFh']
    
    print("Mismatched DB entries:")
    print("=" * 80)
    for v in videos:
        vid = v.get("video_id") or v.get("id")
        if vid in mismatched_db_ids:
            print(f"ID: {vid} -> Content: {v}")
            
    print("\nLet's also look at all IDs containing '-' to check if there are others:")
    print("=" * 80)
    hyphen_ids = [v.get("video_id") or v.get("id") for v in videos if '-' in str(v.get("video_id") or v.get("id"))]
    print(f"Total IDs with hyphen: {len(hyphen_ids)}")
    print(f"Sample hyphen IDs: {hyphen_ids[:10]}")

if __name__ == "__main__":
    inspect_mismatched()
