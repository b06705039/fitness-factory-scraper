# check_stores.py
import httpx
from bs4 import BeautifulSoup
from urllib.parse import unquote

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
STORE_PAGE = "https://www.fitnessfactory.com.tw/tw/course?page=schedule"
FILTER_COURSE = "https://www.fitnessfactory.com.tw/tw/course/ajax/filterCourse"

with httpx.Client(follow_redirects=True) as client:
    client.get(STORE_PAGE, headers={"User-Agent": UA})
    xsrf = client.cookies.get("XSRF-TOKEN", "")

    resp = client.get(
        FILTER_COURSE,
        params={"store": "台北信義"},
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "X-XSRF-TOKEN": xsrf,
            "Referer": STORE_PAGE,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
    )
    data = resp.json()
    print("所有 JSON 鍵：", list(data.keys()))

    # 印出所有含 Store 或 store 的鍵
    for key, val in data.items():
        if isinstance(val, str) and "data-id" in val:
            print(f"\n=== {key} ===")
            soup = BeautifulSoup(val, "html.parser")
            for li in soup.select("[data-id]"):
                print(f"  data-id='{li.get('data-id')}' → {li.get_text(strip=True)}")