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
# Session State 初始化
# ══════════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    "page": "home",
    "user_code": None,
    # ── 記錄中的比賽 ─────────────────────────
    "match_id": None,
    "match_name": "",
    "players": [
        {"id": 1, "name": "球員A", "pos": "大砲"},
        {"id": 2, "name": "球員B", "pos": "舉球"},
        {"id": 3, "name": "球員C", "pos": "自由"},
    ],
    "logs": [],
    "current_set": 1,
    # ── 快記狀態 ─────────────────────────────
    "selected_player_id": 1,
    "selected_action": None,
    "selected_context": None,
    "prev_action_state": {
        "quality": None, "action": None,
        "logId": None, "playerId": None, "context": None,
    },
    "history_stack": [],
    # ── 分析 ─────────────────────────────────
    "selected_match_ids": [],
    "view_set": None,           # None=完整比賽, 1/2/3=特定局
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════

def go(page: str):
    st.session_state.page = page
    st.rerun()


def auto_save():
    """若已有 match_id 就更新資料庫，否則先建立"""
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

    # 舉球→攻擊失分 → 更新舉球員那筆紀錄
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
        "id": log_id,
        "type": "action",
        "setNo": ss.current_set,
        "playerId": player_id,
        "action": action,
        "context": context,
        "quality": quality,
        "prevQuality": prev.get("quality"),
        "prevAction": prev.get("action"),
        "prevPlayerId": prev.get("playerId"),
        "prevContext": prev.get("context"),
        "scoreDelta": score_delta,
        "note": note,
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
    """結束這分：win / oppError / lose / opponent"""
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
        # 找本局最後一筆 action
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
        "id": str(uuid.uuid4()),
        "type": "divider",
        "setNo": ss.current_set,
        "result": result_label,
        "winner": winner,
    }
    ss.logs.insert(0, divider)
    ss.prev_action_state = {k: None for k in ss.prev_action_state}
    ss.selected_action = None
    ss.selected_context = None
    auto_save()


def get_rally_logs():
    """本局、本分（上一個 divider 之前）的 action 紀錄"""
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
    """
    合併多場比賽資料。
    同名球員視為同一人（使用 name 作為主鍵，pos 取第一場的設定）。
    回傳 (unified_players, merged_logs)
    """
    name_to_player: dict[str, dict] = {}
    name_to_new_id: dict[str, str] = {}
    merged_logs: list[dict] = []

    for mid in match_ids:
        m = storage.get_match(mid)
        if not m:
            continue
        # 建立舊 id → 新 id 的對應
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
# Plotly 圖表工具函式
# ══════════════════════════════════════════════════════════════════════════════

_PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e8eaf2", family="DM Sans, sans-serif"),
    margin=dict(l=10, r=10, t=30, b=10),
)
_RADAR_GRID = dict(gridcolor="#252b3b", color="#7a849e")


def _fig_radar(stats: dict, color: str = "#f5a623") -> pgo.Figure | None:
    """球員屬性雷達圖。少於 3 項時回傳 None。"""
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
        **_PLOTLY_LAYOUT,
        height=260,
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], **_RADAR_GRID),
            angularaxis=_RADAR_GRID,
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=False,
    )
    return fig


def _fig_donut(groups: dict, total: int) -> pgo.Figure:
    """攻擊策略中空圓餅圖。"""
    ctx_def = [("一般攻擊", "#4a9eff"), ("吊球", "#f5a623"), ("處理球", "#3ecf6a")]
    labels  = [c for c, _ in ctx_def]
    values  = [len(groups.get(c, [])) for c, _ in ctx_def]
    colors  = [col for _, col in ctx_def]
    fig = pgo.Figure(pgo.Pie(
        labels=labels, values=values, hole=0.55,
        marker=dict(colors=colors, line=dict(color="rgba(12,14,19,1)", width=3)),
        textfont=dict(size=11, color="white"),
        textinfo="label+percent", textposition="outside",
        pull=[0.04, 0.04, 0.04],
    ))
    fig.update_layout(**_PLOTLY_LAYOUT, height=220, showlegend=False)
    return fig


def _fig_setter_heatmap(heatmap: dict) -> pgo.Figure:
    """舉球品質熱力圖。行=舉球品質，列=一傳品質。"""
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
        height=230,
        margin=dict(l=70, r=10, t=40, b=60),
        xaxis=dict(side="top", gridcolor="#252b3b", color="#7a849e"),
        yaxis=dict(gridcolor="#252b3b", color="#7a849e", autorange="reversed"),
    )
    return fig


def _fig_defense_radar(def_data: list) -> pgo.Figure | None:
    """團隊防守雷達圖。"""
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
# ── 首頁 ──────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def page_home():
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
            max_chars=8,
            placeholder="例：A1B2C3D4",
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
        st.markdown(
            "系統將為您產生一組**唯一代碼**，請務必**記錄下來**，之後憑此代碼載入所有比賽紀錄。"
        )
        if st.button("建立新帳號並取得代碼", use_container_width=True):
            code = storage.create_user()
            st.session_state.user_code = code
            st.session_state.selected_match_ids = []
            st.success(f"✅ 您的代碼是：**{code}**　請截圖或記下！")
            st.balloons()
            time.sleep(2)
            go("matches")


# ══════════════════════════════════════════════════════════════════════════════
# ── 我的比賽 ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def page_matches():
    ss = st.session_state
    code = ss.user_code

    st.markdown(
        f"<h2 style='color:#f5a623;'>📋 我的比賽　<span style='font-size:14px;color:#7a849e;'>代碼：{code}</span></h2>",
        unsafe_allow_html=True,
    )

    col_new, col_analyze, col_logout = st.columns([2, 2, 1])
    with col_new:
        if st.button("➕ 新增比賽", type="primary", use_container_width=True):
            # 重置記錄狀態
            ss.match_id = None
            ss.match_name = ""
            ss.players = [
                {"id": 1, "name": "球員A", "pos": "大砲"},
                {"id": 2, "name": "球員B", "pos": "舉球"},
                {"id": 3, "name": "球員C", "pos": "自由"},
            ]
            ss.logs = []
            ss.current_set = 1
            ss.selected_player_id = 1
            ss.selected_action = None
            ss.selected_context = None
            ss.prev_action_state = {k: None for k in ss.prev_action_state}
            ss.history_stack = []
            go("setup")

    with col_analyze:
        if st.button("📊 分析選中比賽", use_container_width=True, disabled=not ss.selected_match_ids):
            go("analysis")

    with col_logout:
        if st.button("登出", use_container_width=True):
            ss.user_code = None
            ss.selected_match_ids = []
            go("home")

    st.divider()

    matches = storage.get_user_matches(code)

    if not matches:
        st.info("尚無比賽紀錄，點擊「新增比賽」開始記錄！")
        return

    # 說明文字
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
                checked = st.checkbox(
                    "", key=f"chk_{mid}",
                    value=(mid in ss.selected_match_ids),
                )
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
                    ss.match_id = mid
                    ss.match_name = data["match_name"]
                    ss.players = data["players"]
                    ss.logs = data["logs"]
                    ss.current_set = data.get("current_set", 1)
                    ss.selected_player_id = data["players"][0]["id"] if data["players"] else None
                    ss.selected_action = None
                    ss.selected_context = None
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
# ── 新增比賽（設定球員） ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def page_setup():
    ss = st.session_state
    st.markdown("<h2 style='color:#f5a623;'>⚙️ 新增比賽 — 設定球員</h2>", unsafe_allow_html=True)

    if st.button("← 返回比賽列表"):
        go("matches")

    st.divider()

    # 比賽名稱
    ss.match_name = st.text_input(
        "📝 比賽名稱（可留空，預設用日期）",
        value=ss.match_name or f"比賽 {datetime.now().strftime('%m/%d %H:%M')}",
    )

    st.subheader("👥 球員設定")

    players = ss.players[:]
    to_delete = None

    for i, p in enumerate(players):
        c1, c2, c3, c4 = st.columns([0.4, 2, 1.5, 0.5])
        with c1:
            st.markdown(f"**{i+1}**")
        with c2:
            new_name = st.text_input(f"姓名_{i}", value=p["name"], label_visibility="collapsed", key=f"pname_{i}")
            players[i]["name"] = new_name
        with c3:
            new_pos = st.selectbox(f"位置_{i}", gl.POSITIONS, index=gl.POSITIONS.index(p["pos"]), label_visibility="collapsed", key=f"ppos_{i}")
            players[i]["pos"] = new_pos
        with c4:
            if st.button("×", key=f"pdel_{i}"):
                to_delete = i

    if to_delete is not None:
        players.pop(to_delete)
    ss.players = players

    if st.button("➕ 新增球員"):
        ss.players.append({
            "id": int(time.time() * 1000) % 1_000_000,
            "name": f"球員{len(ss.players)+1}",
            "pos": "大砲",
        })
        st.rerun()

    st.divider()

    if st.button("🏐 開始記錄這場比賽", type="primary", use_container_width=True):
        if not ss.players:
            st.error("至少需要一位球員！")
            return
        # 確保 match_name 不空
        if not ss.match_name.strip():
            ss.match_name = f"比賽 {datetime.now().strftime('%m/%d %H:%M')}"
        ss.selected_player_id = ss.players[0]["id"]
        go("record")


# ══════════════════════════════════════════════════════════════════════════════
# ── 快速記錄 ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def page_record():
    ss = st.session_state

    # ── 頂部資訊列 ────────────────────────────────────────────────────────────
    hcol1, hcol2, hcol3 = st.columns([3, 2, 1])
    with hcol1:
        st.markdown(f"<h2 style='color:#f5a623;margin-bottom:0;'>⚡ {ss.match_name}</h2>", unsafe_allow_html=True)
    with hcol2:
        # 局數切換
        set_cols = st.columns(4)
        for idx, n in enumerate([1, 2, 3]):
            with set_cols[idx]:
                active = ss.current_set == n
                if st.button(f"第{n}局", key=f"set_{n}",
                             type="primary" if active else "secondary",
                             use_container_width=True):
                    ss.current_set = n
                    ss.selected_action = None
                    ss.selected_context = None
                    ss.prev_action_state = {k: None for k in ss.prev_action_state}
                    st.rerun()
        with set_cols[3]:
            if st.button("＋局", disabled=ss.current_set >= 3,
                         use_container_width=True, key="nextset"):
                ss.current_set = min(3, ss.current_set + 1)
                ss.selected_action = None
                ss.selected_context = None
                ss.prev_action_state = {k: None for k in ss.prev_action_state}
                st.rerun()
    with hcol3:
        if st.button("← 離開", use_container_width=True):
            auto_save()
            go("matches")

    st.divider()

    # ── 球員選擇 ──────────────────────────────────────────────────────────────
    st.markdown("**👤 選擇球員**")
    p_cols = st.columns(len(ss.players))
    for i, p in enumerate(ss.players):
        with p_cols[i]:
            is_sel = ss.selected_player_id == p["id"]
            if st.button(
                f"{p['name']}\n({p['pos']})",
                key=f"player_sel_{p['id']}",
                type="primary" if is_sel else "secondary",
                use_container_width=True,
            ):
                ss.selected_player_id = p["id"]
                ss.selected_action = None
                ss.selected_context = None
                st.rerun()

    # ── 狀態列 ────────────────────────────────────────────────────────────────
    sel_player = next((p for p in ss.players if p["id"] == ss.selected_player_id), None)
    prev = ss.prev_action_state
    prev_label = f"{prev.get('context') or prev.get('action')} ({prev.get('quality')})" if prev.get("action") else "無"

    rally_logs = get_rally_logs()
    used_serve = any(l.get("action") == "發球" for l in rally_logs)
    used_receive = any(l.get("action") == "接發" for l in rally_logs)
    last_divider = next((l for l in ss.logs if l["type"] == "divider" and l.get("setNo", 1) == ss.current_set), None)
    last_winner = last_divider["winner"] if last_divider else None

    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("前置動作", prev_label)
    sc2.metric("發球狀態", "✅ 已發球" if used_serve else "— 未發球")
    sc3.metric("接發狀態", "✅ 已接發" if used_receive else "— 未接發")

    # ── 得分結束按鈕 ──────────────────────────────────────────────────────────
    st.markdown("**📌 本分結果**")
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1:
        if st.button("✓ 我方得分", use_container_width=True, key="win"):
            resolve_point("win")
            st.rerun()
    with rc2:
        if st.button("＋ 對方失誤", use_container_width=True, key="opperr"):
            resolve_point("oppError")
            st.rerun()
    with rc3:
        if st.button("✗ 我方失分", use_container_width=True, key="lose"):
            resolve_point("lose")
            st.rerun()
    with rc4:
        if st.button("🛡 對手好球", use_container_width=True, key="opp"):
            resolve_point("opponent")
            st.rerun()

    st.divider()

    # ── 建議動作 ──────────────────────────────────────────────────────────────
    quick_opts = gl.suggest_quick_options(
        ss.prev_action_state, sel_player,
        used_serve, used_receive, last_winner,
    )

    st.markdown("**⚡ 建議動作**")
    if quick_opts:
        n_cols = min(len(quick_opts), 5)
        opt_cols = st.columns(n_cols)
        for i, opt in enumerate(quick_opts):
            with opt_cols[i % n_cols]:
                is_active = (ss.selected_action == opt["a"] and ss.selected_context == opt["c"])
                label = f"**{opt['label']}**\n{opt['why']}"
                if st.button(
                    opt["label"],
                    key=f"opt_{i}_{opt['a']}_{opt['c']}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                    help=opt["why"],
                ):
                    ss.selected_action = opt["a"]
                    ss.selected_context = opt["c"]
                    st.rerun()
    else:
        st.caption("（無自動建議，請用下方全動作面板）")

    # ── 展開完整動作 ──────────────────────────────────────────────────────────
    with st.expander("📋 完整動作面板（進階）"):
        act_cols = st.columns(len(gl.ACTION_MAP))
        for i, (act, ainfo) in enumerate(gl.ACTION_MAP.items()):
            with act_cols[i]:
                if st.button(act, key=f"fullact_{act}", use_container_width=True):
                    ss.selected_action = act
                    ss.selected_context = gl.default_context(act)
                    st.rerun()

        if ss.selected_action:
            ctx_list = gl.ACTION_MAP.get(ss.selected_action, {}).get("contexts") or ["一般"]
            if len(ctx_list) > 1:
                st.markdown(f"**{ss.selected_action} 細項：**")
                ctx_cols = st.columns(len(ctx_list))
                for i, c in enumerate(ctx_list):
                    with ctx_cols[i]:
                        is_active = ss.selected_context == c
                        if st.button(c, key=f"ctx_{c}", use_container_width=True,
                                     type="primary" if is_active else "secondary"):
                            ss.selected_context = c
                            st.rerun()

    # ── 品質按鈕 ──────────────────────────────────────────────────────────────
    if ss.selected_action:
        ctx_display = ss.selected_context or gl.default_context(ss.selected_action)
        st.markdown(f"**🎯 {ss.selected_action} — {ctx_display}　選擇品質：**")
        q_cols = st.columns(5)
        q_colors = gl.QUALITY_COLORS
        for i, q in enumerate(gl.Q_KEYS):
            with q_cols[i]:
                label_html = f"{q}\n{gl.QUALITY_LABELS[q]}"
                if st.button(
                    label_html,
                    key=f"quality_{q}",
                    use_container_width=True,
                ):
                    add_log(q)
                    st.rerun()

    # ── 復原 / 斷開前置 ───────────────────────────────────────────────────────
    undo_col, reset_col = st.columns(2)
    with undo_col:
        if st.button("⮌ 復原上一步", disabled=not ss.history_stack, use_container_width=True):
            do_undo()
            st.rerun()
    with reset_col:
        if st.button("↻ 斷開前置狀態", use_container_width=True):
            ss.prev_action_state = {k: None for k in ss.prev_action_state}
            ss.selected_action = None
            ss.selected_context = None
            st.rerun()

    # ── 本局紀錄 ──────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**📜 本局紀錄**")
    cur_logs = [l for l in ss.logs if l.get("setNo", 1) == ss.current_set]

    if not cur_logs:
        st.caption("本局尚無紀錄")
    else:
        def score_badge(v):
            color = gl.score_color_hex(v)
            return f"<span style='color:{color};font-weight:bold;'>{v:+}</span>"

        for l in cur_logs:
            if l["type"] == "divider":
                winner_color = "#3ecf6a" if l["winner"] == "us" else "#e84343"
                st.markdown(
                    f"<div style='text-align:center;padding:6px 0;border-top:1px dashed #252b3b;'>"
                    f"<span style='background:{winner_color};color:#000;padding:3px 12px;border-radius:10px;font-size:12px;font-weight:bold;'>"
                    f"第{l.get('setNo',1)}局 ｜ {l['result']}"
                    f"</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                p_name = next((p["name"] for p in ss.players if p["id"] == l["playerId"]), "未知")
                ctx = l.get("context", "一般")
                display = ctx if ctx != "一般" else l["action"]
                note = f" <small style='color:#7a849e;'>{l['note']}</small>" if l.get("note") else ""
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1b1f2e;font-size:13px;'>"
                    f"<span><b>{p_name}</b>：{display} ({l['quality']}) {note}</span>"
                    f"{score_badge(round(l['scoreDelta']))}"
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# ── 分析 & PDF 匯出 ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def page_analysis():
    import pandas as pd

    ss = st.session_state

    if not ss.selected_match_ids:
        st.warning("請先在「我的比賽」頁面勾選至少一場比賽！")
        if st.button("← 返回"):
            go("matches")
        return

    # ── 取比賽名稱 & 合併資料 ────────────────────────────────────────────────
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

    # ── 局數篩選 ─────────────────────────────────────────────────────────────
    st.markdown("**🔍 局數篩選**")
    vs = ss.view_set
    fc1, fc2, fc3, fc4 = st.columns(4)
    if fc1.button("完整比賽", type="primary" if vs is None else "secondary", use_container_width=True):
        ss.view_set = None; st.rerun()
    for col, n in zip([fc2, fc3, fc4], [1, 2, 3]):
        if col.button(f"第 {n} 局", type="primary" if vs == n else "secondary", use_container_width=True):
            ss.view_set = n; st.rerun()

    st.divider()

    # ── 合併資料 & 依局數篩選 ────────────────────────────────────────────────
    players, logs_all = merge_matches_for_analysis(ss.selected_match_ids)
    logs = logs_all if ss.view_set is None else [l for l in logs_all if l.get("setNo", 1) == ss.view_set]
    action_logs = [l for l in logs if l.get("type") == "action"]
    player_stats = gl.compute_player_stats(players, action_logs)

    if not action_logs:
        st.info("選中的比賽（該局）尚無動作紀錄。")
        return

    # ══════════════════════════════════════════════════════════════════════════
    # 頁籤
    # ══════════════════════════════════════════════════════════════════════════
    tab_score, tab_detail, tab_visual = st.tabs(["🏅 評分", "📋 詳情", "📈 視覺分析"])

    # ────────────────────────────────────────────────────────────────────────
    # 評分 tab — OVR + 雷達圖
    # ────────────────────────────────────────────────────────────────────────
    with tab_score:
        n_cols = min(len(player_stats), 3)
        cols = st.columns(n_cols)
        for i, ps in enumerate(player_stats):
            with cols[i % n_cols]:
                with st.container(border=True):
                    ovr_color = gl.score_color_hex(ps["ovr"])
                    st.markdown(
                        f"<div style='text-align:center;'>"
                        f"<div style='font-size:46px;font-weight:900;color:{ovr_color};line-height:1;'>{ps['ovr']}</div>"
                        f"<div style='font-size:16px;font-weight:bold;margin-top:4px;'>{ps['name']}</div>"
                        f"<div style='color:#7a849e;font-size:12px;'>{ps['pos']}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    fig = _fig_radar(ps["stats"], color=ovr_color)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.caption("需要 3 項以上數據才能顯示雷達圖")
                    # 屬性數值列表
                    for attr, val in ps["stats"].items():
                        c_name, c_val = st.columns([3, 1])
                        c_name.caption(gl.ATTR_TO_CHINESE.get(attr, attr))
                        c_val.markdown(f"<b style='color:{gl.score_color_hex(val)};'>{val}</b>",
                                       unsafe_allow_html=True)

    # ────────────────────────────────────────────────────────────────────────
    # 詳情 tab — 屬性總表 + 動作明細
    # ────────────────────────────────────────────────────────────────────────
    with tab_detail:
        attr_keys = ["ATK", "REC", "DEF", "BLK", "SET", "SRV"]
        tbl = {"球員": [], "位置": [], "OVR": []}
        for a in attr_keys:
            tbl[gl.ATTR_TO_CHINESE[a]] = []
        for ps in player_stats:
            tbl["球員"].append(ps["name"]); tbl["位置"].append(ps["pos"]); tbl["OVR"].append(ps["ovr"])
            for a in attr_keys:
                tbl[gl.ATTR_TO_CHINESE[a]].append(ps["stats"].get(a, "—"))
        st.dataframe(pd.DataFrame(tbl), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📋 動作明細")
        for ps in player_stats:
            p_logs = [l for l in action_logs if l.get("playerId") == ps["id"]]
            if not p_logs:
                continue
            with st.expander(f"{ps['pos']} · {ps['name']}　（{len(p_logs)} 筆）"):
                groups: dict[str, list] = {}
                for l in p_logs:
                    key = l["action"] + "|" + l.get("context", "一般")
                    groups.setdefault(key, []).append(l)
                rows = []
                for key, arr in groups.items():
                    action, ctx = key.split("|", 1)
                    counts = {q: sum(1 for l in arr if l.get("quality") == q) for q in gl.Q_KEYS}
                    rows.append({
                        "動作": action, "細項": ctx,
                        **{f"{q}({gl.QUALITY_LABELS[q]})": counts.get(q, 0) for q in gl.Q_KEYS},
                        "均分": gl.safe_avg([l["scoreDelta"] for l in arr]),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ────────────────────────────────────────────────────────────────────────
    # 視覺分析 tab
    # ────────────────────────────────────────────────────────────────────────
    with tab_visual:
        attackers = [p for p in players if gl.is_attacker(p)]
        setters   = [p for p in players if p.get("pos") == "舉球"]

        # ── 攻擊手：策略圓餅圖 ────────────────────────────────────────────
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
                        st.markdown(f"**{p['name']}** <span style='color:#7a849e;font-size:12px;'>({p['pos']}) {len(arr)} 次</span>",
                                    unsafe_allow_html=True)
                        if arr:
                            st.plotly_chart(_fig_donut(groups, len(arr)),
                                            use_container_width=True, config={"displayModeBar": False})
                            for ctx, col in [("一般攻擊", "#4a9eff"), ("吊球", "#f5a623"), ("處理球", "#3ecf6a")]:
                                ctx_arr = groups.get(ctx, [])
                                pct = round(len(ctx_arr) / len(arr) * 100) if arr else 0
                                sc  = gl.safe_avg([l["scoreDelta"] for l in ctx_arr])
                                st.markdown(
                                    f"<div style='display:flex;justify-content:space-between;font-size:12px;'>"
                                    f"<span><span style='background:{col};border-radius:50%;display:inline-block;"
                                    f"width:8px;height:8px;margin-right:5px;'></span>{ctx}</span>"
                                    f"<span>{pct}% · <b style='color:{gl.score_color_hex(sc)};'>{sc if ctx_arr else '—'}</b></span>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                        else:
                            st.caption("無攻擊數據")
        else:
            st.caption("尚無攻擊手數據")

        st.markdown("---")

        # ── 舉球員：配球分佈 + 熱力圖 ─────────────────────────────────────
        st.subheader("🧠 舉球員：配球效益 & 品質熱力圖")
        T_COLORS = ["#4a9eff", "#f5a623", "#3ecf6a", "#e84343", "#9b59b6", "#e07a5f"]
        if setters:
            for s_p in setters:
                sets_arr = [l for l in action_logs if l.get("playerId") == s_p["id"] and l.get("action") == "舉球"]
                atk_after = [l for l in action_logs if l.get("action") == "攻擊" and l.get("prevPlayerId") == s_p["id"]]
                by_target: dict = {}
                for l in atk_after:
                    by_target.setdefault(l.get("playerId"), []).append(l)
                total_sets = len(atk_after)
                avg_set = gl.safe_avg([l["scoreDelta"] for l in sets_arr])

                with st.container(border=True):
                    h1, h2 = st.columns([3, 1])
                    h1.markdown(f"**{s_p['name']}**")
                    h2.markdown(f"<div style='text-align:right;color:#7a849e;font-size:12px;'>舉球均分 "
                                f"<b style='color:{gl.score_color_hex(avg_set)};'>{avg_set if sets_arr else '—'}</b>"
                                f" / {len(sets_arr)} 次</div>", unsafe_allow_html=True)

                    # 配球比例色條
                    if total_sets > 0:
                        atk_list = [p for p in players if gl.is_attacker(p)]
                        strip = "<div style='display:flex;height:22px;border-radius:8px;overflow:hidden;margin:8px 0;'>"
                        for ti, t in enumerate(atk_list):
                            a = by_target.get(t["id"], [])
                            pct = len(a) / total_sets * 100
                            if pct > 0:
                                col = T_COLORS[ti % len(T_COLORS)]
                                strip += (f"<div style='width:{pct:.1f}%;background:{col};display:flex;"
                                          f"align-items:center;justify-content:center;font-size:10px;"
                                          f"font-weight:900;color:#000;overflow:hidden;'>"
                                          f"{'&nbsp;'+t['name'] if pct >= 10 else ''}</div>")
                        strip += "</div>"
                        st.markdown(strip, unsafe_allow_html=True)

                        # 各攻擊手詳細列
                        for ti, t in enumerate(atk_list):
                            a = by_target.get(t["id"], [])
                            pct = round(len(a) / total_sets * 100) if total_sets else 0
                            sc  = gl.safe_avg([l["scoreDelta"] for l in a])
                            col = T_COLORS[ti % len(T_COLORS)]
                            rc1, rc2, rc3 = st.columns([3, 1, 1])
                            rc1.markdown(f"<span style='color:{col};font-size:14px;'>●</span> **{t['name']}** "
                                         f"<span style='color:#7a849e;font-size:11px;'>{t['pos']}</span>",
                                         unsafe_allow_html=True)
                            rc2.markdown(f"<div style='text-align:center;font-size:12px;'>{len(a)}球 / {pct}%</div>",
                                         unsafe_allow_html=True)
                            rc3.markdown(f"<div style='text-align:center;font-weight:900;"
                                         f"color:{gl.score_color_hex(sc)};'>{sc if a else '—'}</div>",
                                         unsafe_allow_html=True)

                    # 熱力圖
                    st.markdown("**舉球品質熱力圖**　<span style='color:#7a849e;font-size:11px;'>行＝舉球品質 / 列＝一傳品質</span>",
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

        # ── 團隊防守：雷達 + 數值列 ────────────────────────────────────────
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
            def_data.append({"ctx": ctx, "arr": arr, "score": gl.safe_avg([l["scoreDelta"] for l in arr]) if arr else 0})

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
                dn1.markdown(f"**{d['ctx']}** <span style='color:#7a849e;font-size:11px;'>({len(d['arr'])} 次)</span>",
                             unsafe_allow_html=True)
                dn2.markdown(f"<b style='color:{gl.score_color_hex(sc)};'>{sc if d['arr'] else '—'}</b>",
                             unsafe_allow_html=True)
                if d["arr"]:
                    st.progress(sc / 100)


# ══════════════════════════════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════════════════════════════

def main():
    page = st.session_state.page

    # 未登入時強制回首頁
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
