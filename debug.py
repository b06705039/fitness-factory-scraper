# debug.py
import httpx
from urllib.parse import quote, unquote

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
STORE_PAGE = "https://www.fitnessfactory.com.tw/tw/course?page=schedule"
FILTER_SCHEDULE = "https://www.fitnessfactory.com.tw/tw/course/ajax/filterSchedule"
FILTER_COURSE   = "https://www.fitnessfactory.com.tw/tw/course/ajax/filterCourse"

# 測試這幾個名稱格式
test_stores = ["台北信義廠", "台北信義", "26", "台北健康廠", "台北健康"]

with httpx.Client(follow_redirects=True) as client:
    client.get(STORE_PAGE, headers={"User-Agent": UA})

    for store in test_stores:
        xsrf = client.cookies.get("XSRF-TOKEN", "")
        # 先刷 token
        client.get(FILTER_COURSE, params={"store": store}, headers={
            "User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "Referer": f"{STORE_PAGE}&store={quote(store)}&cate=0&class=0&teacher=0&room=0&date=2026-05-30",
            "X-XSRF-TOKEN": xsrf,
            "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
        })
        xsrf = client.cookies.get("XSRF-TOKEN", "")
        resp = client.get(
            FILTER_SCHEDULE,
            params={"page": "schedule", "store": store, "cate": "0",
                    "class": "0", "teacher": "0", "room": "0", "date": "2026-05-30"},
            headers={
                "User-Agent": UA, "Accept": "application/json, text/plain, */*",
                "Referer": f"{STORE_PAGE}&store={quote(store)}&cate=0&class=0&teacher=0&room=0&date=2026-05-30",
                "X-XSRF-TOKEN": xsrf,
                "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
            }
        )
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            data = resp.json()
            print(f"✅ '{store}' → JSON, count={data.get('count','?')}")
        else:
            print(f"✗  '{store}' → HTML（不接受此名稱）")