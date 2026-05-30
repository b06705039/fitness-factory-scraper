import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote

STORE_PAGE = "https://www.fitnessfactory.com.tw/tw/course?page=schedule"
store = "台北信義"
date  = "2026-05-30"

with httpx.Client(follow_redirects=True) as client:
    # 取得 XSRF token
    client.get(STORE_PAGE, headers={"User-Agent": "Mozilla/5.0 Chrome/148.0.0.0 Safari/537.36"})
    xsrf = client.cookies.get("XSRF-TOKEN", "")

    # 抓含課表的完整頁面
    url = f"{STORE_PAGE}&store={quote(store)}&cate=0&class=0&teacher=0&room=0&date={date}"
    resp = client.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language": "zh-TW,zh;q=0.9",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
    })

    print("Status:", resp.status_code)
    soup = BeautifulSoup(resp.text, "html.parser")

    # 找所有可能是課表容器的元素，印出 class 名稱
    print("\n── 含 'schedule' 或 'course' 或 'timetable' 的元素 ──")
    for el in soup.select("[class]"):
        cls = " ".join(el.get("class", []))
        if any(k in cls.lower() for k in ["schedule", "timetable", "course-list", "bkcourse"]):
            print(f"  <{el.name} class='{cls}'> → {el.get_text(strip=True)[:60]}")

    # 找 table
    tables = soup.select("table")
    print(f"\n── 找到 {len(tables)} 個 table ──")
    for i, t in enumerate(tables):
        print(f"  table[{i}] class='{' '.join(t.get('class', []))}' → {t.get_text(strip=True)[:80]}")