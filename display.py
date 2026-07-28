"""
第三個執行檔案

app.py — 健身工廠課表查詢介面
==============================
執行方式：
    streamlit run display.py
    py -m streamlit run display.py

依賴：
    pip install streamlit pandas
需要同目錄下有 gym_db.py
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# 選填：瀏覽器 localStorage 元件（用於記住上次的篩選條件）
#   pip install streamlit-local-storage
try:
    from streamlit_local_storage import LocalStorage
    _HAS_LOCAL_STORAGE = True
except ImportError:
    _HAS_LOCAL_STORAGE = False

# ════════════════════════════════════════════════════════════════
#  頁面設定
# ════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="健身工廠 課表查詢",
    page_icon="🏋️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════════════
#  自訂樣式
# ════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans TC', sans-serif; }

.page-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 16px; padding: 28px 36px; margin-bottom: 24px;
    display: flex; align-items: center; gap: 20px;
}
.page-header h1 { color: #fff; font-size: 2rem; font-weight: 700; margin: 0; }
.page-header p  { color: #a0aec0; font-size: 0.9rem; margin: 4px 0 0 0; }
.header-icon    { font-size: 3rem; line-height: 1; }

.stat-bar {
    background: #f0f4ff; border-left: 4px solid #4361ee;
    border-radius: 0 10px 10px 0; padding: 12px 20px; margin-bottom: 16px;
    display: flex; align-items: center; gap: 10px;
    font-size: 0.95rem; color: #2d3748;
}
.stat-bar strong { color: #4361ee; font-size: 1.3rem; }
.stat-sub { color: #718096; font-size: 0.85rem; margin-left: auto; }

.empty-state { text-align: center; padding: 60px 20px; color: #a0aec0; }
.empty-state .icon { font-size: 3rem; margin-bottom: 12px; }
.empty-state p { font-size: 1rem; }

.sidebar-section {
    font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: #a0aec0; margin: 16px 0 6px 0;
}
[data-testid="stDataFrame"] { width: 100% !important; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
#  常數
# ════════════════════════════════════════════════════════════════

DB_PATH = Path("gym_schedule.db")

# localStorage 的鍵名（記住上次挑選的：廠區 / 課程名稱 / 老師）
FILTER_STORAGE_KEY = "gym_schedule_filters_v1"

TIME_SLOTS = {
    "全部":                   (None, None),
    "☀️ 早上（06:00–12:00）": ("06:00", "12:00"),
    "🌤 下午（12:00–18:00）": ("12:00", "18:00"),
    "🌙 晚上（18:00–24:00）": ("18:00", "24:00"),
}

# 包含 room 欄位
DISPLAY_COLS = {
    "course_date":  "日期",
    "weekday":      "星期",
    "start_time":   "開始",
    "end_time":     "結束",
    "course_name":  "課程名稱",
    "teacher_name": "老師",
    "room":         "教室",
    "branch_name":  "廠區",
}

WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ════════════════════════════════════════════════════════════════
#  資料讀取（帶快取，從 gym_db 讀取）
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner="載入課表資料中…")
def load_data(db_path: str = str(DB_PATH)) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    try:
        # 注意：同時讀取 room 欄位（gym_db.py 有此欄位）
        df = pd.read_sql_query(
            """
            SELECT
                branch_name, course_date, start_time, end_time,
                course_name, teacher_name,
                COALESCE(room, '') AS room,
                is_substitution
            FROM schedules
            ORDER BY course_date, start_time, branch_name
            """,
            conn,
        )
    except Exception:
        # 若 room 欄不存在（舊版 DB），降級讀取
        df = pd.read_sql_query(
            """
            SELECT
                branch_name, course_date, start_time, end_time,
                course_name, teacher_name, is_substitution
            FROM schedules
            ORDER BY course_date, start_time, branch_name
            """,
            conn,
        )
        df["room"] = ""
    finally:
        conn.close()

    # 型別標準化
    df["is_substitution"] = df["is_substitution"].fillna(0).astype(bool)
    for col in ["branch_name", "course_date", "start_time", "end_time",
                "course_name", "teacher_name", "room"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # 動態計算星期
    def _to_weekday(date_str: str) -> str:
        for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                return WEEKDAY_ZH[datetime.strptime(date_str, fmt).weekday()]
            except ValueError:
                continue
        return ""

    df["weekday"] = df["course_date"].apply(_to_weekday)
    return df

# ════════════════════════════════════════════════════════════════
#  Header
# ════════════════════════════════════════════════════════════════

st.markdown("""
<div class="page-header">
    <div class="header-icon">🏋️</div>
    <div>
        <h1>健身工廠 課表查詢</h1>
        <p>Fitness Factory Group Class Schedule</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
#  側邊欄：上傳 CSV 匯入 DB
# ════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 📂 資料匯入")
    uploaded = st.file_uploader(
        "上傳爬蟲 CSV 直接匯入 DB",
        type=["csv"],
        help="上傳 fitnessfactory_YYYY-MM-DD.csv",
    )
    if uploaded is not None:
        try:
            from gym_db import init_db, save_schedule_to_db
            df_upload = pd.read_csv(uploaded)
            init_db()
            result = save_schedule_to_db(df_upload)
            st.cache_data.clear()
            st.success(f"✅ 匯入完成：{result['inserted_or_updated']} 筆寫入/更新")
            st.rerun()
        except Exception as e:
            st.error(f"匯入失敗：{e}")

# ════════════════════════════════════════════════════════════════
#  DB 不存在時提示
# ════════════════════════════════════════════════════════════════

if not DB_PATH.exists():
    st.error(
        "⚠️ 找不到資料庫。請先執行爬蟲：\n"
        "```bash\npython fitnessfactory_scraper.py\n```\n"
        "或在左側上傳 CSV 直接匯入。"
    )
    st.stop()

df_all = load_data()

if df_all.empty:
    st.warning("資料庫中尚無資料，請先執行爬蟲或上傳 CSV。")
    st.stop()

# ════════════════════════════════════════════════════════════════
#  讀取 localStorage 中上次挑選的篩選條件
# ════════════════════════════════════════════════════════════════

# localS：瀏覽器 localStorage 存取物件（不可用時為 None）
localS = LocalStorage() if _HAS_LOCAL_STORAGE else None

# saved_filters：上次挑選的條件 {"branches": [...], "courses": [...], "teachers": [...]}
saved_raw = localS.getItem(FILTER_STORAGE_KEY) if localS is not None else None
try:
    saved_filters = json.loads(saved_raw) if saved_raw else {}
    if not isinstance(saved_filters, dict):
        saved_filters = {}
except (json.JSONDecodeError, TypeError):
    saved_filters = {}


# 追蹤要記憶的三個篩選器：localStorage 欄位 → widget 的 session_state key
FILTER_WIDGET_KEYS = {
    "branches": "flt_branches",
    "courses":  "flt_courses",
    "teachers": "flt_teachers",
}

# 一次性：等 getItem 回傳後，把上次挑選的值灌進各 widget 的 session_state。
# 只保留目前資料中仍存在的選項，避免 multiselect 因選項不存在而報錯。
# 之後就由 widget 的 key 自行持有狀態，不再被 localStorage 的額外 rerun 重置。
if (
    localS is not None
    and saved_raw is not None
    and not st.session_state.get("_filters_loaded", False)
):
    _valid_options = {
        "branches": set(df_all["branch_name"].unique()),
        "courses":  set(df_all["course_name"].unique()),
        "teachers": set(df_all["teacher_name"].unique()),
    }
    for _field, _wkey in FILTER_WIDGET_KEYS.items():
        _vals = saved_filters.get(_field, [])
        if isinstance(_vals, list):
            st.session_state[_wkey] = [
                v for v in _vals if v in _valid_options[_field]
            ]
    st.session_state["_filters_loaded"] = True

# ════════════════════════════════════════════════════════════════
#  側邊欄篩選器
# ════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("---")
    st.markdown("## 🔍 篩選條件")

    st.markdown('<div class="sidebar-section">📍 廠區</div>', unsafe_allow_html=True)
    all_branches = sorted(df_all["branch_name"].unique().tolist())
    sel_branches = st.multiselect(
        "選擇廠區", options=all_branches, key="flt_branches",
        placeholder="可多選廠區…", label_visibility="collapsed",
    )

    st.markdown('<div class="sidebar-section">📅 日期</div>', unsafe_allow_html=True)
    all_dates = sorted(df_all["course_date"].unique().tolist())
    week_dates = []
    for d in all_dates:
        for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                if datetime.strptime(d, fmt) >= datetime.now() - timedelta(days=1):
                    week_dates.append(d)
                break
            except ValueError:
                continue
    date_options = ["全部日期"] + (week_dates if week_dates else all_dates)
    # 預設帶入「今天」；若今天無資料則退回「全部日期」
    today_str = datetime.now().strftime("%Y/%m/%d")
    default_date_index = (
        date_options.index(today_str) if today_str in date_options else 0
    )
    sel_date_option = st.selectbox(
        "選擇日期", options=date_options, index=default_date_index,
        label_visibility="collapsed",
    )
    with st.expander("📆 或選擇精確日期"):
        custom_date = st.date_input("指定日期", value=None, label_visibility="collapsed")

    st.markdown('<div class="sidebar-section">⏰ 時段</div>', unsafe_allow_html=True)
    sel_slot = st.selectbox(
        "選擇時段", options=list(TIME_SLOTS.keys()), label_visibility="collapsed"
    )

    st.markdown('<div class="sidebar-section">🏃 課程名稱</div>', unsafe_allow_html=True)
    all_courses = sorted(df_all["course_name"].unique().tolist())
    sel_courses = st.multiselect(
        "選擇課程", options=all_courses, key="flt_courses",
        placeholder="不選則顯示全部…", label_visibility="collapsed"
    )

    st.markdown('<div class="sidebar-section">👤 老師</div>', unsafe_allow_html=True)
    all_teachers = sorted(
        [t for t in df_all["teacher_name"].unique().tolist() if t],
        key=lambda x: x.lower(),
    )
    sel_teachers = st.multiselect(
        "選擇老師", options=all_teachers, key="flt_teachers",
        placeholder="不選則顯示全部…", label_visibility="collapsed"
    )

    # ── 將本次挑選的（廠區 / 課程名稱 / 老師）寫回 localStorage ──
    if localS is not None:
        current_payload = json.dumps(
            {
                "branches": sel_branches,
                "courses":  sel_courses,
                "teachers": sel_teachers,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        # 僅在值有變動時才寫入，避免無限 rerun。
        # 用「內容雜湊」當元件 key，確保每個不同的值都會實際寫進 localStorage。
        if current_payload != saved_raw:
            _sk = "_save_" + hashlib.md5(current_payload.encode("utf-8")).hexdigest()[:8]
            localS.setItem(FILTER_STORAGE_KEY, current_payload, key=_sk)
    else:
        st.caption("💡 安裝 `streamlit-local-storage` 可記住上次的篩選條件")

    st.markdown('<div class="sidebar-section">🏢 教室</div>', unsafe_allow_html=True)
    all_rooms = sorted([r for r in df_all["room"].unique().tolist() if r])
    sel_rooms = st.multiselect(
        "選擇教室", options=all_rooms,
        placeholder="不選則顯示全部…", label_visibility="collapsed"
    )

    st.markdown('<div class="sidebar-section">🔄 代課篩選</div>', unsafe_allow_html=True)
    only_sub = st.toggle("僅顯示代課課程", value=False)

    st.markdown("---")
    if st.button("🔄 重新載入資料", use_container_width=True, type="secondary"):
        st.cache_data.clear()
        st.rerun()

    try:
        conn = sqlite3.connect(DB_PATH)
        last_update = conn.execute("SELECT MAX(updated_at) FROM schedules").fetchone()[0]
        total_db    = conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
        conn.close()
        if last_update:
            st.caption(f"更新時間：{last_update[:16].replace('T', ' ')}")
            st.caption(f"資料庫共 {total_db} 筆")
    except Exception:
        pass

# ════════════════════════════════════════════════════════════════
#  篩選邏輯
# ════════════════════════════════════════════════════════════════

df = df_all.copy()

if sel_branches:
    df = df[df["branch_name"].isin(sel_branches)]

if custom_date is not None:
    df = df[df["course_date"] == custom_date.strftime("%Y/%m/%d")]
elif sel_date_option != "全部日期":
    df = df[df["course_date"] == sel_date_option]

slot_start, slot_end = TIME_SLOTS[sel_slot]
if slot_start and slot_end:
    df = df[(df["start_time"] >= slot_start) & (df["start_time"] < slot_end)]

if sel_courses:
    df = df[df["course_name"].isin(sel_courses)]

if sel_teachers:
    df = df[df["teacher_name"].isin(sel_teachers)]

if sel_rooms:
    df = df[df["room"].isin(sel_rooms)]

if only_sub:
    df = df[df["is_substitution"]]

df = df.reset_index(drop=True)

# ════════════════════════════════════════════════════════════════
#  主畫面
# ════════════════════════════════════════════════════════════════

total      = len(df)
sub_count  = int(df["is_substitution"].sum())
branch_cnt = df["branch_name"].nunique()

sub_note    = f"｜其中代課 {sub_count} 堂" if sub_count > 0 else ""
branch_note = f"｜{branch_cnt} 個廠區"    if branch_cnt > 1 else ""

st.markdown(f"""
<div class="stat-bar">
    🗓️ 共找到 <strong>{total}</strong> 堂符合條件的課程
    <span class="stat-sub">{branch_note}{sub_note}</span>
</div>
""", unsafe_allow_html=True)

if df.empty:
    st.markdown("""
    <div class="empty-state">
        <div class="icon">🔍</div>
        <p>沒有符合條件的課程，請調整篩選條件。</p>
    </div>
    """, unsafe_allow_html=True)
else:
    df_display = df.copy()
    df_display["course_name"] = df_display.apply(
        lambda r: f"🔄 [代課] {r['course_name']}" if r["is_substitution"] else r["course_name"],
        axis=1,
    )
    df_display = df_display[list(DISPLAY_COLS.keys())].rename(columns=DISPLAY_COLS)

    col_config = {
        "日期":   st.column_config.TextColumn("日期",   width="small"),
        "星期":   st.column_config.TextColumn("星期",   width="small"),
        "開始":   st.column_config.TextColumn("開始",   width="small"),
        "結束":   st.column_config.TextColumn("結束",   width="small"),
        "課程名稱": st.column_config.TextColumn("課程名稱", width="medium"),
        "老師":   st.column_config.TextColumn("老師",   width="small"),
        "教室":   st.column_config.TextColumn("教室",   width="small"),
        "廠區":   st.column_config.TextColumn("廠區",   width="small"),
    }

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        column_config=col_config,
        height=min(50 + len(df_display) * 35, 640),
    )

    csv_out = df_display.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="⬇️ 匯出 CSV",
        data=csv_out,
        file_name=f"gym_schedule_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )