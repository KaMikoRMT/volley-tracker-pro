# game_logic.py — 排球記錄系統核心邏輯

POSITIONS = ["大砲", "副攻", "背", "攔中", "舉球", "自由"]

POS_WEIGHTS = {
    "大砲": {"ATK": .35, "REC": .30, "DEF": .20, "BLK": .05, "SET": 0.0, "FIX": 0.0, "SRV": .10},
    "副攻": {"ATK": .45, "REC": 0.0, "DEF": .20, "BLK": .15, "SET": 0.0, "FIX": .05, "SRV": .15},
    "背":   {"ATK": .45, "REC": 0.0, "DEF": .20, "BLK": .15, "SET": 0.0, "FIX": .05, "SRV": .15},
    "攔中": {"ATK": .35, "REC": 0.0, "DEF": .10, "BLK": .40, "SET": 0.0, "FIX": .05, "SRV": .10},
    "舉球": {"ATK": .05, "REC": 0.0, "DEF": .15, "BLK": .10, "SET": .60, "FIX": 0.0, "SRV": .10},
    "自由": {"ATK": 0.0, "REC": .50, "DEF": .45, "BLK": 0.0, "SET": 0.0, "FIX": .05, "SRV": 0.0},
}

ACTION_MAP = {
    "發球": {"contexts": None, "attr": "SRV"},
    "接發": {"contexts": None, "attr": "REC"},
    "接扣": {"contexts": None, "attr": "DEF"},
    "防守": {"contexts": ["一般防守", "吊球/Cover", "接嗆司"], "attr": "DEF"},
    "舉球": {"contexts": ["舉球", "二次處理/吊球"], "attr": "SET"},
    "攻擊": {"contexts": ["一般攻擊", "吊球", "處理球"], "attr": "ATK"},
    "攔網": {"contexts": None, "attr": "BLK"},
    "修正": {"contexts": None, "attr": "FIX"},
}

ATTR_TO_CHINESE = {
    "ATK": "攻擊", "REC": "接發", "DEF": "防守",
    "BLK": "攔網", "SET": "舉球", "FIX": "修正", "SRV": "發球",
}

QUALITY_SCORES = {"S": 100, "A": 75, "B": 50, "C": 25, "F": 0}
QUALITY_LABELS = {"S": "完美", "A": "有效", "B": "一般", "C": "不佳", "F": "失誤"}
QUALITY_COLORS = {"S": "#3ecf6a", "A": "#4a9eff", "B": "#f5a623", "C": "#e07a5f", "F": "#e84343"}
Q_KEYS = ["S", "A", "B", "C", "F"]


def is_attacker(player: dict) -> bool:
    return player.get("pos") in ["大砲", "副攻", "背", "攔中"]


def safe_avg(arr: list) -> int:
    if not arr:
        return 0
    return round(sum(arr) / len(arr))


def score_color_hex(v: float) -> str:
    if v >= 75:
        return "#3ecf6a"
    if v >= 50:
        return "#f5a623"
    if v > 0:
        return "#e07a5f"
    return "#e84343"


def default_context(action: str) -> str:
    ctx = ACTION_MAP.get(action, {}).get("contexts")
    return ctx[0] if ctx else "一般"


def compute_score_delta(quality: str, prev_state: dict, action: str) -> tuple[int, str]:
    """
    計算得分增量，並套用舉球→攻擊組合加成/扣分。
    回傳 (score_delta, note_str)
    """
    base = QUALITY_SCORES[quality]
    note = ""
    prev_action = prev_state.get("action")
    prev_quality = prev_state.get("quality")

    if prev_action == "舉球" and action == "攻擊":
        if prev_quality in ["B", "C", "F"]:
            if quality == "F":
                base = 25
                note = "爛球豁免(25分)"
            elif quality in ["S", "A"]:
                base = round(base * 1.2)
                note = "神救援(1.2x)"
        elif prev_quality in ["S", "A"] and quality == "F":
            base -= 20
            note = "浪費好配球(-20)"

    return base, note


def compute_player_stats(players: list, logs: list) -> list:
    """計算每位球員的各項屬性分數與 OVR 總評"""
    result = []
    for p in players:
        p_logs = [
            l for l in logs
            if l.get("type") == "action" and l.get("playerId") == p["id"]
        ]
        base = POS_WEIGHTS.get(p.get("pos", "大砲"), {})
        attr_logs: dict[str, list] = {a: [] for a in ATTR_TO_CHINESE}

        for l in p_logs:
            attr = ACTION_MAP.get(l.get("action", ""), {}).get("attr")
            if attr:
                attr_logs[attr].append(l)

        stats: dict[str, int] = {}
        total_w = 0.0
        for a, alogs in attr_logs.items():
            if base.get(a, 0) > 0 and alogs:
                stats[a] = min(100, max(0, safe_avg([x["scoreDelta"] for x in alogs])))
                total_w += base[a]

        norm_weights: dict[str, float] = {}
        ovr = 0.0
        for a, val in stats.items():
            w = base[a] / total_w if total_w > 0 else 0
            norm_weights[a] = w
            ovr += val * w

        result.append({**p, "stats": stats, "normWeights": norm_weights, "ovr": round(ovr)})
    return result


def suggest_quick_options(prev_state: dict, player: dict | None,
                           used_serve: bool, used_receive: bool,
                           last_point_winner: str | None) -> list[dict]:
    """
    根據前置狀態、球員位置、已用動作，回傳建議的動作選項（已展開細項）。
    每個元素: {'a': action, 'c': context_str, 'label': display_label, 'why': reason}
    """
    opts: list[dict] = []
    prev = prev_state.get("action")
    ppos = player.get("pos") if player else None

    # ── 無前置動作時推薦開球選項 ──
    if not prev:
        if last_point_winner == "us":
            if not used_serve:
                opts.append({"a": "發球", "c": ["一般"], "why": "上一分我方得分，優先發球"})
        elif last_point_winner == "them":
            if not used_receive:
                opts.append({"a": "接發", "c": ["一般"], "why": "上一分對方得分，優先接發"})
        else:
            if not used_serve:
                opts.append({"a": "發球", "c": ["一般"], "why": "開局可選"})
            if not used_receive:
                opts.append({"a": "接發", "c": ["一般"], "why": "開局可選"})

    if prev == "接發" and ppos == "舉球":
        opts.append({"a": "舉球", "c": ["舉球", "二次處理/吊球"], "why": "接發後的主要選項"})
        opts.append({"a": "修正", "c": ["一般"], "why": "接發不到位時"})
    elif prev in ["舉球", "修正"] and is_attacker(player or {}):
        opts.append({"a": "攻擊", "c": ["一般攻擊", "吊球", "處理球"], "why": "進攻回合"})
    elif prev and prev != "接發":
        opts.append({"a": "接扣", "c": ["一般"], "why": "防守回合"})
        opts.append({"a": "防守", "c": ["一般防守", "吊球/Cover", "接嗆司"], "why": "防守回合"})
        if ppos != "自由":
            opts.append({"a": "攔網", "c": ["一般"], "why": "網前防守"})

    if not opts:
        if ppos == "舉球":
            opts.append({"a": "舉球", "c": ["舉球", "二次處理/吊球"], "why": "舉球員常用"})
        if ppos not in ["舉球", "自由"]:
            opts.append({"a": "攻擊", "c": ["一般攻擊", "吊球", "處理球"], "why": "攻擊手常用"})
        if ppos == "自由":
            opts.append({"a": "攻擊", "c": ["吊球", "處理球"], "why": "自由限定處理"})
        opts.append({"a": "防守", "c": ["一般防守", "吊球/Cover", "接嗆司"], "why": "通用"})

    # ── 過濾限制 ──
    opts = [o for o in opts if not (o["a"] == "舉球" and ppos != "舉球")]
    opts = [o for o in opts if not (o["a"] == "攔網" and ppos == "自由")]
    if ppos == "自由":
        new_opts = []
        for o in opts:
            if o["a"] == "攻擊":
                fc = [c for c in o["c"] if c != "一般攻擊"]
                if fc:
                    new_opts.append({**o, "c": fc})
            else:
                new_opts.append(o)
        opts = new_opts
    if used_serve:
        opts = [o for o in opts if o["a"] != "發球"]
    if used_receive:
        opts = [o for o in opts if o["a"] != "接發"]
    if ppos == "舉球" and not any(o["a"] == "舉球" for o in opts):
        opts.append({"a": "舉球", "c": ["舉球", "二次處理/吊球"], "why": "舉球員常用"})

    # ── 去重 ──
    seen: set = set()
    unique = []
    for o in opts:
        key = o["a"] + "|".join(o["c"])
        if key not in seen:
            seen.add(key)
            unique.append(o)

    # ── 展開細項 ──
    flat = []
    for o in unique:
        if len(o["c"]) == 1:
            c = o["c"][0]
            flat.append({"a": o["a"], "c": c, "label": o["a"], "why": o["why"]})
        else:
            for c in o["c"]:
                flat.append({"a": o["a"], "c": c, "label": c, "why": o["why"]})
    return flat
