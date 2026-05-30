"""
gym_db.py — 健身工廠課表 SQLite 資料庫管理模組
================================================
資料庫檔案：gym_schedule.db

【設計決策說明】

  唯一鍵（UNIQUE KEY）：
    (branch_name, course_date, start_time, course_name, teacher_name)
    → 同廠區、同日、同時段可能有不同教室的課（如飛輪 + 有氧同時開課）
    → 加入 course_name + teacher_name 才能精準識別一堂課
    → 代課時 teacher_name 會換人，所以舊課程自然產生新列，不會覆蓋錯誤

  UPSERT 策略（INSERT OR REPLACE）：
    → 比「先 DELETE 再 INSERT」更安全：不會誤刪同週其他廠區/日期的資料
    → 重複執行冪等（idempotent）：任何時間執行結果一致
    → is_substitution 有變動時自動更新（代課資訊隨時更新核心需求）
    → updated_at 每次寫入都刷新，可追蹤最後同步時間

  索引設計（針對前端最常見查詢路徑）：
    idx_branch_date        → 查詢「某廠區某天的課表」（最高頻）
    idx_date               → 查詢「今天所有廠區課表」
    idx_substitution       → 篩選「所有代課課程」
    idx_branch_sub         → 「某廠區的代課課程」（複合索引，覆蓋查詢）
    idx_teacher            → 查詢「某老師的課程」
    idx_updated_at         → 監控「最近更新批次」

  更新頻率設計：
    → 季度大更新（全廠區完整重爬）：直接呼叫 save_schedule_to_db(df)
    → 代課頻繁更新（每日 / 數小時重爬）：同樣呼叫 save_schedule_to_db(df)
    → 兩種情境呼叫相同函數，UPSERT 確保歷史資料不受影響
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd


# ════════════════════════════════════════════════════════════════
#  設定
# ════════════════════════════════════════════════════════════════

DB_PATH = "gym_schedule.db"

# DDL：資料表與索引
_DDL_TABLE = """
CREATE TABLE IF NOT EXISTS schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 課程識別欄位
    branch_name     TEXT    NOT NULL,           -- 廠區名稱，如「台北信義」
    course_date     TEXT    NOT NULL,           -- 日期，格式 YYYY/MM/DD
    start_time      TEXT    NOT NULL,           -- 開始時間，格式 HH:MM
    end_time        TEXT    NOT NULL DEFAULT '',-- 結束時間，格式 HH:MM
    course_name     TEXT    NOT NULL,           -- 課程名稱
    teacher_name    TEXT    NOT NULL DEFAULT '',-- 老師姓名

    -- 狀態欄位
    is_substitution INTEGER NOT NULL DEFAULT 0 CHECK(is_substitution IN (0, 1)),
                                                -- 是否代課：0=否, 1=是

    -- 稽核欄位
    updated_at      TEXT    NOT NULL,           -- 最後寫入時間，ISO-8601

    -- 唯一約束：同廠區、同日、同時段、同課程、同老師視為同一堂課
    UNIQUE (branch_name, course_date, start_time, course_name, teacher_name)
);
"""

_DDL_INDEXES = [
    # 最高頻：查詢某廠區某天的課表（前端首頁）
    "CREATE INDEX IF NOT EXISTS idx_branch_date     ON schedules (branch_name, course_date);",
    # 查詢今天 / 某天所有廠區課表
    "CREATE INDEX IF NOT EXISTS idx_date            ON schedules (course_date);",
    # 篩選所有代課課程
    "CREATE INDEX IF NOT EXISTS idx_substitution    ON schedules (is_substitution);",
    # 某廠區的代課課程（複合索引，可覆蓋查詢避免回表）
    "CREATE INDEX IF NOT EXISTS idx_branch_sub      ON schedules (branch_name, is_substitution, course_date);",
    # 查詢某老師的課程
    "CREATE INDEX IF NOT EXISTS idx_teacher         ON schedules (teacher_name);",
    # 監控最近更新批次（營運用）
    "CREATE INDEX IF NOT EXISTS idx_updated_at      ON schedules (updated_at);",
]


# ════════════════════════════════════════════════════════════════
#  Context Manager（自動處理 commit / rollback）
# ════════════════════════════════════════════════════════════════

@contextmanager
def _get_conn(db_path: str = DB_PATH):
    """
    提供帶有 WAL 模式的資料庫連線。
    WAL（Write-Ahead Logging）讓讀寫可並行，適合前端讀取 + 爬蟲寫入同時發生的情境。
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL;")   # 讀寫並行
    conn.execute("PRAGMA synchronous = NORMAL;") # 效能 / 安全平衡
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row               # 支援欄位名稱存取
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════
#  對外介面
# ════════════════════════════════════════════════════════════════

def init_db(db_path: str = DB_PATH) -> None:
    """
    初始化資料庫：建立資料表與索引（若已存在則跳過）。
    可在應用程式啟動時安全地重複呼叫。

    參數
    ----
    db_path : SQLite 檔案路徑（預設 gym_schedule.db）
    """
    with _get_conn(db_path) as conn:
        conn.execute(_DDL_TABLE)
        for ddl in _DDL_INDEXES:
            conn.execute(ddl)

    print(f"[init_db] ✅ 資料庫已就緒：{Path(db_path).resolve()}")


def save_schedule_to_db(
    df: pd.DataFrame,
    db_path: str = DB_PATH,
    batch_size: int = 500,
) -> dict:
    """
    將爬蟲產生的 DataFrame 以 UPSERT 方式寫入資料庫。

    【冪等保證】
      重複執行不會產生重複資料，也不會影響其他廠區 / 日期的歷史資料。
      is_substitution 有變動時自動更新（代課資訊核心需求）。

    【效能設計】
      分批寫入（batch_size 筆），避免大量資料一次鎖表。
      使用 executemany 批次執行，減少 Python↔SQLite 往返次數。

    參數
    ----
    df         : 爬蟲產生的 DataFrame（欄位需符合爬蟲輸出格式）
    db_path    : SQLite 檔案路徑
    batch_size : 每批寫入筆數（預設 500）

    回傳
    ----
    dict，包含：
      inserted  : 新增筆數
      updated   : 更新筆數（代課狀態變動等）
      skipped   : 略過筆數（資料不完整）
      total     : 處理總筆數
      elapsed   : 寫入耗時（秒）
    """
    import time as _time
    t0 = _time.perf_counter()

    # ── 欄位映射：爬蟲 → 資料庫 ──────────────────────────────────
    FIELD_MAP = {
        "store":           "branch_name",
        "date":            "course_date",
        "start_time":      "start_time",
        "end_time":        "end_time",
        "course_name":     "course_name",
        "instructor":      "teacher_name",
        "is_substitution": "is_substitution",
    }

    # ── 前處理 ────────────────────────────────────────────────────
    df = df.copy()

    # 重命名爬蟲欄位 → 資料庫欄位（僅重命名存在的欄位）
    rename_map = {k: v for k, v in FIELD_MAP.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # 確保必要欄位都存在
    required = ["branch_name", "course_date", "start_time", "course_name"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame 缺少必要欄位：{missing}")

    # 補齊選填欄位預設值
    for col, default in [("end_time", ""), ("teacher_name", "")]:
        if col not in df.columns:
            df[col] = default

    # bool → int（SQLite 不支援 bool）
    df["is_substitution"] = df["is_substitution"].fillna(False).astype(int)

    # 統一空值處理
    for col in ["end_time", "teacher_name"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # 記錄寫入時間（同一批次用相同時間戳，方便追蹤）
    now_str = datetime.now().isoformat(timespec="seconds")
    df["updated_at"] = now_str

    # ── 過濾不完整資料 ────────────────────────────────────────────
    mask_valid = (
        df["branch_name"].str.strip().ne("") &
        df["course_date"].str.strip().ne("") &
        df["start_time"].str.strip().ne("") &
        df["course_name"].str.strip().ne("")
    )
    skipped = int((~mask_valid).sum())
    df = df[mask_valid].reset_index(drop=True)

    if df.empty:
        print("[save_schedule_to_db] ⚠ 無有效資料可寫入")
        return {"inserted": 0, "updated": 0, "skipped": skipped,
                "total": skipped, "elapsed": 0.0}

    # ── UPSERT SQL ────────────────────────────────────────────────
    upsert_sql = """
    INSERT INTO schedules
        (branch_name, course_date, start_time, end_time,
         course_name, teacher_name, is_substitution, updated_at)
    VALUES
        (:branch_name, :course_date, :start_time, :end_time,
         :course_name, :teacher_name, :is_substitution, :updated_at)
    ON CONFLICT (branch_name, course_date, start_time, course_name, teacher_name)
    DO UPDATE SET
        end_time        = excluded.end_time,
        is_substitution = excluded.is_substitution,
        updated_at      = excluded.updated_at
    WHERE
        -- 僅在有實際變動時才更新（避免無謂寫入）
        schedules.end_time        IS NOT excluded.end_time OR
        schedules.is_substitution != excluded.is_substitution;
    """

    # ── 分批寫入 ──────────────────────────────────────────────────
    cols = ["branch_name", "course_date", "start_time", "end_time",
            "course_name", "teacher_name", "is_substitution", "updated_at"]
    records = df[cols].to_dict(orient="records")

    total_rows    = len(records)
    rows_affected = 0

    with _get_conn(db_path) as conn:
        for start in range(0, total_rows, batch_size):
            batch = records[start: start + batch_size]
            cursor = conn.executemany(upsert_sql, batch)
            rows_affected += cursor.rowcount

    elapsed   = round(_time.perf_counter() - t0, 3)
    # rowcount for executemany 計算的是實際變動列數（INSERT + UPDATE）
    inserted_or_updated = rows_affected
    unchanged = total_rows - inserted_or_updated

    result = {
        "inserted_or_updated": inserted_or_updated,
        "unchanged":           unchanged,
        "skipped":             skipped,
        "total":               total_rows + skipped,
        "elapsed_sec":         elapsed,
    }

    print(
        f"[save_schedule_to_db] ✅ "
        f"處理 {result['total']} 筆 | "
        f"寫入/更新 {inserted_or_updated} 筆 | "
        f"無變動 {unchanged} 筆 | "
        f"略過 {skipped} 筆 | "
        f"耗時 {elapsed}s"
    )
    return result


# ════════════════════════════════════════════════════════════════
#  查詢工具函數（供前端或其他模組使用）
# ════════════════════════════════════════════════════════════════

def query_by_branch_date(
    branch_name: str,
    course_date: str,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """
    查詢某廠區某天的完整課表。

    參數
    ----
    branch_name : 廠區名稱，如「台北信義」
    course_date : 日期字串，格式 YYYY/MM/DD，如「2026/05/30」
    """
    sql = """
    SELECT id, branch_name, course_date, start_time, end_time,
           course_name, teacher_name, is_substitution, updated_at
    FROM   schedules
    WHERE  branch_name = ? AND course_date = ?
    ORDER  BY start_time;
    """
    with _get_conn(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=(branch_name, course_date))


def query_substitutions(
    branch_name: str | None = None,
    course_date: str | None = None,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """
    查詢代課課程，可依廠區和日期篩選。

    參數
    ----
    branch_name : 廠區名稱（None = 全部廠區）
    course_date : 日期字串（None = 全部日期）
    """
    conditions = ["is_substitution = 1"]
    params: list = []

    if branch_name:
        conditions.append("branch_name = ?")
        params.append(branch_name)
    if course_date:
        conditions.append("course_date = ?")
        params.append(course_date)

    where = " AND ".join(conditions)
    sql = f"""
    SELECT id, branch_name, course_date, start_time, end_time,
           course_name, teacher_name, is_substitution, updated_at
    FROM   schedules
    WHERE  {where}
    ORDER  BY course_date, branch_name, start_time;
    """
    with _get_conn(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def query_by_teacher(
    teacher_name: str,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """查詢某老師本週所有課程（模糊比對）。"""
    sql = """
    SELECT id, branch_name, course_date, start_time, end_time,
           course_name, teacher_name, is_substitution, updated_at
    FROM   schedules
    WHERE  teacher_name LIKE ?
    ORDER  BY course_date, start_time;
    """
    with _get_conn(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=(f"%{teacher_name}%",))


def get_db_stats(db_path: str = DB_PATH) -> dict:
    """
    取得資料庫統計資訊（監控用）。

    回傳
    ----
    dict 包含：總筆數、廠區數、代課筆數、最後更新時間
    """
    sql = """
    SELECT
        COUNT(*)                          AS total_rows,
        COUNT(DISTINCT branch_name)       AS branch_count,
        SUM(is_substitution)              AS sub_count,
        MAX(updated_at)                   AS last_updated
    FROM schedules;
    """
    with _get_conn(db_path) as conn:
        row = conn.execute(sql).fetchone()
        return dict(row)


# ════════════════════════════════════════════════════════════════
#  整合測試（直接執行此檔案時觸發）
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("  gym_db.py — 資料庫模組整合測試")
    print("=" * 60)

    # ── Step 1：初始化 ────────────────────────────────────────────
    print("\n[TEST 1] init_db()")
    init_db()

    # ── Step 2：建立測試資料（模擬爬蟲輸出格式）────────────────────
    print("\n[TEST 2] 建立模擬 DataFrame")
    test_data = {
        "store":           ["台北信義"] * 5,
        "date":            ["2026/05/30"] * 3 + ["2026/05/31"] * 2,
        "weekday":         ["星期六"] * 3 + ["星期日"] * 2,
        "start_time":      ["08:30", "09:40", "10:10", "09:00", "10:00"],
        "end_time":        ["09:30", "10:40", "11:10", "10:00", "11:00"],
        "course_name":     ["陰瑜珈", "極限槓鈴", "活力有氧", "哈達瑜珈", "飛輪課程"],
        "instructor":      ["Sean", "金仁", "Hermit L.", "SONI", "Fanny T."],
        "room":            ["有氧大教室"] * 4 + ["飛輪教室"],
        "is_substitution": [True, False, True, False, False],
    }
    df_test = pd.DataFrame(test_data)
    print(df_test.to_string(index=False))

    # ── Step 3：首次寫入 ──────────────────────────────────────────
    print("\n[TEST 3] 首次寫入（預期全部為新增）")
    r1 = save_schedule_to_db(df_test)

    # ── Step 4：重複寫入（應無變動）──────────────────────────────
    print("\n[TEST 4] 重複寫入相同資料（預期無變動）")
    r2 = save_schedule_to_db(df_test)
    assert r2["inserted_or_updated"] == 0, "重複寫入應無變動"
    print("  → ✅ 冪等性驗證通過")

    # ── Step 5：代課狀態更新 ──────────────────────────────────────
    print("\n[TEST 5] 代課狀態變動（極限槓鈴從 False → True）")
    df_update = df_test.copy()
    df_update.loc[df_update["course_name"] == "極限槓鈴", "is_substitution"] = True
    r3 = save_schedule_to_db(df_update)
    assert r3["inserted_or_updated"] == 1, "代課更新應有 1 筆變動"
    print("  → ✅ 代課狀態更新驗證通過")

    # ── Step 6：查詢驗證 ──────────────────────────────────────────
    print("\n[TEST 6] 查詢 台北信義 / 2026/05/30")
    df_q = query_by_branch_date("台北信義", "2026/05/30")
    print(df_q[["start_time","course_name","teacher_name","is_substitution"]].to_string(index=False))

    print("\n[TEST 7] 查詢代課課程")
    df_sub = query_substitutions()
    print(df_sub[["branch_name","course_date","course_name","teacher_name"]].to_string(index=False))

    print("\n[TEST 8] 資料庫統計")
    stats = get_db_stats()
    for k, v in stats.items():
        print(f"  {k:<20}: {v}")

    print("\n" + "=" * 60)
    print("  ✅ 所有測試通過")
    print("=" * 60)