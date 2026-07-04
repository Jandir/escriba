## 2025-02-21 - [Cross-Domain Cookie Leakage in File Parsing]
**Vulnerability:** Substring match (`"youtube.com" in line_str`) during Netscape HTTP Cookie File parsing exposed cookies to broad cross-domain leakage (e.g., `fake-youtube.com`).
**Learning:** Netscape HTTP Cookie Files use tab separation (`\t`) for columns and may use `#HttpOnly_` prefix for HttpOnly cookies. Broad string matching logic on lines can easily be bypassed or inadvertently scoop up unintended cookies.
**Prevention:** Always split cookie lines by `\t` to extract the domain column explicitly. Then perform strict exact match or subdomain match boundaries (e.g. `domain.endswith('.youtube.com') or domain == 'youtube.com'`).
