# pdf_generator.py — 生成比賽分析 PDF 報表
import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, KeepTogether, PageBreak,
)
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics import renderPDF
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from game_logic import (
    compute_player_stats, ATTR_TO_CHINESE, Q_KEYS,
    ACTION_MAP, safe_avg, score_color_hex, is_attacker,
    POS_WEIGHTS, QUALITY_LABELS,
)

# ── 字型（內建 CJK，不需嵌入） ────────────────────────────────────────────────
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"

# ── 色盤 ──────────────────────────────────────────────────────────────────────
C_BG      = HexColor("#0c0e13")
C_SURFACE = HexColor("#141720")
C_CARD    = HexColor("#1b1f2e")
C_BORDER  = HexColor("#252b3b")
C_ACCENT  = HexColor("#f5a623")
C_SUCCESS = HexColor("#3ecf6a")
C_DANGER  = HexColor("#e84343")
C_INFO    = HexColor("#4a9eff")
C_WARN    = HexColor("#e07a5f")
C_TEXT    = HexColor("#e8eaf2")
C_MUTED   = HexColor("#7a849e")


def _hex(h: str) -> HexColor:
    return HexColor(h)


def _score_color(v: float) -> HexColor:
    return _hex(score_color_hex(v))


# ── 工具：進度條 Drawing ───────────────────────────────────────────────────────

def _bar(value: float, width: float = 240, height: float = 10) -> Drawing:
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=_hex("#0f121a"), strokeColor=None))
    bar_w = max(0, min(width, width * value / 100))
    if bar_w > 0:
        d.add(Rect(0, 0, bar_w, height, fillColor=_score_color(value), strokeColor=None))
    return d


# ── 樣式工廠 ──────────────────────────────────────────────────────────────────

def _styles() -> dict:
    return {
        "title": ParagraphStyle(
            "title", fontName=FONT, fontSize=26,
            textColor=C_ACCENT, alignment=TA_CENTER, spaceAfter=3,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=FONT, fontSize=11,
            textColor=C_MUTED, alignment=TA_CENTER, spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2", fontName=FONT, fontSize=15,
            textColor=C_TEXT, spaceBefore=14, spaceAfter=7,
        ),
        "h3": ParagraphStyle(
            "h3", fontName=FONT, fontSize=12,
            textColor=C_ACCENT, spaceBefore=8, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "body", fontName=FONT, fontSize=10, textColor=C_TEXT, spaceAfter=4,
        ),
        "muted": ParagraphStyle(
            "muted", fontName=FONT, fontSize=9, textColor=C_MUTED, spaceAfter=2,
        ),
        "center": ParagraphStyle(
            "center", fontName=FONT, fontSize=10,
            textColor=C_TEXT, alignment=TA_CENTER,
        ),
        "ovr": ParagraphStyle(
            "ovr", fontName=FONT, fontSize=32,
            textColor=C_ACCENT, alignment=TA_CENTER,
        ),
        "footer": ParagraphStyle(
            "footer", fontName=FONT, fontSize=8,
            textColor=C_MUTED, alignment=TA_CENTER,
        ),
    }


# ── 表格基礎樣式 ──────────────────────────────────────────────────────────────

def _base_table_style(header_rows: int = 1) -> list:
    return [
        ("FONTNAME",      (0, 0), (-1, -1), FONT),
        ("FONTSIZE",      (0, 0), (-1,  0), 9),
        ("FONTSIZE",      (0, 1), (-1, -1), 10),
        ("BACKGROUND",    (0, 0), (-1,  0), C_SURFACE),
        ("TEXTCOLOR",     (0, 0), (-1,  0), C_MUTED),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_CARD, C_SURFACE]),
        ("GRID",          (0, 0), (-1, -1), 0.3, C_BORDER),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]


# ── 主函式 ────────────────────────────────────────────────────────────────────

def generate_pdf(
    match_titles: list[str],
    all_players: list[dict],
    all_logs: list[dict],
) -> bytes:
    """
    生成 PDF 並回傳 bytes。

    參數
    ----
    match_titles : 納入分析的比賽名稱列表（用於報表標題）
    all_players  : 合併後的球員列表（去重）
    all_logs     : 合併後的動作紀錄列表
    """
    buffer = io.BytesIO()
    s = _styles()
    W, H = A4  # 595.27 x 841.89 pt

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="VolleyTracker 報表",
    )

    story = []

    # ── 封面標題 ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("VOLLEY TRACKER REPORT", s["title"]))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    match_label = "、".join(match_titles) if match_titles else "（未命名）"
    story.append(Paragraph(f"比賽：{match_label}", s["subtitle"]))
    story.append(Paragraph(f"產生時間：{now_str}", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=C_ACCENT, spaceAfter=10))

    # ── 計算統計 ──────────────────────────────────────────────────────────────
    action_logs = [l for l in all_logs if l.get("type") == "action"]
    player_stats = compute_player_stats(all_players, action_logs)

    # ── 1. 球員 OVR 總覽 ──────────────────────────────────────────────────────
    story.append(Paragraph("📊 球員評分總覽", s["h2"]))

    attr_keys = ["ATK", "REC", "DEF", "BLK", "SET", "SRV"]
    header = ["球員", "位置", "OVR"] + [ATTR_TO_CHINESE[a] for a in attr_keys]
    col_w = [32*mm, 14*mm, 18*mm] + [14*mm]*len(attr_keys)

    rows = [header]
    for ps in player_stats:
        row = [ps["name"], ps["pos"], str(ps["ovr"])]
        for a in attr_keys:
            row.append(str(ps["stats"].get(a, "—")))
        rows.append(row)

    t = Table(rows, colWidths=col_w)
    style = _base_table_style()
    style += [
        ("ALIGN",     (0, 0), (1, -1), "LEFT"),
        ("FONTSIZE",  (2, 1), (2, -1), 18),
        ("TEXTCOLOR", (2, 1), (2, -1), C_ACCENT),
    ]
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 8 * mm))

    # ── 2. 各球員詳細屬性 ─────────────────────────────────────────────────────
    story.append(Paragraph("📈 球員詳細屬性", s["h2"]))

    for ps in player_stats:
        block = []
        block.append(Paragraph(f"{ps['pos']} · {ps['name']}　OVR {ps['ovr']}", s["h3"]))

        if not ps["stats"]:
            block.append(Paragraph("（本場次無紀錄）", s["muted"]))
        else:
            for attr, val in ps["stats"].items():
                attr_cn = ATTR_TO_CHINESE.get(attr, attr)
                bar_row = [
                    [
                        Paragraph(attr_cn, s["muted"]),
                        _bar(val, width=220, height=9),
                        Paragraph(
                            f'<font color="{score_color_hex(val)}"><b>{val}</b></font>',
                            s["body"]
                        ),
                    ]
                ]
                bt = Table(bar_row, colWidths=[18*mm, 58*mm, 14*mm])
                bt.setStyle(TableStyle([
                    ("FONTNAME",     (0, 0), (-1, -1), FONT),
                    ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING",   (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
                ]))
                block.append(bt)

        story.append(KeepTogether(block))
        story.append(Spacer(1, 4 * mm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 4 * mm))

    # ── 3. 動作明細（各球員） ─────────────────────────────────────────────────
    story.append(Paragraph("📋 動作明細", s["h2"]))

    for p in all_players:
        p_logs = [l for l in action_logs if l.get("playerId") == p["id"]]
        if not p_logs:
            continue

        story.append(Paragraph(f"{p['pos']} · {p['name']}", s["h3"]))

        groups: dict[str, list] = {}
        for l in p_logs:
            key = l["action"] + "|" + l.get("context", "一般")
            groups.setdefault(key, []).append(l)

        detail_header = ["動作", "細項"] + [f"{q}\n{QUALITY_LABELS[q]}" for q in Q_KEYS] + ["均分"]
        detail_rows = [detail_header]
        for key, arr in groups.items():
            action, ctx = key.split("|", 1)
            counts = {q: sum(1 for l in arr if l.get("quality") == q) for q in Q_KEYS}
            avg_sc = safe_avg([l["scoreDelta"] for l in arr])
            detail_rows.append(
                [action, ctx] + [str(counts.get(q, 0)) for q in Q_KEYS] + [str(avg_sc)]
            )

        cw = [18*mm, 30*mm] + [11*mm]*5 + [15*mm]
        dt = Table(detail_rows, colWidths=cw)
        dstyle = _base_table_style()
        dstyle += [
            ("ALIGN", (0, 0), (1, -1), "LEFT"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
        ]
        dt.setStyle(TableStyle(dstyle))
        story.append(dt)
        story.append(Spacer(1, 5 * mm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 4 * mm))

    # ── 4. 團隊防守分析 ───────────────────────────────────────────────────────
    story.append(Paragraph("🛡 團隊防守分析", s["h2"]))

    def_contexts = ["接發", "接扣", "一般防守", "吊球/Cover", "接嗆司"]
    def_header = ["防守項目", "次數", "均分", "評級"]
    def_rows = [def_header]
    for ctx in def_contexts:
        if ctx == "接發":
            arr = [l for l in action_logs if l.get("action") == "接發"]
        elif ctx == "接扣":
            arr = [l for l in action_logs if l.get("action") == "接扣"]
        else:
            arr = [l for l in action_logs if l.get("action") == "防守" and l.get("context") == ctx]
        sc = safe_avg([l["scoreDelta"] for l in arr]) if arr else 0
        level = "優秀" if sc >= 75 else "良好" if sc >= 50 else "待改善" if arr else "—"
        def_rows.append([ctx, str(len(arr)), str(sc) if arr else "—", level])

    defw = [40*mm, 20*mm, 20*mm, 25*mm]
    deft = Table(def_rows, colWidths=defw)
    deft.setStyle(TableStyle(_base_table_style()))
    story.append(deft)
    story.append(Spacer(1, 4 * mm))

    # ── 5. 攻擊手攻擊分析 ─────────────────────────────────────────────────────
    attackers = [p for p in all_players if is_attacker(p)]
    if attackers:
        story.append(Paragraph("🔥 攻擊分析", s["h2"]))
        atk_contexts = ["一般攻擊", "吊球", "處理球"]
        atk_header = ["球員", "攻擊方式", "次數", "佔比 %", "均分"]
        atk_rows = [atk_header]
        for p in attackers:
            p_atk = [l for l in action_logs if l.get("playerId") == p["id"] and l.get("action") == "攻擊"]
            total = len(p_atk)
            for ctx in atk_contexts:
                arr = [l for l in p_atk if l.get("context") == ctx]
                pct = round(len(arr) / total * 100) if total else 0
                sc = safe_avg([l["scoreDelta"] for l in arr]) if arr else "—"
                atk_rows.append([p["name"], ctx, str(len(arr)), f"{pct}%", str(sc)])
        atkw = [28*mm, 28*mm, 16*mm, 18*mm, 18*mm]
        atkt = Table(atk_rows, colWidths=atkw)
        atkt.setStyle(TableStyle(_base_table_style()))
        story.append(atkt)
        story.append(Spacer(1, 4 * mm))

    # ── 6. 舉球員配球分析 ─────────────────────────────────────────────────────
    setters = [p for p in all_players if p.get("pos") == "舉球"]
    if setters and attackers:
        story.append(Paragraph("🧠 舉球配球分析", s["h2"]))
        for s_p in setters:
            s_logs = [l for l in action_logs if l.get("playerId") == s_p["id"] and l.get("action") == "舉球"]
            story.append(Paragraph(f"{s_p['name']}　舉球均分 {safe_avg([l['scoreDelta'] for l in s_logs]) if s_logs else '—'}", s["h3"]))

            set_header = ["配球對象", "次數", "攻擊均分"]
            set_rows = [set_header]
            for atk in attackers:
                atk_after = [
                    l for l in action_logs
                    if l.get("playerId") == atk["id"]
                    and l.get("action") == "攻擊"
                    and l.get("prevPlayerId") == s_p["id"]
                ]
                sc = safe_avg([l["scoreDelta"] for l in atk_after]) if atk_after else "—"
                set_rows.append([atk["name"], str(len(atk_after)), str(sc)])
            setw = [40*mm, 20*mm, 28*mm]
            sett = Table(set_rows, colWidths=setw)
            sett.setStyle(TableStyle(_base_table_style()))
            story.append(sett)
            story.append(Spacer(1, 4 * mm))

    # ── 頁尾 ──────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_MUTED))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"VolleyTracker Pro · 產生於 {now_str}",
        s["footer"]
    ))

    doc.build(story)
    return buffer.getvalue()
