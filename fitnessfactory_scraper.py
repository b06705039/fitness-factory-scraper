"""
第二個執行檔案

健身工廠團課課表爬蟲（全廠區版）
==================================
目標網址：https://www.fitnessfactory.com.tw/tw/course?page=schedule

【技術分析】
  網頁透過兩支 AJAX API 動態載入，不需要 Playwright：
    1. GET /tw/course/ajax/filterCourse?store=<廠區>
       → 回傳含 bkStoreList HTML 片段的 JSON（廠區選單）
       → 同時刷新 XSRF-TOKEN（每次打 filterSchedule 前必須先呼叫）
    2. GET /tw/course/ajax/filterSchedule?...
       → 回傳含 dateView / scheduleView HTML 片段的 JSON（課表）

【代課偵測】
  scheduleView 的 .course-box > .name 文字若以 🔺（U+1F53A）開頭
  → is_substitution = True，並自動去除符號還原乾淨課程名稱

【安裝依賴】
  pip install httpx beautifulsoup4 pandas

【使用方式】
  python fitnessfactory_scraper.py
"""

import time
from datetime import datetime
from urllib.parse import quote, unquote

import httpx
from bs4 import BeautifulSoup
import pandas as pd


# ════════════════════════════════════════════════════════════════
#  常數設定
# ════════════════════════════════════════════════════════════════

BASE_URL        = "https://www.fitnessfactory.com.tw"
STORE_PAGE      = BASE_URL + "/tw/course?page=schedule"
FILTER_COURSE   = BASE_URL + "/tw/course/ajax/filterCourse"
FILTER_SCHEDULE = BASE_URL + "/tw/course/ajax/filterSchedule"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

TODAY = datetime.now().strftime("%Y-%m-%d")

SUBSTITUTION_MARK = "\U0001F53A"  # 🔺

COLUMNS = [
    "store", "date", "weekday",
    "start_time", "end_time",
    "course_name", "instructor", "room",
    "is_substitution",
]


# ════════════════════════════════════════════════════════════════
#  Session 管理
# ════════════════════════════════════════════════════════════════

def make_client() -> httpx.Client:
    """建立 Client，造訪主頁讓伺服器種下初始 cookie。"""
    client = httpx.Client(follow_redirects=True, timeout=20)
    client.get(
        STORE_PAGE,
        headers={
            "User-Agent":      UA,
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    return client


def _get_xsrf(client: httpx.Client) -> str:
    """取出並 URL-decode XSRF-TOKEN（httpx 不自動 decode）。"""
    return unquote(client.cookies.get("XSRF-TOKEN", ""))


def _build_headers(client: httpx.Client, store: str) -> dict:
    """組合每次 AJAX 請求的 headers。"""
    referer = (
        f"{STORE_PAGE}&store={quote(store)}"
        f"&cate=0&class=0&teacher=0&room=0&date={TODAY}"
    )
    return {
        "User-Agent":         UA,
        "Accept":             "application/json, text/plain, */*",
        "Accept-Language":    "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer":            referer,
        "X-XSRF-TOKEN":      _get_xsrf(client),
        "sec-fetch-dest":     "empty",
        "sec-fetch-mode":     "cors",
        "sec-fetch-site":     "same-origin",
        "sec-ch-ua":          '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"macOS"',
        "priority":           "u=1, i",
    }


# ════════════════════════════════════════════════════════════════
#  廠區清單（從 filterCourse API 的 bkStoreList 解析）
# ════════════════════════════════════════════════════════════════

def get_all_stores(client: httpx.Client) -> list[dict]:
    """
    從主頁面 HTML 的 .bkLocationStore li 解析所有廠區。
    data-id 為數字 ID，傳給 API 時使用 ID；name 為顯示用中文名稱。
    """
    print("[步驟 1/3] 從主頁面取得廠區清單...")

    resp = client.get(
        STORE_PAGE,
        headers={
            "User-Agent":      UA,
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    stores: list[dict] = []
    for li in soup.select("li.bkLocationStore[data-id]"):
        store_id   = li.get("data-id", "").strip()
        store_name = li.get_text(strip=True).removesuffix("廠")
        if store_id and store_name:
            stores.append({"id": store_id, "name": store_name})

    if stores:
        print(f"  → 找到 {len(stores)} 個廠區")
    else:
        print("  → 解析失敗，使用備用清單")
        stores = _fallback_stores()

    return stores


def _fallback_stores() -> list[dict]:
    names = [
        "基隆基隆", "台北信義", "台北健康", "台北長春", "台北中山北", "台北萬隆",
        "新北汐止", "新北新埔", "新北三重", "新北中和", "新北淡水", "新北板橋",
        "新北土城", "新北新莊", "新北林口", "新北汐科", "新北雙和",
        "桃園大有", "桃園中壢", "桃園復興", "桃園南崁", "桃園青埔", "桃園正光",
        "新竹湳雅", "新竹公道五", "新竹西大", "新竹光埔", "新竹新竹北",
        "苗栗頭份",
        "台中中清", "台中新時代", "台中精明", "台中豐原", "台中文心南",
        "台中福科", "台中逢甲", "台中景賢", "台中沙鹿",
        "彰化員林", "彰化金馬",
        "嘉義嘉義",
        "台南中華", "台南開元", "台南永華", "台南永康", "台南西門",
        "高雄博愛", "高雄九如", "高雄鳳山", "高雄草衙", "高雄同盟",
        "高雄楠梓", "高雄南岡山", "高雄光華", "高雄建國",
        "屏東屏東", "屏東潮州",
    ]
    return [{"id": n, "name": n} for n in names]


# ════════════════════════════════════════════════════════════════
#  課表抓取（兩步驟：先刷 token，再取課表）
# ════════════════════════════════════════════════════════════════

def fetch_schedule(client: httpx.Client, store_id: str, date: str = TODAY) -> dict:
    """
    Step 1 → filterCourse?store=...   刷新 XSRF-TOKEN
    Step 2 → filterSchedule?...       帶入新 token 取得課表 JSON
    """
    # Step 1：刷新 token
    client.get(
        FILTER_COURSE,
        params={"store": store_id},
        headers=_build_headers(client, store_id),
    )

    # Step 2：取課表
    resp = client.get(
        FILTER_SCHEDULE,
        params={
            "page":    "schedule",
            "store":   store_id,
            "cate":    "0",
            "class":   "0",
            "teacher": "0",
            "room":    "0",
            "date":    date,
        },
        headers=_build_headers(client, store_id),
    )
    resp.raise_for_status()
    return resp.json()


# ════════════════════════════════════════════════════════════════
#  HTML 解析
# ════════════════════════════════════════════════════════════════

def parse_schedule(json_data: dict, store_name: str) -> list[dict]:
    """
    解析 filterSchedule JSON：

      dateView     → 7 欄 .th > .date-box（日期 / 星期）
      scheduleView → N 列 .tr，每列含 7 個 .td
      year         → 民國年（+1911 = 西元年）
      month        → 月份

    代課偵測：.name 以 🔺 開頭 → is_substitution = True
    """
    records: list[dict] = []

    # ── 日期標頭（7 天）──
    date_soup = BeautifulSoup(json_data.get("dateView", ""), "html.parser")
    date_headers: list[dict] = []
    for th in date_soup.select(".th"):
        date_el = th.select_one(".date")
        week_el = th.select_one(".week")
        date_headers.append({
            "date": date_el.get_text(strip=True) if date_el else "",
            "week": week_el.get_text(strip=True) if week_el else "",
        })

    # ── 民國年 → 西元年 ──
    try:
        ce_year = int(json_data.get("year", 0)) + 1911
    except (ValueError, TypeError):
        ce_year = None
    month = str(json_data.get("month", ""))

    # ── 課表本體 ──
    schedule_soup = BeautifulSoup(json_data.get("scheduleView", ""), "html.parser")

    for tr in schedule_soup.select(".tr"):
        for col_idx, td in enumerate(tr.select(".td")):
            course_box = td.select_one(".course-box")
            if not course_box:
                continue

            name_el      = course_box.select_one(".name")
            time_el      = course_box.select_one(".time")
            classroom_el = course_box.select_one(".classroom")
            teacher_el   = course_box.select_one(".teacher span")

            raw_name = name_el.get_text(strip=True) if name_el else ""
            time_str = time_el.get_text(strip=True) if time_el else ""

            # 時間拆解
            start_time = end_time = ""
            if " - " in time_str:
                parts = time_str.split(" - ", 1)
                start_time, end_time = parts[0].strip(), parts[1].strip()

            # 代課偵測
            is_sub     = raw_name.startswith(SUBSTITUTION_MARK)
            clean_name = raw_name.lstrip(SUBSTITUTION_MARK).strip()

            # 日期對應
            col_date = col_week = ""
            if col_idx < len(date_headers):
                dh = date_headers[col_idx]
                col_week = dh["week"]
                if dh["date"] and ce_year and month:
                    try:
                        col_date = f"{ce_year}/{int(month):02d}/{int(dh['date']):02d}"
                    except ValueError:
                        pass

            records.append({
                "store":           store_name,
                "date":            col_date,
                "weekday":         col_week,
                "start_time":      start_time,
                "end_time":        end_time,
                "course_name":     clean_name,
                "instructor":      teacher_el.get_text(strip=True) if teacher_el else "",
                "room":            classroom_el.get_text(strip=True) if classroom_el else "",
                "is_substitution": is_sub,
            })

    return records


# ════════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════════

def scrape_all(
    target_stores: list[str] | None = None,
    date: str = TODAY,
    delay: float = 0.5,
) -> pd.DataFrame:
    """
    抓取所有（或指定）廠區的本週課表。

    參數
    ----
    target_stores : 廠區名稱清單，如 ["台北信義", "台北內湖"]
                    None（預設）→ 自動從 API 取得全部廠區
    date          : 查詢週次基準日，格式 YYYY-MM-DD
    delay         : 每廠區間的禮貌延遲秒數

    回傳
    ----
    pd.DataFrame，欄位同 COLUMNS 常數
    """
    client = make_client()

    if target_stores is None:
        stores = get_all_stores(client)
    else:
        stores = [{"id": s, "name": s} for s in target_stores]

    print(f"\n[步驟 2/3] 開始抓取 {len(stores)} 個廠區（基準日：{date}）...")

    all_records: list[dict] = []
    failed: list[str] = []

    for i, store in enumerate(stores, 1):
        name = store["name"]
        sid  = store["id"]
        print(f"  [{i:>2}/{len(stores)}] {name:<10} ...", end=" ", flush=True)
        try:
            data    = fetch_schedule(client, name, date)
            count   = data.get("count", "?")
            records = parse_schedule(data, name)
            if records:
                all_records.extend(records)
                print(f"✓ {len(records)} 筆（API 回報 {count} 筆）")
            else:
                print(f"－ 無課程資料（API 回報 {count} 筆）")
        except httpx.HTTPStatusError as e:
            print(f"✗ HTTP {e.response.status_code}")
            failed.append(name)
        except Exception as e:
            print(f"✗ {type(e).__name__}: {e}")
            failed.append(name)
        time.sleep(delay)

    if failed:
        print(f"\n  ⚠ 失敗廠區（{len(failed)} 個）：{failed}")

    print(f"\n[步驟 3/3] 整理資料...")

    if not all_records:
        print("  → 無資料")
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(all_records)

    # 清理字串空白
    for col in df.select_dtypes(include="str").columns:
        df[col] = df[col].str.strip()

    df = df.replace("", pd.NA).dropna(subset=["course_name"])
    df["is_substitution"] = df["is_substitution"].fillna(False).astype(bool)
    df = df.sort_values(["store", "date", "start_time"]).reset_index(drop=True)

    sub_count = int(df["is_substitution"].sum())
    print(f"  → 廠區 {df['store'].nunique()} 個，課程 {len(df)} 筆，代課 {sub_count} 筆")

    return df[COLUMNS]


# ════════════════════════════════════════════════════════════════
#  執行入口
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", 20)
    pd.set_option("display.unicode.east_asian_width", True)

    print("=" * 65)
    print("  健身工廠團課課表爬蟲  —  全廠區版")
    print("=" * 65)

    # ── 選擇執行模式（取消對應的註解）────────────────────────────
    #
    # 模式 A：自動抓取全部廠區（預設）
    df = scrape_all()
    #
    # 模式 B：指定廠區
    # df = scrape_all(target_stores=["台北信義", "台北內湖"])
    #
    # 模式 C：指定日期週次
    # df = scrape_all(date="2026-06-01")
    # ─────────────────────────────────────────────────────────────

    print("\n" + "=" * 65)
    print(f"  廠區數    : {df['store'].nunique() if not df.empty else 0}")
    print(f"  總筆數    : {len(df)}")
    print(f"  代課筆數  : {int(df['is_substitution'].sum()) if not df.empty else 0}")
    print("=" * 65)

    print("\n── 前 5 筆 ──")
    print(df.head().to_string())

    if not df.empty and df["is_substitution"].any():
        print("\n── 代課課程（前 10 筆）──")
        print(df[df["is_substitution"]].head(10).to_string())

    if not df.empty:
        out = f"fitnessfactory_{TODAY}.csv"
        df.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n✅ 已儲存至 {out}")
       
        # 寫入 SQLite
        from gym_db import init_db, save_schedule_to_db
        init_db()
        save_schedule_to_db(df)