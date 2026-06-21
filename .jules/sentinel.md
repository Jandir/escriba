
## 2026-06-21 - [CRITICAL] Cross-Domain Cookie Leakage in yt-dlp Cookie Filter
**Vulnerability:** The cookie sanitization logic used a naive substring search (`"youtube.com" in line_str`) to filter Netscape HTTP Cookie files. This could allow cookies for unrelated or attacker-controlled domains (e.g., `evilyoutube.com.br`) to be included and potentially leaked, and the logic was indiscriminately ignoring `#HttpOnly_` lines.
**Learning:** Naive substring matching on configuration files like `cookies.txt` is inherently dangerous and can bypass the intention of restricting access to specific domains.
**Prevention:** Always parse structured file formats according to their specification. For Netscape Cookie format, properly split lines by tabs to isolate and validate the domain column precisely. Treat `#HttpOnly_` entries as active cookies, not header comments.
