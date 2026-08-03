import json
from pathlib import Path

def test_part():
    db_path = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell/escriba_johnmaxwell.json")
    with open(db_path, "r", encoding="utf-8") as f:
        text_content = f.read()
        
    part = text_content[:123068]
    print(f"Length of part: {len(part)}")
    print("Last 100 characters of part:")
    print(repr(part[-100:]))
    
    try:
        data = json.loads(part)
        print("[OK] SUCCESS: Part is valid JSON!")
        print(f"Root keys: {list(data.keys())}")
        if "videos" in data:
            print(f"Number of videos: {len(data['videos'])}")
            if len(data['videos']) > 0:
                print(f"First video: {data['videos'][0].get('title')} ({data['videos'][0].get('video_id')})")
                print(f"Last video: {data['videos'][-1].get('title')} ({data['videos'][-1].get('video_id')})")
    except Exception as e:
        print(f"[X] FAILED to parse part: {e}")

if __name__ == "__main__":
    test_part()
