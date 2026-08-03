from pathlib import Path

def analyze_file():
    db_path = Path("C:/Users/Jandir/Documents/youtubedownloads/johnmaxwell/escriba_johnmaxwell.json")
    
    # Read as text to get the character string
    with open(db_path, "r", encoding="utf-8") as f:
        text_content = f.read()
        
    # Read as bytes to get raw bytes
    with open(db_path, "rb") as f:
        byte_content = f.read()
        
    print(f"File size in chars: {len(text_content)}")
    print(f"File size in bytes: {len(byte_content)}")
    
    # Find all NUL characters in text
    nul_char_indices = [i for i, c in enumerate(text_content) if c == '\x00']
    print(f"Total NUL characters: {len(nul_char_indices)}")
    if nul_char_indices:
        print(f"First NUL char index: {nul_char_indices[0]}")
        print(f"Last NUL char index: {nul_char_indices[-1]}")
        
    # Find all NUL bytes in raw bytes
    nul_byte_indices = [i for i, b in enumerate(byte_content) if b == 0]
    print(f"Total NUL bytes: {len(nul_byte_indices)}")
    if nul_byte_indices:
        print(f"First NUL byte index: {nul_byte_indices[0]}")
        print(f"Last NUL byte index: {nul_byte_indices[-1]}")
        
    # Let's inspect the text around the first NUL character
    if nul_char_indices:
        idx = nul_char_indices[0]
        start = max(0, idx - 100)
        end = min(len(text_content), idx + 100)
        print("\nText around first NUL char:")
        print("=" * 80)
        print(repr(text_content[start:end]))
        print("=" * 80)
        
        # Let's see what is after the block of NUL characters
        # Find the first non-NUL character after the first NUL
        non_nul_after = -1
        for i in range(idx, len(text_content)):
            if text_content[i] != '\x00':
                non_nul_after = i
                break
        print(f"First non-NUL character after NUL block: index {non_nul_after}")
        if non_nul_after != -1:
            print("Text after NUL block:")
            print("=" * 80)
            print(text_content[non_nul_after:non_nul_after+300])
            print("=" * 80)

if __name__ == "__main__":
    analyze_file()
