# app.py — VolleyTracker Pro  Streamlit 主應用
import copy
import time
import uuid
from datetime import datetime

import plotly.graph_objects as pgo
import streamlit as st

import storage
import game_logic as gl
from pdf_generator import generate_pdf

# ══════════════════════════════════════════════════════════════════════════════
# 頁面設定
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="VolleyTracker Pro",
    page_icon="🏐",
    layout="wide",
    initial_sidebar_state="collapsed",
)

storage.init_db()

# ══════════════════════════════════════════════════════════════════════════════
# 全域 CSS
# ══════════════════════════════════════════════════════════════════════════════
GLOBAL_CSS = """
<style>
#MainMenu, footer { display:none !important; }
[data-testid="stHeader"] { display:none !important; }
[data-testid="stSidebar"] { display:none !important; }
.block-container { padding-top:0.75rem !important; padding-bottom:1rem !important; }

/* ── Tab pill nav ── */
[data-testid="stTabs"] [role="tablist"] {
    gap: 5px !important; background: transparent !important;
    border-bottom: none !important;
}
[data-testid="stTabs"] [role="tab"] {
    background: #141820 !important;
    border: 1.5px solid #252d42 !important;
    border-radius: 8px !important;
    color: #7a849e !important;
    font-size: 13px !important; font-weight: 700 !important;
    padding: 4px 16px !important; min-height: 32px !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    background: #f5a623 !important;
    border-color: #f5a623 !important;
    color: #000 !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display:none !important; }

/* ── General buttons ── */
div[data-testid="stButton"] button {
    border-radius: 10px !important; font-weight: 700 !important;
    font-size: 14px !important; min-height: 50px !important;
    transition: all 0.15s ease !important;
}
div[data-testid="stButton"] button[kind="secondary"] {
    background: #141820 !important;
    border: 1.5px solid #252d42 !important;
    color: #bec8de !important;
}
div[data-testid="stButton"] button[kind="secondary"]:hover {
    border-color: #f5a623 !important; color: #f5a623 !important;
    background: #1f1b0f !important;
}

/* ── Set selector pills (小一點) ── */
.set-row div[data-testid="stButton"] button {
    min-height: 36px !important; border-radius: 20px !important;
    font-size: 13px !important; padding: 0 14px !important;
}

/* ── Containers / cards ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important; border-color: #252d42 !important;
    background: #0e1320 !important;
}
</style>
"""


# ══════════════════════════════════════════════════════════════════════════════
# Session State 初始化
# ══════════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    "page": "home",
    "user_code": None,
    "match_id": None,
    "match_name": "",
    "players": [
        {"id": 1, "name": "球員A", "pos": "大砲"},
        {"id": 2, "name": "球員B", "pos": "舉球"},
        {"id": 3, "name": "球員C", "pos": "自由"},
    ],
    "logs": [],
    "current_set": 1,
    "selected_player_id": 1,
    "selected_action": None,
    "selected_context": None,
    "prev_action_state": {
        "quality": None, "action": None,
        "logId": None, "playerId": None, "context": None,
    },
    "history_stack": [],
    "selected_match_ids": [],
    "view_set": None,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# 工具函式（邏輯不變）
# ══════════════════════════════════════════════════════════════════════════════

def go(page: str):
    st.session_state.page = page
    st.rerun()


def auto_save():
    ss = st.session_state
    if ss.match_id is None:
        ss.match_id = storage.create_match(
            ss.user_code, ss.match_name,
            ss.players, ss.logs, ss.current_set,
        )
    else:
        storage.update_match(ss.match_id, ss.players, ss.logs, ss.current_set)


def save_history():
    ss = st.session_state
    ss.history_stack.append({
        "logs": copy.deepcopy(ss.logs),
        "prev_action_state": copy.deepcopy(ss.prev_action_state),
        "current_set": ss.current_set,
    })


def do_undo():
    ss = st.session_state
    if not ss.history_stack:
        return
    snap = ss.history_stack.pop()
    ss.logs = snap["logs"]
    ss.prev_action_state = snap["prev_action_state"]
    ss.current_set = snap["current_set"]
    ss.selected_action = None
    ss.selected_context = None
    auto_save()


def add_log(quality: str):
    ss = st.session_state
    player_id = ss.selected_player_id
    action = ss.selected_action
    context = ss.selected_context or "一般"

    if not player_id or not action:
        return

    save_history()

    score_delta, note = gl.compute_score_delta(quality, ss.prev_action_state, action)
    log_id = str(uuid.uuid4())

    prev = ss.prev_action_state
    if prev.get("action") == "舉球" and action == "攻擊":
        if prev.get("quality") in ["B", "C", "F"] and quality == "F":
            prev_lid = prev.get("logId")
            for i, l in enumerate(ss.logs):
                if l.get("id") == prev_lid:
                    old_note = l.get("note", "")
                    ss.logs[i] = {
                        **l,
                        "scoreDelta": l["scoreDelta"] - 25,
                        "note": (old_note + ", " if old_note else "") + "配球失分主責",
                    }
                    break

    new_log = {
        "id": log_id, "type": "action",
        "setNo": ss.current_set, "playerId": player_id,
        "action": action, "context": context, "quality": quality,
        "prevQuality": prev.get("quality"), "prevAction": prev.get("action"),
        "prevPlayerId": prev.get("playerId"), "prevContext": prev.get("context"),
        "scoreDelta": score_delta, "note": note,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }

    ss.logs.insert(0, new_log)
    ss.prev_action_state = {
        "quality": quality, "action": action,
        "logId": log_id, "playerId": player_id, "context": context,
    }
    ss.selected_action = None
    ss.selected_context = None
    auto_save()


def resolve_point(point_type: str):
    ss = st.session_state
    save_history()

    labels = {
        "win": ("我方得分", "us"),
        "oppError": ("對方失誤", "us"),
        "lose": ("我方失分", "them"),
        "opponent": ("對手好球", "them"),
    }
    result_label, winner = labels[point_type]
    bonus = point_type in ("win", "lose")

    if bonus:
        delta = 20 if point_type == "win" else -20
        note_str = "得分加成" if point_type == "win" else "失分責任"
        cur_set = ss.current_set
        for i, l in enumerate(ss.logs):
            if l.get("type") == "action" and l.get("setNo", 1) == cur_set:
                old_note = l.get("note", "")
                ss.logs[i] = {
                    **l,
                    "scoreDelta": l["scoreDelta"] + delta,
                    "note": (old_note + " / " if old_note else "") + note_str,
                }
                break

    divider = {
        "id": str(uuid.uuid4()), "type": "divider",
        "setNo": ss.current_set, "result": result_label, "winner": winner,
    }
    ss.logs.insert(0, divider)
    ss.prev_action_state = {k: None for k in ss.prev_action_state}
    ss.selected_action = None
    ss.selected_context = None
    auto_save()


def get_rally_logs():
    ss = st.session_state
    out = []
    for l in ss.logs:
        if l.get("setNo", 1) != ss.current_set:
            continue
        if l["type"] == "divider":
            break
        out.append(l)
    return out


def merge_matches_for_analysis(match_ids: list) -> tuple[list, list]:
    name_to_player: dict[str, dict] = {}
    name_to_new_id: dict[str, str] = {}
    merged_logs: list[dict] = []

    for mid in match_ids:
        m = storage.get_match(mid)
        if not m:
            continue
        old_to_new: dict = {}
        for p in m["players"]:
            name = p["name"]
            if name not in name_to_player:
                new_id = str(uuid.uuid4())
                name_to_player[name] = {**p, "id": new_id}
                name_to_new_id[name] = new_id
            old_to_new[p["id"]] = name_to_new_id[name]

        for l in m["logs"]:
            new_l = {**l}
            pid = l.get("playerId")
            if pid in old_to_new:
                new_l["playerId"] = old_to_new[pid]
            ppid = l.get("prevPlayerId")
            if ppid in old_to_new:
                new_l["prevPlayerId"] = old_to_new[ppid]
            merged_logs.append(new_l)

    return list(name_to_player.values()), merged_logs


# ══════════════════════════════════════════════════════════════════════════════
# Plotly 圖表函式
# ══════════════════════════════════════════════════════════════════════════════

_PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e8eaf2", family="DM Sans, sans-serif"),
    margin=dict(l=10, r=10, t=30, b=10),
)
_RADAR_GRID = dict(gridcolor="#252b3b", color="#7a849e")


def _fig_radar(stats: dict, color: str = "#f5a623") -> pgo.Figure | None:
    keys = list(stats.keys())
    if len(keys) < 3:
        return None
    labels = [gl.ATTR_TO_CHINESE.get(k, k) for k in keys]
    values = [stats[k] for k in keys]
    labels.append(labels[0]); values.append(values[0])
    fig = pgo.Figure(pgo.Scatterpolar(
        r=values, theta=labels, fill="toself",
        fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.18)",
        line=dict(color=color, width=2.5),
        marker=dict(size=5, color=color),
    ))
    fig.update_layout(
        **_PLOTLY_LAYOUT, height=240, showlegend=False,
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], **_RADAR_GRID),
            angularaxis=_RADAR_GRID, bgcolor="rgba(0,0,0,0)",
        ),
    )
    return fig


def _fig_donut(groups: dict, total: int) -> pgo.Figure:
    ctx_def = [("一般攻擊", "#4a9eff"), ("吊球", "#f5a623"), ("處理球", "#3ecf6a")]
    labels = [c for c, _ in ctx_def]
    values = [len(groups.get(c, [])) for c, _ in ctx_def]
    colors = [col for _, col in ctx_def]
    fig = pgo.Figure(pgo.Pie(
        labels=labels, values=values, hole=0.55,
        marker=dict(colors=colors, line=dict(color="rgba(12,14,19,1)", width=3)),
        textfont=dict(size=11, color="white"),
        textinfo="label+percent", textposition="outside",
        pull=[0.04, 0.04, 0.04],
    ))
    fig.update_layout(**_PLOTLY_LAYOUT, height=220, showlegend=False)
    return fig


def _fig_score_bar(groups: dict) -> pgo.Figure | None:
    ctx_def = [("一般攻擊", "#4a9eff"), ("吊球", "#f5a623"), ("處理球", "#3ecf6a")]
    labels, scores, colors = [], [], []
    for ctx, col in ctx_def:
        arr = groups.get(ctx, [])
        if arr:
            labels.append(ctx)
            scores.append(gl.safe_avg([l["scoreDelta"] for l in arr]))
            colors.append(col)
    if not labels:
        return None
    fig = pgo.Figure(pgo.Bar(
        y=labels, x=scores, orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[f"{s:+.0f}" for s in scores],
        textposition="outside", textfont=dict(color="#e8eaf2", size=13),
    ))
    fig.update_layout(
        **{k: v for k, v in _PLOTLY_LAYOUT.items() if k != "margin"},
        height=160, margin=dict(l=10, r=55, t=20, b=10),
        xaxis=dict(range=[-100, 100], gridcolor="#252b3b", color="#7a849e",
                   zeroline=True, zerolinecolor="#505a6e", showticklabels=False),
        yaxis=dict(gridcolor="rgba(0,0,0,0)", color="#e8eaf2"),
        showlegend=False,
    )
    return fig


def _fig_setter_heatmap(heatmap: dict) -> pgo.Figure:
    Q = gl.Q_KEYS
    z = [[heatmap.get(f"{pq}|{sq}", 0) for pq in Q] for sq in Q]
    max_val = max((v for row in z for v in row), default=1) or 1
    fig = pgo.Figure(pgo.Heatmap(
        z=z,
        x=[f"一傳 {q}" for q in Q],
        y=[f"舉球 {q}" for q in Q],
        colorscale=[[0, "#141720"], [0.4, "#7a4a10"], [1, "#f5a623"]],
        text=[[str(v) if v else "·" for v in row] for row in z],
        texttemplate="%{text}", textfont=dict(size=13),
        showscale=False, zmin=0, zmax=max_val,
    ))
    fig.update_layout(
        **{k: v for k, v in _PLOTLY_LAYOUT.items() if k != "margin"},
        height=230, margin=dict(l=70, r=10, t=40, b=60),
        xaxis=dict(side="top", gridcolor="#252b3b", color="#7a849e"),
        yaxis=dict(gridcolor="#252b3b", color="#7a849e", autorange="reversed"),
    )
    return fig


def _fig_defense_radar(def_data: list) -> pgo.Figure | None:
    filled = [(d["ctx"], d["score"]) for d in def_data if d["arr"]]
    if len(filled) < 3:
        return None
    labels = [c for c, _ in filled]; values = [v for _, v in filled]
    labels.append(labels[0]); values.append(values[0])
    fig = pgo.Figure(pgo.Scatterpolar(
        r=values, theta=labels, fill="toself",
        fillcolor="rgba(74,158,255,0.18)",
        line=dict(color="#4a9eff", width=2.5),
        marker=dict(size=5, color="#4a9eff"),
    ))
    fig.update_layout(
        **_PLOTLY_LAYOUT, height=260, showlegend=False,
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], **_RADAR_GRID),
            angularaxis=_RADAR_GRID, bgcolor="rgba(0,0,0,0)",
        ),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 首頁
# ══════════════════════════════════════════════════════════════════════════════

def page_home():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    st.markdown(
        "<h1 style='text-align:center;color:#f5a623;letter-spacing:3px;'>🏐 VOLLEY TRACKER PRO</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;color:#7a849e;'>智慧快記 × 雲端儲存 × PDF 報表</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.subheader("🔑 已有代碼？輸入載入")
        code_input = st.text_input(
            "輸入您的 8 碼個人代碼",
            max_chars=8, placeholder="例：A1B2C3D4",
        ).upper().strip()
        if st.button("載入我的比賽紀錄", type="primary", use_container_width=True):
            if not code_input:
                st.error("請輸入代碼！")
            elif not storage.user_exists(code_input):
                st.error("❌ 找不到此代碼，請確認後再試。")
            else:
                st.session_state.user_code = code_input
                st.session_state.selected_match_ids = []
                go("matches")

    with col2:
        st.subheader("✨ 第一次使用？建立新帳號")
        st.markdown("系統將為您產生一組**唯一代碼**，請務必**記錄下來**，之後憑此代碼載入所有比賽紀錄。")
        if st.button("建立新帳號並取得代碼", use_container_width=True):
            code = storage.create_user()
            st.session_state.user_code = code
            st.session_state.selected_match_ids = []
            st.success(f"✅ 您的代碼是：**{code}**　請截圖或記下！")
            st.balloons()
            time.sleep(2)
            go("matches")


# ══════════════════════════════════════════════════════════════════════════════
# 我的比賽
# ══════════════════════════════════════════════════════════════════════════════

def page_matches():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    ss = st.session_state
    code = ss.user_code

    st.markdown(
        f"<h2 style='color:#f5a623;'>📋 我的比賽　"
        f"<span style='font-size:14px;color:#7a849e;'>代碼：{code}</span></h2>",
        unsafe_allow_html=True,
    )

    col_new, col_analyze, col_logout = st.columns([2, 2, 1])
    with col_new:
        if st.button("➕ 新增比賽", type="primary", use_container_width=True):
            ss.match_id = None; ss.match_name = ""
            ss.players = [
                {"id": 1, "name": "球員A", "pos": "大砲"},
                {"id": 2, "name": "球員B", "pos": "舉球"},
                {"id": 3, "name": "球員C", "pos": "自由"},
            ]
            ss.logs = []; ss.current_set = 1
            ss.selected_player_id = 1
            ss.selected_action = None; ss.selected_context = None
            ss.prev_action_state = {k: None for k in ss.prev_action_state}
            ss.history_stack = []
            go("setup")
    with col_analyze:
        if st.button("📊 分析選中比賽", use_container_width=True, disabled=not ss.selected_match_ids):
            go("analysis")
    with col_logout:
        if st.button("登出", use_container_width=True):
            ss.user_code = None; ss.selected_match_ids = []
            go("home")

    st.divider()
    matches = storage.get_user_matches(code)

    if not matches:
        st.info("尚無比賽紀錄，點擊「新增比賽」開始記錄！")
        return

    st.caption("☑️ 勾選要納入分析的比賽，再點「分析選中比賽」")

    for m in matches:
        mid = m["id"]
        mname = m["match_name"]
        created = m["created_at"][:16].replace("T", " ")
        n_logs = len([l for l in m["logs"] if l.get("type") == "action"])
        n_sets = m.get("current_set", 1)

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([0.5, 3, 1.5, 1])
            with c1:
                checked = st.checkbox("", key=f"chk_{mid}", value=(mid in ss.selected_match_ids))
                if checked and mid not in ss.selected_match_ids:
                    ss.selected_match_ids.append(mid)
                elif not checked and mid in ss.selected_match_ids:
                    ss.selected_match_ids.remove(mid)
            with c2:
                st.markdown(f"**{mname}**")
                st.caption(f"🕐 {created}　｜　動作紀錄 {n_logs} 筆　｜　第 {n_sets} 局")
            with c3:
                if st.button("▶ 繼續記錄", key=f"cont_{mid}", use_container_width=True):
                    data = storage.get_match(mid)
                    ss.match_id = mid; ss.match_name = data["match_name"]
                    ss.players = data["players"]; ss.logs = data["logs"]
                    ss.current_set = data.get("current_set", 1)
                    ss.selected_player_id = data["players"][0]["id"] if data["players"] else None
                    ss.selected_action = None; ss.selected_context = None
                    ss.prev_action_state = {k: None for k in ss.prev_action_state}
                    ss.history_stack = []
                    go("record")
            with c4:
                if st.button("🗑️ 刪除", key=f"del_{mid}", use_container_width=True):
                    storage.delete_match(mid)
                    if mid in ss.selected_match_ids:
                        ss.selected_match_ids.remove(mid)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# 新增比賽設定
# ══════════════════════════════════════════════════════════════════════════════

def page_setup():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    ss = st.session_state
    st.markdown("<h2 style='color:#f5a623;'>⚙️ 新增比賽 — 設定球員</h2>", unsafe_allow_html=True)

    if st.button("← 返回比賽列表"):
        go("matches")
    st.divider()

    ss.match_name = st.text_input(
        "📝 比賽名稱（可留空，預設用日期）",
        value=ss.match_name or f"比賽 {datetime.now().strftime('%m/%d %H:%M')}",
    )
    st.subheader("👥 球員設定")

    players = ss.players[:]
    to_delete = None
    for i, p in enumerate(players):
        c1, c2, c3, c4 = st.columns([0.4, 2, 1.5, 0.5])
        with c1: st.markdown(f"**{i+1}**")
        with c2:
            new_name = st.text_input(f"姓名_{i}", value=p["name"], label_visibility="collapsed", key=f"pname_{i}")
            players[i]["name"] = new_name
        with c3:
            new_pos = st.selectbox(f"位置_{i}", gl.POSITIONS, index=gl.POSITIONS.index(p["pos"]),
                                   label_visibility="collapsed", key=f"ppos_{i}")
            players[i]["pos"] = new_pos
        with c4:
            if st.button("×", key=f"pdel_{i}"):
                to_delete = i

    if to_delete is not None:
        players.pop(to_delete)
    ss.players = players

    if st.button("➕ 新增球員"):
        ss.players.append({"id": int(time.time() * 1000) % 1_000_000, "name": f"球員{len(ss.players)+1}", "pos": "大砲"})
        st.rerun()
    st.divider()
    if st.button("🏐 開始記錄這場比賽", type="primary", use_container_width=True):
        if not ss.players:
            st.error("至少需要一位球員！")
            return
        if not ss.match_name.strip():
            ss.match_name = f"比賽 {datetime.now().strftime('%m/%d %H:%M')}"
        ss.selected_player_id = ss.players[0]["id"]
        go("record")


# ══════════════════════════════════════════════════════════════════════════════
# 比賽主畫面（含 Tab）
# ══════════════════════════════════════════════════════════════════════════════

def _render_match_header():
    """頂部 Logo + 結束按鈕列"""
    ss = st.session_state
    h1, h2 = st.columns([5, 1.2])
    with h1:
        st.markdown(
            "<div style='padding:2px 0 6px;'>"
            "<span style='font-size:20px;font-weight:900;letter-spacing:2px;color:#f5a623;'>VOLLEY TRACKER PRO</span>"
            "<span style='font-size:11px;color:#7a849e;margin-left:12px;'>智慧快記 × 視覺分析 × 分局報告</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    with h2:
        if st.button("💾 結束存檔", use_container_width=True, key="exit_match"):
            auto_save()
            go("matches")


def _render_set_selector():
    """局數切換列（pill 樣式）"""
    ss = st.session_state
    st.markdown('<div class="set-row">', unsafe_allow_html=True)
    sc = st.columns([1, 1, 1, 1.3, 8])
    for col, n, lbl in zip(sc[:3], [1, 2, 3], ["第1局", "第2局", "第3局"]):
        with col:
            if st.button(lbl, key=f"set_{n}",
                         type="primary" if ss.current_set == n else "secondary",
                         use_container_width=True):
                ss.current_set = n
                ss.selected_action = None; ss.selected_context = None
                ss.prev_action_state = {k: None for k in ss.prev_action_state}
                st.rerun()
    with sc[3]:
        if st.button("+ 下一局", disabled=ss.current_set >= 3,
                     use_container_width=True, key="nextset"):
            ss.current_set = min(3, ss.current_set + 1)
            ss.selected_action = None; ss.selected_context = None
            ss.prev_action_state = {k: None for k in ss.prev_action_state}
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


def _tab_roster():
    """名單 tab：可編輯球員"""
    ss = st.session_state
    with st.container(border=True):
        st.markdown("**👥 球員名單**　<span style='color:#7a849e;font-size:12px;'>可於比賽中修改名稱與位置</span>",
                    unsafe_allow_html=True)
        players = ss.players[:]
        to_delete = None
        for i, p in enumerate(players):
            c1, c2, c3, c4 = st.columns([0.4, 2, 1.5, 0.5])
            with c1: st.markdown(f"**{i+1}**")
            with c2:
                new_name = st.text_input(f"姓名_{i}", value=p["name"],
                                         label_visibility="collapsed", key=f"rname_{i}")
                players[i]["name"] = new_name
            with c3:
                new_pos = st.selectbox(f"位置_{i}", gl.POSITIONS,
                                       index=gl.POSITIONS.index(p["pos"]) if p["pos"] in gl.POSITIONS else 0,
                                       label_visibility="collapsed", key=f"rpos_{i}")
                players[i]["pos"] = new_pos
            with c4:
                if st.button("×", key=f"rdel_{i}"):
                    to_delete = i
        if to_delete is not None:
            players.pop(to_delete)
        ss.players = players
        if st.button("➕ 新增球員", key="roster_add"):
            ss.players.append({"id": int(time.time() * 1000) % 1_000_000,
                                "name": f"球員{len(ss.players)+1}", "pos": "大砲"})
            st.rerun()


def _tab_record():
    """智慧快記 tab"""
    ss = st.session_state

    with st.container(border=True):
        th1, th2, th3 = st.columns([4, 1, 1])
        with th1:
            st.markdown(
                "<span style='font-size:16px;font-weight:800;'>⚡ 智慧快記</span>"
                f"<span style='color:#7a849e;font-size:11px;margin-left:10px;'>"
                f"依照前置動作、位置與本分狀態自動縮小選項。現在是第 {ss.current_set} 局。</span>",
                unsafe_allow_html=True,
            )
        with th2:
            if st.button("↩ 復原", disabled=not ss.history_stack,
                         use_container_width=True, key="undo_btn"):
                do_undo(); st.rerun()
        with th3:
            if st.button("↻ 斷開前置", use_container_width=True, key="reset_btn"):
                ss.prev_action_state = {k: None for k in ss.prev_action_state}
                ss.selected_action = None; ss.selected_context = None
                st.rerun()

        sel_player = next((p for p in ss.players if p["id"] == ss.selected_player_id), None)
        prev = ss.prev_action_state
        prev_label = (f"{prev.get('context') or prev.get('action')} ({prev.get('quality')})"
                      if prev.get("action") else "無")
        rally_logs = get_rally_logs()
        used_serve = any(l.get("action") == "發球" for l in rally_logs)
        used_receive = any(l.get("action") == "接發" for l in rally_logs)
        last_divider = next((l for l in ss.logs if l["type"] == "divider"
                             and l.get("setNo", 1) == ss.current_set), None)
        last_winner = last_divider["winner"] if last_divider else None

        p_cols = st.columns(len(ss.players))
        for i, p in enumerate(ss.players):
            with p_cols[i]:
                is_sel = ss.selected_player_id == p["id"]
                if st.button(
                    f"{i+1}. {p['name']} ({p['pos']})",
                    key=f"player_sel_{p['id']}",
                    type="primary" if is_sel else "secondary",
                    use_container_width=True,
                ):
                    ss.selected_player_id = p["id"]
                    ss.selected_action = None; ss.selected_context = None
                    st.rerun()

        st.markdown(
            f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 2px;"
            f"font-size:12px;color:#7a849e;align-items:center;'>"
            f"目前球員：<b style='color:#f5a623;'>{sel_player['name'] if sel_player else '—'}</b>"
            f"　前置：<b style='color:#e8eaf2;'>{prev_label}</b>"
            f"　發球/接發："
            f"<span style='color:{'#3ecf6a' if used_serve else '#7a849e'};'>"
            f"{'已發球' if used_serve else '未發球'}</span>"
            f" / <span style='color:{'#3ecf6a' if used_receive else '#7a849e'};'>"
            f"{'已接發' if used_receive else '未接發'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── 建議動作（單橫列，精簡標籤）──────────────────────────────────────────
    quick_opts = gl.suggest_quick_options(
        ss.prev_action_state, sel_player, used_serve, used_receive, last_winner,
    )

    if quick_opts:
        opt_cols = st.columns(len(quick_opts))
        for i, opt in enumerate(quick_opts):
            with opt_cols[i]:
                is_active = (ss.selected_action == opt["a"] and ss.selected_context == opt["c"])
                if st.button(
                    opt["label"],
                    key=f"opt_{i}_{opt['a']}_{opt['c']}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                ):
                    ss.selected_action = opt["a"]
                    ss.selected_context = opt["c"]
                    st.rerun()

    with st.expander("📋 完整動作面板（進階）"):
        act_cols = st.columns(len(gl.ACTION_MAP))
        for i, (act, _) in enumerate(gl.ACTION_MAP.items()):
            with act_cols[i]:
                if st.button(act, key=f"fullact_{act}", use_container_width=True):
                    ss.selected_action = act
                    ss.selected_context = gl.default_context(act)
                    st.rerun()

    # ── 品質按鈕（時刻顯示，未選動作時 disabled）────────────────────────────
    if ss.selected_action:
        ctx_display = ss.selected_context or gl.default_context(ss.selected_action)
        q_label_html = (
            f"<b style='color:#e8eaf2;'>{ss.selected_action} — {ctx_display}</b>"
        )
    else:
        q_label_html = "<span style='color:#4a5270;'>請先在上方選擇動作</span>"
    st.markdown(
        f"<span id='qsec' style='display:none;'></span>"
        f"<div style='margin:10px 0 4px;font-size:12px;color:#7a849e;'>"
        f"品質　{q_label_html}</div>"
        """<style>
div:has(>#qsec) + div[data-testid="stHorizontalBlock"] button {
    min-height: 72px !important; font-size: 18px !important; font-weight: 900 !important;
}
div:has(>#qsec) + div[data-testid="stHorizontalBlock"] > div:nth-child(1) button:not(:disabled) {
    color:#3ecf6a!important; border-color:#3ecf6a55!important; background:#0c1e12!important;
}
div:has(>#qsec) + div[data-testid="stHorizontalBlock"] > div:nth-child(2) button:not(:disabled) {
    color:#4a9eff!important; border-color:#4a9eff55!important; background:#0c1525!important;
}
div:has(>#qsec) + div[data-testid="stHorizontalBlock"] > div:nth-child(3) button:not(:disabled) {
    color:#c8d2e8!important; border-color:#3a4560!important;
}
div:has(>#qsec) + div[data-testid="stHorizontalBlock"] > div:nth-child(4) button:not(:disabled) {
    color:#f5a623!important; border-color:#f5a62355!important; background:#1e1608!important;
}
div:has(>#qsec) + div[data-testid="stHorizontalBlock"] > div:nth-child(5) button:not(:disabled) {
    color:#e84343!important; border-color:#e8434355!important; background:#1e0808!important;
}
</style>""",
        unsafe_allow_html=True,
    )
    q_cols = st.columns(5)
    for i, q in enumerate(gl.Q_KEYS):
        with q_cols[i]:
            if st.button(f"{q}\n{gl.QUALITY_LABELS[q]}", key=f"quality_{q}",
                         disabled=not ss.selected_action,
                         use_container_width=True):
                add_log(q); st.rerun()

    # ── 本分結果 ─────────────────────────────────────────────────────────────
    st.markdown(
        "<span id='ressec' style='display:none;'></span>"
        """<style>
div:has(>#ressec) + div[data-testid="stHorizontalBlock"] button {
    min-height: 62px !important; font-size: 13px !important; font-weight: 800 !important;
}
div:has(>#ressec) + div[data-testid="stHorizontalBlock"] > div:nth-child(1) button {
    color:#3ecf6a!important; border-color:#3ecf6a!important; background:#0c1e12!important;
}
div:has(>#ressec) + div[data-testid="stHorizontalBlock"] > div:nth-child(2) button {
    color:#4dbb79!important; border-color:#4dbb7966!important; background:#0c1a10!important;
    border-style: dashed !important;
}
div:has(>#ressec) + div[data-testid="stHorizontalBlock"] > div:nth-child(3) button {
    color:#e84343!important; border-color:#e84343!important; background:#2a0a0a!important;
}
div:has(>#ressec) + div[data-testid="stHorizontalBlock"] > div:nth-child(4) button {
    color:#f5a623!important; border-color:#f5a62366!important; background:#1e1608!important;
}
</style>""",
        unsafe_allow_html=True,
    )
    _RESULT_CFG = [
        ("✓ 我方得分\n最後觸球加成", "win"),
        ("＋ 對方失誤\n不加成球員",  "oppError"),
        ("✗ 我方失分\n最後觸球扣分", "lose"),
        ("○ 對手好球\n不扣分",       "opponent"),
    ]
    res_cols = st.columns(4)
    for col, (label, ptype) in zip(res_cols, _RESULT_CFG):
        with col:
            if st.button(label, key=f"res_{ptype}", use_container_width=True):
                resolve_point(ptype); st.rerun()

    # ── 本局紀錄（快記下方）──────────────────────────────────────────────────
    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
    cur_logs = [l for l in ss.logs if l.get("setNo", 1) == ss.current_set]
    if cur_logs:
        st.markdown(
            "<div style='font-size:12px;color:#7a849e;margin-bottom:4px;'>📜 本局紀錄</div>",
            unsafe_allow_html=True,
        )
        def score_badge(v):
            color = gl.score_color_hex(v)
            return f"<span style='color:{color};font-weight:bold;'>{v:+}</span>"
        with st.container(border=True):
            for l in cur_logs:
                if l["type"] == "divider":
                    winner_color = "#3ecf6a" if l["winner"] == "us" else "#e84343"
                    st.markdown(
                        f"<div style='text-align:center;padding:5px 0;"
                        f"border-top:1px dashed #252b3b;'>"
                        f"<span style='background:{winner_color};color:#000;padding:2px 10px;"
                        f"border-radius:10px;font-size:11px;font-weight:bold;'>"
                        f"第{l.get('setNo',1)}局 ｜ {l['result']}</span></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    p_name = next((p["name"] for p in ss.players
                                   if p["id"] == l["playerId"]), "未知")
                    ctx = l.get("context", "一般")
                    display = ctx if ctx != "一般" else l["action"]
                    note = (f" <small style='color:#7a849e;'>{l['note']}</small>"
                            if l.get("note") else "")
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"padding:5px 0;border-bottom:1px solid #1b1f2e;font-size:13px;'>"
                        f"<span><b>{p_name}</b>：{display} ({l['quality']}) {note}</span>"
                        f"{score_badge(round(l['scoreDelta']))}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
    else:
        st.markdown(
            "<div style='text-align:center;color:#3a4560;font-size:13px;"
            "padding:20px 0;'>本局尚無紀錄</div>",
            unsafe_allow_html=True,
        )


def _tab_log():
    """完整紀錄 tab"""
    ss = st.session_state
    cur_logs = [l for l in ss.logs if l.get("setNo", 1) == ss.current_set]

    if not cur_logs:
        st.caption("本局尚無紀錄")
        return

    def score_badge(v):
        color = gl.score_color_hex(v)
        return f"<span style='color:{color};font-weight:bold;'>{v:+}</span>"

    with st.container(border=True):
        for l in cur_logs:
            if l["type"] == "divider":
                winner_color = "#3ecf6a" if l["winner"] == "us" else "#e84343"
                st.markdown(
                    f"<div style='text-align:center;padding:6px 0;border-top:1px dashed #252b3b;'>"
                    f"<span style='background:{winner_color};color:#000;padding:3px 12px;"
                    f"border-radius:10px;font-size:12px;font-weight:bold;'>"
                    f"第{l.get('setNo',1)}局 ｜ {l['result']}"
                    f"</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                p_name = next((p["name"] for p in ss.players if p["id"] == l["playerId"]), "未知")
                ctx = l.get("context", "一般")
                display = ctx if ctx != "一般" else l["action"]
                note = (f" <small style='color:#7a849e;'>{l['note']}</small>"
                        if l.get("note") else "")
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;"
                    f"padding:6px 0;border-bottom:1px solid #1b1f2e;font-size:13px;'>"
                    f"<span><b>{p_name}</b>：{display} ({l['quality']}) {note}</span>"
                    f"{score_badge(round(l['scoreDelta']))}"
                    f"</div>",
                    unsafe_allow_html=True,
                )


def _compute_action_breakdown(pid, action_logs):
    p_logs = [l for l in action_logs if l.get("playerId") == pid]
    if not p_logs:
        return ""
    counts = {}
    for l in p_logs:
        counts[l["action"]] = counts.get(l["action"], 0) + 1
    total = len(p_logs)
    parts = [f"{a} {round(c/total*100)}%"
             for a, c in sorted(counts.items(), key=lambda x: -x[1])]
    return " / ".join(parts[:3])


def _tab_score():
    """評分 tab"""
    ss = st.session_state
    logs = [l for l in ss.logs if l.get("type") == "action"]
    if ss.view_set is not None:
        logs = [l for l in logs if l.get("setNo", 1) == ss.view_set]

    if not logs:
        st.info("本局尚無動作紀錄")
        return

    player_stats = gl.compute_player_stats(ss.players, logs)
    n_cols = min(len(player_stats), 3)
    cols = st.columns(n_cols)

    for i, ps in enumerate(player_stats):
        with cols[i % n_cols]:
            with st.container(border=True):
                ovr_color = gl.score_color_hex(ps["ovr"])
                breakdown = _compute_action_breakdown(ps["id"], logs)

                # 橫向 OVR 數字 + 名稱
                st.markdown(
                    f"<div style='display:flex;align-items:flex-start;gap:14px;margin-bottom:10px;'>"
                    f"<div style='font-size:52px;font-weight:900;color:{ovr_color};"
                    f"line-height:1;min-width:60px;'>{ps['ovr']}</div>"
                    f"<div style='padding-top:4px;'>"
                    f"<div style='font-size:17px;font-weight:800;'>{ps['name']}</div>"
                    f"<div style='font-size:12px;color:#7a849e;margin-top:1px;'>{ps['pos']}</div>"
                    f"<div style='font-size:11px;color:#7a849e;margin-top:3px;'>{breakdown}</div>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )

                # 屬性列 + 進度條
                for attr, val in ps["stats"].items():
                    attr_name = gl.ATTR_TO_CHINESE.get(attr, attr)
                    bar_color = gl.score_color_hex(val)
                    pct = max(0, min(100, val))
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:8px;margin:5px 0;'>"
                        f"<span style='width:36px;font-size:12px;color:#8a94a8;"
                        f"text-align:right;flex-shrink:0;'>{attr_name}</span>"
                        f"<div style='flex:1;background:#1e2638;border-radius:4px;height:7px;'>"
                        f"<div style='width:{pct}%;background:{bar_color};"
                        f"border-radius:4px;height:7px;'></div></div>"
                        f"<span style='width:28px;font-size:13px;font-weight:800;"
                        f"color:{bar_color};text-align:right;flex-shrink:0;'>{val}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


def _tab_detail():
    """詳情 tab"""
    import pandas as pd
    ss = st.session_state
    logs = [l for l in ss.logs if l.get("type") == "action"]
    if ss.view_set is not None:
        logs = [l for l in logs if l.get("setNo", 1) == ss.view_set]

    if not logs:
        st.info("本局尚無動作紀錄")
        return

    player_stats = gl.compute_player_stats(ss.players, logs)
    _POS_COLORS = {
        "大砲": "#f5a623", "副攻": "#9b59b6", "背": "#e07a5f",
        "攔中": "#4a9eff", "舉球": "#4a9eff", "自由": "#3ecf6a",
    }

    for ps in player_stats:
        p_logs = [l for l in logs if l.get("playerId") == ps["id"]]
        if not p_logs:
            continue

        pos_color = _POS_COLORS.get(ps["pos"], "#7a849e")

        # 標題列
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;margin:16px 0 6px;'>"
            f"<span style='background:{pos_color};color:#000;padding:2px 10px;"
            f"border-radius:6px;font-size:12px;font-weight:800;'>{ps['pos']}</span>"
            f"<span style='font-size:17px;font-weight:800;'>{ps['name']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            # Header row
            hcols = st.columns([2.2, 2, 1, 1, 1, 1, 1, 1.8])
            labels = ["動作", "細項"] + gl.Q_KEYS + ["均分"]
            for col, lbl in zip(hcols, labels):
                col.markdown(f"<div style='color:#5a6480;font-size:11px;"
                             f"text-align:center;padding-bottom:4px;'>{lbl}</div>",
                             unsafe_allow_html=True)

            # Data rows
            groups: dict[str, list] = {}
            for l in p_logs:
                key = l["action"] + "|" + l.get("context", "一般")
                groups.setdefault(key, []).append(l)

            for key, arr in groups.items():
                action, ctx = key.split("|", 1)
                counts = {q: sum(1 for l in arr if l.get("quality") == q) for q in gl.Q_KEYS}
                avg = gl.safe_avg([l["scoreDelta"] for l in arr])
                avg_color = gl.score_color_hex(avg)

                st.markdown("<div style='border-top:1px solid #1a2035;'></div>",
                            unsafe_allow_html=True)
                rcols = st.columns([2.2, 2, 1, 1, 1, 1, 1, 1.8])
                rcols[0].markdown(f"<div style='font-size:13px;padding:3px 0;'>{action}</div>",
                                  unsafe_allow_html=True)
                rcols[1].markdown(f"<div style='font-size:12px;color:#7a849e;padding:3px 0;'>{ctx}</div>",
                                  unsafe_allow_html=True)
                for j, q in enumerate(gl.Q_KEYS):
                    v = counts.get(q, 0)
                    c_str = "#c8d2e8" if v else "#2a3450"
                    rcols[2 + j].markdown(
                        f"<div style='text-align:center;font-size:13px;color:{c_str};'>{v}</div>",
                        unsafe_allow_html=True,
                    )
                rcols[7].markdown(
                    f"<div style='text-align:right;font-size:13px;font-weight:800;"
                    f"color:{avg_color};padding-right:4px;'>{avg}</div>",
                    unsafe_allow_html=True,
                )


def _tab_visual():
    """視覺分析 tab"""
    ss = st.session_state
    logs = [l for l in ss.logs if l.get("type") == "action"]
    if ss.view_set is not None:
        logs = [l for l in logs if l.get("setNo", 1) == ss.view_set]

    if not logs:
        st.info("本局尚無動作紀錄")
        return

    attackers = [p for p in ss.players if gl.is_attacker(p)]
    setters = [p for p in ss.players if p.get("pos") == "舉球"]

    # ── 攻擊手：策略分佈 ──────────────────────────────────────────────────────
    st.subheader("🔥 攻擊手：策略分佈")
    if attackers:
        atk_cols = st.columns(min(len(attackers), 3))
        for i, p in enumerate(attackers):
            arr = [l for l in logs if l.get("playerId") == p["id"] and l.get("action") == "攻擊"]
            groups: dict[str, list] = {}
            for l in arr:
                groups.setdefault(l.get("context", ""), []).append(l)
            with atk_cols[i % len(atk_cols)]:
                with st.container(border=True):
                    st.markdown(
                        f"**{p['name']}** <span style='color:#7a849e;font-size:12px;'>"
                        f"({p['pos']}) {len(arr)} 次</span>",
                        unsafe_allow_html=True,
                    )
                    if arr:
                        pie_col, bar_col = st.columns([1, 1])
                        with pie_col:
                            st.caption("策略頻率")
                            st.plotly_chart(_fig_donut(groups, len(arr)),
                                            use_container_width=True,
                                            config={"displayModeBar": False})
                        with bar_col:
                            st.caption("各策略評分")
                            fig_bar = _fig_score_bar(groups)
                            if fig_bar:
                                st.plotly_chart(fig_bar, use_container_width=True,
                                               config={"displayModeBar": False})
                    else:
                        st.caption("無攻擊數據")
    else:
        st.caption("尚無攻擊手數據")

    st.markdown("---")

    # ── 舉球員熱力圖 ──────────────────────────────────────────────────────────
    st.subheader("🧠 舉球員：配球效益 & 品質熱力圖")
    T_COLORS = ["#4a9eff", "#f5a623", "#3ecf6a", "#e84343", "#9b59b6", "#e07a5f"]
    if setters:
        for s_p in setters:
            sets_arr = [l for l in logs if l.get("playerId") == s_p["id"] and l.get("action") == "舉球"]
            atk_after = [l for l in logs if l.get("action") == "攻擊" and l.get("prevPlayerId") == s_p["id"]]
            by_target: dict = {}
            for l in atk_after:
                by_target.setdefault(l.get("playerId"), []).append(l)
            total_sets = len(atk_after)
            avg_set = gl.safe_avg([l["scoreDelta"] for l in sets_arr])

            with st.container(border=True):
                h1, h2 = st.columns([3, 1])
                h1.markdown(f"**{s_p['name']}**")
                h2.markdown(
                    f"<div style='text-align:right;color:#7a849e;font-size:12px;'>"
                    f"舉球均分 <b style='color:{gl.score_color_hex(avg_set)};'>"
                    f"{avg_set if sets_arr else '—'}</b> / {len(sets_arr)} 次</div>",
                    unsafe_allow_html=True,
                )

                if total_sets > 0:
                    atk_list = [p for p in ss.players if gl.is_attacker(p)]
                    strip = "<div style='display:flex;height:22px;border-radius:8px;overflow:hidden;margin:8px 0;'>"
                    for ti, t in enumerate(atk_list):
                        a = by_target.get(t["id"], [])
                        pct = len(a) / total_sets * 100
                        if pct > 0:
                            col = T_COLORS[ti % len(T_COLORS)]
                            strip += (
                                f"<div style='width:{pct:.1f}%;background:{col};"
                                f"display:flex;align-items:center;justify-content:center;"
                                f"font-size:10px;font-weight:900;color:#000;overflow:hidden;'>"
                                f"{'&nbsp;' + t['name'] if pct >= 10 else ''}</div>"
                            )
                    strip += "</div>"
                    st.markdown(strip, unsafe_allow_html=True)

                    for ti, t in enumerate(atk_list):
                        a = by_target.get(t["id"], [])
                        pct = round(len(a) / total_sets * 100) if total_sets else 0
                        sc = gl.safe_avg([l["scoreDelta"] for l in a])
                        col = T_COLORS[ti % len(T_COLORS)]
                        rc1, rc2, rc3 = st.columns([3, 1, 1])
                        rc1.markdown(
                            f"<span style='color:{col};font-size:14px;'>●</span> **{t['name']}** "
                            f"<span style='color:#7a849e;font-size:11px;'>{t['pos']}</span>",
                            unsafe_allow_html=True,
                        )
                        rc2.markdown(f"<div style='text-align:center;font-size:12px;'>"
                                     f"{len(a)}球 / {pct}%</div>", unsafe_allow_html=True)
                        rc3.markdown(
                            f"<div style='text-align:center;font-weight:900;"
                            f"color:{gl.score_color_hex(sc)};'>{sc if a else '—'}</div>",
                            unsafe_allow_html=True,
                        )

                st.markdown("**舉球品質熱力圖**　"
                            "<span style='color:#7a849e;font-size:11px;'>行＝舉球品質 / 列＝一傳品質</span>",
                            unsafe_allow_html=True)
                heatmap: dict[str, int] = {f"{pq}|{sq}": 0 for pq in gl.Q_KEYS for sq in gl.Q_KEYS}
                for l in sets_arr:
                    pq = l.get("prevQuality")
                    if pq:
                        heatmap[f"{pq}|{l['quality']}"] = heatmap.get(f"{pq}|{l['quality']}", 0) + 1
                st.plotly_chart(_fig_setter_heatmap(heatmap),
                                use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("尚無舉球員")

    st.markdown("---")

    # ── 團隊防守 ──────────────────────────────────────────────────────────────
    st.subheader("🛡 團隊防守")
    def_ctxs = ["接發", "接扣", "一般防守", "吊球/Cover", "接嗆司"]
    def_data = []
    for ctx in def_ctxs:
        if ctx == "接發":
            arr = [l for l in logs if l.get("action") == "接發"]
        elif ctx == "接扣":
            arr = [l for l in logs if l.get("action") == "接扣"]
        else:
            arr = [l for l in logs if l.get("action") == "防守" and l.get("context") == ctx]
        def_data.append({
            "ctx": ctx, "arr": arr,
            "score": gl.safe_avg([l["scoreDelta"] for l in arr]) if arr else 0,
        })

    dc1, dc2 = st.columns([1, 1])
    with dc1:
        fig_def = _fig_defense_radar(def_data)
        if fig_def:
            st.plotly_chart(fig_def, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("需要 3 項以上防守數據才能顯示雷達圖")
    with dc2:
        for d in def_data:
            sc = d["score"]
            dn1, dn2 = st.columns([3, 1])
            dn1.markdown(
                f"**{d['ctx']}** <span style='color:#7a849e;font-size:11px;'>({len(d['arr'])} 次)</span>",
                unsafe_allow_html=True,
            )
            dn2.markdown(
                f"<b style='color:{gl.score_color_hex(sc)};'>{sc if d['arr'] else '—'}</b>",
                unsafe_allow_html=True,
            )
            if d["arr"]:
                st.progress(sc / 100)


def page_record():
    ss = st.session_state
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    # Header
    _render_match_header()

    # Set selector
    _render_set_selector()

    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

    # 主 Tab 區
    tabs = st.tabs(["名單", "智慧快記", "評分", "詳情", "視覺分析"])
    with tabs[0]: _tab_roster()
    with tabs[1]: _tab_record()
    with tabs[2]: _tab_score()
    with tabs[3]: _tab_detail()
    with tabs[4]: _tab_visual()


# ══════════════════════════════════════════════════════════════════════════════
# 多場次分析頁（從比賽列表進入）
# ══════════════════════════════════════════════════════════════════════════════

def page_analysis():
    import pandas as pd
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    ss = st.session_state

    if not ss.selected_match_ids:
        st.warning("請先在「我的比賽」頁面勾選至少一場比賽！")
        if st.button("← 返回"):
            go("matches")
        return

    match_titles = []
    for mid in ss.selected_match_ids:
        m = storage.get_match(mid)
        if m:
            match_titles.append(m["match_name"])

    st.markdown("<h2 style='color:#f5a623;'>📊 數據分析</h2>", unsafe_allow_html=True)
    st.caption(f"分析範圍：{' / '.join(match_titles)}")

    hdr1, hdr2 = st.columns([1, 1])
    with hdr1:
        if st.button("← 返回比賽列表"):
            go("matches")
    with hdr2:
        if st.button("🖨️ 產生 PDF 報表", type="primary", use_container_width=True):
            players_full, logs_full = merge_matches_for_analysis(ss.selected_match_ids)
            with st.spinner("正在生成 PDF，請稍候..."):
                pdf_bytes = generate_pdf(match_titles, players_full, logs_full)
            fname = f"VolleyReport_{'_'.join(match_titles[:2])}_{datetime.now().strftime('%Y%m%d')}.pdf"
            st.download_button("⬇️ 下載 PDF", data=pdf_bytes, file_name=fname,
                               mime="application/pdf", use_container_width=True)

    st.divider()

    # 局數篩選
    st.markdown("**🔍 局數篩選**")
    vs = ss.view_set
    fc1, fc2, fc3, fc4 = st.columns(4)
    if fc1.button("完整比賽", type="primary" if vs is None else "secondary", use_container_width=True):
        ss.view_set = None; st.rerun()
    for col, n in zip([fc2, fc3, fc4], [1, 2, 3]):
        if col.button(f"第 {n} 局", type="primary" if vs == n else "secondary", use_container_width=True):
            ss.view_set = n; st.rerun()

    st.divider()

    players, logs_all = merge_matches_for_analysis(ss.selected_match_ids)
    logs = logs_all if ss.view_set is None else [l for l in logs_all if l.get("setNo", 1) == ss.view_set]
    action_logs = [l for l in logs if l.get("type") == "action"]
    player_stats = gl.compute_player_stats(players, action_logs)

    if not action_logs:
        st.info("選中的比賽（該局）尚無動作紀錄。")
        return

    tab_score, tab_detail, tab_visual = st.tabs(["🏅 評分", "📋 詳情", "📈 視覺分析"])

    with tab_score:
        n_cols = min(len(player_stats), 3)
        cols = st.columns(n_cols)
        for i, ps in enumerate(player_stats):
            with cols[i % n_cols]:
                with st.container(border=True):
                    ovr_color = gl.score_color_hex(ps["ovr"])
                    breakdown = _compute_action_breakdown(ps["id"], action_logs)
                    st.markdown(
                        f"<div style='display:flex;align-items:flex-start;gap:14px;margin-bottom:10px;'>"
                        f"<div style='font-size:52px;font-weight:900;color:{ovr_color};"
                        f"line-height:1;min-width:60px;'>{ps['ovr']}</div>"
                        f"<div style='padding-top:4px;'>"
                        f"<div style='font-size:17px;font-weight:800;'>{ps['name']}</div>"
                        f"<div style='font-size:12px;color:#7a849e;'>{ps['pos']}</div>"
                        f"<div style='font-size:11px;color:#7a849e;margin-top:2px;'>{breakdown}</div>"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
                    for attr, val in ps["stats"].items():
                        attr_name = gl.ATTR_TO_CHINESE.get(attr, attr)
                        bar_color = gl.score_color_hex(val)
                        pct = max(0, min(100, val))
                        st.markdown(
                            f"<div style='display:flex;align-items:center;gap:8px;margin:5px 0;'>"
                            f"<span style='width:36px;font-size:12px;color:#8a94a8;"
                            f"text-align:right;flex-shrink:0;'>{attr_name}</span>"
                            f"<div style='flex:1;background:#1e2638;border-radius:4px;height:7px;'>"
                            f"<div style='width:{pct}%;background:{bar_color};"
                            f"border-radius:4px;height:7px;'></div></div>"
                            f"<span style='width:28px;font-size:13px;font-weight:800;"
                            f"color:{bar_color};text-align:right;flex-shrink:0;'>{val}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

    with tab_detail:
        _POS_COLORS = {
            "大砲": "#f5a623", "副攻": "#9b59b6", "背": "#e07a5f",
            "攔中": "#4a9eff", "舉球": "#4a9eff", "自由": "#3ecf6a",
        }
        for ps in player_stats:
            p_logs = [l for l in action_logs if l.get("playerId") == ps["id"]]
            if not p_logs:
                continue
            pos_color = _POS_COLORS.get(ps["pos"], "#7a849e")
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;margin:16px 0 6px;'>"
                f"<span style='background:{pos_color};color:#000;padding:2px 10px;"
                f"border-radius:6px;font-size:12px;font-weight:800;'>{ps['pos']}</span>"
                f"<span style='font-size:17px;font-weight:800;'>{ps['name']}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                hcols = st.columns([2.2, 2, 1, 1, 1, 1, 1, 1.8])
                for col, lbl in zip(hcols, ["動作", "細項"] + gl.Q_KEYS + ["均分"]):
                    col.markdown(
                        f"<div style='color:#5a6480;font-size:11px;text-align:center;"
                        f"padding-bottom:4px;'>{lbl}</div>",
                        unsafe_allow_html=True,
                    )
                groups: dict[str, list] = {}
                for l in p_logs:
                    key = l["action"] + "|" + l.get("context", "一般")
                    groups.setdefault(key, []).append(l)
                for key, arr in groups.items():
                    action, ctx = key.split("|", 1)
                    counts = {q: sum(1 for l in arr if l.get("quality") == q) for q in gl.Q_KEYS}
                    avg = gl.safe_avg([l["scoreDelta"] for l in arr])
                    avg_color = gl.score_color_hex(avg)
                    st.markdown("<div style='border-top:1px solid #1a2035;'></div>",
                                unsafe_allow_html=True)
                    rcols = st.columns([2.2, 2, 1, 1, 1, 1, 1, 1.8])
                    rcols[0].markdown(f"<div style='font-size:13px;padding:3px 0;'>{action}</div>",
                                      unsafe_allow_html=True)
                    rcols[1].markdown(f"<div style='font-size:12px;color:#7a849e;'>{ctx}</div>",
                                      unsafe_allow_html=True)
                    for j, q in enumerate(gl.Q_KEYS):
                        v = counts.get(q, 0)
                        c_str = "#c8d2e8" if v else "#2a3450"
                        rcols[2+j].markdown(
                            f"<div style='text-align:center;font-size:13px;color:{c_str};'>{v}</div>",
                            unsafe_allow_html=True,
                        )
                    rcols[7].markdown(
                        f"<div style='text-align:right;font-size:13px;font-weight:800;"
                        f"color:{avg_color};'>{avg}</div>",
                        unsafe_allow_html=True,
                    )

    with tab_visual:
        # 重用 _tab_visual 的邏輯但使用 action_logs + players
        attackers = [p for p in players if gl.is_attacker(p)]
        setters = [p for p in players if p.get("pos") == "舉球"]

        st.subheader("🔥 攻擊手：策略分佈")
        if attackers:
            atk_cols = st.columns(min(len(attackers), 3))
            for i, p in enumerate(attackers):
                arr = [l for l in action_logs if l.get("playerId") == p["id"] and l.get("action") == "攻擊"]
                groups: dict[str, list] = {}
                for l in arr:
                    groups.setdefault(l.get("context", ""), []).append(l)
                with atk_cols[i % len(atk_cols)]:
                    with st.container(border=True):
                        st.markdown(f"**{p['name']}** <span style='color:#7a849e;font-size:12px;'>"
                                    f"({p['pos']}) {len(arr)} 次</span>", unsafe_allow_html=True)
                        if arr:
                            pie_col, bar_col = st.columns([1, 1])
                            with pie_col:
                                st.caption("策略頻率")
                                st.plotly_chart(_fig_donut(groups, len(arr)),
                                                use_container_width=True, config={"displayModeBar": False})
                            with bar_col:
                                st.caption("各策略評分")
                                fig_bar = _fig_score_bar(groups)
                                if fig_bar:
                                    st.plotly_chart(fig_bar, use_container_width=True,
                                                   config={"displayModeBar": False})
                        else:
                            st.caption("無攻擊數據")
        else:
            st.caption("尚無攻擊手數據")

        st.markdown("---")
        st.subheader("🧠 舉球員：配球效益 & 品質熱力圖")
        T_COLORS = ["#4a9eff", "#f5a623", "#3ecf6a", "#e84343", "#9b59b6", "#e07a5f"]
        if setters:
            for s_p in setters:
                sets_arr = [l for l in action_logs
                            if l.get("playerId") == s_p["id"] and l.get("action") == "舉球"]
                atk_after = [l for l in action_logs
                             if l.get("action") == "攻擊" and l.get("prevPlayerId") == s_p["id"]]
                by_target: dict = {}
                for l in atk_after:
                    by_target.setdefault(l.get("playerId"), []).append(l)
                total_sets = len(atk_after)
                avg_set = gl.safe_avg([l["scoreDelta"] for l in sets_arr])

                with st.container(border=True):
                    h1, h2 = st.columns([3, 1])
                    h1.markdown(f"**{s_p['name']}**")
                    h2.markdown(
                        f"<div style='text-align:right;color:#7a849e;font-size:12px;'>"
                        f"舉球均分 <b style='color:{gl.score_color_hex(avg_set)};'>"
                        f"{avg_set if sets_arr else '—'}</b> / {len(sets_arr)} 次</div>",
                        unsafe_allow_html=True,
                    )
                    if total_sets > 0:
                        atk_list = [p for p in players if gl.is_attacker(p)]
                        strip = "<div style='display:flex;height:22px;border-radius:8px;overflow:hidden;margin:8px 0;'>"
                        for ti, t in enumerate(atk_list):
                            a = by_target.get(t["id"], [])
                            pct = len(a) / total_sets * 100
                            if pct > 0:
                                col = T_COLORS[ti % len(T_COLORS)]
                                strip += (
                                    f"<div style='width:{pct:.1f}%;background:{col};"
                                    f"display:flex;align-items:center;justify-content:center;"
                                    f"font-size:10px;font-weight:900;color:#000;overflow:hidden;'>"
                                    f"{'&nbsp;'+t['name'] if pct >= 10 else ''}</div>"
                                )
                        strip += "</div>"
                        st.markdown(strip, unsafe_allow_html=True)
                    heatmap: dict[str, int] = {f"{pq}|{sq}": 0 for pq in gl.Q_KEYS for sq in gl.Q_KEYS}
                    for l in sets_arr:
                        pq = l.get("prevQuality")
                        if pq:
                            heatmap[f"{pq}|{l['quality']}"] = heatmap.get(f"{pq}|{l['quality']}", 0) + 1
                    st.plotly_chart(_fig_setter_heatmap(heatmap),
                                    use_container_width=True, config={"displayModeBar": False})

        st.markdown("---")
        st.subheader("🛡 團隊防守")
        def_ctxs = ["接發", "接扣", "一般防守", "吊球/Cover", "接嗆司"]
        def_data = []
        for ctx in def_ctxs:
            if ctx == "接發":
                arr = [l for l in action_logs if l.get("action") == "接發"]
            elif ctx == "接扣":
                arr = [l for l in action_logs if l.get("action") == "接扣"]
            else:
                arr = [l for l in action_logs if l.get("action") == "防守" and l.get("context") == ctx]
            def_data.append({
                "ctx": ctx, "arr": arr,
                "score": gl.safe_avg([l["scoreDelta"] for l in arr]) if arr else 0,
            })
        dc1, dc2 = st.columns([1, 1])
        with dc1:
            fig_def = _fig_defense_radar(def_data)
            if fig_def:
                st.plotly_chart(fig_def, use_container_width=True, config={"displayModeBar": False})
            else:
                st.caption("需要 3 項以上防守數據才能顯示雷達圖")
        with dc2:
            for d in def_data:
                sc = d["score"]
                dn1, dn2 = st.columns([3, 1])
                dn1.markdown(
                    f"**{d['ctx']}** <span style='color:#7a849e;font-size:11px;'>({len(d['arr'])} 次)</span>",
                    unsafe_allow_html=True,
                )
                dn2.markdown(
                    f"<b style='color:{gl.score_color_hex(sc)};'>{sc if d['arr'] else '—'}</b>",
                    unsafe_allow_html=True,
                )
                if d["arr"]:
                    st.progress(max(0.0, min(1.0, sc / 100)))


# ══════════════════════════════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════════════════════════════

def main():
    page = st.session_state.page
    if page != "home" and not st.session_state.user_code:
        st.session_state.page = "home"
        page = "home"

    if page == "home":
        page_home()
    elif page == "matches":
        page_matches()
    elif page == "setup":
        page_setup()
    elif page == "record":
        page_record()
    elif page == "analysis":
        page_analysis()
    else:
        page_home()


if __name__ == "__main__":
    main()
