import pytest
from pathlib import Path
from vimeo import filter_vimeo_cookies

def test_filter_vimeo_cookies(tmp_path):
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("""# Netscape HTTP Cookie File
# http://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file!  Do not edit.

.vimeo.com\tTRUE\t/\tFALSE\t1712211933\tvimeo_cookie\tqwerty
www.akamaized.net\tFALSE\t/\tTRUE\t1712211933\takamai_cookie\t12345
#HttpOnly_.vimeo.com\tTRUE\t/\tTRUE\t1712211933\tvimeo_session\tabcde
fakevimeo.com\tTRUE\t/\tFALSE\t1712211933\tsession\tbadcookie
malicious.com\tTRUE\t/\tFALSE\t1712211933\thijack\tvimeo.com
#HttpOnly_fake.com\tTRUE\t/\tTRUE\t1712211933\tfake_session\tabcde
""", encoding="utf-8")

    filter_vimeo_cookies(cookies_path)
    content = cookies_path.read_text(encoding="utf-8")

    assert ".vimeo.com\tTRUE\t/\tFALSE\t1712211933\tvimeo_cookie\tqwerty" in content
    assert "www.akamaized.net\tFALSE\t/\tTRUE\t1712211933\takamai_cookie\t12345" in content
    assert "#HttpOnly_.vimeo.com\tTRUE\t/\tTRUE\t1712211933\tvimeo_session\tabcde" in content
    assert "fakevimeo.com" not in content
    assert "malicious.com" not in content
    assert "#HttpOnly_fake.com" not in content
