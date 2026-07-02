
## 2025-07-02 - Cross-Domain Cookie Leakage in yt-dlp Cookie Filter
**Vulnerability:** The cookie filtering logic for `yt-dlp` used naive substring matching (`"youtube.com" in line_str`) to validate Netscape HTTP Cookie domains, which would erroneously match malicious domains like `evil-youtube.com`, leaking sensitive cookies across domains.
**Learning:** Broad substring matches for domain validation are inherently insecure. Furthermore, `#HttpOnly_` prefix in the Netscape cookie file format requires special handling as it modifies the domain string structure but is not merely a comment.
**Prevention:** Always strictly parse cookie files by splitting into columns (tab-separated) and perform exact domain matches or proper suffix matches (e.g. `domain == "youtube.com" or domain.endswith(".youtube.com")`). Strip `#HttpOnly_` before validating the domain.
