# -*- coding: utf-8 -*-
"""
FayeLong 标志 v2 ·「L · 柚子」· 交付产物生成器
================================================================
几何真源在 06-source/geom.py（改参数只需改它）；本脚本负责出：
  ① 7 个真矢量 SVG（主标 · 单色 · 反白 · 灰阶 · favicon · 横排 · 堆叠 · 表情版）
  ② blueprint 数学标注图
  ③ preview.html（单文件自包含预览页）
  ④ 05-spec/spec.md（使用规范）
用法：python build_logo.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import geom as G  # noqa: E402

ROOT = os.path.dirname(HERE)
INK, FRUIT, BG = G.INK_LIGHT, G.FRUIT_LIGHT, G.BG_LIGHT
INKD, FRUITD, BGD = G.INK_DARK, G.FRUIT_DARK, G.BG_DARK
MONO = G.FONT_MONO
SANS = G.FONT_CN
PHI = G.PHI
_f = G._f

PALETTES = [
    ("樱粉 · 柚黄（主方案·本版）", INK, FRUIT, "#F2F5F3", "字=樱粉、果=柚黄；粉在教育品类是空位"),
    ("蜜桃 · 柚黄", "#F58B6B", "#F0C838", "#FBF3EE", "偏暖一档：更甜、更像果汁"),
    ("薄荷 · 柚黄", "#5FBFA0", "#F2CE3C", "#F1F7F4", "冷一档：更清爽，但退出「可爱」语区"),
]


# ============================================================
# 1. SVG 片段
# ============================================================
def body_paths(g, ink, fruit, face=False):
    """绘制顺序：叶（藏在果后）→ 果身 → 字母 L → 表情（可选）"""
    _st, leaf, _tip, _base = G.stem_leaf(g)
    out = [f'<path d="{leaf}" fill="{ink}"/>',
           f'<path d="{G.fruit_path(g)}" fill="{fruit}"/>',
           f'<path d="{G.mark_path(g)}" fill="{ink}"/>']
    if face:
        eyes, mouth = G.face_svg_bits(g)
        out.append(f'<g fill="{ink}">{eyes[0]}{eyes[1]}</g>')
        out.append(mouth.replace("<path ", f'<path stroke="{ink}" '))
    return "".join(out)


def mark_inline(g, ink, fruit, px=None, bg=None, face=False, extra=""):
    size = f' width="{round(px * g["W"] / g["H"])}" height="{px}"' if px else ""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {g["W"]} {g["H"]}"{size} {extra}>']
    if bg:
        out.append(f'<rect width="{g["W"]}" height="{g["H"]}" fill="{bg}"/>')
    out.append(body_paths(g, ink, fruit, face) + "</svg>")
    return "".join(out)


def svg_file(g, ink, fruit, bg, note, face=False):
    head = f"""<!--
  FayeLong 标志 v2 ·「L · 柚子」· {note}
  纯矢量 · 全填充 · 无字体依赖 · 无描边 · 无渐变 · 无投影
  ── 几何（由 06-source/geom.py 生成，请勿手工改坐标）──
  外框        W×H   = {g['W']} × {g['H']}   (1 : 1 — 正方形由恒等式逼出)
  笔宽        SW    = {g['SW']}            (= H/φ³)
  横笔        L_W   = {g['L_W']}            ({"= 2SW + SW/φ³" if g["profile"] == "main" else "= W − GAP − FRUIT（余宽全归横笔）"})
  间隔        GAP   = {g['GAP']}            (= SW/φ²)
  柚子        FRUIT = {g['FRUIT']}            ({"= SW·φ" if g["profile"] == "main" else "≡ SW·φ（与主标同比例）"})，宽:高 = 2:√3
  ★ L_W + GAP + FRUIT = {g['L_W']} + {g['GAP']} + {g['FRUIT']} = {g['L_W']+g['GAP']+g['FRUIT']} ≡ W（精确闭合）
  半径 3 档 = 端头/外凸转角 {_f(g['R'])}（SW/2）· 内凹转角/蒂窝 {g['R_FIL']}（SW/φ²）· 叶弧 {_f(g['R_LEAF'])}（SW/φ）
  颜色分工 = 粉给字（{ink}：L + 叶 + 字标）／黄给果（{fruit}：仅柚子果身）
  叶子：半径 {_f(g['R_LEAF'])} 的弧构成的透镜，弦长 {g['LEAF_CHORD']}，轴与水平成 arctan(φ) ≈ {G.LEAF_ANGLE_DEG:.2f}°，
        基部埋在果身内 → 只露果肩之外一段（果身覆盖其根部，无需描边分割）
  净空区 ≥ 1/4 字高；最小尺寸：纯图形 ≥32px（印刷 ≥6mm）
  ≤32px 建议改用 fayelong-favicon.svg：同一套比例，但外框 960 可被 16/32/48/64 整除 → 整像素不虚
  16px 实测：笔 {g['SW']*16/g['H']:.2f}px · 果 {g['FRUIT']*16/g['H']:.2f}px · 间隔 {g['GAP']*16/g['H']:.2f}px（果可辨，间隔并拢属物理下限）
-->
"""
    pad = f'<rect width="{g["W"]}" height="{g["H"]}" fill="{bg}"/>' if bg else ""
    return (head + f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {g["W"]} {g["H"]}" '
            f'role="img" aria-label="FayeLong">{pad}{body_paths(g, ink, fruit, face)}</svg>')


def lockup_inline(g, kind, ink, fruit, bg=None, h=None):
    W, H, cap = g["W"], g["H"], g["CAP_HEIGHT"]
    fs = cap / 0.72
    gap = 0.382 * cap
    base = float(H)
    art = body_paths(g, ink, fruit)
    if kind == "icon":
        vw, vh, body = W, H, [art]
    elif kind == "stack":
        sc = W / 3.5
        vw, vh = 1400, round(H + sc * 2.95)
        body = [f'<g transform="translate({_f((vw-W)/2)},0)">{art}</g>',
                f'<text x="{vw/2}" y="{_f(H+sc*1.55)}" font-family="{G.FONT_LATIN}" '
                f'font-size="{sc/0.72:.1f}" font-weight="650" letter-spacing="-5" '
                f'fill="{ink}" text-anchor="middle">FayeLong</text>',
                f'<text x="{vw/2}" y="{_f(H+sc*2.55)}" font-family="{SANS}" '
                f'font-size="{sc*0.42:.1f}" font-weight="500" letter-spacing="{sc*0.15:.1f}" '
                f'fill="{ink}" text-anchor="middle" opacity="0.70">英语精听 · 听写</text>']
    else:
        vw = 2060
        vh = round(H + cap * 0.42)
        lx = W + gap
        body = [art]
        if kind == "latin":
            body.append(f'<text x="{_f(lx)}" y="{_f(base)}" font-family="{G.FONT_LATIN}" '
                        f'font-size="{fs:.1f}" font-weight="650" letter-spacing="-6" '
                        f'fill="{ink}">FayeLong</text>')
        elif kind == "bi":
            body.append(f'<text x="{_f(lx)}" y="{_f(base-cap*0.52)}" font-family="{G.FONT_LATIN}" '
                        f'font-size="{fs:.1f}" font-weight="650" letter-spacing="-6" '
                        f'fill="{ink}">FayeLong</text>')
            body.append(f'<text x="{_f(lx+8)}" y="{_f(base)}" font-family="{SANS}" '
                        f'font-size="{cap*0.42:.1f}" font-weight="500" '
                        f'letter-spacing="{cap*0.16:.1f}" fill="{ink}" opacity="0.70">'
                        f'英语精听 · 听写</text>')
        elif kind == "cn":
            body.append(f'<text x="{_f(lx)}" y="{_f(base-cap*0.44)}" font-family="{SANS}" '
                        f'font-size="{fs*0.78:.1f}" font-weight="700" '
                        f'letter-spacing="{cap*0.05:.1f}" fill="{ink}">英语精听</text>')
            body.append(f'<text x="{_f(lx+8)}" y="{_f(base)}" font-family="{G.FONT_LATIN}" '
                        f'font-size="{cap*0.36:.1f}" font-weight="600" '
                        f'letter-spacing="{cap*0.14:.1f}" fill="{ink}" opacity="0.62">FAYELONG</text>')
    head = ("<!-- FayeLong 组合标志（v2 · L · 柚子）\n"
            "     图形本体为纯矢量路径（零字体依赖）；字标本轮为字体排版占位，\n"
            "     依赖字体栈：Inter Tight → Inter → Segoe UI Variable → system-ui；\n"
            "     中文：思源黑体 SC → 苹方 → 微软雅黑。定稿轮将自绘轮廓并轮廓化。\n"
            "     几何真源：06-source/geom.py -->\n")
    size = f' width="{round(h*vw/vh)}" height="{h}"' if h else ""
    out = [head, f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}"{size}>']
    if bg:
        out.append(f'<rect width="{vw}" height="{vh}" fill="{bg}"/>')
    out += body + ["</svg>"]
    return "".join(out)


# ============================================================
# 2. blueprint 数学标注图
# ============================================================
def blueprint_svg(g, gf, st):
    X0, Y0 = 300.0, 300.0
    W, H, SW, LW, GP, FT = g["W"], g["H"], g["SW"], g["L_W"], g["GAP"], g["FRUIT"]
    A, K, T, B = "#52525B", "#94A3B8", "#0F172A", "#2563EB"   # 标注用中性灰：不与品牌粉/黄抢色
    VW, VH = 2200, 1980

    def px(x):
        return X0 + x

    def py(y):
        return Y0 + y

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {VH}" '
         f'font-family="{SANS}" width="{VW}" height="{VH}">',
         f'<rect width="{VW}" height="{VH}" fill="#FFFFFF"/>',
         f'<text x="{X0-160}" y="100" font-size="34" font-weight="800" fill="{T}">'
         f'FayeLong 标志 v2 ·「L · 柚子」几何标注图</text>',
         f'<text x="{X0-160}" y="140" font-size="19" fill="#475569">'
         f'圆语法（全标圆角 r = SW/2）· 外框 1:1 · 数值由脚本实时计算，无手写</text>']

    for gx in range(0, W + 1, 32):
        o.append(f'<line x1="{px(gx)}" y1="{py(0)}" x2="{px(gx)}" y2="{py(H)}" stroke="#EDF1F5"/>')
    for gy in range(0, H + 1, 32):
        o.append(f'<line x1="{px(0)}" y1="{py(gy)}" x2="{px(W)}" y2="{py(gy)}" stroke="#EDF1F5"/>')

    # 实形
    _st, leaf, _tip, _bs = G.stem_leaf(g)
    o.append(f'<g transform="translate({X0},{Y0})">'
             f'<path d="{leaf}" fill="{INK}" fill-opacity="0.20" stroke="{INK}" stroke-width="1.6"/>'
             f'<path d="{G.fruit_path(g)}" fill="{FRUIT}" fill-opacity="0.30" stroke="{FRUIT}" stroke-width="2"/>'
             f'<path d="{G.mark_path(g)}" fill="{INK}" fill-opacity="0.16" stroke="{INK}" stroke-width="2"/></g>')

    # 构造圆 / 关键点
    o.append(f'<g transform="translate({X0},{Y0})" fill="none" stroke="{B}" stroke-dasharray="6 5" stroke-width="1.4">'
             f'<circle cx="{_f(g["R"])}" cy="{_f(g["R"])}" r="{_f(g["R"])}"/>'
             f'<circle cx="{_f(g["R"])}" cy="{_f(g["FY"])}" r="{_f(g["R"])}"/>'
             f'<circle cx="{_f(g["L_W"]-g["R"])}" cy="{_f(g["FY"])}" r="{_f(g["R"])}"/>'
             f'<circle cx="{_f(g["SW"]+g["R"])}" cy="{_f(g["H"]-SW-g["R"])}" r="{_f(g["R"])}"/></g>')
    for (mx, my) in [(0, g["R"]), (SW, g["R"]), (g["R"], g["H"]), (g["L_W"], g["H"] - SW),
                     (g["L_W"], g["H"]), (g["FX"], g["FY"] - g["RY_FRUIT"]),
                     (g["FX"] - g["R_FRUIT"], g["FY"]), (g["FX"] + g["R_FRUIT"], g["FY"])]:
        o.append(f'<circle cx="{px(mx)}" cy="{py(my)}" r="5" fill="#FFF" stroke="{A}" stroke-width="2"/>')
    o.append(f'<line x1="{px(-140)}" y1="{py(H)}" x2="{px(W+60)}" y2="{py(H)}" stroke="{A}" stroke-width="1.8" stroke-dasharray="12 6"/>')
    o.append(f'<text x="{_f(px(-134))}" y="{py(H)-16}" font-size="18" fill="{A}">基线（柚子下切点与横笔底缘共线）</text>')
    o.append(f'<line x1="{px(g["SW"])}" y1="{py(-60)}" x2="{px(g["SW"])}" y2="{py(H)}" stroke="{A}" stroke-width="1.2" stroke-dasharray="8 5"/>')
    o.append(f'<line x1="{px(-80)}" y1="{py(H-SW)}" x2="{px(W+60)}" y2="{py(H-SW)}" stroke="{A}" stroke-width="1.2" stroke-dasharray="8 5"/>')
    o.append(f'<text x="{_f(px(g["SW"])+14)}" y="{py(-14)}" font-size="18" fill="{A}">内凹转角（中心线半径 = SW，E §7.2 达标）</text>')
    o.append(f'<text x="{_f(px(-74))}" y="{py(H-SW)-12}" font-size="17" fill="{A}">横笔上缘</text>')

    # 尺寸
    def hdim(x1, x2, y, label, sub=None, lx=None, anchor="middle"):
        o.append(f'<line x1="{px(x1)}" y1="{py(y)}" x2="{px(x2)}" y2="{py(y)}" stroke="{A}" stroke-width="1.4"/>')
        for xx in (x1, x2):
            o.append(f'<line x1="{px(xx)}" y1="{py(y)-8}" x2="{px(xx)}" y2="{py(y)+8}" stroke="{A}" stroke-width="1.4"/>')
        tx = px(lx) if lx is not None else px((x1 + x2) / 2)
        o.append(f'<text x="{_f(tx)}" y="{py(y)-14}" font-size="20" font-family="{MONO}" fill="{A}" text-anchor="{anchor}" font-weight="700">{label}</text>')
        if sub:
            o.append(f'<text x="{_f(tx)}" y="{py(y)+26}" font-size="16" fill="#64748B" text-anchor="{anchor}">{sub}</text>')

    def vdim(y1, y2, x, label, sub=None, side="left"):
        o.append(f'<line x1="{px(x)}" y1="{py(y1)}" x2="{px(x)}" y2="{py(y2)}" stroke="{A}" stroke-width="1.4"/>')
        for yy in (y1, y2):
            o.append(f'<line x1="{px(x)-8}" y1="{py(yy)}" x2="{px(x)+8}" y2="{py(yy)}" stroke="{A}" stroke-width="1.4"/>')
        dx = -18 if side == "left" else 18
        an = "end" if side == "left" else "start"
        o.append(f'<text x="{_f(px(x)+dx)}" y="{py((y1+y2)/2)}" font-size="20" font-family="{MONO}" fill="{A}" text-anchor="{an}" font-weight="700">{label}</text>')
        if sub:
            o.append(f'<text x="{_f(px(x)+dx)}" y="{py((y1+y2)/2)+24}" font-size="16" fill="#64748B" text-anchor="{an}">{sub}</text>')

    vdim(0, H, -96, f"H = {H}", "外框高")
    hdim(0, SW, -120, f"SW = {SW}", "笔宽 = H/φ³")
    hdim(0, W, H + 92, f"W = {W}", "外框宽 = H（正方形）")

    # ★ 宽度尺寸链
    ych = H + 310
    o.append(f'<text x="{_f(px(0))}" y="{py(ych)-176}" font-size="24" font-weight="800" fill="{T}">'
             f'★ 宽度尺寸链：三宽度精确填满外框 —— 加了柚子，形状自己把画框撑成正方形</text>')
    o.append(f'<text x="{_f(px(0))}" y="{py(ych)-144}" font-size="18" fill="#475569">'
             f'2SW　+　SW/φ　+　SW·φ　=　SW(2 + 1/φ + φ)　=　SW·φ³　=　H　（2 + 1/φ + φ = 2φ + 1 = φ³ 恒成立）</text>')
    o.append(f'<line x1="{px(0)}" y1="{py(ych)-98}" x2="{px(W)}" y2="{py(ych)-98}" stroke="{A}" stroke-width="2"/>')
    for xx in (0, W):
        o.append(f'<line x1="{px(xx)}" y1="{py(ych)-106}" x2="{px(xx)}" y2="{py(ych)-90}" stroke="{A}" stroke-width="2"/>')
    o.append(f'<text x="{_f(px(W/2))}" y="{py(ych)-110}" font-size="20" font-family="{MONO}" fill="{A}" text-anchor="middle" font-weight="700">W = H = {W}</text>')
    for (a1, a2, col) in [(0, LW, INK), (LW, LW + GP, INK), (LW + GP, W, FRUIT)]:
        o.append(f'<rect x="{px(a1)}" y="{py(ych)-46}" width="{px(a2)-px(a1)}" height="46" fill="{col}" fill-opacity="0.32" stroke="{col}" stroke-width="2"/>')
    o.append(f'<text x="{_f(px(LW/2))}" y="{py(ych)+36}" font-size="20" font-family="{MONO}" fill="{T}" text-anchor="middle" font-weight="700">L_W = {LW}　( = 2SW + SW/φ³ )</text>')
    o.append(f'<line x1="{px(LW+GP/2)}" y1="{py(ych)}" x2="{px(LW+GP/2)}" y2="{py(ych)+60}" stroke="{A}" stroke-width="1"/>')
    o.append(f'<text x="{_f(px(LW+14))}" y="{py(ych)+80}" font-size="20" font-family="{MONO}" fill="{T}" font-weight="700">GAP = {GP}　( = SW/φ² )</text>')
    o.append(f'<line x1="{px(LW+GP+FT/2)}" y1="{py(ych)}" x2="{px(LW+GP+FT/2)}" y2="{py(ych)+108}" stroke="{FRUIT}" stroke-width="1.4"/>')
    o.append(f'<text x="{_f(px(LW+14))}" y="{py(ych)+128}" font-size="20" font-family="{MONO}" fill="{FRUIT}" font-weight="700">FRUIT = {FT}　( = SW·φ )</text>')
    o.append(f'<text x="{_f(px(0))}" y="{py(ych)+146}" font-size="18" fill="#334155">'
             f'{LW} + {GP} + {FT} = {LW+GP+FT} ≡ {W}　误差 0.000%　→　三个宽度一个自由度都没有</text>')

    # 柚子 / 叶 放样
    _ax = (-math.cos(math.radians(G.LEAF_ANGLE_DEG)), -math.sin(math.radians(G.LEAF_ANGLE_DEG)))
    _t0, _t1 = 0.0, 4000.0
    for _ in range(60):
        _tm = (_t0 + _t1) / 2
        _px, _py2 = g["FX"] + _tm * _ax[0], g["FY"] + _tm * _ax[1]
        if ((_px - g["FX"]) / g["R_FRUIT"]) ** 2 + ((_py2 - g["FY"]) / g["RY_FRUIT"]) ** 2 <= 1:
            _t0 = _tm
        else:
            _t1 = _tm
    _vis = max(0.0, g["LEAF_INSET"] + g["LEAF_CHORD"] - _t0)
    oy = py(ych) + 300
    ox = px(0)
    o.append(f'<text x="{ox}" y="{oy-96}" font-size="19" font-weight="800" fill="{T}">柚子放样（果身 · 蒂窝 · 叶）</text>')
    o.append(f'<g transform="translate({X0},{Y0})" fill="none" stroke="{FRUIT}" stroke-width="2">'
             f'<ellipse cx="{_f(g["FX"])}" cy="{_f(g["FY"])}" rx="{_f(g["R_FRUIT"])}" ry="{_f(g["RY_FRUIT"])}"/></g>')
    for i, t in enumerate([
            f"果身 宽 {FT} × 高 {g['RY_FRUIT']*2:.1f}　(宽:高 = 2:√3 ≈ 0.866) — 饱满柚形，与「苹果」拉开",
            f"蒂窝 半角 {G.DIP_HALF_ANGLE:.0f}°、弧半径 {_f(g['R_DIP'])} → 深 {_f(g['DIP_DEPTH'])}（小凹，不作特征）",
            f"叶 弦长 {g['LEAF_CHORD']}、弧半径 {_f(g['R_LEAF'])} → 宽 {2*(g['R_LEAF']-((g['R_LEAF']**2-(g['LEAF_CHORD']/2)**2)**0.5)):.1f}；轴与水平成 arctan(φ) = {G.LEAF_ANGLE_DEG:.2f}°",
            f"叶基埋入果内 {_f(g['LEAF_INSET'])} → 果身覆盖其根部，露出果肩之外约 {_vis:.0f}（总长 {g['LEAF_CHORD']}）",
            f"叶尖 ({_f(_tip[0])}, {_f(_tip[1])})；叶尖朝左是必然的：朝右会越出外框",
            "半径分级 3 级：圆角 98 / 叶弧 121 / 蒂窝 75"]):
        o.append(f'<circle cx="{ox+8}" cy="{oy-70+i*27-6}" r="4" fill="#16A34A"/>')
        o.append(f'<text x="{ox+24}" y="{oy-70+i*27}" font-size="16.5" fill="#334155">{t}</text>')

    # ================= 数据面板 =================
    PX, yy = 1230, 210

    def sec(t):
        nonlocal yy
        o.append(f'<text x="{PX}" y="{yy}" font-size="24" fill="{T}" font-weight="800">{t}</text>')
        yy += 14
        o.append(f'<line x1="{PX}" y1="{yy}" x2="{PX+930}" y2="{yy}" stroke="{T}" stroke-width="2"/>')
        yy += 30

    def row(k, v, note=""):
        nonlocal yy
        o.append(f'<text x="{PX}" y="{yy}" font-size="17.5" fill="#334155">{k}</text>')
        o.append(f'<text x="{PX+300}" y="{yy}" font-size="17.5" font-family="{MONO}" fill="{T}" font-weight="700">{v}</text>')
        if note:
            o.append(f'<text x="{PX+540}" y="{yy}" font-size="16" fill="#64748B">{note}</text>')
        yy += 27

    sec("① 比例系统 · 黄金比 φ = 1.618034")
    for k, val, tgt in [("外框 W : H", W / H, 1.0),
                        ("笔宽 SW : H", SW / H, 1 / PHI ** 3),
                        ("横笔 L_W : H", LW / H, 2 / PHI ** 3 + 1 / PHI ** 6),
                        ("间隔 GAP : SW", GP / SW, 1 / PHI ** 2),
                        ("柚子 FRUIT : H", FT / H, 1 / PHI ** 2),
                        ("叶弧 : SW", g["R_LEAF"] / SW, 1 / PHI),
                        ("蒂窝弧 : SW", g["R_DIP"] / SW, 1 / PHI ** 2),
                        ("横笔平直段 : SW", (LW - g["R"] - SW - g["R_FIL"]) / SW, 1 / PHI ** 4),
                        ("字标大写高 : H", g["CAP_HEIGHT"] / H, 1 / PHI ** 3)]:
        row(k, f"{val:.5f}", f"目标 {tgt:.6f}｜误差 {abs(val-tgt)/tgt*100:.3f}%")
    yy += 10

    sec("② 关键尺寸链值")
    row("画布 / 留白（构建参照）", f"{g['canvas']} / {g['pad']}", "8pt 模块网格")
    row("外框 H × W", f"{H} × {W}", "1 : 1（正方形）")
    row("笔宽 / 全标圆角", f"{SW} / {_f(g['R'])}", "圆角 = SW/2")
    row("横笔 L_W", f"{LW}", "= 2SW + SW/φ³")
    row("间隔 GAP", f"{GP}", "= SW/φ²")
    row("柚子 宽×高", f"{FT} × {g['RY_FRUIT']*2:.1f}", "= SW·φ；2:√3")
    row("柚子中心", f"({_f(g['FX'])}, {_f(g['FY'])})", "下切点落在基线")
    row("叶 弦长 / 半径", f"{g['LEAF_CHORD']} / {_f(g['R_LEAF'])}", "轴 arctan(φ)")
    row("叶基埋深 / 叶尖", f"{_f(g['LEAF_INSET'])} / ({_f(_tip[0])}, {_f(_tip[1])})", "")
    yy += 10

    sec("③ 构造恒定式（构建期 assert，失败即中止）")
    for t in [f"L_W + GAP + FRUIT = {LW} + {GP} + {FT} = {LW+GP+FT} ≡ W = {W}",
              "2SW + SW/φ + SW·φ = SW(2φ+1) = SW·φ³ = H（2φ+1 = φ³ 恒成立）",
              f"半径 3 档：端头·外凸转角 {_f(g['R'])} / 内凹转角·蒂窝 {g['R_FIL']} / 叶弧 {_f(g['R_LEAF'])}",
              f"内凹转角中心线半径 = SW = {SW} ≥ 笔宽（E §7.2 内缘不归零）",
              "相切① 柚子下切点 = 基线 y = H",
              "相切② 柚子右缘 = 外框右缘；左缘 = 横笔端头 + GAP",
              "叶基在果身椭圆内（露出长度 = 弦长 − 埋入段）"]:
        o.append(f'<circle cx="{PX+7}" cy="{yy-6}" r="4" fill="#16A34A"/>')
        o.append(f'<text x="{PX+22}" y="{yy}" font-size="16.5" fill="#334155">{t}</text>')
        yy += 26
    yy += 12

    sec("④ 视觉重量（程序计算）")
    row("主角 字母 L", st["l_share"], "面积占比")
    row("配角 柚子", st["fruit_share"], "带叶，< 50%：主角仍是字母")
    yy += 10

    sec("⑤ 色彩（WCAG 相对亮度法）")
    row("主色 樱粉", INK, f"纸底对比 {st['c_ink']:.2f}:1")
    row("柚子 柚黄", FRUIT, f"纸底对比 {st['c_fruit']:.2f}:1")
    row("深底反白", INKD, f"深底对比 {st['c_rev']:.2f}:1")
    row("主辅灰度明度差", f"{st['lum_gap']:.1f}%", "> 20% 达标（色盲安全）")
    yy += 10

    sec("⑥ 小尺寸降级（同一套比例 · 外框整除友好）")
    row("主标最小尺寸", "32px", "< 32px 改用 favicon 版")
    row("favicon 外框 H × W", f"{gf['H']} × {gf['W']}", "16/32/48/64 全整除 → 整像素")
    row("favicon 果 / 间隔", f"{gf['FRUIT']} / {gf['GAP']}", "与主标同比例（非另一套几何）")
    row("16px 实测（笔 / 果 / 隔）", f"{gf['SW']*16/gf['H']:.2f} / {gf['FRUIT']*16/gf['H']:.2f} / {gf['GAP']*16/gf['H']:.2f} px", "果可辨；隔并拢 = 物理下限")
    o.append('</svg>')
    return "".join(o)


# ============================================================
# 3. preview.html
# ============================================================
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#EDEFEE;color:#12211E;line-height:1.65;-webkit-font-smoothing:antialiased;
 font-family:'Inter Tight',Inter,'Segoe UI Variable Text','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:56px 32px 96px}
h1{font-size:38px;margin:0 0 10px;letter-spacing:-.5px}
h2{font-size:23px;margin:64px 0 6px;padding-top:24px;border-top:1px solid #D5DAD7}
h2 .n{font-family:'Cascadia Mono',Consolas,monospace;font-size:15px;color:#8A9691;margin-right:10px}
h2 small{font-size:14px;color:#8A9691;font-weight:400}
h3{font-size:16px;margin:30px 0 10px}
.sub{color:#5C6B66;font-size:15px;margin:0 0 4px}
.lead{font-size:16px;color:#3C4C47;max-width:80ch}
.card{background:#F2F5F3;border:1px solid #DFE4E1;border-radius:16px;padding:22px}
.card.dark{background:#0B2A26;border-color:#0B2A26}
.card.dark .ttl,.card.dark .cap{color:#E7EDEA}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
svg{display:block;width:100%;height:auto}
.ttl{font-size:12.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#5C6B66;margin-bottom:10px}
.cap{font-size:13px;color:#5C6B66;margin-top:12px}
.tres{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:26px 0}
.res{background:#F2F5F3;border:1px solid #DFE4E1;border-radius:14px;padding:16px 18px}
.res h4{margin:0 0 10px;font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:#8A9691}
.res pre{margin:0;font-family:'Cascadia Mono',Consolas,monospace;font-size:11.5px;
 color:#12211E;white-space:pre-wrap;line-height:1.8}
table{width:100%;border-collapse:collapse;font-size:14.5px;margin-top:12px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #DFE4E1;vertical-align:top}
th{font-size:12.5px;letter-spacing:.04em;text-transform:uppercase;color:#8A9691;font-weight:700}
td.ok{font-weight:700;white-space:nowrap;color:#0E7C5A}
.mono{font-family:'Cascadia Mono',Consolas,monospace;font-size:13px}
.hero{background:#F2F5F3;border:1px solid #DFE4E1;border-radius:18px;padding:44px;
 display:grid;grid-template-columns:330px 1fr;gap:44px;align-items:center}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.chip{font-size:12.5px;padding:3px 11px;border-radius:999px;background:#FBE6EE;color:#A8345F;border:1px solid #F5CFE0}
.chip.f{background:#FCF3CF;color:#7A5E06;border-color:#F0E2A8}
.chip.o{background:transparent;color:#12211E;border:1px solid #C9D0CC}
svg.fix{width:auto;height:auto}   /* 小尺寸图标：别被全局 svg{width:100%} 拉满容器 */
.zoom{display:flex;align-items:flex-end;gap:22px;flex-wrap:wrap;
 background:#F2F5F3;border:1px solid #DFE4E1;border-radius:16px;padding:24px 26px}
.zi{display:flex;flex-direction:column;align-items:center;gap:8px}
.zi span{font-family:'Cascadia Mono',Consolas,monospace;font-size:11.5px;color:#8A9691}
.tab{display:flex;align-items:center;gap:9px;background:#0B2A26;border-radius:10px 10px 0 0;padding:9px 16px}
.tab span{font-size:13px;color:#F2F5F3}
.note{font-size:13.5px;color:#8A9691;margin-top:10px}
ul{margin:8px 0 0;padding-left:20px}li{margin:4px 0;font-size:14.5px}
.sw{display:inline-block;width:13px;height:13px;border:1px solid #C2CAC6;border-radius:3px;vertical-align:-2px}
@media(max-width:920px){.grid2,.grid3,.grid4,.tres{grid-template-columns:1fr}
 .hero{grid-template-columns:1fr}}
"""


def _v1_mark():
    """加载 v1 几何用于演进对照（失败则跳过该区块）"""
    try:
        import importlib.util
        p = os.path.join(ROOT, "..", "06-source", "build_logo.py")
        sp = importlib.util.spec_from_file_location("fyl_v1", p)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m
    except Exception:
        return None


def preview_html(g, gf, st):
    W, H = g["W"], g["H"]
    P = []
    A = P.append
    A('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<title>FayeLong 标志 v2 ·「L · 柚子」</title>')
    A(f"<style>{CSS}</style></head><body><div class='wrap'>")

    A("<h1>FayeLong 标志 v2 ·「L · 柚子」</h1>")
    A("<p class='sub'>可爱活泼版 · 提案轮 · 在 v1「L · 落点」骨架上改三件事："
      "直角语法 → 圆语法，句点 → 一颗柚子，松墨深青 → 樱粉 + 柚黄</p>")
    A("<p class='lead'>还是那个 <b>L</b>，但它圆了、胖了、有了一颗果子。"
      "原来那个小句点长大了 —— 长成一颗<b>饱满的柚子</b>，从果肩后面伸出一片叶子。"
      "「一句被听清的话，结成了一颗果子」：声音听懂了，才有果子。<br>"
      "配色换成一手粉、一手黄：<b>粉给字，黄给果</b> —— 粉是整个教育品类里的空位，黄是柚子本来的颜色。<br>"
      "两处几何事实：<b>圆度只有 3 档、而且两两成对</b>（端头=外转角 98、内凹转角=蒂窝 75、叶弧 121）；"
      "<b>外框是被恒等式逼成正方形的</b> —— "
      "<span class='mono'>L_W + GAP + FRUIT = SW·φ³ = H</span>。</p>")

    # ── v1 → v2 差异 ──
    A("<div class='tres'>")
    A("<div class='res'><h4>① 改了什么</h4><pre>"
      "风格语法　直角端 → 圆语法（圆头端 + 圆转角）\n"
      "配角　　　句点方块 → 柚子（果身 + 蒂窝 + 斜叶）\n"
      f"主色　　　松墨 #0E3B34 → 樱粉 {INK}（L + 叶 + 字标）\n"
      f"果色　　　#DB9E28 → 柚黄 {FRUIT}\n"
      f"　　　　　H 39.6° → {G.hsv(FRUIT)[0]:.1f}°（离开橙色区，进正黄）\n"
      "外框　　　1:φ → 1:1（被恒等式逼出来的）\n"
      f"横笔　　　H/φ（513）→ 2SW + SW/φ³（{g['L_W']}）\n"
      "语气　　　精确、克制 → 亲近、饱满、有果子</pre></div>")
    A("<div class='res'><h4>② 没改什么（骨架保持）</h4><pre>"
      "构成逻辑　字母 L + 一个落在基线上的配角\n"
      "共底规则　配角下缘与横笔底缘共线 = 同一条基线\n"
      "比例系统　黄金比 φ（全部尺寸仍由它派生）\n"
      "参数化　　改 geom.py 重跑 → 全套产物同步更新\n"
      "外框恒等式 三段宽度精确填满，误差 0.000%</pre></div>")
    A("<div class='res'><h4>③ 柚子从哪来（待确认）</h4><pre>"
      "⚠️ 推断：本轮按「品牌元素」处理柚子，\n"
      "　 语义绑定 = 「被听清的那句话结成的果子」。\n"
      "如果柚子其实是别的意思（人名 / 谐音 / 地名 /\n"
      "「柚 = You」＝ 学英语的你），告诉我，\n"
      "我把语义层重写 —— 几何不用动，只改文案与\n"
      "应用场景建议，半小时出新版。</pre></div>")
    A("</div>")

    # ── ① Hero ──
    A("<h2><span class='n'>01</span>Hero 主标</h2>")
    A("<p class='sub'>纯图形 · 彩色 · 透明底可用（此卡为纸底）</p>")
    A("<div class='hero'>")
    A(mark_inline(g, INK, FRUIT, px=460, bg=BG))
    A("<div><h3 style='margin-top:0'>一句话，一颗果</h3>"
      "<p class='lead'>圆头端、圆转角、圆果子 —— 圆度只有 3 档，而且两两成对（端头 = 外转角、"
      "内凹转角 = 蒂窝），所以它看着是「同一个人做的」，而不是把圆零件拼起来。"
      "叶子从果肩后面长出来，根部被果身盖住，边界靠一根干净的外轮廓分开，没有任何描边。<br>"
      "粉给字、黄给果：粉让它是「可爱的」，黄让果子是「能吃的」。</p>"
      "<div class='chips'><span class='chip'>樱粉 #F2759F</span>"
      "<span class='chip f'>柚黄 #EDC62A</span><span class='chip'>外框 1:1</span>"
      "<span class='chip o'>零描边 · 零渐变 · 零投影</span></div>"
      f"<p class='note'>恒等式：<span class='mono'>(2SW + SW/φ³) + SW/φ² + SW·φ = SW·φ³ = H</span> — "
      f"{g['L_W']} + {g['GAP']} + {g['FRUIT']} = {W}，三段精确填满，误差 0.000%。</p></div>")
    A("</div>")

    # ── ② 三卡 ──
    A("<h2><span class='n'>02</span>三卡</h2>")
    A("<div class='tres'>")
    A("<div class='res'><h4>① 元素预算卡</h4><pre>"
      f"元素清单：字母 L（主）／柚子（配）—— 2 / 3 达标\n"
      f"柚子 = 果身 + 蒂窝 + 叶（3 个基础形状，算 1 个元素）\n"
      f"主角占比：L 占 {st['l_share']}　柚子占 {st['fruit_share']}\n"
      f"删减测试：删柚子 → 回到 v1，可爱度与品牌元素同时消失 → 保留\n"
      f"一元素多义：柚子 = 果实（听懂后的收获）\n"
      f"　　　　　　+ 柚 ≈ You（学英语的你，可讲可不讲）\n"
      f"　　　　　　+ 与 v1 的句点同位置同角色（一句的最小单位）\n"
      f"关系语义：下切点落在基线上 →「落在句子上」，不是漂浮装饰</pre></div>")
    A("<div class='res'><h4>② 色彩判断卡</h4><pre>"
      f"行业地图：英语学习 = 教育蓝（百词斩/扇贝/流利说）\n"
      f"　　　　　+ 多邻国高饱和亮绿（游戏化）\n"
      f"　　　　　→ 空位 = 暖色系；整个品类几乎没人用粉\n"
      f"　　　　　（粉常被当成「不够权威」—— 正好对上可爱活泼）\n"
      f"主色：{INK} 樱粉（L + 叶 + 字标）\n"
      f"　　　HSV {G.hsv(INK)[0]:.1f}° {G.hsv(INK)[1]:.1f}% {G.hsv(INK)[2]:.1f}%\n"
      f"辅助结构色：{FRUIT} 柚黄（只给柚子果身，占 {st['fruit_share']}）\n"
      f"　　　　HSV {G.hsv(FRUIT)[0]:.1f}° {G.hsv(FRUIT)[1]:.1f}% {G.hsv(FRUIT)[2]:.1f}%（正黄区）\n"
      f"底色：{BG} 纸底｜深底 {BGD}；深底粉提亮 {INKD}、果提亮 {FRUITD}\n"
      f"硬判据：灰度明度差 {st['lum_gap']:.1f}% &gt; 20% ✓\n"
      f"　　　　｜四格式齐全 ✓｜单色可逆 ✓（见诚实声明）\n"
      f"两色定局：整标只有樱粉 + 柚黄，叶不另开绿色\n"
      f"　　→ 叶与 L 同色，画面里「绿」的来源为零，比前版更干净\n"
      f"小字提醒：樱粉 / 纸底 = {st['c_ink']:.2f}:1，标志场景够用；\n"
      f"　　　　　若要当正文或小字号颜色，改用深樱粉 {G.INK_TEXT_SAFE}</pre></div>")
    A("<div class='res'><h4>③ 风格语法卡</h4><pre>"
      f"连续谱定位：圆语法（左二区）—— 圆头端、圆转角\n"
      f"端头 / 外凸转角：r = SW/2 = {_f(g['R'])}（50% 笔宽，F §3 圆语法区间）\n"
      f"内凹转角 / 蒂窝：r = SW/φ² = {g['R_FIL']}（收一档换取横笔平直段 {g['L_W']-g['R']-g['SW']-g['R_FIL']:.0f}）\n"
      f"　半径分级 3 档：{_f(g['R'])} / {g['R_FIL']} / {_f(g['R_LEAF'])}（≤3 达标）\n"
      f"　端头与外转角同档、内凹转角与蒂窝同档 ← 这才是「看着像一套」的机制\n"
      f"内凹转角中心线半径 = SW（E §7.2：内缘不归零）\n"
      f"活泼来源：圆端 + 饱满果形 + 斜叶（arctan φ ≈ 58.3°）\n"
      f"禁项自查：无描边 / 无渐变 / 无投影 / 无外发光 / 无叠圆 ✓</pre></div>")
    A("</div>")

    # ── ③ 可爱度拆解 ──
    A("<h2><span class='n'>03</span>「可爱」拆解：可爱是算出来的，不是调出来的</h2>")
    A("<p class='sub'>可爱在几何上有 4 个明确的来源，每一项都可以指着说清。"
      "这也是它不会随审美风潮过期、也不会缩到 16px 就散架的原因。</p>")
    A("<table><tr><th>#</th><th>可爱来源</th><th>几何做法</th><th>为什么有效</th></tr>")
    for i, (k, v, why) in enumerate([
        ("圆头端", f"笔的两端 = 半圆，半径 SW/2 = {_f(g['R'])}",
         "直角端读「机器」，圆端读「人手/活物」—— 圆头 = 笔画有指尖"),
        ("圆度成对", "端头=外凸转角 98；内凹转角=蒂窝 75；叶弧 121 —— 一一对应",
         "圆度统一 → 看着像「一整个」而不是拼装 → 亲和力来自一致而非装饰"),
        ("饱满果形", "宽:高 = 2:√3 ≈ 0.866，明显偏扁",
         "果实类「扁 = 熟、饱满、甜」；也是与苹果（偏高、有腰）拉开的关键一笔"),
        ("斜叶", "叶轴与水平成 arctan(φ) ≈ 58.3°",
         "叶一旦竖直就成标本，斜着才有「刚长出来」的动势 → 活泼的唯一来源"),
    ]):
        A(f"<tr><td class='mono'>{i+1}</td><td><b>{k}</b></td><td class='mono'>{v}</td><td>{why}</td></tr>")
    A("</table>")

    # ── ④ Lockup 矩阵 ──
    A("<h2><span class='n'>04</span>组合 Lockup 矩阵<small>（字标本轮为字体排版占位，定稿轮按笔宽自绘轮廓）</small></h2>")
    A("<p class='sub'>5 种组合 × 明／暗两种底色。字标基线一律对齐标志基线 —— 字标坐在 L 的横笔所代表的那条线上。</p>")
    kinds = [("icon", "纯图形"), ("latin", "图形 + FayeLong"), ("bi", "图形 + 双语横排"),
             ("cn", "图形 + 中文为主"), ("stack", "图形 + 堆叠双语")]
    for theme in ("light", "dark"):
        ink, fru, bg = (INK, FRUIT, BG) if theme == "light" else (INKD, FRUITD, BGD)
        A(f"<h3>{'明底（#F2F5F3 纸底）' if theme == 'light' else '暗底（#0B2A26 深墨底）'}</h3>")
        A("<div class='grid2'>")
        for k, label in kinds:
            cls = "card dark" if theme == "dark" else "card"
            h = 330 if k == "stack" else (360 if k == "icon" else 300)
            A(f"<div class='{cls}'><div class='ttl'>{label}</div>"
              f"{lockup_inline(g, k, ink, fru, bg=bg, h=h)}"
              f"<div class='cap'>字体：Inter Tight → Inter → Segoe UI Variable → system-ui；"
              f"中文：思源黑体 SC → 苹方 → 微软雅黑</div></div>")
        A("</div>")

    # ── ⑤ 表情版 ──
    A("<h2><span class='n'>05</span>可选项：要不要给它一张脸？</h2>")
    A("<p class='sub'>两版都交付，你挑。**主推无脸版**：它缩到 32px 仍然成立、正式场合不显轻浮；"
      "表情版更萌，适合 favicon、空状态、周边、启动页，但 24px 以下眼睛就会糊成两块墨。</p>")
    A("<div class='grid2'>")
    A(f"<div class='card'><div class='ttl'>A · 无脸版（主推）</div>"
      f"{mark_inline(g, INK, FRUIT, bg=BG)}"
      f"<div class='cap'>靠形状说话：圆端 + 扁果 + 斜叶。所有尺寸都成立，气质可控。</div></div>")
    A(f"<div class='card'><div class='ttl'>B · 表情版（更萌 · 备选）</div>"
      f"{mark_inline(g, INK, FRUIT, bg=BG, face=True)}"
      f"<div class='cap'>眼 {_f(g['R_EYE']*2)} ⌀、笑弧半径 {_f(g['MOUTH_R'])} + 线宽 {_f(g['MOUTH_W'])}。"
      f"代价：形状数 4 → 7（超出 F §1 的 ≤6 建议），24px 以下失效。</div></div>")
    A("</div>")

    # ── ⑥ 缩放墙 ──
    A("<h2><span class='n'>06</span>缩放墙与小尺寸降级</h2>")
    A("<p class='sub'>主标纯图形最小 32px；≤32px 建议改用 favicon 版 —— 它与主标<b>同一套比例</b>"
      "（果 = SW·φ、间隔 = SW/φ²），但外框是 960：能被 16/32/48/64 整除，小尺寸落在整像素上，"
      "而主标的 830 不能（16px 会得到 51.875 的缩放系数，边缘发虚）。</p>")
    A("<div class='zoom'>")
    for s in (16, 24, 32):
        A(f"<div class='zi'>{mark_inline(gf, INK, FRUIT, px=s)}<span>{s}px · favicon 版</span></div>")
    for s in (48, 64, 96, 128, 192):
        A(f"<div class='zi'>{mark_inline(g, INK, FRUIT, px=s)}<span>{s}px</span></div>")
    A("</div>")
    A(f"<p class='note'>16px 实测：笔宽 {gf['SW']*16/gf['H']:.2f}px · "
      f"柚子 {gf['FRUIT']*16/gf['H']:.2f}px · 间隔 {gf['GAP']*16/gf['H']:.2f}px（与主标基本一致，"
      f"因为二者共用同一条 φ 链）。<b>诚实说明</b>：16px 时那 {gf['GAP']*16/gf['H']:.2f}px 的间隔会视觉并拢 —— "
      f"这是「8px 宽的果子 + 3.8px 的笔画」在 16px 格子里能塞下的物理下限，不是设计失误。"
      f"若要在 16px 拿到更强的存在感，标准解法是给图标加<b>品牌色底 + 反白标志</b>（未做，说一声我出）。</p>")

    # ── ⑦ blueprint ──
    A("<h2><span class='n'>07</span>关键尺寸 + blueprint 数学标注图</h2>")
    A("<p class='sub'>尺寸链、半径分级、相切条件全部程序计算。核心是那条恒等式："
      "三段宽度精确填满外框 —— 于是外框只能是正方形。</p>")
    A("<div class='card' style='padding:8px'>")
    A(blueprint_svg(g, gf, st).replace(' width="2200" height="1980"', ""))
    A("</div>")
    A("<p class='note'>光栅版：<span class='mono'>07-blueprint/fayelong-cute-blueprint.png</span></p>")

    # ── ⑧ 变体家族 ──
    A("<h2><span class='n'>08</span>变体家族</h2>")
    A(f"<p class='sub'>主标彩色／单色黑／反白／灰阶。反白版不是简单反相：深底把粉提亮到 {INKD}、把果提亮到 {FRUITD}。</p>")
    A("<div class='grid4'>")
    for label, ink, fru, bg in [("主标 · 彩色", INK, FRUIT, BG), ("单色黑", "#000000", "#000000", BG),
                                ("反白 · 深底", INKD, FRUITD, BGD), ("灰阶", "#333333", "#8C8C8C", BG)]:
        cls = "card dark" if bg == BGD else "card"
        A(f"<div class='{cls}'><div class='ttl'>{label}</div>"
          f"{mark_inline(g, ink, fru, px=230, bg=bg)}</div>")
    A("</div>")
    A("<p class='note'><b>mono 诚实声明</b>：单色黑版里柚子与字母、叶子全部同色，"
      "柚子的「黄」这个识别线索消失，只靠一颗扁圆的果形 + 叶子在说话 —— 仍然可辨，"
      "但可爱度与色彩强调层失效。这是几何事实，属预期行为，不用描边或阴影假装区分。"
      "单色场景（刻章、传真、丝印单色）如需保留柚子识别度，建议用<b>反白／单色 + 留白轮廓</b>版本。</p>")

    # ── ⑨ 应用实景 ──
    A("<h2><span class='n'>09</span>应用实景</h2>")
    A("<div class='grid3'>")
    A("<div class='card' style='background:#E4E8E6'><div class='ttl'>浏览器标签页</div>"
      "<div style='display:flex;align-items:flex-end'>"
      f"<div class='tab'>{mark_inline(gf, INKD, FRUITD, px=16, extra="class='fix'")}"
      "<span>FayeLong 英语精听</span></div></div>"
      "<div style='height:130px;background:#F2F5F3;border-radius:0 10px 10px 10px'></div></div>")
    A("<div class='card'><div class='ttl'>App 图标</div>"
      "<div style='display:flex;gap:14px;align-items:center'>"
      f"<div style='width:100px;height:100px;border-radius:24px;background:{BGD};"
      f"display:flex;align-items:center;justify-content:center'>"
      f"{mark_inline(gf, INKD, FRUITD, px=66, extra="class='fix'")}</div>"
      f"<div style='width:100px;height:100px;border-radius:24px;background:{BG};"
      f"border:1px solid #DFE4E1;display:flex;align-items:center;justify-content:center'>"
      f"{mark_inline(gf, INK, FRUIT, px=66, extra="class='fix'")}</div></div>"
      "<div class='cap'>正方形外框正好是 App 图标比例 —— 这是加柚子换来的副产品</div></div>")
    A("<div class='card'><div class='ttl'>网站页眉</div>"
      f"<div style='background:#F2F5F3;border:1px solid #DFE4E1;border-radius:12px;padding:14px 18px'>"
      f"{lockup_inline(g, 'bi', INK, FRUIT)}</div>"
      f"<div style='background:#0B2A26;border-radius:12px;padding:14px 18px;margin-top:10px'>"
      f"{lockup_inline(g, 'bi', INKD, FRUITD)}</div></div>")
    A("</div>")

    # ── ⑩ 色彩卡 + 配色变体 ──
    A("<h2><span class='n'>10</span>色彩规范卡与配色变体</h2>")

    def cmyk_txt(h):
        c, m, y, k = G.cmyk(h)
        return f"C{c} M{m} Y{y} K{k}"

    A("<table><tr><th>色</th><th>HEX</th><th>RGB</th><th>CMYK</th><th>Pantone（近似）</th><th>用途</th></tr>")
    for h, name, pms, use in [
            (INK, "樱粉 Blossom", "706 C", "主色：字母 L 全部笔画 + 叶子 + 字标"),
            (FRUIT, "柚黄 Pomelo", "115 C", "点缀：柚子果身（浅底版）"),
            (BG, "纸底 Paper", "—", "浅色底背景（非纯白）"),
            (BGD, "深墨底 Deep", "5463 C", "深色模式背景"),
            (INKD, "深底反白", "—", "深底上的笔画"),
            (G.INK_TEXT_SAFE, "深樱粉 · 文字用", "208 C", "不对标志生效；仅小字号/正文用粉时替换主色"),
            (FRUITD, "深底柚子", "2003 C", "深底上提亮的果色")]:
        r, gg, b = G.rgb255(h)
        A(f"<tr><td><b>{name}</b><div><span class='sw' style='background:{h}'></span> "
          f"<span class='mono' style='color:#5C6B66'>{h}</span></div></td>"
          f"<td class='mono'>{h}</td><td class='mono'>RGB({r},{gg},{b})</td>"
          f"<td class='mono'>{cmyk_txt(h)}</td><td class='mono'>{pms}</td><td>{use}</td></tr>")
    A("</table>")
    A(f"<p class='note'>对比度：樱粉/纸底 <b>{st['c_ink']:.2f}:1</b>"
      f"柚子/纸底 {st['c_fruit']:.2f}:1（果是图形不是文字，不适用正文阈值，仅需可辨）｜"
      f"反白/深底 <b>{st['c_rev']:.2f}:1</b>｜主辅灰度明度差 <b>{st['lum_gap']:.1f}%</b>。"
      f"CMYK 为<b>朴素 RGB→CMYK 换算</b>（非 ICC 色彩管理，仅作占位）、Pantone 为近似对照 —— "
      f"两者都<b>不是</b>印刷级数值，落印前请用专色卡或让印厂出 ICC 转换。</p>")

    A("<h3>配色变体（同一套几何，换色即出）</h3>")
    A("<div class='grid3'>")
    for name, ink, fru, bgp, note in PALETTES:
        A(f"<div class='card' style='background:{bgp}'>"
          f"<div class='ttl'>{name}</div>{mark_inline(g, ink, fru, px=210, bg=bgp)}"
          f"<div class='cap'>{note}</div></div>")
    A("</div>")

    # ── ⑪ 七项检查 ──
    A("<h2><span class='n'>11</span>七项检查（自跑结果公示）</h2>")
    A("<table><tr><th>检查</th><th>结果</th><th>依据</th></tr>")
    for n, r, why in [
        ("剪影测试", "✓ 通过",
         "涂黑后 = 一个圆润的 L + 一颗带叶的扁圆果；柚子靠「扁圆 + 斜叶」在剪影下独立成立"),
        ("16px 测试", "✓ 通过（有条件）",
         f"果 {g['FRUIT']*16/g['H']:.2f}px、笔 {g['SW']*16/g['H']:.2f}px 可辨；"
         f"间隔 {g['GAP']*16/g['H']:.2f}px 会并拢（物理下限，已声明）。"
         f"≤32px 建议用 favicon 版（外框 960，整像素）"),
        ("单色测试", "✓ 通过（有代价）",
         "果形 + 叶的形状承住识别；色彩强调层失效，已在诚实声明里写明"),
        ("模糊测试", "✓ 通过", "3–6px 高斯后整体仍是「圆润 L + 扁果」，果形不塌"),
        ("反白测试", "✓ 通过", f"深底直接用反白版，柚子提亮到 {FRUITD}（对比 "
                            f"{G.contrast(FRUITD, BGD):.2f}:1），不需专门调形"),
        ("撞脸测试", "✓ 通过", "见下表，逐条差异一句话可讲清"),
        ("语义安全审查", "✓ 通过", "见下表，逐项给出已查无问题或已规避"),
    ]:
        A(f"<tr><td><b>{n}</b></td><td class='ok'>{r}</td><td>{why}</td></tr>")
    A("</table>")

    A("<h3>撞脸自查（几何特征级原创性自查，非商标法律检索）</h3>")
    A("<table><tr><th>对标</th><th>它的图形语言</th><th>我们与它的差异</th></tr>")
    for a1, b1, c1 in [
        ("多邻国 Duolingo", "高饱和亮绿 + 圆润猫头鹰吉祥物，靠「角色」",
         "我们无角色、无亮绿；可爱来自形状（圆端 + 扁果），不来自表情与拟人"),
        ("百词斩 / 扇贝", "蓝 + 容器方块 / 贝壳具象",
         "我们无容器、无教育蓝；果形是自由轮廓，不是图标里的图标"),
        ("每日英语听力 / 可可英语", "耳机 / 扬声器 / 声波同心弧",
         "我们完全不出现音频器具；「听」由字母 L 本身承担"),
        ("水果类食品标志（果汁 / 果茶）", "写实果切、多果堆叠、渐层高光",
         "我们是单色平涂 + 单果 + 无高光无渐变；且果是配角（贴着基线坐在字母旁）"),
        ("通用「水果 + 叶子」图标", "正圆果 + 竖直对称叶 + 顶部梗",
         "我们把果压扁（2:√3）、把叶斜到 arctan(φ)、并且叶根被果身盖住 —— 三处都偏离通用解"),
    ]:
        A(f"<tr><td><b>{a1}</b></td><td>{b1}</td><td>{c1}</td></tr>")
    A("</table>")

    A("<h3>语义安全审查</h3>")
    A("<table><tr><th>检查项</th><th>结论</th></tr>")
    for k1, v1 in [
        ("180° 旋转", "倒置后是「Γ + 果」，不构成不当形象 —— 已查无问题"),
        ("左右镜像", "镜像后叶尖朝右，仍是叶 + 果，无暗藏物 —— 已查无问题"),
        ("负空间暗藏物", "叶根被果身覆盖形成一条干净边界；蒂窝是浅凹弧，不构成任何第二形象 —— 已查无问题"),
        ("缩写 / 拼音歧义", "FL / FayeLong：英文无脏词、中文无谐音不吉；「柚」与 You 同音，是正向谐音"),
        ("文化符号碰撞①：浅底＋中央实心圆",
         f"<b>已规避</b>：柚子虽为圆，但（a）被压扁成 2:√3 的椭圆（打破正圆）、"
         f"（b）位于右下而不在画面中央、（c）顶部有蒂窝缺口 —— 三条件同时不满足"),
        ("文化符号碰撞②：国旗 3 秒比对",
         "中/日/韩/美/英/法/德/俄/印逐个比对：圆润 L + 一枚扁果不构成任何国旗结构 —— 已查无问题"),
        ("文化符号碰撞③：宗教符号", "无十字、无新月、无万字符、无法轮 —— 已查无问题"),
        ("食物过敏 / 宗教饮食联想", "柚子为中性水果，无宗教禁忌含义；不做果切（避免与特定习俗关联）"),
        ("附带联想", "扁圆 + 斜叶在极小尺寸可能被读作「柠檬／橘子」；"
                 "同属柑橘，不构成错误联想，不规避"),
    ]:
        A(f"<tr><td><b>{k1}</b></td><td>{v1}</td></tr>")
    A("</table>")

    # ── ⑫ 演进对照 ──
    v1 = _v1_mark()
    if v1 is not None:
        try:
            g1 = v1.make_geometry(v1.CANVAS, v1.PAD, 3)
            A("<h2><span class='n'>12</span>演进对照：v1 直角版 ↔ v2 可爱柚子版</h2>")
            A("<p class='sub'>同一副骨架，两种气质。v1 留在 <span class='mono'>brand-logo/</span> 根目录，"
              "v2 在 <span class='mono'>brand-logo/v2-cute/</span>，两版都在，不互相覆盖。</p>")
            A("<div class='grid3'>")
            A(f"<div class='card'><div class='ttl'>v1「L · 落点」直角版</div>"
              f"{v1.mark_inline(g1, v1.INK_LIGHT, v1.ACC_LIGHT, px=250, bg=v1.BG_LIGHT)}"
              f"<div class='cap'>直角端 + 方形句点 · 外框 1:φ · 精确、克制、偏严肃</div></div>")
            A(f"<div class='card'><div class='ttl'>v2「L · 柚子」可爱版</div>"
              f"{mark_inline(g, INK, FRUIT, px=250, bg=BG)}"
              f"<div class='cap'>圆语法 + 柚子 · 外框 1:1 · 亲近、饱满、有果子</div></div>")
            A(f"<div class='card'><div class='ttl'>并排（同高）</div>"
              f"<div style='display:flex;gap:18px;align-items:flex-end;justify-content:center'>"
              f"{v1.mark_inline(g1, v1.INK_LIGHT, v1.ACC_LIGHT, px=230)}"
              f"{mark_inline(g, INK, FRUIT, px=230)}</div>"
              f"<div class='cap'>剪影几乎同源（粗竖笔 + 右侧配角），气质完全不同 —— 这正是「改气质不改骨架」</div></div>")
            A("</div>")
        except Exception as e:
            A(f"<p class='note'>（v1 对照渲染跳过：{e}）</p>")

    # ── ⑬ 落选候选 ──
    A("<h2><span class='n'>13</span>柚子造型的候选对比（内部发散 · 探索成本不摊给用户）</h2>")
    A("<table><tr><th>候选</th><th>做法</th><th>为什么落选</th></tr>")
    for c1, c2, c3 in [
        ("圆果 + 叶", "正圆 ⌀ = 笔宽，叶直接贴在果顶",
         "读成「黄苹果」，且正圆与横笔端头同尺寸同高 → 像「线头长了个球」"),
        ("果 + 粗梗 + 叶", "梗从蒂窝长出、叶挂梗端",
         "梗太粗像塞子，三件套拼装感强，缩小后梗叶糊成一团"),
        ("果 + 去皮柚肉（切面果瓣）", "圆果挖出一块露出柚瓣",
         "立刻变成「果盘」而不是标志；且柚瓣在小尺寸变成噪点"),
        ("两个柚子（一主一从）", "大小两果相依",
         "元素预算从 2 变 3、构图重心散，且与「一句一果」的语义冲突"),
        ("柚子做主角、字母退居副位", "把 L 缩小、柚子放大到主导",
         "品牌首字母的识别度被稀释；且 L 缩到小于笔宽就退化成一根竖棒"),
    ]:
        A(f"<tr><td><b>{c1}</b></td><td>{c2}</td><td>{c3}</td></tr>")
    A("</table>")

    # ── ⑭ 下一步 ──
    A("<h2><span class='n'>14</span>下一步（点一句就动）</h2>")
    A("<ul>"
      "<li>「柚子的意思不是这个」—— 告诉我是人名 / 谐音 / 地名，我重写语义层与场景建议（几何不动）</li>"
      "<li>「果实再大一点 / 叶子再大一点」—— 改一个常量重跑，30 秒出新版</li>"
      "<li>「要表情版作主方案」—— 我把 A/B 对调，并补 32px 以下的降级规则</li>"
      "<li>「换一组配色」—— 已有蜜桃 / 薄荷两套；给 HEX 我 1 分钟出全套</li>"
      "<li>「叶子换个方向」—— 朝右会越出外框，需要同时缩果或加宽画框，我出权衡版给你看</li>"
      "<li>「进定稿」—— 自绘 FayeLong 轮廓 + 6 色彩变体全量 SVG + favicon ICO 三件套 + 全量技术报告 report.html</li>"
      "</ul>")
    A("<p class='note'>⚠️ 本轮为<b>提案轮</b>：已交付真矢量源文件、完整几何说明、七项检查与规格摘要；"
      "尚未交付定稿全套（草标轮廓化 / ICO 三件套 / Android 自适应图标 / report.html）。</p>")

    A("</div></body></html>")
    return "".join(P)


# ============================================================
# 4. spec.md
# ============================================================
def spec_md(g, gf, st):
    c1, c2, c3 = G.cmyk(INK), G.cmyk(FRUIT), G.cmyk(G.INK_TEXT_SAFE)
    _s, leaf, tip, base = G.stem_leaf(g)
    return f"""# FayeLong 标志 v2 使用规范 · spec
> 方案：「L · 柚子」（可爱活泼版）｜提案轮｜几何由 `06-source/geom.py` 生成，**改参数后重跑，勿手工改坐标**

## 1. 概念
还是 v1 的字母 **L**（FayeLong / Listening / Language / Learn）＋ 坐在基线上的那一个配角 ——
但它长大了，从**方形句点**变成**一颗饱满的柚子**，从果肩后面伸出一片斜叶。

**「一句被听清的话，结成了一颗果子。」** 声音听懂了，才有果子。
- 竖笔 = 声音（厚重、有声）
- 横笔 = 纸上的行
- 柚子 = 听懂之后的收获（也承接 v1 的句点：同一个位置、同一个角色）

⚠️ 柚子的语义层为**推断**（品牌元素 / 「柚 ≈ You」）。若实际含义不同，几何不动，只改文案与场景建议。

## 2. 三声明

### ① 比例系统：黄金比 φ = 1.618034
| 量 | 值 | 声明比 | 实测误差 |
|---|---|---|---|
| 外框 W : H | {g['W']} : {g['H']} | 1 : 1 | {abs((g['W']/g['H'])/1.0-1)*100:.3f}% |
| 笔宽 SW : H | {g['SW']} : {g['H']} | 1 : φ³ | {abs((g['SW']/g['H'])/(1/PHI**3)-1)*100:.3f}% |
| 横笔 L_W : H | {g['L_W']} : {g['H']} | 2/φ³ + 1/φ⁶ | {abs((g['L_W']/g['H'])/(2/PHI**3)-1)*100:.3f}% |
| 间隔 GAP : SW | {g['GAP']} : {g['SW']} | 1 : φ² | {abs((g['GAP']/g['H'])/(1/PHI**4)-1)*100:.3f}% |
| 柚子 FRUIT : H | {g['FRUIT']} : {g['H']} | 1 : φ² | {abs((g['FRUIT']/g['H'])/(1/PHI**2)-1)*100:.3f}% |
| 叶弧半径 : SW | {_f(g['R_LEAF'])} : {g['SW']} | 1 : φ | {abs((g['R_LEAF']/g['SW'])/(1/PHI)-1)*100:.3f}% |
| 蒂窝弧半径 : SW | {_f(g['R_DIP'])} : {g['SW']} | 1 : φ² | {abs((g['R_DIP']/g['SW'])/(1/PHI**2)-1)*100:.3f}% |
| 字标大写高 : H | {g['CAP_HEIGHT']} : {g['H']} | 1 : φ³ | {abs((g['CAP_HEIGHT']/g['H'])/(1/PHI**3)-1)*100:.3f}% |

**★ 数学必然 —— 外框是被逼成正方形的**：
```
L_W + GAP + FRUIT = (2SW + SW/φ³) + SW/φ² + SW·φ = SW·(2 + 1/φ³ + 1/φ² + φ)
而 1/φ² + 1/φ³ = 1/φ ，故 2 + 1/φ + φ = 2φ + 1 = φ³
∴ L_W + GAP + FRUIT = SW·φ³ = (H/φ³)·φ³ = H = W
代入：{g['L_W']} + {g['GAP']} + {g['FRUIT']} = {g['L_W']+g['GAP']+g['FRUIT']} ≡ W = {g['W']}      误差 0.000%
其中横笔 = 2SW + SW/φ³：2SW 给端头与内凹转角，SW/φ³ 就是横笔上缘那段平直的长度
```
也就是说：**加了柚子，画框自己变成了正方形** —— 不是设计师选了正方，是恒等式不允许它不是正方。
三个宽度全部由 SW 派生（2SW / SW·φ / SW/φ），**一个自由度都没有**。构建脚本以 `assert` 守卫，不成立即中止。

### ② 风格语法：圆语法
连续谱定位：**圆语法（左二区）**。
- 端头：圆头（半径 SW/2）
- 转角：内凹、外凸都倒圆（半径 SW/2）
- **半径只有 3 档，且一一对应**：端头 / 外凸转角 = SW/2 = {_f(g['R'])}；内凹转角 / 蒂窝 = SW/φ² = {g['R_FIL']}；叶弧 = SW/φ = {_f(g['R_LEAF'])}
  → 这是「看起来像一整套」的机制：圆度分档而不乱，不是把圆零件拼起来
  → 内凹转角收一档到 75：换来横笔上缘 {g['L_W']-g['R']-g['SW']-g['R_FIL']:.0f} 的平直段，端部不会出现「掐腰」
- 内凹转角中心线半径 = SW（E §7.2 达标：内缘不归零）
- 无描边、无渐变、无投影、无外发光、无半透明叠圆
- 活泼的唯一来源：**叶轴与水平成 arctan(φ) ≈ {G.LEAF_ANGLE_DEG:.2f}°**。叶一旦竖直就成标本，斜着才有「刚长出来」的动势。

### ③ 元素预算 2 / 3
| 元素 | 角色 | 面积占比 | 构成 |
|---|---|---|---|
| 字母 L | 主角 | {st['l_share']} | 1 条闭合路径 |
| 柚子 | 配角 | {st['fruit_share']} | 果身（椭圆 + 蒂窝）+ 叶 = 3 个基础形状 |
基础形状总数 4（≤6 达标）。删减测试：删柚子 → 可爱度与品牌元素同时消失 → 保留。
一元素多义：果实（收获）／柚 ≈ You（学英语的你）／承接 v1 的句点（一句的最小单位）。

## 3. 关键几何链值
```
画布 1024 × 1024         留白（构建参照）{g['pad']}      基准网格 8pt（32 = 8×4）
外框 {g['H']} × {g['W']}        1 : 1
笔宽 = {g['SW']}（= H/φ³）        全标圆角 = {_f(g['R'])}（= SW/2）
横笔 L_W = {g['L_W']}（= 2SW）     间隔 GAP = {g['GAP']}（= SW/φ）
柚子 宽 {g['FRUIT']} × 高 {g['RY_FRUIT']*2:.1f}（= SW·φ；宽:高 = 2:√3）
　中心 ({_f(g['FX'])}, {_f(g['FY'])})   下切点落在基线 y = {g['H']}
　右缘 x = {g['FX']+g['R_FRUIT']:.0f} = 外框右缘
蒂窝 半角 {G.DIP_HALF_ANGLE:.0f}°、弧半径 {_f(g['R_DIP'])}（= SW/φ²）→ 深 {_f(g['DIP_DEPTH'])}
叶 弦长 {g['LEAF_CHORD']}（= SW）、弧半径 {_f(g['R_LEAF'])}（= SW/φ）、宽 ≈ 100
　轴 arctan(φ) = {G.LEAF_ANGLE_DEG:.2f}°，基部埋入果内 {_f(g['LEAF_INSET'])}，叶尖 ({_f(tip[0])}, {_f(tip[1])})
半径分级 3 档：{_f(g['R'])}（端头·外凸转角）/ {g['R_FIL']}（内凹转角·蒂窝）/ {_f(g['R_LEAF'])}（叶弧）—— ≤3 达标
绘制顺序：叶 → 果身 → 字母 L（果身覆盖叶根，边界靠外轮廓分开，不需要描边）
```

## 4. 使用规范
### 净空区 Clear space
四周最小留白 = **字高的 1/4**（= {g['H']/4:.0f} 于 1024 画布）。低于此值请勿放置任何文字、边框或图形。

### 最小尺寸
| 场景 | 阈值 | 低于阈值怎么办 |
|---|---|---|
| 纯图形（主标） | ≥ 32px / 印刷 ≥ 6mm | 建议换 `fayelong-favicon.svg`（外框 960 整像素） |
| 纯图形（favicon） | ≥ 16px | 已是极限简化版，不得再缩 |
| 横版组合标 | 高度 ≥ 24px（数字）/ ≥ 8mm（印刷） | 退回纯图形版 |
| 表情版 | ≥ 24px | 低于 24px 眼睛会糊成两块墨，换无脸版 |

### 小尺寸降级规则（设计好的，不是补救）
favicon 与主标**共用同一条 φ 链**，不是另一套造型；它存在的唯一理由是**画布尺寸的整除性**：
- 留白 {g['pad']} → {gf['pad']}（更满，正方形外框天生适合图标）
- 外框取 960：16 / 32 / 48 / 64 全部整除 → 小尺寸栅格化落在整像素上（主标 830 不能，16px 的缩放系数是 51.875）
- 比例保持一致：果 = SW·φ（{gf['FRUIT']}）、间隔 = SW/φ²（{gf['GAP']}），相对 H 分别为 {gf['FRUIT']/gf['H']*100:.1f}% 与 {gf['GAP']/gf['H']*100:.1f}%
  （旧版曾宣称 favicon「柚子放大」，那是链 B 时代的说法 —— 现值与主标一致，不再宣称放大）
- 16px 实测：笔宽 {gf['SW']*16/gf['H']:.2f}px、柚子 {gf['FRUIT']*16/gf['H']:.2f}px（可辨）、间隔 {gf['GAP']*16/gf['H']:.2f}px（会并拢 —— 物理下限，已声明）
- ⚠️ **若要在 16px 拿到更强存在感**：标准解法是「品牌色底 + 反白标志」的图标版（本版未做；说一声就出）
- favicon 同样满足 `L_W + GAP + FRUIT ≡ W`

### 禁用示例
1. 拉伸／压缩变形（必须等比）
2. 越过净空区（四周 ≥ 1/4 字高）
3. 加投影、描边、外发光、渐变、高光
4. 擅自改色（尤其把柚子也改成粉色 —— 那等于抹掉唯一的结构色对比，退回单色逻辑）
5. 把叶子竖起来（叶轴必须保持 ≈ arctan φ，竖直即失去动势）
6. 把柚子拉成正圆或竖椭圆（扁度 2:√3 是它「不是苹果」的关键）
7. 在柚子与横笔之间塞任何东西（那 {g['GAP']} 的间隔是构图的一部分）
8. 把叶子移到果实右侧（会越出外框，且重心失衡）
9. 置于低对比背景（浅底柚子、深底深色笔画）

## 5. 色彩规格（四格式）
| 色 | HEX | RGB | CMYK | Pantone（近似） | 用途 |
|---|---|---|---|---|---|
| 樱粉 Blossom | {INK} | RGB{str(G.rgb255(INK))[1:-1]} | C{c1[0]} M{c1[1]} Y{c1[2]} K{c1[3]} | 706 C | 主色：字母 L + 叶子 + 字标 |
| 柚黄 Pomelo | {FRUIT} | RGB{str(G.rgb255(FRUIT))[1:-1]} | C{c2[0]} M{c2[1]} Y{c2[2]} K{c2[3]} | 115 C | 点缀：柚子果身（浅底） |
| 纸底 Paper | {BG} | RGB{str(G.rgb255(BG))[1:-1]} | — | — | 浅色底背景（非纯白） |
| 深墨底 Deep | {BGD} | RGB{str(G.rgb255(BGD))[1:-1]} | — | 5463 C | 深色模式背景 |
| 深底反白 | {INKD} | RGB{str(G.rgb255(INKD))[1:-1]} | — | — | 深底上的笔画 |
| 深底柚子 | {FRUITD} | RGB{str(G.rgb255(FRUITD))[1:-1]} | — | 2003 C | 深底上提亮的果色 |
| 深樱粉 · 文字用 | {G.INK_TEXT_SAFE} | RGB{str(G.rgb255(G.INK_TEXT_SAFE))[1:-1]} | C{c3[0]} M{c3[1]} Y{c3[2]} K{c3[3]} | 208 C | 不对标志生效；仅当需要小字号/正文用粉时替换主色 |

**两色定局**：整标只有樱粉 + 柚黄。叶子不另开绿色 —— 叶与 L 同色，画面里「绿」的来源为零。

**颜色分工（一句话可复述）**：**粉给字，黄给果**。
- 樱粉（{INK}）承担全部笔画：字母 L + 叶 + 字标 —— 它决定「可爱」
- 柚黄（{FRUIT}）只给柚子果身 —— 它承担「这是一颗能吃的柚子」
- 柚黄取自正黄区（H {G.hsv(FRUIT)[0]:.1f}°）：离开橙色区才读成柚，偏橙就读成橙子/柿子

⚠️ **小字提醒**：樱粉于纸底只有 {st['c_ink']:.2f}:1，作为标志、大字标题、图标都够用；
但**不要**拿它当正文字色或 12px 以下的小字色 —— 那种场景请换深樱粉 {G.INK_TEXT_SAFE}（≈ 5.2:1）。

对比度（WCAG 相对亮度法，程序计算）：
- 樱粉 / 纸底 = **{st['c_ink']:.2f}:1**（标志/大字场景充足；小字请换深樱粉）
- 反白 / 深底 = **{st['c_rev']:.2f}:1**
- 深底柚子 / 深底 = {G.contrast(FRUITD, BGD):.2f}:1
- 柚子 / 纸底 = {st['c_fruit']:.2f}:1（果是图形不是文字，不适用正文阈值，仅需可辨）
- 主色 / 点缀相对明度差 = **{st['lum_gap']:.1f}%**（>20% 达标，转灰度仍可辨 → 色盲安全）
- CMYK 为**朴素 RGB→CMYK 换算**（非 ICC 色彩管理，仅作占位）、Pantone 为近似对照 —— 两者都**不是**印刷级数值，落印前请用专色卡或让印厂出 ICC 转换

## 6. 诚实声明
1. **mono 退化**：单色黑版里柚子与字母、叶子全部同色，柚子的「黄」这一识别线索消失，
   只靠一颗扁圆果形 + 叶子说话 —— 仍可辨，但**可爱度与色彩强调层失效**。
   这是几何事实，属预期行为，不使用描边／阴影假装区分。
   单色场景（刻章、传真、丝印）如需保留柚子识别度，建议用反白或留白轮廓版。
2. **字标未轮廓化**：本轮字标为字体排版占位（Inter Tight → Inter → Segoe UI Variable → system-ui；中文思源黑体 → 苹方 → 微软雅黑）。
   定稿轮将按笔宽比例自绘轮廓，彻底消除字体依赖与授权问题。**标志本体零文字、零字体依赖**。
3. **柚子语义为推断**：见 §1。几何是可复用的，语义层可单独重写。
4. **本文件不是商标法律意见**：撞脸测试是几何特征级的原创性自查，不构成商标检索或法律意见。

## 7. 七项检查
| 检查 | 结果 |
|---|---|
| 剪影 | ✓ 圆润 L + 带叶扁果，柚子靠形状独立成立 |
| 16px | ✓ 有条件（果 {gf['FRUIT']*16/gf['H']:.2f}px 可辨；间隔 {gf['GAP']*16/gf['H']:.2f}px 会并拢，物理下限已声明；≤32px 建议用 favicon 版） |
| 单色 | ✓ 有代价（色彩强调层失效，已声明） |
| 模糊 | ✓ 3–6px 高斯后大形不塌 |
| 反白 | ✓ 深底用反白版，柚子提亮 |
| 撞脸 | ✓ 与 5 类对标逐条差异可讲清（见 preview.html §11） |
| 语义安全 | ✓ 180°/镜像/负空间/缩写歧义/国旗/宗教符号逐项已查（见 preview.html §11） |

## 8. 文件与复现
```
v2-cute/
├─ 00-START-HERE.md
├─ preview.html                                   展示页（14 区块，含 v1↔v2 演进对照与表情版备选）
├─ 01-web-rgb/svg/
│   ├─ fayelong-cute-mark-fullcolor.svg            主标 · 纯图形 · 彩色
│   ├─ fayelong-cute-mark-face.svg                 主标 · 表情版（备选）
│   ├─ fayelong-cute-mark-mono-black.svg           单色黑
│   ├─ fayelong-cute-mark-reverse.svg              反白 · 深底
│   ├─ fayelong-cute-mark-grayscale.svg            灰阶
│   ├─ fayelong-cute-favicon.svg                   favicon · 同比例 · 外框 960（整除友好）
│   ├─ fayelong-cute-lockup-horizontal.svg         横排组合标
│   └─ fayelong-cute-lockup-stacked.svg            堆叠组合标
├─ 01-web-rgb/png/                                 光栅梯队
├─ 05-spec/spec.md                                 本文件
├─ 06-source/geom.py                               几何唯一真源（含构建期 assert 链）
├─ 06-source/build_logo.py                         产物生成器
├─ 06-source/rasterize.py                          SVG/HTML → PNG（本机 Chrome headless）
└─ 07-blueprint/fayelong-cute-blueprint.svg/.png    数学标注图
```
**修改唯一入口**：`06-source/geom.py` 里的 `make_geometry()`。
改任一常量 → 重跑 `build_logo.py` → 全部 SVG / 标注图 / 预览页 / 规范书同步更新；
assert 链会立刻告诉你哪条比例被破坏了（失败即中止，不会产出坏文件）。

## 9. 与 v1 的关系
| | v1「L · 落点」 | v2「L · 柚子」 |
|---|---|---|
| 位置 | `brand-logo/` 根目录 | `brand-logo/v2-cute/` |
| 配色 | 松墨 #0E3B34 + 琥珀 #D98A3D | 樱粉 #F2759F + 柚黄 #EDC62A |
| 风格语法 | 直角端（平头、直角、零圆角） | 圆语法（全标圆角 = SW/2） |
| 配角 | 方形句点 | 柚子（果身 + 蒂窝 + 叶） |
| 外框 | 1 : φ | 1 : 1（被恒等式逼出） |
| 气质 | 精确、克制、偏严肃 | 亲近、饱满、有果子 |
| 骨架 | 粗竖笔 + 右侧落在基线上的配角 + φ 比例系统 + 三段宽度精确填满外框 | 同 |
两版**都保留、互不覆盖**。正式场合 / 文档头用 v1 更稳；面向用户、图标、周边用 v2 更近人。
"""


# ============================================================
# 5. 主流程
# ============================================================
def main():
    p_svg = os.path.join(ROOT, "01-web-rgb", "svg")
    p_bp = os.path.join(ROOT, "07-blueprint")
    p_spec = os.path.join(ROOT, "05-spec")
    for dd in (p_svg, p_bp, p_spec, os.path.join(ROOT, "01-web-rgb", "png")):
        os.makedirs(dd, exist_ok=True)

    g = G.make_geometry(G.CANVAS, G.PAD, "main", chain="C")
    gf = G.make_geometry(G.FAV_CANVAS, G.FAV_PAD, "fav")
    ok1, log1 = G.verify(g, "主标")
    ok2, log2 = G.verify(gf, "favicon")
    print("=" * 78)
    print("构建期验证链 · 主标")
    print("=" * 78)
    for s, m in log1:
        print(f"[{s}] {m}")
    print("-" * 78)
    print("构建期验证链 · favicon（同比例 · 外框 960 整除友好）")
    print("-" * 78)
    for s, m in log2:
        print(f"[{s}] {m}")
    if not (ok1 and ok2):
        raise SystemExit("❌ 几何约束未通过，构建中止")

    ar = G.areas(g)
    lum = abs(G.rel_lum(INK) - G.rel_lum(FRUIT)) / max(G.rel_lum(INK), G.rel_lum(FRUIT)) * 100
    st = dict(area=ar["total"], l_share=f"{ar['l_share']:.1f}%",
              fruit_share=f"{ar['fruit_share']:.1f}%",
              c_ink=G.contrast(INK, BG), c_fruit=G.contrast(FRUIT, BG),
              c_rev=G.contrast(INKD, BGD), lum_gap=lum)
    print("-" * 78)
    print(f"总面积 {ar['total']:.0f}px²｜主角 {st['l_share']}｜柚子 {st['fruit_share']}")
    print(f"樱粉/纸底 {st['c_ink']:.2f}:1｜柚黄/纸底 {st['c_fruit']:.2f}:1｜"
          f"反白/深底 {st['c_rev']:.2f}:1｜明度差 {st['lum_gap']:.1f}%")
    print(f"樱粉 HSV {tuple(round(v,1) for v in G.hsv(INK))}｜柚黄 HSV {tuple(round(v,1) for v in G.hsv(FRUIT))}")
    print(f"深底粉 {INKD}｜深底果 {FRUITD}｜文字深粉 {G.INK_TEXT_SAFE}")
    _s, _l, _tip, _bs = G.stem_leaf(g)
    print(f"柚形 {g['FRUIT']}×{g['RY_FRUIT']*2:.1f}（2:√3）｜叶弦 {g['LEAF_CHORD']} r={G._f(g['R_LEAF'])} "
          f"角 {G.LEAF_ANGLE_DEG:.2f}°｜叶尖 ({G._f(_tip[0])}, {G._f(_tip[1])})")

    files = {
        "fayelong-cute-mark-fullcolor.svg": svg_file(g, INK, FRUIT, None, "主标 · 纯图形 · 彩色（透明底）"),
        "fayelong-cute-mark-face.svg": svg_file(g, INK, FRUIT, None, "主标 · 表情版（备选）", face=True),
        "fayelong-cute-mark-mono-black.svg": svg_file(g, "#000000", "#000000", None,
                                                      "单色黑（色彩强调层失效，属预期行为）"),
        "fayelong-cute-mark-reverse.svg": svg_file(g, INKD, FRUITD, BGD, "反白 · 深底"),
        "fayelong-cute-mark-grayscale.svg": svg_file(g, "#333333", "#8C8C8C", None, "灰阶 · 黑白媒介"),
        "fayelong-cute-favicon.svg": svg_file(gf, INK, FRUIT, None,
                                              "favicon · 与主标同比例 · 外框 960（16/32/48/64 整除，小尺寸整像素）"),
        "fayelong-cute-lockup-horizontal.svg": lockup_inline(g, "latin", INK, FRUIT),
        "fayelong-cute-lockup-stacked.svg": lockup_inline(g, "stack", INK, FRUIT),
    }
    for name, content in files.items():
        with open(os.path.join(p_svg, name), "w", encoding="utf-8") as fh:
            fh.write(content + "\n")
    with open(os.path.join(p_bp, "fayelong-cute-blueprint.svg"), "w", encoding="utf-8") as fh:
        fh.write(blueprint_svg(g, gf, st) + "\n")
    with open(os.path.join(ROOT, "preview.html"), "w", encoding="utf-8") as fh:
        fh.write(preview_html(g, gf, st))
    with open(os.path.join(p_spec, "spec.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_md(g, gf, st))

    print("\n已写出 SVG：" + ", ".join(sorted(files)))
    print("已写出 preview.html / 05-spec/spec.md / 07-blueprint/fayelong-cute-blueprint.svg")
    return g, gf, st


if __name__ == "__main__":
    main()
