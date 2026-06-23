import pytest
from pathlib import Path
from youtube import filter_youtube_cookies

def test_filter_youtube_cookies(tmp_path):
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("""# Netscape HTTP Cookie File
# http://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file!  Do not edit.

.youtube.com\tTRUE\t/\tFALSE\t1712211933\tyoutube_cookie\tqwerty
www.google.com\tFALSE\t/\tTRUE\t1712211933\tgoogle_cookie\t12345
#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1712211933\tyoutube_session\tabcde
fakeyoutube.com\tTRUE\t/\tFALSE\t1712211933\tsession\tbadcookie
malicious.com\tTRUE\t/\tFALSE\t1712211933\thijack\tyoutube.com
#HttpOnly_fake.com\tTRUE\t/\tTRUE\t1712211933\tfake_session\tabcde
""", encoding="utf-8")

    filter_youtube_cookies(cookies_path)
    content = cookies_path.read_text(encoding="utf-8")

    assert ".youtube.com\tTRUE\t/\tFALSE\t1712211933\tyoutube_cookie\tqwerty" in content
    assert "www.google.com\tFALSE\t/\tTRUE\t1712211933\tgoogle_cookie\t12345" in content
    assert "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1712211933\tyoutube_session\tabcde" in content
    assert "fakeyoutube.com" not in content
    assert "malicious.com" not in content
    assert "#HttpOnly_fake.com" not in content
