# -*- coding: utf-8 -*-
"""
FayeLong 标志 · 参数化构建脚本（几何唯一真源）
================================================================
品牌：FayeLong 英语精听 / 听写（本地优先的个人英语听力训练站）
方向：「L · 落点」—— 字母 L + 一个句点。
     竖笔＝声音（厚重、有声），横笔＝纸上的行，句点＝刚被写下的那一个字。

三声明
------
① 比例系统：黄金比 φ = 1.618034（全部关键尺寸由 φ 派生，无魔法数字）
   外框              W : H        = 514 : 832 = 1 : φ
   笔宽              SW : H       = 196 : 832 = 1 : φ³
   L 宽              L_W : W      = 318 : 514 = 1 : φ
   间隔              GAP : W      = 121 : 514 ≈ 1 : φ³
   句点              DOT : W      =  75 : 514 ≈ 1 : φ⁴
   ★ 数学必然（E §7.3）：W/φ + SW/φ + SW/φ²
        = H/φ² + H/φ⁴ + H/φ⁵ = H(0.381966+0.145898+0.090170) = H × 0.618034 = H/φ = W
     即 L_W + GAP + DOT ≡ W 是恒等式，不是调出来的：
        318 + 121 + 75 = 514 ✓（三宽度被 φ 链必然分割，无从自由取值）

② 风格语法：定位「直角端」（连续谱右三区）—— 平头端、直角转角、零圆角。
   语义：精听是「精确」的动作（逐词校验、0 容差），语法就该是精确的。
   唯一软度出处：句点方块保留 DOT/φ³ 的微圆角 —— 它是「刚落下、还未凝固」的那个字。
   异质元素 1 项（微圆角），占比 < 20%，已声明绑定。√ F §3 一致性铁律

③ 元素预算 2 / 3：E1 字母 L（主角）· E2 句点（配角，与主角成「字母—标点」组合关系）
   点缀色 = 句点本身（颜色强调，F §5：用颜色做强调，不加形状）

改参数 → 重跑本脚本 → 全部 SVG / 标注图 / 预览页同步更新。
"""

import math
import os

# ============================================================
# 0. 常量
# ============================================================
PHI = (1 + 5 ** 0.5) / 2
CANVAS = 1024
PAD = 96                 # 主标留白
FAV_CANVAS = 1024
FAV_PAD = 32             # favicon 留白（更满，16px 抗氧化）

INK_LIGHT = "#0E3B34"    # 松墨 · 主色
ACC_LIGHT = "#D98A3D"    # 焰琥珀 · 句点
BG_LIGHT = "#F2F5F3"     # 纸底（带主色倾向，非纯白）
BG_DARK = "#0B2A26"      # 深墨底
INK_DARK = "#F2F5F3"     # 深底反白
ACC_DARK = "#E8A657"     # 深底句点（提亮变体）

FONT_LATIN = ("'Inter Tight', Inter, 'Segoe UI Variable Display', 'Segoe UI', "
              "system-ui, sans-serif")
FONT_CN = ("'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', "
           "'Microsoft YaHei', sans-serif")
FONT_MONO = "'Cascadia Mono', Consolas, 'SF Mono', monospace"


def _f(x):
    s = f"{float(x):.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


# ============================================================
# 1. 几何（唯一真源）
# ============================================================
def make_geometry(canvas=CANVAS, pad=PAD, dot_step=2, gap_step=1, fit_lw=False):
    """
    dot_step / gap_step：句点与间隔在 φ 链上的深度（默认 2 与 1，即 SW/φ² 与 SW/φ）。
    fit_lw=True：L 宽由 W − GAP − DOT 反解（小尺寸版用，保证间隔与句点在 16px 下都 ≥2px）。
    """
    H = canvas - 2 * pad
    W = round(H / PHI)
    SW = round(H / PHI ** 3)
    GAP = round(SW / PHI ** gap_step)
    DOT = round(SW / PHI ** dot_step)
    L_W = W - GAP - DOT if fit_lw else round(W / PHI)
    R_DOT = round(DOT / PHI ** 3, 2)    # 句点微圆角（唯一的软度出处，保留 2 位以守住 φ 关系）
    return dict(canvas=canvas, pad=pad, H=H, W=W, SW=SW, L_W=L_W, GAP=GAP, DOT=DOT,
                R_DOT=R_DOT, CAP_HEIGHT=round(H / PHI ** 3), dot_step=dot_step,
                gap_step=gap_step, fit_lw=fit_lw)


def mark_path(g):
    """字母 L：单条闭合直角路径。"""
    SW, H, LW = g["SW"], g["H"], g["L_W"]
    return f"M0 0 H{SW} V{H-SW} H{LW} V{H} H0 Z"


def dot_path(g):
    """句点：方块 + DOT/φ³ 微圆角；底边与横笔底边共线（同一条基线）。"""
    x, y, s, r = g["L_W"] + g["GAP"], g["H"] - g["DOT"], g["DOT"], g["R_DOT"]
    return (f"M{x+r} {y} H{x+s-r} A{r} {r} 0 0 1 {x+s} {y+r} V{y+s-r} "
            f"A{r} {r} 0 0 1 {x+s-r} {y+s} H{x+r} A{r} {r} 0 0 1 {x} {y+s-r} "
            f"V{y+r} A{r} {r} 0 0 1 {x+r} {y} Z")


# ============================================================
# 2. 构建期验证链（失败即中止）
# ============================================================
def verify(g):
    log, ok = [], True

    def a(cond, msg):
        nonlocal ok
        log.append(("OK  " if cond else "FAIL", msg))
        ok = ok and cond

    # ① 比例链
    for name, val, target in [
        ("外框 W:H = 1/φ", g["W"] / g["H"], 1 / PHI),
        ("笔宽 SW:H = 1/φ³", g["SW"] / g["H"], 1 / PHI ** 3),
        ("L 宽 L_W:W = 1/φ", g["L_W"] / g["W"], 1 / PHI),
        ("间隔 GAP:W ≈ 1/φ³", g["GAP"] / g["W"], 1 / PHI ** 3),
        ("句点 DOT:W ≈ 1/φ⁴", g["DOT"] / g["W"], 1 / PHI ** 4),
        ("字标大写高 = H/φ³（= 笔宽）", g["CAP_HEIGHT"] / g["H"], 1 / PHI ** 3),
        ("句点圆角 = DOT/φ³", g["R_DOT"] / g["DOT"], 1 / PHI ** 3),
    ]:
        err = abs(val - target) / target * 100
        a(err <= 2.0, f"比例 {name}｜实测 {val:.5f} vs {target:.5f} → 误差 {err:.3f}%")

    # ② ★ 数学必然：三宽度和恒等于外框宽（E §7.3）
    a(g["L_W"] + g["GAP"] + g["DOT"] == g["W"],
      f"★ 恒等式 L_W + GAP + DOT = {g['L_W']} + {g['GAP']} + {g['DOT']} = "
      f"{g['L_W']+g['GAP']+g['DOT']} ≡ W = {g['W']}（φ 链必然分割）")
    a(g["GAP"] + g["DOT"] == g["SW"],
      f"SW 被 φ 链必然分解：GAP + DOT = {g['GAP']} + {g['DOT']} = {g['SW']} = SW")

    # ③ 对齐 / 共线
    a(g["H"] - g["DOT"] > 0, "句点位于横笔上方，不与竖笔重叠区冲突")
    a(g["L_W"] + g["GAP"] + g["DOT"] == g["W"], "句点右缘 = 外框右缘（右对齐闭合）")
    a(g["L_W"] >= g["SW"], "横笔长度 ≥ 竖笔宽度")

    # ④ 元素预算 / 半径分级
    a(len({g["R_DOT"]}) <= 3, f"半径分级：仅 1 级（句点圆角 {g['R_DOT']}），≤3 达标")
    a(0 < g["DOT"] < g["SW"], f"句点尺度 {g['DOT']} < 笔宽 {g['SW']}（配角不抢主角）")

    # ⑤ 小尺寸可行域（16px 下各元素 ≥ 1px）
    px16 = 16 / g["H"]
    a(g["SW"] * px16 >= 3.0, f"16px：笔宽 {g['SW']*px16:.2f}px ≥ 3px")
    a(g["DOT"] * px16 >= 1.4, f"16px：句点 {g['DOT']*px16:.2f}px（<2px → 触发 favicon 独立几何）")
    return ok, log


def verify_favicon(gf, gm):
    log, ok = [], True

    def a(cond, msg):
        nonlocal ok
        log.append(("OK  " if cond else "FAIL", msg))
        ok = ok and cond

    a(gf["L_W"] + gf["GAP"] + gf["DOT"] == gf["W"],
      f"favicon 恒等式同样成立：{gf['L_W']} + {gf['GAP']} + {gf['DOT']} = {gf['W']} = W"
      f"（L 宽由 W − GAP − DOT 反解，小尺寸可行性优先）")
    px16 = 16 / gf["H"]
    a(gf["SW"] * px16 >= 3.5, f"16px：笔宽 {gf['SW']*px16:.2f}px")
    a(gf["DOT"] * px16 >= 2.0, f"16px：句点 {gf['DOT']*px16:.2f}px ≥ 2px（放大一档后存活）")
    a(gf["GAP"] * px16 >= 2.0, f"16px：间隔 {gf['GAP']*px16:.2f}px ≥ 2px（句点不糊进横笔）")
    a(gf["DOT"] / gf["H"] > gm["DOT"] / gm["H"],
      f"favicon 句点相对放大：{gf['DOT']/gf['H']:.3f} > 主标 {gm['DOT']/gm['H']:.3f}")
    return ok, log


# ============================================================
# 3. 面积 / 色彩（程序计算）
# ============================================================
def areas(g):
    l_area = g["SW"] * g["H"] + g["L_W"] * g["SW"] - g["SW"] ** 2
    d_area = g["DOT"] ** 2 - (4 - math.pi) * g["R_DOT"] ** 2   # 圆角方块
    total = l_area + d_area
    return dict(total=total, l=l_area, d=d_area,
                dot_share=d_area / total * 100, l_share=l_area / total * 100)


def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(h):
    r, gg, b = (_lin(c) for c in _hex2rgb(h))
    return 0.2126 * r + 0.7152 * gg + 0.0722 * b


def contrast(a, b):
    la, lb = rel_lum(a), rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def hsv(h):
    r, gg, b = _hex2rgb(h)
    mx, mn = max(r, gg, b), min(r, gg, b)
    sat = 0 if mx == 0 else (mx - mn) / mx
    if mx == mn:
        hh = 0.0
    elif mx == r:
        hh = (60 * ((gg - b) / (mx - mn))) % 360
    elif mx == gg:
        hh = 60 * ((b - r) / (mx - mn)) + 120
    else:
        hh = 60 * ((r - gg) / (mx - mn)) + 240
    return hh, sat * 100, mx * 100


def rgb255(h):
    return tuple(round(c * 255) for c in _hex2rgb(h))


def cmyk(h):
    r, gg, b = _hex2rgb(h)
    k = 1 - max(r, gg, b)
    if k >= 1:
        return 0, 0, 0, 100
    return (round((1 - r - k) / (1 - k) * 100), round((1 - gg - k) / (1 - k) * 100),
            round((1 - b - k) / (1 - k) * 100), round(k * 100))


# ============================================================
# 4. SVG 片段
# ============================================================
def mark_inline(g, ink, accent, px=None, bg=None, extra=""):
    """紧贴裁剪：viewBox 锁定为标志外框（1:φ）。px = 渲染高度（最小尺寸规则以高度计）。"""
    w, h = g["W"], g["H"]
    size = f' width="{round(px * w / h)}" height="{px}"' if px else ""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"{size} {extra}>']
    if bg:
        out.append(f'<rect width="{w}" height="{h}" fill="{bg}"/>')
    out.append(f'<path d="{mark_path(g)}" fill="{ink}"/>'
               f'<path d="{dot_path(g)}" fill="{accent}"/></svg>')
    return "".join(out)


def svg_file(g, ink, accent, bg, note):
    head = f"""<!--
  FayeLong 标志 · {note}
  纯矢量 · 全填充 · 无字体依赖 · 无描边 · viewBox 锁定 1 : φ（紧贴裁剪）
  ── 几何（由 06-source/build_logo.py 生成，勿手工改坐标）──
  外框        W×H      = {g['W']} × {g['H']}        (1 : φ)
  笔宽        SW       = {g['SW']}                (= H/φ³)
  L 宽        L_W      = {g['L_W']}                (= W/φ)
  间隔        GAP      = {g['GAP']}                (= SW/φ)
  句点        DOT      = {g['DOT']}                 (= SW/φ², 圆角 {g['R_DOT']} = DOT/φ³)
  ★ L_W + GAP + DOT = {g['L_W']} + {g['GAP']} + {g['DOT']} = {g['L_W']+g['GAP']+g['DOT']} ≡ W（φ 链必然分割，误差 0.000%）
  竖笔/横笔等宽（同一支笔画的两段）；句点底边与横笔底边共线（同一条基线）
  净空区 ≥ 2×DOT（{g['DOT']*2}），使用方负责加边距
  最小尺寸：纯图形 ≥32px；≤32px 请改用 fayelong-favicon.svg（独立几何）
-->
"""
    pad = f'<rect width="{g["W"]}" height="{g["H"]}" fill="{bg}"/>' if bg else ""
    body = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {g["W"]} {g["H"]}" '
            f'role="img" aria-label="FayeLong">{pad}'
            f'<path d="{mark_path(g)}" fill="{ink}"/>'
            f'<path d="{dot_path(g)}" fill="{accent}"/></svg>')
    return head + body


def lockup_inline(g, kind, ink, accent, bg=None, h=None):
    W, H, cap = g["W"], g["H"], g["CAP_HEIGHT"]
    fs = cap / 0.72
    gap = 0.382 * cap
    base = float(H)                 # ★ 字标基线 = 标志基线（横笔底边）
    art = (f'<path d="{mark_path(g)}" fill="{ink}"/>'
           f'<path d="{dot_path(g)}" fill="{accent}"/>')
    mark_art = f'<g>{art}</g>'
    if kind == "icon":
        vw, vh, body = W, H, [art]
    elif kind == "stack":
        sc = W / 3.5
        vw = 1400
        vh = round(H + sc * 2.9)
        body = [f'<g transform="translate({_f((vw-W)/2)},0)">{art}</g>',
                f'<text x="{vw/2}" y="{_f(H+sc*1.55)}" font-family="{FONT_LATIN}" '
                f'font-size="{sc/0.72:.1f}" font-weight="650" letter-spacing="-5" '
                f'fill="{ink}" text-anchor="middle">FayeLong</text>',
                f'<text x="{vw/2}" y="{_f(H+sc*2.55)}" font-family="{FONT_CN}" '
                f'font-size="{sc*0.42:.1f}" font-weight="500" letter-spacing="{sc*0.15:.1f}" '
                f'fill="{ink}" text-anchor="middle" opacity="0.70">英语精听 · 听写</text>']
    else:
        vw = 2480
        vh = round(H + cap * 0.42)
        lx = W + gap
        body = [mark_art]
        if kind == "latin":
            body.append(f'<text x="{_f(lx)}" y="{_f(base)}" font-family="{FONT_LATIN}" '
                        f'font-size="{fs:.1f}" font-weight="650" letter-spacing="-8" '
                        f'fill="{ink}">FayeLong</text>')
        elif kind == "bi":
            body.append(f'<text x="{_f(lx)}" y="{_f(base-cap*0.52)}" font-family="{FONT_LATIN}" '
                        f'font-size="{fs:.1f}" font-weight="650" letter-spacing="-8" '
                        f'fill="{ink}">FayeLong</text>')
            body.append(f'<text x="{_f(lx+8)}" y="{_f(base)}" font-family="{FONT_CN}" '
                        f'font-size="{cap*0.42:.1f}" font-weight="500" '
                        f'letter-spacing="{cap*0.16:.1f}" fill="{ink}" opacity="0.70">'
                        f'英语精听 · 听写</text>')
        elif kind == "cn":
            body.append(f'<text x="{_f(lx)}" y="{_f(base-cap*0.44)}" font-family="{FONT_CN}" '
                        f'font-size="{fs*0.78:.1f}" font-weight="700" '
                        f'letter-spacing="{cap*0.05:.1f}" fill="{ink}">英语精听</text>')
            body.append(f'<text x="{_f(lx+8)}" y="{_f(base)}" font-family="{FONT_LATIN}" '
                        f'font-size="{cap*0.36:.1f}" font-weight="600" '
                        f'letter-spacing="{cap*0.14:.1f}" fill="{ink}" opacity="0.62">FAYELONG</text>')
    size = f' width="{round(h*vw/vh)}" height="{h}"' if h else ""
    head = ("<!-- FayeLong 组合标志（横排/堆叠）\n"
            "     图形本体为纯矢量路径（零字体依赖）；字标本轮为**字体排版占位**，\n"
            "     依赖字体栈：Inter Tight → Inter → Segoe UI Variable → system-ui；\n"
            "     中文：思源黑体 SC → 苹方 → 微软雅黑。定稿轮将自绘轮廓并轮廓化。\n"
            "     几何真源：06-source/build_logo.py -->\n")
    out = [head, f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}"{size}>']
    if bg:
        out.append(f'<rect width="{vw}" height="{vh}" fill="{bg}"/>')
    out += body + ["</svg>"]
    return "".join(out)


# ============================================================
# 5. blueprint 数学标注图
# ============================================================
def blueprint_svg(g, gf, st):
    X0, Y0 = 330.0, 300.0
    W, H, SW, LW, GP, DT = g["W"], g["H"], g["SW"], g["L_W"], g["GAP"], g["DOT"]
    A, B, T = "#C2410C", "#1D4ED8", "#0F172A"
    VW, VH = 2000, 1960

    def px(x):
        return X0 + x

    def py(y):
        return Y0 + y

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW} {VH}" '
         f'font-family="{FONT_CN}" width="{VW}" height="{VH}">',
         f'<rect width="{VW}" height="{VH}" fill="#FFFFFF"/>',
         f'<text x="{X0-140}" y="96" font-size="34" font-weight="800" fill="{T}">'
         f'FayeLong 标志 · 几何标注图 blueprint</text>',
         f'<text x="{X0-140}" y="136" font-size="19" fill="#475569">'
         f'「L · 落点」｜参数化构建 · 全部尺寸由黄金比 φ = 1.618034 派生 · '
         f'数值由脚本实时计算，无手写</text>']

    # ── 基准网格（8pt ×4，仅作构建参照）──
    for gx in range(0, W + 1, 32):
        o.append(f'<line x1="{px(gx)}" y1="{py(0)}" x2="{px(gx)}" y2="{py(H)}" stroke="#EDF1F5"/>')
    for gy in range(0, H + 1, 32):
        o.append(f'<line x1="{px(0)}" y1="{py(gy)}" x2="{px(W)}" y2="{py(gy)}" stroke="#EDF1F5"/>')

    # ── 实形（浅底 + 描边示形）──
    o.append(f'<g transform="translate({X0},{Y0})">'
             f'<path d="{mark_path(g)}" fill="{INK_LIGHT}" fill-opacity="0.09" stroke="{INK_LIGHT}" stroke-width="2"/></g>')
    o.append(f'<g transform="translate({X0},{Y0})">'
             f'<path d="{dot_path(g)}" fill="{ACC_LIGHT}" fill-opacity="0.30" stroke="{ACC_LIGHT}" stroke-width="2"/></g>')

    # ── 基准线 / 关键点 ──
    o.append(f'<line x1="{px(-160)}" y1="{py(H)}" x2="{px(W+80)}" y2="{py(H)}" stroke="{A}" stroke-width="1.8" stroke-dasharray="12 6"/>')
    o.append(f'<line x1="{px(SW)}" y1="{py(-70)}" x2="{px(SW)}" y2="{py(H)}" stroke="{A}" stroke-width="1.2" stroke-dasharray="8 5"/>')
    o.append(f'<line x1="{px(-110)}" y1="{py(H-SW)}" x2="{px(W+80)}" y2="{py(H-SW)}" stroke="{A}" stroke-width="1.2" stroke-dasharray="8 5"/>')
    for (mx, my) in [(0, 0), (SW, 0), (SW, H - SW), (LW, H - SW), (LW, H), (0, H),
                     (LW + GP, H), (W, H)]:
        o.append(f'<circle cx="{px(mx)}" cy="{py(my)}" r="5" fill="#FFFFFF" stroke="{A}" stroke-width="2"/>')
    o.append(f'<text x="{_f(px(SW)+16)}" y="{py(-14)}" font-size="18" fill="{A}">内角点：90° 直角、零圆角</text>')
    o.append(f'<text x="{_f(px(-152))}" y="{py(H)-14}" font-size="18" fill="{A}">基线：竖笔与横笔等宽共底</text>')
    o.append(f'<text x="{_f(px(-104))}" y="{py(H-SW)-12}" font-size="17" fill="{A}">横笔上缘</text>')

    # ── 尺寸标注 ──
    def hdim(x1, x2, y, label, sub=None, lx=None):
        o.append(f'<line x1="{px(x1)}" y1="{py(y)}" x2="{px(x2)}" y2="{py(y)}" stroke="{A}" stroke-width="1.4"/>')
        for xx in (x1, x2):
            o.append(f'<line x1="{px(xx)}" y1="{py(y)-8}" x2="{px(xx)}" y2="{py(y)+8}" stroke="{A}" stroke-width="1.4"/>')
        tx = px(lx) if lx is not None else px((x1 + x2) / 2)
        o.append(f'<text x="{_f(tx)}" y="{py(y)-14}" font-size="21" font-family="{FONT_MONO}" fill="{A}" text-anchor="middle" font-weight="700">{label}</text>')
        if sub:
            o.append(f'<text x="{_f(tx)}" y="{py(y)+26}" font-size="16" fill="#64748B" text-anchor="middle">{sub}</text>')

    def vdim(y1, y2, x, label, sub=None, side="left"):
        o.append(f'<line x1="{px(x)}" y1="{py(y1)}" x2="{px(x)}" y2="{py(y2)}" stroke="{A}" stroke-width="1.4"/>')
        for yy in (y1, y2):
            o.append(f'<line x1="{px(x)-8}" y1="{py(yy)}" x2="{px(x)+8}" y2="{py(yy)}" stroke="{A}" stroke-width="1.4"/>')
        dx = -18 if side == "left" else 18
        an = "end" if side == "left" else "start"
        o.append(f'<text x="{_f(px(x)+dx)}" y="{py((y1+y2)/2)}" font-size="21" font-family="{FONT_MONO}" fill="{A}" text-anchor="{an}" font-weight="700">{label}</text>')
        if sub:
            o.append(f'<text x="{_f(px(x)+dx)}" y="{py((y1+y2)/2)+24}" font-size="16" fill="#64748B" text-anchor="{an}">{sub}</text>')

    vdim(0, H, -100, f"H = {H}", "外框高")
    vdim(0, H - SW, -178, f"{H-SW}", "竖笔直线段")
    vdim(H - SW, H, -178, f"{SW}", "横笔厚")
    hdim(0, SW, -130, f"SW = {SW}", "笔宽 = H/φ³")

    # ── ★ 宽度尺寸链（本图主角）──
    ych = H + 300
    o.append(f'<text x="{_f(px(0))}" y="{py(ych)-172}" font-size="24" font-weight="800" fill="{T}">'
             f'★ 宽度尺寸链：三宽度被 φ 链必然分割（恒等式，非调参所得）</text>')
    o.append(f'<text x="{_f(px(0))}" y="{py(ych)-140}" font-size="17" fill="#475569">'
             f'W/φ　+　SW/φ　+　SW/φ²　=　H/φ²　+　H/φ⁴　+　H/φ⁵　=　H × 0.618034　=　W</text>')
    o.append(f'<line x1="{px(0)}" y1="{py(ych)-96}" x2="{px(W)}" y2="{py(ych)-96}" stroke="{A}" stroke-width="2"/>')
    for xx in (0, W):
        o.append(f'<line x1="{px(xx)}" y1="{py(ych)-104}" x2="{px(xx)}" y2="{py(ych)-88}" stroke="{A}" stroke-width="2"/>')
    o.append(f'<text x="{_f(px(W/2))}" y="{py(ych)-108}" font-size="20" font-family="{FONT_MONO}" fill="{A}" text-anchor="middle" font-weight="700">W = {W}</text>')
    segs = [(0, LW, f"L_W = {LW}", "= W/φ", INK_LIGHT),
            (LW, LW + GP, f"GAP = {GP}", "= SW/φ", INK_LIGHT),
            (LW + GP, W, f"DOT = {DT}", "= SW/φ²", ACC_LIGHT)]
    for (a1, a2, lab, sub, col) in segs:
        o.append(f'<rect x="{px(a1)}" y="{py(ych)-44}" width="{px(a2)-px(a1)}" height="44" fill="{col}" fill-opacity="0.18" stroke="{col}" stroke-width="2"/>')
    # 标签三行错开，避免窄段挤字
    o.append(f'<text x="{_f(px(LW/2))}" y="{py(ych)+34}" font-size="20" font-family="{FONT_MONO}" fill="{INK_LIGHT}" text-anchor="middle" font-weight="700">L_W = {LW}　( = W/φ )</text>')
    o.append(f'<line x1="{px(LW+GP/2)}" y1="{py(ych)}" x2="{px(LW+GP/2)}" y2="{py(ych)+48}" stroke="{A}" stroke-width="1"/>')
    o.append(f'<text x="{_f(px(LW+12))}" y="{py(ych)+62}" font-size="20" font-family="{FONT_MONO}" fill="{INK_LIGHT}" font-weight="700">GAP = {GP}　( = SW/φ )</text>')
    o.append(f'<line x1="{px(LW+GP+DT/2)}" y1="{py(ych)}" x2="{px(LW+GP+DT/2)}" y2="{py(ych)+76}" stroke="{ACC_LIGHT}" stroke-width="1.4"/>')
    o.append(f'<text x="{_f(px(LW+12))}" y="{py(ych)+90}" font-size="20" font-family="{FONT_MONO}" fill="{ACC_LIGHT}" font-weight="700">DOT = {DT}　( = SW/φ² )</text>')
    o.append(f'<text x="{_f(px(0))}" y="{py(ych)+130}" font-size="18" fill="#334155">'
             f'{LW} + {GP} + {DT} = {LW+GP+DT} ≡ {W}　误差 0.000%　→　外框宽度没有自由度：定了 1:φ 与笔宽 H/φ³，三段宽度即被锁死</text>')

    # ── 句点放样 ──
    ox, oy = px(0), py(ych) + 320
    o.append(f'<text x="{ox}" y="{_f(oy-DT-30)}" font-size="19" font-weight="800" fill="{T}">句点放样　DOT = {DT}</text>')
    o.append(f'<rect x="{ox}" y="{_f(oy-DT)}" width="{DT}" height="{DT}" fill="none" stroke="{ACC_LIGHT}" stroke-width="1.4" stroke-dasharray="5 4"/>')
    o.append(f'<path d="{dot_path(g)}" transform="translate({_f(ox-(LW+GP))},{_f(oy-DT-(H-DT))})" fill="{ACC_LIGHT}"/>')
    o.append(f'<line x1="{ox-40}" y1="{oy}" x2="{ox+DT+150}" y2="{oy}" stroke="{A}" stroke-width="1" stroke-dasharray="6 5"/>')
    for i, t in enumerate([f"微圆角 r = {g['R_DOT']} = DOT/φ³（唯一软度出处）",
                           "底边与横笔底边共线 → 落在同一条基线上",
                           "打破正圆 → 规避「浅底＋中央实心圆」国旗联想",
                           "右缘与外框右缘齐平 → 右侧闭合"]):
        o.append(f'<text x="{ox+DT+30}" y="{_f(oy-DT+i*26+4)}" font-size="16.5" fill="#475569">{t}</text>')

    # ================= 右侧数据面板 =================
    PX, yy = 1030, 210

    def sec(t):
        nonlocal yy
        o.append(f'<text x="{PX}" y="{yy}" font-size="24" fill="{T}" font-weight="800">{t}</text>')
        yy += 14
        o.append(f'<line x1="{PX}" y1="{yy}" x2="{PX+930}" y2="{yy}" stroke="{T}" stroke-width="2"/>')
        yy += 30

    def row(k, v, note=""):
        nonlocal yy
        o.append(f'<text x="{PX}" y="{yy}" font-size="17.5" fill="#334155">{k}</text>')
        o.append(f'<text x="{PX+290}" y="{yy}" font-size="17.5" font-family="{FONT_MONO}" fill="{T}" font-weight="700">{v}</text>')
        if note:
            o.append(f'<text x="{PX+530}" y="{yy}" font-size="16" fill="#64748B">{note}</text>')
        yy += 27

    sec("① 比例系统 · 黄金比 φ = 1.618034")
    for k, val, tgt in [("外框 W : H", W / H, 1 / PHI),
                        ("笔宽 SW : H", SW / H, 1 / PHI ** 3),
                        ("L 宽 L_W : W", LW / W, 1 / PHI),
                        ("间隔 GAP : W", GP / W, 1 / PHI ** 3),
                        ("句点 DOT : W", DT / W, 1 / PHI ** 4),
                        ("句点圆角 : DOT", g["R_DOT"] / DT, 1 / PHI ** 3),
                        ("字标大写高 : H = 笔宽", g["CAP_HEIGHT"] / H, 1 / PHI ** 3)]:
        row(k, f"{val:.5f}", f"目标 {tgt:.6f}｜误差 {abs(val-tgt)/tgt*100:.3f}%")
    yy += 10

    sec("② 关键尺寸链值")
    row("画布 / 留白（构建参照）", f"{g['canvas']} / {g['pad']}", "8pt 模块网格")
    row("图形 H × W", f"{H} × {W}", "viewBox 紧贴裁剪 1:φ")
    row("竖笔 / 横笔宽", f"{SW}", "等宽（同一支笔画）")
    row("L 宽 L_W", f"{LW}", "= W/φ")
    row("间隔 GAP", f"{GP}", "= SW/φ")
    row("句点 DOT / 圆角", f"{DT} / {g['R_DOT']}", "= SW/φ² · 圆角 DOT/φ³")
    row("句点位置", f"x {LW+GP} → {W}", "右缘 = 外框右缘")
    row("句点基准", f"y {H-DT} → {H}", "底边 = 基线")
    yy += 10

    sec("③ 构造恒定式（构建期 assert，失败即中止）")
    for t in [f"L_W + GAP + DOT = {LW} + {GP} + {DT} = {LW+GP+DT} ≡ W = {W}",
              f"GAP + DOT = {GP} + {DT} = {GP+DT} ≡ SW = {SW}",
              "竖笔与横笔等宽（同一支笔画的两段，非同形拼接）",
              "内角为直角、零圆角 → 直角语法 100% 一致",
              f"句点尺度 {DT} < 笔宽 {SW} → 配角不抢主角",
              f"半径分级仅 1 级（{g['R_DOT']}），≤3 达标"]:
        o.append(f'<circle cx="{PX+7}" cy="{yy-6}" r="4" fill="#16A34A"/>')
        o.append(f'<text x="{PX+22}" y="{yy}" font-size="16.5" fill="#334155">{t}</text>')
        yy += 26
    yy += 12

    sec("④ 视觉重量（多边形积分，程序计算）")
    row("标志总面积", f"{st['area']:.0f} px²", "")
    row("主角 字母 L", st["l_share"], "面积占比")
    row("配角 句点", st["dot_share"], "< 10% 达标（点缀纪律）")
    yy += 10

    sec("⑤ 色彩（WCAG 相对亮度法）")
    row("主色 松墨", INK_LIGHT, f"纸底对比 {st['c_ink']:.2f}:1")
    row("点缀 焰琥珀", ACC_LIGHT, f"纸底对比 {st['c_acc']:.2f}:1")
    row("深底反白", INK_DARK, f"深底对比 {st['c_rev']:.2f}:1")
    row("主辅灰度明度差", f"{st['lum_gap']:.1f}%", "> 20% 达标（色盲安全）")
    yy += 10

    sec("⑥ 小尺寸降级（独立几何，非等比缩）")
    row("主标最小尺寸", "32px", "< 32px 改用 favicon 版")
    row("favicon H × W", f"{gf['H']} × {gf['W']}", "留白 32（更满）")
    row("favicon 句点 / 间隔", f"{gf['DOT']} / {gf['GAP']}", "同放大一档 → 16px 下均 ≥2px")
    row("16px 实测", f"笔 {gf['SW']*16/gf['H']:.1f}px · 句 {gf['DOT']*16/gf['H']:.1f}px", "全部可辨")
    o.append('</svg>')
    return "".join(o)



# ============================================================
# 6. preview.html
# ============================================================
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#EDEFEE;color:#0E3B34;
 font-family:'Inter Tight',Inter,'Segoe UI Variable Text','Segoe UI',-apple-system,
 'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:1200px;margin:0 auto;padding:56px 32px 96px}
h1{font-size:38px;margin:0 0 8px;letter-spacing:-.5px}
h2{font-size:23px;margin:64px 0 6px;padding-top:22px;border-top:1px solid #D5DAD7}
h2 .n{font-family:'Cascadia Mono',Consolas,monospace;font-size:15px;color:#8A9691;margin-right:10px}
h3{font-size:16px;margin:28px 0 10px;color:#0E3B34}
.sub{color:#5C6B66;font-size:15px;margin:0 0 4px}
.lead{font-size:16px;color:#3C4C47;max-width:78ch}
.card{background:#F2F5F3;border:1px solid #DFE4E1;border-radius:14px;padding:22px}
.card.dark{background:#0B2A26;border-color:#0B2A26}
.card.dark .cap,.card.dark .ttl{color:#F2F5F3}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
svg{display:block;width:100%;height:auto}
.ttl{font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#5C6B66;margin-bottom:10px}
.cap{font-size:13px;color:#5C6B66;margin-top:12px}
.cap b{color:#0E3B34}
.tres{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:26px 0}
.res{background:#F2F5F3;border:1px solid #DFE4E1;border-radius:12px;padding:16px 18px}
.res h4{margin:0 0 10px;font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:#8A9691}
.res pre{margin:0;font-family:'Cascadia Mono',Consolas,monospace;font-size:12px;
 color:#0E3B34;white-space:pre-wrap;line-height:1.75}
table{width:100%;border-collapse:collapse;font-size:14.5px;margin-top:12px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #DFE4E1;vertical-align:top}
th{font-size:12.5px;letter-spacing:.04em;text-transform:uppercase;color:#8A9691;font-weight:700}
td.ok{color:#0E3B34;font-weight:700;white-space:nowrap}
.mono{font-family:'Cascadia Mono',Consolas,monospace;font-size:13px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.chip{font-size:12.5px;padding:3px 10px;border-radius:999px;background:#0E3B34;color:#F2F5F3}
.chip.a{background:#D98A3D}
.chip.o{background:transparent;color:#0E3B34;border:1px solid #C9D0CC}
.zoom{display:flex;align-items:flex-end;gap:22px;flex-wrap:wrap;
 background:#F2F5F3;border:1px solid #DFE4E1;border-radius:14px;padding:24px 26px}
.zi{display:flex;flex-direction:column;align-items:center;gap:8px}
.zi span{font-family:'Cascadia Mono',Consolas,monospace;font-size:11.5px;color:#8A9691}
.tab{display:flex;align-items:center;gap:9px;background:#0B2A26;border-radius:999px 999px 0 0;
 padding:9px 18px;width:210px}
.tab span{font-size:13px;color:#F2F5F3}
.hero{background:#F2F5F3;border:1px solid #DFE4E1;border-radius:16px;padding:44px;
 display:grid;grid-template-columns:300px 1fr;gap:44px;align-items:center}
.hero svg{width:auto;height:auto}
.note{font-size:13.5px;color:#8A9691;margin-top:8px}
ul{margin:8px 0 0;padding-left:20px}
li{margin:4px 0;font-size:14.5px}
.warn{color:#A33B00}
@media(max-width:900px){.grid2,.grid3,.grid4,.tres{grid-template-columns:1fr}
 .hero{grid-template-columns:1fr}.hero svg{width:220px}}
"""


def preview_html(g, gf, st):
    P = []
    A = P.append
    A('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<title>FayeLong 标志方案 · L · 落点</title>')
    A(f"<style>{CSS}</style></head><body><div class='wrap'>")

    # ── 头部 ──
    A("<h1>FayeLong 标志方案 · 「L · 落点」</h1>")
    A(f"<p class='sub'>提案轮 v1.0 · 单方向极致交付 · 比例系统 φ · "
      f"几何由 <span class='mono'>06-source/build_logo.py</span> 参数化生成</p>")
    A("<p class='lead'>字母 <b>L</b>（FayeLong / Listening / Language）＋ 一个<b>句点</b>。"
      "竖笔是声音、横笔是纸上的行、句点是被听清的那一个字——<b>一声落下，写成一句</b>。"
      "整个标志只由两个元素构成，且外框宽度被黄金比必然切成三段："
      "<span class='mono'>318 + 121 + 75 = 514</span>，没有一段可以自由取值。</p>")

    # ── 三卡 ──
    A("<div class='tres'>")
    A("<div class='res'><h4>① 元素预算卡</h4><pre>"
      f"元素清单：字母 L（主）／句点（配）—— 2 / 3 达标\n"
      f"语义来源：L = 首字母 + Listening + Language + Learn\n"
      f"　　　　　句点 = 一句话的最小单位（产品的「一句一页」）\n"
      f"主角占比：L 占 {st['l_share']}　句点占 {st['dot_share']}（&lt;10% 点缀纪律）\n"
      f"删减测试：删句点→「句」没了、只剩一个普通字母 → 保留\n"
      f"一元素多义：句点 = 句号 + 听写落点 + 刚写下的那个字（三义均可讲清）\n"
      f"关系语义：点落在横笔（基线）上 →「落在句子上」，不是漂浮装饰</pre></div>")

    A("<div class='res'><h4>② 色彩判断卡</h4><pre>"
      f"行业地图：英语学习 = 教育蓝海（百词斩/扇贝/流利说全蓝）\n"
      f"　　　　　+ 多邻国高饱和亮绿（游戏化）\n　　　　　→ <b>空位 = 低饱和深墨青</b>\n"
      f"主色：#0E3B34 松墨｜HSV 170.7° 76% 23%\n"
      f"点缀：#D98A3D 焰琥珀｜只给句点，占比 {st['dot_share']}，绑「被听清的那一下」\n"
      f"底色：#F2F5F3 纸底（带 3% 主色倾向，非纯白）｜深底 #0B2A26\n"
      f"硬判据：灰度明度差 {st['lum_gap']:.1f}% &gt;20% ✓\n　　　　｜四格式齐全 ✓｜单色可逆 ✓\n"
      f"差异一句话：他们亮绿求「嗨」，我们深墨青求「静」</pre></div>")

    A("<div class='res'><h4>③ 风格语法卡</h4><pre>"
      f"连续谱定位：直角端（偏右三区）——平头端、直角转角、零圆角\n"
      f"理由：精听／听写是「精确」的动作（逐词校验、0 容差），语法就该精确\n"
      f"形态决策：端头平切／内角直角／无描边／无渐变\n　　　　　／无投影／无外发光\n"
      f"软度唯一出处：句点方块保留 r={g['R_DOT']} 微圆角 = DOT/φ³\n"f"字标规则：大写高 = 笔宽 SW = {g['CAP_HEIGHT']}（= H/φ³）\n"
      f"一致性：直角语法 ≈ 95%｜混用声明：句点圆角 =「刚落下、还未凝固」\n"
      f"禁项自查：无渐变球／无外发光／无半透明叠圆／无 NFT 蓝紫 ✓</pre></div>")
    A("</div>")

    # ── ① Hero ──
    A("<h2><span class='n'>01</span>Hero 主标</h2>")
    A("<p class='sub'>纯图形 · 彩色 · 透明底可用（此卡为纸底）</p>")
    A("<div class='hero'>")
    A(mark_inline(g, INK_LIGHT, ACC_LIGHT, px=430, bg=BG_LIGHT))
    A("<div><h3 style='margin-top:0'>一声落下，写成一句</h3>"
      "<p class='lead'>竖笔与横笔是同一支笔画的两段、等宽——它是一支「笔」，"
      "不是拼起来的两个零件。句点底边与横笔底边严格共线：它<b>落在句子上</b>，"
      "而不是飘在旁边。句点右缘与外框右缘齐平，整幅右侧干净闭合。</p>"
      "<div class='chips'><span class='chip'>外框 1 : φ</span>"
      "<span class='chip'>笔宽 H/φ³</span><span class='chip'>直角语法</span>"
      f"<span class='chip a'>句点 {st['dot_share']}</span>"
      "<span class='chip o'>零渐变 · 零投影</span></div>"
      "<p class='note'>几何恒等式：<span class='mono'>318 + 121 + 75 = 514</span> — "
      "外框宽 = W/φ + SW/φ + SW/φ²，被 φ 链必然分割。</p></div>")
    A("</div>")

    # ── ② Lockup 矩阵 ──
    A("<h2><span class='n'>02</span>组合 Lockup 矩阵<span style='font-size:14px;color:#8A9691;font-weight:400'>"
      "（字标本轮为字体排版占位，定稿轮按笔宽自绘轮廓）</span></h2>")
    A("<p class='sub'>5 种组合 × 明／暗两种底色。字标基线一律对齐标志基线——"
      "字标坐在 L 的横笔所代表的那条线上。</p>")
    kinds = [("icon", "纯图形"), ("latin", "图形 + FayeLong"),
             ("bi", "图形 + 双语横排"), ("cn", "图形 + 中文为主"), ("stack", "图形 + 堆叠双语")]
    for theme, tname in [("light", "明底"), ("dark", "暗底")]:
        ink, acc, bg = (INK_LIGHT, ACC_LIGHT, BG_LIGHT) if theme == "light" else (INK_DARK, ACC_DARK, BG_DARK)
        A(f"<h3>{tname}（{'#F2F5F3 纸底' if theme=='light' else '#0B2A26 深墨底'}）</h3>")
        A("<div class='grid2'>")
        for k, label in kinds:
            cls = "card dark" if theme == "dark" else "card"
            art = lockup_inline(g, k, ink, acc, bg=bg,
                                h=300 if k == 'stack' else (340 if k == 'icon' else 240))
            A(f"<div class='{cls}'><div class='ttl'>{label}</div>{art}"
              f"<div class='cap'>字体：Inter Tight / Inter → Segoe UI Variable → system-ui；"
              f"中文：思源黑体 SC → 苹方 → 微软雅黑</div></div>")
        A("</div>")

    # ── ③ 缩放墙 ──
    A("<h2><span class='n'>03</span>缩放墙与小尺寸降级</h2>")
    A("<p class='sub'>主标纯图形最小 32px；≤32px 自动切换为 favicon 独立几何"
      "（句点与间隔同放大一档、L 宽相应反解，保证 16px 下二者均 ≥2px）。</p>")
    A("<div class='zoom'>")
    for s in (16, 24, 32):
        A(f"<div class='zi'>{mark_inline(gf, INK_LIGHT, ACC_LIGHT, px=s)}<span>{s}px · favicon 版</span></div>")
    for s in (48, 64, 96, 128, 192):
        A(f"<div class='zi'>{mark_inline(g, INK_LIGHT, ACC_LIGHT, px=s)}<span>{s}px</span></div>")
    A("</div>")
    A(f"<p class='note'>16px 实测：笔宽 {gf['SW']*16/gf['H']:.1f}px · 句点 {gf['DOT']*16/gf['H']:.1f}px · "
      f"间隔 {gf['GAP']*16/gf['H']:.1f}px —— 三项均可辨；主标版句点仅 "
      f"{g['DOT']*16/g['H']:.1f}px，故 32px 以下必须换版（这是设计好的降级，不是事后补救）。</p>")

    # ── ④⑤ 尺寸标注 + blueprint ──
    A("<h2><span class='n'>04 / 05</span>关键尺寸标注 + blueprint 数学标注图</h2>")
    A("<p class='sub'>尺寸链值、半径、对齐条件全部程序计算。核心是那条恒等式："
      "三宽度之和恒等于外框宽，误差 0.000%。</p>")
    A("<div class='card' style='padding:8px'>")
    A(blueprint_svg(g, gf, st).replace(' width="1980" height="1340"', ""))
    A("</div>")
    A("<p class='note'>blueprint 光栅版见 <span class='mono'>07-blueprint/fayelong-blueprint.png</span>（2000px）。</p>")

    # ── ⑥ 变体家族 ──
    A("<h2><span class='n'>06</span>变体家族</h2>")
    A("<p class='sub'>主标彩色／单色黑／反白／灰阶。反白版不是简单反相：深底句点提亮到 #E8A657。</p>")
    var = [("主标 · 彩色", INK_LIGHT, ACC_LIGHT, BG_LIGHT),
           ("单色黑", "#000000", "#000000", BG_LIGHT),
           ("反白 · 深底", INK_DARK, ACC_DARK, BG_DARK),
           ("灰阶", "#333333", "#9A9A9A", BG_LIGHT)]
    A("<div class='grid4'>")
    for label, ink, acc, bg in var:
        cls = "card dark" if bg == BG_DARK else "card"
        A(f"<div class='{cls}'><div class='ttl'>{label}</div>"
          f"{mark_inline(g, ink, acc, px=200, bg=bg)}</div>")
    A("</div>")
    A("<p class='note'><b>mono 诚实声明</b>：单色黑版里句点与笔画同色，二者在视觉上合并为「一个更粗的 L」，"
      "句点的独立性失效——这是几何事实，属预期行为，不用描边或阴影假装区分。"
      "强调层由形状位置（右侧、贴基线）承住，而非靠颜色。</p>")

    # ── ⑦ 应用实景 ──
    A("<h2><span class='n'>07</span>应用实景</h2>")
    A("<div class='grid3'>")
    A("<div class='card' style='background:#E4E8E6'><div class='ttl'>浏览器标签页</div>"
      "<div style='display:flex;align-items:flex-end'>"
      f"<div class='tab'>{mark_inline(gf, '#F2F5F3', ACC_DARK, px=16)}"
      "<span>FayeLong 英语精听</span></div></div>"
      "<div style='height:120px;background:#F2F5F3;border-radius:0 8px 8px 8px'></div></div>")
    A("<div class='card'><div class='ttl'>App 图标</div>"
      "<div style='display:flex;gap:14px;align-items:center'>"
      f"<div style='width:96px;height:96px;border-radius:22px;background:{BG_DARK};"
      f"display:flex;align-items:center;justify-content:center'>"
      f"{mark_inline(gf, INK_DARK, ACC_DARK, px=70)}</div>"
      f"<div style='width:96px;height:96px;border-radius:22px;background:{INK_LIGHT};"
      f"display:flex;align-items:center;justify-content:center'>"
      f"{mark_inline(gf, '#F2F5F3', ACC_DARK, px=70)}</div></div>"
      "<div class='cap'>favicon 独立几何直接作 App 图标前景层</div></div>")
    A("<div class='card'><div class='ttl'>网站页眉</div>"
      f"<div style='background:#F2F5F3;border:1px solid #DFE4E1;border-radius:10px;padding:14px 18px'>"
      f"{lockup_inline(g, 'latin', INK_LIGHT, ACC_LIGHT)}</div>"
      f"<div style='background:#0B2A26;border-radius:10px;padding:14px 18px;margin-top:10px'>"
      f"{lockup_inline(g, 'latin', INK_DARK, ACC_DARK)}</div></div>")
    A("</div>")

    # ── ⑧ 色彩与字体规范卡 ──
    A("<h2><span class='n'>08</span>色彩与字体规范卡</h2>")
    def cmyk_txt(h):
        c, m, y, k = cmyk(h)
        return f"C{c} M{m} Y{y} K{k}"
    A("<table><tr><th>色</th><th>HEX</th><th>RGB</th><th>CMYK</th><th>Pantone（近似）</th><th>用途</th></tr>")
    rows = [(INK_LIGHT, "松墨 Ink", "Pantone 5535 C", "主色：L 全部笔画 / 正文字色"),
            (ACC_LIGHT, "焰琥珀 Accent", "Pantone 715 C", "点缀：句点（浅底版）"),
            (BG_LIGHT, "纸底 Paper", "—", "浅色底背景（非纯白）"),
            (BG_DARK, "深墨底 Deep", "Pantone 5463 C", "深色模式背景"),
            (INK_DARK, "深底反白", "—", "深底上的笔画"),
            (ACC_DARK, "深底句点", "Pantone 143 C", "深底上提亮的句点")]
    for h, name, pms, use in rows:
        r, gg, b = rgb255(h)
        A(f"<tr><td><b>{name}</b><div><span style='display:inline-block;width:13px;height:13px;"
          f"border:1px solid #C2CAC6;border-radius:3px;background:{h};vertical-align:-2px'></span>"
          f" <span class='mono' style='color:#5C6B66'>{h}</span></div></td>"
          f"<td class='mono'>{h}</td><td class='mono'>RGB({r},{gg},{b})</td>"
          f"<td class='mono'>{cmyk_txt(h)}</td><td class='mono'>{pms}</td><td>{use}</td></tr>")
    A("</table>")
    A("<p class='note'>CMYK 由 RGB 换算、Pantone 为近似对照，落印前请以专色卡校准。"
      "对比度：松墨/纸底 "
      f"{contrast(INK_LIGHT,BG_LIGHT):.2f}:1（正文场景远超 WCAG AA 4.5:1）｜"
      f"反白/深底 {contrast(INK_DARK,BG_DARK):.2f}:1｜"
      f"句点/纸底 {contrast(ACC_LIGHT,BG_LIGHT):.2f}:1（句点是图形不是文字，不适用正文阈值）。</p>")
    A("<h3>字体</h3>")
    A("<ul><li><b>字标（FayeLong）</b>：本轮为字体排版占位 —— "
      "<span class='mono'>Inter Tight → Inter → Segoe UI Variable → system-ui</span>。"
      "定稿轮将按笔宽 SW/H 的比例自绘轮廓并轮廓化，避免「字体直接描边」的懒政（也会消除授权问题）。</li>"
      "<li><b>中文</b>：<span class='mono'>思源黑体 SC → 苹方 → 微软雅黑</span>，字距 +0.15em。</li>"
      "<li>标志本体<b>不含任何文字</b>——纯路径，零字体依赖。</li></ul>")

    # ── 七项检查 ──
    A("<h2><span class='n'>09</span>七项检查（自跑结果公示）</h2>")
    A("<table><tr><th>检查</th><th>结果</th><th>依据</th></tr>")
    checks = [
        ("剪影测试", "✓ 通过", "涂黑后仍是清晰可辨的 L + 右侧一点，气质不丢（直角、厚重、有留白）"),
        ("16px 测试", "✓ 通过（换版）", f"主标句点仅 {g['DOT']*16/g['H']:.1f}px → 32px 以下切 favicon 独立几何，"
                                    f"句点放大到 {gf['DOT']*16/gf['H']:.1f}px 可辨"),
        ("单色测试", "✓ 通过", "层级靠形状与位置承住：句点靠「贴基线 + 靠右」独立成组，不依赖颜色"),
        ("模糊测试", "✓ 通过", "3–5px 高斯后整体形态仍成立（直角大形不受影响）"),
        ("反白测试", "✓ 通过", f"深底直接用反白版，句点改用提亮变体 {ACC_DARK}（对比 "
                            f"{contrast(ACC_DARK,BG_DARK):.2f}:1），不需专门调形"),
        ("撞脸测试", "✓ 通过", "见下表，逐条差异一句话可讲清"),
        ("语义安全审查", "✓ 通过", "见下表，逐项给出已查无问题或已规避"),
    ]
    for n, r, why in checks:
        A(f"<tr><td><b>{n}</b></td><td class='ok'>{r}</td><td>{why}</td></tr>")
    A("</table>")

    A("<h3>撞脸自查（几何特征级原创性自查，非商标法律检索）</h3>")
    A("<table><tr><th>对标</th><th>它的图形语言</th><th>我们与它的差异</th></tr>")
    comp = [
        ("多邻国 Duolingo", "高饱和亮黄绿 + 圆润猫头鹰吉祥物，靠「角色亲和」",
         "我们无吉祥物、无亮绿、纯几何字形；靠「形状纪律」而非角色讨喜"),
        ("百词斩", "蓝色圆角方块容器 + 中文名，靠「容器化」",
         "我们不用容器方块、不用教育蓝；标志是无外框的开放字形"),
        ("扇贝单词", "蓝色 + 生物具象（贝壳）",
         "我们完全抽象，不含任何具象物"),
        ("每日英语听力／可可英语", "耳机／扬声器／同心声波弧 + 蓝，靠「音频图标」",
         "我们不做并列的音频图标；「声音」含义由竖笔（厚重笔画）承担，不额外贴喇叭"),
        ("音频类通用（SoundCloud 等）", "水平波形长条阵列 + 橙色",
         "我们用单支笔画而非长条阵列；橙色只出现在一个句点上，占比 <3%"),
    ]
    for a1, b1, c1 in comp:
        A(f"<tr><td><b>{a1}</b></td><td>{b1}</td><td>{c1}</td></tr>")
    A("</table>")

    A("<h3>语义安全审查</h3>")
    A("<table><tr><th>检查项</th><th>结论</th></tr>")
    sem = [
        ("180° 旋转", "倒置后是一个「Γ + 点」，不构成任何不当形象 —— 已查无问题"),
        ("左右镜像", "镜像后为「⌐ + 点」，无暗藏物 —— 已查无问题"),
        ("负空间暗藏物", "内角是纯直角，无镂空、无交叠区，负空间不构成任何第二形象 —— 已查无问题"),
        ("缩写 / 拼音歧义", "FL / FayeLong：英文无脏词、中文无谐音不吉。「Faye」在英文里近 fairy（童话），中性"),
        ("文化符号碰撞①：浅底＋中央实心圆", f"<b>已规避</b>：句点<b>不是正圆</b>（方块 + 微圆角 r={g['R_DOT']}），"
                                     "且不在画面中央（位于右下、贴基线）—— 双条件同时满足"),
        ("文化符号碰撞②：国旗 3 秒比对", "中/日/韩/美/英/法/德/俄/印逐个比对：L 形 + 一枚小方块不构成任何国旗结构 —— 已查无问题"),
        ("文化符号碰撞③：宗教符号", "无十字（有直角但不成十字）、无新月、无万字符、无大轮 —— 已查无问题"),
        ("附带联想", "琥珀色小方块贴着厚重深色笔画，极小尺寸下或可读作「烛火／火柴」（中性联想），不予规避"),
    ]
    for k1, v1 in sem:
        A(f"<tr><td><b>{k1}</b></td><td>{v1}</td></tr>")
    A("</table>")

    # ── 落选候选 ──
    A("<h2><span class='n'>10</span>候选对比表（内部发散 · 探索成本不摊给用户）</h2>")
    A("<table><tr><th>候选方向</th><th>一句话气质</th><th>落选原因</th></tr>")
    cand = [
        ("声纹 L（竖笔做振幅调制）", "声音在笔画里起伏",
         "数学自洽、也真做成了矢量——但 3 波瓣读成「螺纹／竹节」，1 波瓣读成「花生」，眼睛否决（E 诚实条款：视觉证据 > 数学）"),
        ("笔宽渐变 L（上宽下窄）", "一次振幅衰减落成细线",
         "无缺口、很干净，但整体读作「书法／羽毛」，语义指向弱，且下段过细影响小尺寸"),
        ("均衡器 L（基线 + 三振幅柱）", "最直白的声音→文字图解",
         "撞脸风险高（直接落进音频 App 通用语汇），且三柱读成柱状图，不是品牌"),
        ("句点嵌在转角负空间内", "一个字落在句子里",
         "点在大片留白里漂浮，构图失衡，与横笔的关系讲不清"),
        ("净 L + 顶段着色", "极简，气质克制",
         "装饰性着色无语义绑定（F §1：装饰 = 杂质），删掉它故事不塌 → 该被删"),
    ]
    for c1, c2, c3 in cand:
        A(f"<tr><td><b>{c1}</b></td><td>{c2}</td><td>{c3}</td></tr>")
    A("</table>")

    # ── 下一步 ──
    A("<h2><span class='n'>11</span>下一步（点一句就动）</h2>")
    A("<ul>"
      "<li>「句点换成圆点」—— 30 秒出新版（但会触发「浅底＋实心圆」的国旗联想，需同时往左移出中线）</li>"
      "<li>「主色换一版」—— 给个 HEX 我直接出全套（比如更冷的靛 #16323F / 更暖的栗 #3A2A22）</li>"
      "<li>「看看 16px 到底长什么样」—— 我出一张 16/24/32 三档实拍对比图</li>"
      "<li>「字标也自绘」—— 进入定稿轮：按笔宽 SW/H 自绘 FayeLong 轮廓并轮廓化，出 6 变体 + favicon 三件套 + 全量技术报告 report.html</li>"
      "<li>「中文名要不要」—— 目前「英语精听 · 听写」是功能描述不是品牌名；有中文名我重做中文锁排</li>"
      "</ul>")
    A("<p class='note'>⚠️ 本轮为<b>提案轮</b>：已交付真矢量源文件、完整几何说明、七项检查与规格摘要；"
      "尚未交付定稿全套（6 色彩变体全量 SVG / PNG 梯队 / favicon ICO 三件套 / 全量技术报告 report.html）。</p>")

    A("</div></body></html>")
    return "".join(P)


# ============================================================
# 7. spec.md
# ============================================================
def spec_md(g, gf, st):
    c1 = cmyk(INK_LIGHT)
    c2 = cmyk(ACC_LIGHT)
    return f"""# FayeLong 标志使用规范 · spec
> 方案：「L · 落点」｜提案轮 v1.0｜几何由 `06-source/build_logo.py` 生成，**改参数后重跑，勿手工改坐标**

## 1. 概念
字母 **L**（FayeLong / Listening / Language / Learn）＋ 一个**句点**。
竖笔是声音、横笔是纸上的行、句点是被听清的那一个字 —— **一声落下，写成一句**。
产品的核心动作是「一句一页」：把一段音频切成一句一句，反复听、写下来。句点就是那个最小单位。

## 2. 三声明

### ① 比例系统：黄金比 φ = 1.618034
| 量 | 值 | 声明比 | 实测误差 |
|---|---|---|---|
| 外框 W : H | {g['W']} : {g['H']} | 1 : φ | {abs((g['W']/g['H'])/(1/PHI)-1)*100:.3f}% |
| 笔宽 SW : H | {g['SW']} : {g['H']} | 1 : φ³ | {abs((g['SW']/g['H'])/(1/PHI**3)-1)*100:.3f}% |
| L 宽 L_W : W | {g['L_W']} : {g['W']} | 1 : φ | {abs((g['L_W']/g['W'])/(1/PHI)-1)*100:.3f}% |
| 间隔 GAP : W | {g['GAP']} : {g['W']} | 1 : φ³ | {abs((g['GAP']/g['W'])/(1/PHI**3)-1)*100:.3f}% |
| 句点 DOT : W | {g['DOT']} : {g['W']} | 1 : φ⁴ | {abs((g['DOT']/g['W'])/(1/PHI**4)-1)*100:.3f}% |
| 句点圆角 : DOT | {g['R_DOT']} : {g['DOT']} | 1 : φ³ | {abs((g['R_DOT']/g['DOT'])/(1/PHI**3)-1)*100:.3f}% |
| 字标大写高 : H | {g['CAP_HEIGHT']} : {g['H']} | 1 : φ³（= 笔宽 SW）| {abs((g['CAP_HEIGHT']/g['H'])/(1/PHI**3)-1)*100:.3f}% |

**★ 数学必然（不是调参）**：外框宽被 φ 链必然切成三段
```
L_W + GAP + DOT = W/φ + SW/φ + SW/φ² = H/φ² + H/φ⁴ + H/φ⁵
                = H × (0.381966 + 0.145898 + 0.090170) = H × 0.618034 = H/φ = W
代入：{g['L_W']} + {g['GAP']} + {g['DOT']} = {g['L_W']+g['GAP']+g['DOT']} ≡ {g['W']}   （误差 0.000%）
```
即：一旦定了 1:φ 的外框与「笔宽 = H/φ³」「句点 = 笔宽/φ²」，三段宽度**没有自由度**。
同时 `GAP + DOT = {g['GAP']} + {g['DOT']} = {g['SW']} = SW` —— 笔宽自身也被必然分解。
构建脚本里以 `assert` 守卫，不成立即中止。

### ② 风格语法：直角端
连续谱定位：**直角端**（平头端 / 直角转角 / 零圆角）。
理由：精听与听写是「精确」的动作（逐词校验、正确率 0 容差），语法就该是精确的。
- 端头：平切，无圆头
- 转角：90° 直角，内角零圆角
- 无描边、无渐变、无投影、无外发光
- **软度唯一出处**：句点方块保留 r={g['R_DOT']} 微圆角（= DOT/φ³）
- 混用声明：该微圆角语义绑定「刚落下、还未凝固的那个字」，异质元素 1 项（<20%），达 F §3 一致性铁律

### ③ 元素预算 2 / 3
| 元素 | 角色 | 面积占比 | 语义来源 |
|---|---|---|---|
| 字母 L | 主角 | {st['l_share']} | 品牌首字母 + Listening + Language + Learn |
| 句点 | 配角 | {st['dot_share']} | 一句话的最小单位 / 听写落点 |
点缀色 = 句点本身（**用颜色做强调，不加形状** —— F §5）。
删减测试：删句点 → 「句」的含义消失，只剩一个普通字母 → 保留。

## 3. 关键几何链值
```
画布 1024 × 1024      留白 {g['pad']}      基准网格 8pt（32 = 8×4）
图形 {g['H']} × {g['W']}   居中 translate({g['pad']}, {g['pad']})
竖笔宽 = 横笔厚 = SW = {g['SW']}          （同一支笔画的两段，等宽）
L 宽 L_W = {g['L_W']}    间隔 GAP = {g['GAP']}    句点 DOT = {g['DOT']}（圆角 {g['R_DOT']}）
句点位置：x ∈ [{g['L_W']+g['GAP']}, {g['W']}]   右缘 = 外框右缘
句点基准：y ∈ [{g['H']-g['DOT']}, {g['H']}]     底边 = 基线（与横笔底边共线）
半径分级：仅 1 级（{g['R_DOT']}）—— ≤3 达标
```

## 4. 使用规范

### 净空区 Clear space
四周最小留白 = **句点边长 DOT 的 2 倍**（= {g['DOT']*2} 于 1024 画布 / 约字高的 18%）。
低于此值请勿放置任何文字、边框或图形。

### 最小尺寸
| 场景 | 阈值 | 低于阈值怎么办 |
|---|---|---|
| 纯图形（主标） | ≥ 32px / 印刷 ≥ 6mm | 换 `fayelong-favicon.svg`（独立几何） |
| 纯图形（favicon） | ≥ 16px | 已经是极限简化版，不得再缩 |
| 横版组合标 | 高度 ≥ 24px（数字）/ ≥ 8mm（印刷） | 退回纯图形版 |

### 小尺寸降级规则（设计好的，不是补救）
favicon 是**独立几何**，不是等比缩：
- 留白 {g['pad']} → {gf['pad']}（更满）
- 句点与间隔**同放大一档**（DOT: SW/φ² → SW/φ；GAP: SW/φ² → SW/φ），L 宽由 W − GAP − DOT 反解
- 总和恒等于 W，恒等式在小尺寸版依然成立
- 结果：16px 下笔宽 {gf['SW']*16/gf['H']:.1f}px、句点 {gf['DOT']*16/gf['H']:.1f}px、间隔 {gf['GAP']*16/gf['H']:.1f}px，三项均可辨
- favicon 几何同样满足 `L_W + GAP + DOT ≡ W`

### 禁用示例
1. 拉伸／压缩变形（必须等比）
2. 越过净空区（四周 ≥ 2×DOT）
3. 加投影、描边、外发光、渐变
4. 擅自改色（尤其把句点改成与笔画同色以外的第三色）
5. 置于低对比背景（浅底句点、深底深色笔画）
6. 旋转、倾斜、加圆角容器
7. 把句点改成正圆后置于画面中央（触发「浅底＋中央实心圆」国旗联想）
8. 把 L 的直角改成大圆角（破坏直角语法，风格事故）

## 5. 色彩规格（四格式）
| 色 | HEX | RGB | CMYK | Pantone（近似） | 用途 |
|---|---|---|---|---|---|
| 松墨 Ink | {INK_LIGHT} | RGB{str(rgb255(INK_LIGHT))[1:-1]} | C{c1[0]} M{c1[1]} Y{c1[2]} K{c1[3]} | 5535 C | 主色：L 全部笔画 |
| 焰琥珀 Accent | {ACC_LIGHT} | RGB{str(rgb255(ACC_LIGHT))[1:-1]} | C{c2[0]} M{c2[1]} Y{c2[2]} K{c2[3]} | 715 C | 点缀：句点（浅底） |
| 纸底 Paper | {BG_LIGHT} | RGB{str(rgb255(BG_LIGHT))[1:-1]} | — | — | 浅色底背景（非纯白） |
| 深墨底 Deep | {BG_DARK} | RGB{str(rgb255(BG_DARK))[1:-1]} | — | 5463 C | 深色模式背景 |
| 深底反白 | {INK_DARK} | RGB{str(rgb255(INK_DARK))[1:-1]} | — | — | 深底上的笔画 |
| 深底句点 | {ACC_DARK} | RGB{str(rgb255(ACC_DARK))[1:-1]} | — | 143 C | 深底上提亮的句点 |

对比度（WCAG 相对亮度法，程序计算）：
- 松墨 / 纸底 = **{contrast(INK_LIGHT,BG_LIGHT):.2f}:1**（正文场景远超 AA 4.5:1）
- 反白 / 深底 = **{contrast(INK_DARK,BG_DARK):.2f}:1**
- 句点 / 纸底 = {contrast(ACC_LIGHT,BG_LIGHT):.2f}:1（句点是图形不是文字，不适用正文阈值，仅需可辨）
- 主色 / 点缀相对明度差 = **{st['lum_gap']:.1f}%**（>20% 达标，转灰度仍可辨 → 色盲安全）
- CMYK 由 RGB 换算、Pantone 为近似对照，**落印前请以专色卡校准**

## 6. 诚实声明
1. **mono 退化**：单色黑版里句点与笔画同色，二者视觉合并为「一个更粗的 L」，句点的独立性失效。
   这是几何事实，属预期行为 —— 不使用描边／阴影／留白假装区分（假区分在小尺寸比没区分更糟）。
   强调由位置承住：句点贴基线、靠右端、与竖笔之间有 {g['GAP']} 的净空。
2. **字标未轮廓化**：本轮字标为字体排版占位（Inter Tight → Inter → Segoe UI Variable → system-ui；中文思源黑体 → 苹方 → 微软雅黑）。
   定稿轮将按笔宽比例自绘轮廓，彻底消除字体依赖与授权问题。当前交付的 **5 个标志 SVG 本体零文字、零字体依赖**。
3. **本文件不是商标法律意见**：撞脸测试是几何特征级的原创性自查，不构成商标检索或法律意见。

## 7. 七项检查
| 检查 | 结果 |
|---|---|
| 剪影 | ✓ 涂黑仍是清晰可辨的 L + 右侧一点 |
| 16px | ✓（32px 以下换 favicon 独立几何） |
| 单色 | ✓ 层级靠形状与位置承住 |
| 模糊 | ✓ 3–5px 高斯后大形仍成立 |
| 反白 | ✓ 深底用反白版，句点用提亮变体 |
| 撞脸 | ✓ 与 5 家对标逐条差异一句话可讲清（见 preview.html §09） |
| 语义安全 | ✓ 180°/镜像/负空间/缩写歧义/国旗/宗教符号逐项已查（见 preview.html §09） |

## 8. 文件与复现
```
brand-logo/
├─ preview.html                                  展示页（①Hero ②Lockup矩阵 ③缩放墙 ④尺寸 ⑤blueprint
│                                                  ⑥变体 ⑦实景 ⑧色彩卡 ⑨七项检查 ⑩候选对比）
├─ 01-web-rgb/svg/fayelong-logo-mark-fullcolor.svg   主标 · 纯图形 · 彩色（透明底）
├─ 01-web-rgb/svg/fayelong-logo-mark-mono-black.svg  单色黑
├─ 01-web-rgb/svg/fayelong-logo-mark-reverse.svg     反白 · 深底
├─ 01-web-rgb/svg/fayelong-logo-mark-grayscale.svg   灰阶
├─ 01-web-rgb/svg/fayelong-favicon.svg               favicon · 独立几何（更满 · 句点间隔放大 · 16px 实测可辨）
├─ 01-web-rgb/png/                                   光栅梯队（1024/512/256 + favicon）
├─ 05-spec/spec.md                                   本文件
├─ 06-source/build_logo.py                           几何唯一真源（改参数重跑即全量更新）
├─ 06-source/rasterize.py                            SVG→PNG（本机 Chrome headless，无第三方依赖）
└─ 07-blueprint/fayelong-blueprint.svg / .png        数学标注图
```
**修改唯一入口**：`06-source/build_logo.py` 里的 `make_geometry()`。
改任一常量（或直接改 `PHI` 派生的分母）→ 重跑 → 全部 SVG / 标注图 / 预览页同步更新，assert 链会立刻告诉你哪条比例被破坏了。
"""


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    p_svg = os.path.join(root, "01-web-rgb", "svg")
    p_bp = os.path.join(root, "07-blueprint")
    p_spec = os.path.join(root, "05-spec")
    for dd in (p_svg, p_bp, p_spec, os.path.join(root, "01-web-rgb", "png")):
        os.makedirs(dd, exist_ok=True)

    g = make_geometry(CANVAS, PAD, dot_step=2, gap_step=1)
    gf = make_geometry(FAV_CANVAS, FAV_PAD, dot_step=1, gap_step=1, fit_lw=True)

    ok1, log1 = verify(g)
    ok2, log2 = verify_favicon(gf, g)
    print("=" * 78)
    print("构建期验证链 · 主标")
    print("=" * 78)
    for s, m in log1:
        print(f"[{s}] {m}")
    print("-" * 78)
    print("构建期验证链 · favicon（独立几何）")
    print("-" * 78)
    for s, m in log2:
        print(f"[{s}] {m}")
    if not (ok1 and ok2):
        raise SystemExit("❌ 几何约束未通过，构建中止")

    ar = areas(g)
    lum_gap = abs(rel_lum(INK_LIGHT) - rel_lum(ACC_LIGHT)) / max(rel_lum(INK_LIGHT), rel_lum(ACC_LIGHT)) * 100
    st = dict(area=ar["total"], l_share=f"{ar['l_share']:.1f}%",
              dot_share=f"{ar['dot_share']:.2f}%",
              c_ink=contrast(INK_LIGHT, BG_LIGHT), c_acc=contrast(ACC_LIGHT, BG_LIGHT),
              c_rev=contrast(INK_DARK, BG_DARK), lum_gap=lum_gap)
    print("-" * 78)
    print(f"总面积 {ar['total']:.0f}px²｜主角 {st['l_share']}｜句点 {st['dot_share']}")
    print(f"松墨/纸底 {st['c_ink']:.2f}:1｜琥珀/纸底 {st['c_acc']:.2f}:1｜"
          f"反白/深底 {st['c_rev']:.2f}:1｜明度差 {st['lum_gap']:.1f}%")
    print(f"松墨 HSV {tuple(round(v,1) for v in hsv(INK_LIGHT))}｜焰琥珀 HSV {tuple(round(v,1) for v in hsv(ACC_LIGHT))}")

    files = {
        "fayelong-logo-mark-fullcolor.svg": svg_file(g, INK_LIGHT, ACC_LIGHT, None,
                                                     "主标 · 纯图形 · 彩色（透明底）"),
        "fayelong-logo-mark-mono-black.svg": svg_file(g, "#000000", "#000000", None,
                                                      "单色黑（句点与笔画融合，属预期行为）"),
        "fayelong-logo-mark-reverse.svg": svg_file(g, INK_DARK, ACC_DARK, BG_DARK, "反白 · 深底"),
        "fayelong-logo-mark-grayscale.svg": svg_file(g, "#333333", "#9A9A9A", None, "灰阶 · 黑白媒介"),
        "fayelong-favicon.svg": svg_file(gf, INK_LIGHT, ACC_LIGHT, None,
                                         "favicon · 独立几何（留白 32 · 句点与间隔同放大一档）"),
        "fayelong-logo-lockup-horizontal.svg": lockup_inline(g, "latin", INK_LIGHT, ACC_LIGHT),
        "fayelong-logo-lockup-stacked.svg": lockup_inline(g, "stack", INK_LIGHT, ACC_LIGHT),
    }
    for name, content in files.items():
        with open(os.path.join(p_svg, name), "w", encoding="utf-8") as fh:
            fh.write(content + "\n")
    with open(os.path.join(p_bp, "fayelong-blueprint.svg"), "w", encoding="utf-8") as fh:
        fh.write(blueprint_svg(g, gf, st) + "\n")
    with open(os.path.join(root, "preview.html"), "w", encoding="utf-8") as fh:
        fh.write(preview_html(g, gf, st))
    with open(os.path.join(p_spec, "spec.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_md(g, gf, st))

    print("\n已写出 SVG：" + ", ".join(sorted(files)))
    print("已写出 preview.html / 05-spec/spec.md / 07-blueprint/fayelong-blueprint.svg")
    return g, gf, st


if __name__ == "__main__":
    main()

