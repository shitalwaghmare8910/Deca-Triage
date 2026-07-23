#!/usr/bin/env python3
"""Render the solution architecture diagram as a PNG using Pillow only.

Produces docs/architecture_diagram.png. Re-run to regenerate:
    venv/bin/python docs/generate_architecture_png.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "architecture_diagram.png")

S = 2  # supersampling factor for crisp anti-aliased output
W, H = 1760 * S, 1220 * S

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size * S)

f_title = font("DejaVuSans-Bold.ttf", 30)
f_sub   = font("DejaVuSans.ttf", 14)
f_box   = font("DejaVuSans-Bold.ttf", 17)
f_boxsm = font("DejaVuSans.ttf", 13)
f_lbl   = font("DejaVuSans.ttf", 12)
f_band  = font("DejaVuSans-Bold.ttf", 14)

NAVY = (26, 34, 51)
GREY = (90, 100, 115)
WHITE = (255, 255, 255)

img = Image.new("RGB", (W, H), (247, 249, 252))
d = ImageDraw.Draw(img)

def sc(v):
    return v * S

def center_text(cx, cy, text, fnt, fill=NAVY):
    l, t, r, b = d.textbbox((0, 0), text, font=fnt)
    d.text((cx - (r - l) / 2, cy - (b - t) / 2 - t), text, font=fnt, fill=fill)

def band(x, y, w, h, color, label):
    d.rounded_rectangle([sc(x), sc(y), sc(x + w), sc(y + h)], radius=sc(10), fill=color)
    d.text((sc(x + 12), sc(y + 8)), label, font=f_band, fill=(120, 130, 145))

def box(x, y, w, h, title, sub, fill, border):
    d.rounded_rectangle([sc(x), sc(y), sc(x + w), sc(y + h)],
                        radius=sc(9), fill=fill, outline=border, width=max(1, S))
    cx = sc(x + w / 2)
    if sub:
        center_text(cx, sc(y + h / 2 - 11), title, f_box)
        center_text(cx, sc(y + h / 2 + 12), sub, f_boxsm, fill=GREY)
    else:
        center_text(cx, sc(y + h / 2), title, f_box)
    return (x, y, w, h)

def anchor(b, side):
    x, y, w, h = b
    return {
        "t": (x + w / 2, y), "b": (x + w / 2, y + h),
        "l": (x, y + h / 2), "r": (x + w, y + h / 2),
    }[side]

def arrow(p0, p1, label=None, color=(90, 100, 115), dash=False):
    x0, y0 = sc(p0[0]), sc(p0[1])
    x1, y1 = sc(p1[0]), sc(p1[1])
    if dash:
        # simple dashed line
        import math
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        n = max(1, int(dist / (10 * S)))
        for i in range(n):
            if i % 2 == 0:
                a = (x0 + dx * i / n, y0 + dy * i / n)
                b2 = (x0 + dx * (i + 1) / n, y0 + dy * (i + 1) / n)
                d.line([a, b2], fill=color, width=max(1, S))
    else:
        d.line([(x0, y0), (x1, y1)], fill=color, width=max(1, S))
    # arrowhead
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    L = 11 * S
    d.polygon([
        (x1, y1),
        (x1 - L * math.cos(ang - 0.4), y1 - L * math.sin(ang - 0.4)),
        (x1 - L * math.cos(ang + 0.4), y1 - L * math.sin(ang + 0.4)),
    ], fill=color)
    if label:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        l, t, r, b = d.textbbox((0, 0), label, font=f_lbl)
        pad = 3 * S
        d.rectangle([mx - (r - l) / 2 - pad, my - (b - t) / 2 - pad,
                     mx + (r - l) / 2 + pad, my + (b - t) / 2 + pad], fill=(247, 249, 252))
        d.text((mx - (r - l) / 2, my - (b - t) / 2 - t), label, font=f_lbl, fill=GREY)

# ---- Title -------------------------------------------------------------
    d.text((sc(40), sc(24)), "DECA — Decade of Autonomous Triage", font=f_title, fill=NAVY)
d.text((sc(42), sc(64)), "Solution Architecture & Data Flow", font=f_sub, fill=GREY)

# ---- Colours -----------------------------------------------------------
C_ING = (220, 233, 250); B_ING = (47, 111, 181)
C_APP = (221, 243, 228); B_APP = (30, 135, 75)
C_ORC = (231, 222, 248); B_ORC = (107, 63, 160)
C_AGT = (237, 239, 242); B_AGT = (74, 85, 104)
C_DAT = (252, 239, 213); B_DAT = (184, 134, 11)
C_UI  = (214, 242, 240); B_UI  = (13, 148, 136)

# ---- Bands (background) ------------------------------------------------
band(30, 100, 1700, 128, (238, 243, 250), "INGESTION")
band(30, 250, 1700, 132, (236, 247, 240), "APPLICATION  /  DASHBOARD")
band(30, 404, 1700, 118, (243, 238, 251), "ORCHESTRATION")
band(30, 544, 1700, 132, (240, 242, 245), "SPECIALIST AGENTS")
band(30, 698, 1700, 120, (252, 246, 232), "DATA STORES")

# ---- Boxes -------------------------------------------------------------
sn  = box(120, 128, 250, 82, "Mock ServiceNow", ":5001  Table API", C_ING, B_ING)
out = box(755, 128, 250, 82, "Mock Outlook", ":5002  MS Graph", C_ING, B_ING)
el  = box(1390, 128, 250, 82, "Email Listener", "mailbox poller", C_ING, B_ING)

be  = box(430, 278, 300, 92, "Backend + Frontend", ":5000  Flask · SQLite · SSE", C_APP, B_APP)
ui  = box(1150, 278, 300, 92, "Analyst Dashboard", "live SSE + PDF report", C_UI, B_UI)

orc = box(620, 428, 320, 78, "Root Orchestrator", ":8080  FastAPI · Gemini", C_ORC, B_ORC)

kn  = box(60,   568, 250, 86, "Knowledge Ingestion", ":8001  RAG · pgvector", C_AGT, B_AGT)
pg  = box(330,  568, 240, 86, "Postgres Agent", ":8003  SQL proxy", C_AGT, B_AGT)
cr  = box(590,  568, 230, 86, "Critic Agent", ":8004  reviewer", C_AGT, B_AGT)
co  = box(840,  568, 230, 86, "Concept Agent", ":8005  patterns", C_AGT, B_AGT)
jr  = box(1090, 568, 230, 86, "Jira Agent", ":8006  ticketing", C_AGT, B_AGT)
no  = box(1340, 568, 300, 86, "Notification Agent", ":8008  HTML/PDF report", C_AGT, B_AGT)

csql = box(430,  722, 320, 74, "Cloud SQL (PostgreSQL)", "xs2a audit_log · runbooks", C_DAT, B_DAT)

# ---- Arrows ------------------------------------------------------------
arrow(anchor(sn, "b"), anchor(be, "t"), "poll state=1")
arrow(anchor(out, "r"), (el[0], el[1] + el[3] / 2), "unread")
arrow(anchor(el, "b"), anchor(be, "t"), "/api/ingest-alert")
arrow(anchor(be, "b"), anchor(orc, "t"), "/process-alert")
arrow((be[0] + be[2], be[1] + 30), (ui[0], ui[1] + 30), "SSE")
arrow((be[0] + be[2], be[1] + 62), (out[0] + out[2] / 2, out[1] + out[3]), "deliver report")

# orchestrator -> agents
for tgt, lbl in [(kn, "/search"), (pg, "/execute-query"), (cr, "/evaluate"),
                 (co, "/identify"), (jr, "/create-ticket"), (no, "/send")]:
    arrow(anchor(orc, "b"), anchor(tgt, "t"), lbl)

# agents -> data
arrow(anchor(kn, "b"), anchor(csql, "t"))
arrow(anchor(pg, "b"), anchor(csql, "t"))
# notification -> outlook (PDF report back)
arrow(anchor(no, "t"), anchor(out, "b"), "PDF report")

# ---- Footer ------------------------------------------------------------
d.text((sc(40), sc(1170)),
       "Ingestion  →  Backend (SQLite)  →  Orchestrator (Gemini)  →  Specialist agents  →  Cloud SQL evidence  →  PDF report to inbox & dashboard",
       font=f_sub, fill=GREY)

# ---- Save (downscale for anti-aliasing) --------------------------------
img = img.resize((W // S, H // S), Image.LANCZOS)
img.save(OUT, "PNG")
print("wrote", OUT, img.size)
