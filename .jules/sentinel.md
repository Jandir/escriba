
## 2025-03-09 - [Fix cookie leakage via broad substring matching]
**Vulnerability:** Cookie filtering functions (`filter_youtube_cookies` and `filter_vimeo_cookies`) were using broad substring matching (e.g., `'youtube.com' in line`) instead of strict parsing of the Netscape HTTP Cookie File format.
**Learning:** Broad substring matching allows cookies from malicious or unrelated domains (e.g., `fake-youtube.com`) to leak through the filter if their domain contains the target string as a substring, exposing the user's session from those sites to the file. Furthermore, standard `#` comments ignoring `#HttpOnly_` prefixes caused secure cookies to be dropped.
**Prevention:** When parsing Netscape HTTP Cookie Files, always split lines by tabs (`\t`) and validate the domain strictly (using equality or `.endswith` suffix matching, taking care to strip the `#HttpOnly_` prefix if present).
