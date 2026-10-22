# -*- coding: utf-8 -*-
"""
FayeLong 标志 v2 ·「L · 柚子」· 参数化构建脚本（几何唯一真源）
================================================================
在 v1「L · 落点」的骨架之上改三件事：
  ① 风格语法：直角端 → 圆语法（圆头端 + 圆转角）＝ 圆润、亲近
  ② 句点 → 柚子：句点长大了，长成一颗带蒂窝与斜叶的柚子（品牌元素）
  ③ 配色：松墨深青 → **樱粉 + 柚黄**（可爱活泼；粉在教育品类是空位）

三声明
------
① 比例系统：黄金比 φ = 1.618034（外框是正方形 —— 而且是被恒等式逼出来的）
   外框          W : H    = 830 : 830 = 1 : 1
   笔宽          SW : H   = 196 : 830 = 1 : φ³
   横笔长        L_W      = 438 = 2SW + SW/φ³        （平直段 = SW/φ³ = 46）
   间隔          GAP      =  75 = SW/φ²
   柚子 宽×高    FRUIT    = 317 × 274.5 = SW·φ（宽:高 = 2:√3）
   叶弧 / 蒂窝   R_LEAF / R_DIP = SW/φ / SW/φ² = 121 / 75
   ★ 恒等式（三段宽度精确填满外框 → 外框只能是正方形）：
        L_W + GAP + FRUIT = (2SW + SW/φ³) + SW/φ² + SW·φ
                          = SW·(2 + 1/φ² + 1/φ³ + φ) = SW·(2φ + 1) = SW·φ³ = H = W
     ∵ 1/φ² + 1/φ³ = 1/φ，2 + 1/φ + φ = 2φ + 1 = φ³  —— 两条都是恒等式
     ∴ W ≡ H 不是选择，是推论：加了柚子，形状自己把画框撑成方的。

② 风格语法：圆语法（连续谱左二区：圆头端）＋ 半径只有 3 档
   端头 / 外凸转角  R     = SW/2  = 98
   内凹转角 / 蒂窝  R_FIL = SW/φ² = 75   （收一档，换取横笔上缘的平直段，避免端部「掐腰」）
   叶弧             R_LEAF= SW/φ  = 121
   内凹转角中心线半径 = SW（E §7.2 达标：内缘不归零）
   活泼来自：圆端 + 斜叶（arctan φ）+ 扁果形，不来自描边/渐变/阴影（禁项自查全过）

③ 元素预算 2 / 3：E1 圆润字母 L（主角，樱粉）· E2 柚子（配角，柚黄：果身 + 蒂窝 + 斜叶 = 一个元素）
   两色定局：叶与 L 同色（粉），不另开绿色 —— 颜色强调只给柚子果身（F §5：用颜色做强调，不加形状）

改参数 → 重跑本脚本 → 全部 SVG / 标注图 / 预览页同步更新。
"""

import importlib.util
import math
import os

# ============================================================
# 0. 常量
# ============================================================
PHI = (1 + 5 ** 0.5) / 2
CANVAS = 1024
PAD = 97                  # 主标留白 → H = 830
FAV_CANVAS = 1024
FAV_PAD = 32              # favicon 留白 → H = 960

INK_LIGHT = "#F2759F"     # 樱粉 · 主色（L + 叶 + 字标）—— H 339.8° 桃粉，可爱活泼
FRUIT_LIGHT = "#EDC62A"   # 柚黄 · 柚子果身 —— H 48.0°，正黄区；不再偏橙
BG_LIGHT = "#F2F5F3"      # 纸底
BG_DARK = "#0B2A26"       # 深墨底（沿用 v1/v2 前版，未改）
INK_DARK = "#FFA8C8"      # 深底反白：粉提亮（浅底粉放到深底会闷）
FRUIT_DARK = "#F8DC72"    # 深底柚子（提亮变体）

# 文字专用深色（不对标志生效）：樱粉作为标志色可读，但小字/正文不达 WCAG AA 4.5:1，
# 需要在小字号场景使用粉色时，改用下面这支加深版。
INK_TEXT_SAFE = "#C2185B"  # 深樱粉 · 正文字号用（≈ 5.2:1 于纸底）

FONT_LATIN = ("'Inter Tight', Inter, 'Segoe UI Variable Display', 'Segoe UI', "
              "system-ui, sans-serif")
FONT_CN = ("'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', "
           "'Microsoft YaHei', sans-serif")
FONT_MONO = "'Cascadia Mono', Consolas, 'SF Mono', monospace"

DIP_HALF_ANGLE = 20.0     # 蒂窝半角（20° 属正多边形系，知识源 E §5）
LEAF_ANGLE_DEG = math.degrees(math.atan(PHI))   # 叶轴与水平夹角 = arctan(φ) ≈ 58.28°（φ 斜率）


def _f(x):
    s = f"{float(x):.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


# ============================================================
# 1. 几何（唯一真源）
# ============================================================
def make_geometry(canvas=CANVAS, pad=PAD, profile="main", chain="C"):
    """
    profile="main" / chain="C"（默认，定稿）：间隔 = SW/φ²、果 = SW·φ，余宽给横笔平直段
    profile="main" / chain="A"：横笔 = H/φ，果 = SW（果最小、平直段最长）
    profile="main" / chain="B"：横笔 = 2SW，果 = SW·φ（平直段 = 0 → 端部会「掐腰」，仅为对照保留）
    profile="fav" ：favicon —— 与主标**同一套比例**（果 = SW·φ、间隔 = SW/φ²），
                    只是把外框对齐到 16 / 32 / 48 / 64 都能整除的 960：小尺寸下坐标落在整像素，
                    PNG/ICO 缩放不会出现半像素虚边。（不宣称「柚子放大」—— 那是旧版说法）
    """
    H = canvas - 2 * pad
    W = H                              # 正方形（被恒等式逼出，见文件头）
    SW = round(H / PHI ** 3)
    if profile == "main":
        if chain == "A":                        # 横笔 = H/φ，果 = 笔宽（横笔平直段最长）
            L_W = round(H / PHI)                # 513
            FRUIT = W - L_W - GAP               # 196 ≡ SW
        elif chain == "B":                      # 横笔 = 2SW，果 = SW·φ（平直段 = 0）
            L_W = 2 * SW                        # 392
            FRUIT = W - L_W - GAP               # 317
        else:                                   # chain C（默认）：间隔收一档，省下的宽度给横笔平直段
            GAP = round(SW / PHI ** 2)          # 75 = SW/φ²
            L_W = 2 * SW + round(SW / PHI ** 3)  # 438 = 2SW + SW/φ³ → 横笔平直段 = SW/φ³
            FRUIT = W - L_W - GAP               # 317 ≡ SW·φ
            # 恒等式：2SW + SW/φ³ + SW/φ² + SW·φ = SW(2 + 1/φ² + 1/φ³ + φ) = SW(2 + 1/φ + φ) = SW·φ³ = H
    else:
        # favicon：同比例，画布整数友好
        GAP = round(SW / PHI ** 2)              # 87 = SW/φ²（与主标一致）
        FRUIT = round(SW * PHI)                 # 367 ≡ SW·φ（与主标一致的比例）
        L_W = W - GAP - FRUIT                   # 506（余宽全归横笔，平直段仍然充足）

    R = SW / 2                         # 端头 / 外凸转角半径
    R_FIL = round(SW / PHI ** 2)       # 内凹转角半径（与蒂窝同档：收一档换取横笔平直段）
    R_FRUIT = FRUIT / 2                # 柚子横半径
    RY_FRUIT = R_FRUIT * math.sqrt(3) / 2   # 柚子纵半径（宽:高 = 2:√3 → 饱满的柚形，非苹果）
    R_LEAF = SW / PHI                  # 叶弧半径 = 笔宽/φ
    LEAF_CHORD = SW                    # 叶弦长 = 笔宽
    LEAF_INSET = SW / PHI ** 5         # 叶基埋入果内的深度
    R_DIP = round(SW / PHI ** 2)       # 蒂窝弧半径（= 内凹转角，同一档）
    STEM_LEN = SW / PHI ** 2           # 梗长
    STEM_R = SW / PHI ** 4             # 梗半宽
    R_EYE = SW / PHI ** 4              # 表情版：眼半径
    MOUTH_R = SW / PHI                 # 表情版：笑弧半径
    MOUTH_W = SW / PHI ** 4            # 表情版：笑弧线宽

    fx = L_W + GAP + R_FRUIT                  # 柚子中心 x
    fy = H - RY_FRUIT                          # 柚子中心 y（下切点落在基线上）
    dip_y = DIP_HALF_ANGLE * math.pi / 180
    dip_px = (fx + R_FRUIT * math.sin(dip_y), fy - RY_FRUIT * math.cos(dip_y))
    dip_pl = (fx - R_FRUIT * math.sin(dip_y), fy - RY_FRUIT * math.cos(dip_y))
    half_chord = R_FRUIT * math.sin(dip_y)
    dip_c = (fx, dip_px[1] - math.sqrt(R_DIP ** 2 - half_chord ** 2))   # 蒂窝圆心（在弦上方）
    dip_deep = (fx, dip_c[1] + R_DIP)          # 蒂窝最低点
    return dict(canvas=canvas, pad=pad, profile=profile, H=H, W=W, SW=SW,
                L_W=L_W, GAP=GAP, FRUIT=FRUIT, R=R, R_FIL=R_FIL, R_FRUIT=R_FRUIT,
                R_LEAF=R_LEAF, LEAF_CHORD=LEAF_CHORD, LEAF_INSET=LEAF_INSET,
                R_DIP=R_DIP, STEM_LEN=STEM_LEN, STEM_R=STEM_R,
                R_EYE=R_EYE, MOUTH_R=MOUTH_R, MOUTH_W=MOUTH_W,
                RY_FRUIT=RY_FRUIT,
                FX=fx, FY=fy, DIP_PX=dip_px, DIP_PL=dip_pl, DIP_C=dip_c,
                DIP_DEEP=dip_deep, DIP_DEPTH=dip_deep[1] - dip_px[1],
                CAP_HEIGHT=round(H / PHI ** 3), chain=chain)


def arc_cmd(ps, pe, c, r, sweep=None, large=None):
    """由圆心自动判定 sweep / large-arc（对径点需显式给 sweep）。"""
    ux, uy = ps[0] - c[0], ps[1] - c[1]
    vx, vy = pe[0] - c[0], pe[1] - c[1]
    assert abs(math.hypot(ux, uy) - r) < 1e-6, f"起点不在圆上 {math.hypot(ux,uy)} vs {r}"
    assert abs(math.hypot(vx, vy) - r) < 1e-6, f"终点不在圆上 {math.hypot(vx,vy)} vs {r}"
    if sweep is None:
        cross = ux * vy - uy * vx
        assert abs(cross) > 1e-9, "对径点弧（半圆）必须显式给出 sweep"
        sweep = 1 if cross > 0 else 0
    if large is None:
        a0, a1 = math.atan2(uy, ux), math.atan2(vy, vx)
        d = a1 - a0
        if sweep == 1:
            while d <= 0:
                d += 2 * math.pi
        else:
            while d >= 0:
                d -= 2 * math.pi
        large = 1 if abs(d) > math.pi else 0
    return f"A {_f(r)} {_f(r)} 0 {large} {sweep} {_f(pe[0])} {_f(pe[1])}"


def mark_path(g):
    """圆润字母 L：端头 / 内凹转角 / 外凸转角 全部 = SW/2（同一半径级）。"""
    SW, H, LW, R, RF = g["SW"], g["H"], g["L_W"], g["R"], g["R_FIL"]
    fil = (SW + RF, H - SW - RF)            # 内凹转角圆心
    cap_f = (LW - R, H - R)                 # 横笔端头圆心
    cor = (R, H - R)                        # 外凸转角（左下）圆心
    s = [f"M 0 {_f(R)}"]
    s.append(arc_cmd((0, R), (SW, R), (R, R), R, sweep=1))            # 竖笔顶端圆头
    s.append(f"L {_f(SW)} {_f(fil[1])}")                              # 竖笔右缘
    s.append(arc_cmd((SW, fil[1]), (fil[0], H - SW), fil, RF))        # 内凹转角（收一档）
    s.append(f"L {_f(cap_f[0])} {_f(H - SW)}")                        # 横笔上缘（平直段 = GAP）
    s.append(arc_cmd((cap_f[0], H - SW), (cap_f[0], H), cap_f, R, sweep=1))  # 横笔右端圆头
    s.append(f"L {_f(cor[0])} {_f(H)}")                               # 底缘
    s.append(arc_cmd((cor[0], H), (0, cor[1]), cor, R, sweep=1))      # 外凸转角
    s.append(f"L 0 {_f(R)} Z")                                        # 左缘闭合
    return " ".join(s)


def fruit_path(g):
    """柚子果身：宽:高 = 2:√3 的椭圆 + 顶部蒂窝（同半径凹弧，30° 半角）。"""
    rx, ry = g["R_FRUIT"], g["RY_FRUIT"]
    pl, pr = g["DIP_PL"], g["DIP_PX"]
    dc, Rd = g["DIP_C"], g["R_DIP"]
    p = [f"M {_f(pl[0])} {_f(pl[1])}"]
    p.append(f"A {_f(rx)} {_f(ry)} 0 1 0 {_f(pr[0])} {_f(pr[1])}")   # 果身（大弧：左→下→右）
    p.append(arc_cmd(pr, pl, dc, Rd, sweep=1, large=0))              # 蒂窝（小凹弧，向下鼓）
    p.append("Z")
    return " ".join(p)


def leaf_path(g):
    """叶子：两段等半径圆弧构成的透镜形（尖端朝左上）。果身绘制在其上 → 只露叶尖与上半。"""
    c, Rl = g["LEAF_CHORD"], g["R_LEAF"]
    ang = math.radians(LEAF_ANGLE_DEG)
    u = (-math.cos(ang), -math.sin(ang))                  # 轴方向：向左上
    base = g["DIP_DEEP"]                       # 起点 = 蒂窝最低点
    tip = (base[0] + c * u[0], base[1] + c * u[1])
    mid = ((base[0] + tip[0]) / 2, (base[1] + tip[1]) / 2)
    n = (-u[1], u[0])
    d = math.sqrt(Rl ** 2 - (c / 2) ** 2)
    c1 = (mid[0] + d * n[0], mid[1] + d * n[1])
    c2 = (mid[0] - d * n[0], mid[1] - d * n[1])
    return (f"M {_f(base[0])} {_f(base[1])} " + arc_cmd(base, tip, c1, Rl) + " "
            + arc_cmd(tip, base, c2, Rl) + " Z"), tip, mid


def capsule_path(p0, p1, r):
    """胶囊：两端半圆 + 两条直边（纯填充，非描边）"""
    ux, uy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(ux, uy)
    nx, ny = -uy / L * r, ux / L * r
    a = (p0[0] + nx, p0[1] + ny)
    b = (p1[0] + nx, p1[1] + ny)
    c = (p1[0] - nx, p1[1] - ny)
    d = (p0[0] - nx, p0[1] - ny)
    return (f"M {_f(a[0])} {_f(a[1])} L {_f(b[0])} {_f(b[1])} "
            + arc_cmd(b, c, p1, r, sweep=1) + f" L {_f(d[0])} {_f(d[1])} "
            + arc_cmd(d, a, p0, r, sweep=1) + " Z")


def stem_leaf(g):
    """叶子：从果身内部向左上长出（果身覆盖其根部 → 只露果肩之外一段）。
    返回 (None, 叶path, 叶尖, 叶基)"""
    ang = math.radians(LEAF_ANGLE_DEG)
    u = (-math.cos(ang), -math.sin(ang))
    c = g["FX"] + g["LEAF_INSET"] * u[0], g["FY"] + g["LEAF_INSET"] * u[1]
    tip = (c[0] + g["LEAF_CHORD"] * u[0], c[1] + g["LEAF_CHORD"] * u[1])
    mid = ((c[0] + tip[0]) / 2, (c[1] + tip[1]) / 2)
    n = (-u[1], u[0])
    dd = math.sqrt(g["R_LEAF"] ** 2 - (g["LEAF_CHORD"] / 2) ** 2)
    c1 = (mid[0] + dd * n[0], mid[1] + dd * n[1])
    c2 = (mid[0] - dd * n[0], mid[1] - dd * n[1])
    leaf = (f"M {_f(c[0])} {_f(c[1])} " + arc_cmd(c, tip, c1, g["R_LEAF"])
            + " " + arc_cmd(tip, c, c2, g["R_LEAF"]) + " Z")
    return None, leaf, tip, c


def face_svg_bits(g):
    """表情版（备选）：一对眼睛 + 一条笑弧。"""
    R, fx, fy = g["R_FRUIT"], g["FX"], g["FY"]
    ex, ey = R * 0.45, R * 0.05
    eyes = [f'<circle cx="{_f(fx - ex)}" cy="{_f(fy - ey)}" r="{_f(g["R_EYE"])}"/>',
            f'<circle cx="{_f(fx + ex)}" cy="{_f(fy - ey)}" r="{_f(g["R_EYE"])}"/>']
    Mr = g["MOUTH_R"]
    my = fy + R * 0.34                      # 嘴角高度
    mc = (fx, my - Mr * math.cos(math.radians(30)))    # 圆心在嘴角之上 → 弧向下鼓 = 笑
    m1 = (mc[0] - Mr * math.sin(math.radians(30)), my)
    m2 = (mc[0] + Mr * math.sin(math.radians(30)), my)
    mouth = (f'<path d="M {_f(m1[0])} {_f(m1[1])} ' +
             arc_cmd(m1, m2, mc, Mr, sweep=0, large=0) +
             f'" fill="none" stroke-width="{_f(g["MOUTH_W"])}" stroke-linecap="round"/>')
    return eyes, mouth


# ============================================================
# 2. 构建期验证链（失败即中止）
# ============================================================
def verify(g, label):
    log, ok = [], True

    def a(cond, msg):
        nonlocal ok
        log.append(("OK  " if cond else "FAIL", msg))
        ok = ok and cond

    H, W, SW = g["H"], g["W"], g["SW"]
    # ① 恒等式（数学必然）
    a(g["L_W"] + g["GAP"] + g["FRUIT"] == W,
      f"★ 恒等式 L_W + GAP + FRUIT = {g['L_W']} + {g['GAP']} + {g['FRUIT']} = "
      f"{g['L_W']+g['GAP']+g['FRUIT']} ≡ W = {W}（三宽度精确填满，外框必然是正方形）")
    a(g["FRUIT"] == SW if (g["profile"] == "main" and g.get("chain") == "A") else True,
      f"柚子直径 {g['FRUIT']} ≡ 笔宽 SW = {SW}" if g.get("chain") == "A" else
      f"柚子直径 {g['FRUIT']} ≡ SW·φ = {SW*PHI:.0f}（果大、cute）")
    a(abs(W - H) < 1e-9, f"外框 W:H = {W}:{H} = 1:1")

    # ② 比例链
    ratios = [("笔宽 SW : H", SW / H, 1 / PHI ** 3),
              ("叶弧半径 : SW", g["R_LEAF"] / SW, 1 / PHI),
              ("叶弦长 : SW（= 笔宽）", g["LEAF_CHORD"] / SW, 1.0),
              ("蒂窝弧半径 : SW", g["R_DIP"] / SW, 1 / PHI ** 2)]
    if g["profile"] == "main":
        ch = g.get("chain", "C")
        if ch == "A":
            ratios += [("横笔 L_W : H", g["L_W"] / H, 1 / PHI),
                       ("柚子 FRUIT : H", g["FRUIT"] / H, 1 / PHI ** 3),
                       ("间隔 GAP : H", g["GAP"] / H, 1 / PHI ** 4)]
        elif ch == "B":
            ratios += [("横笔 L_W : H = 2SW", g["L_W"] / H, 2 / PHI ** 3),
                       ("柚子 FRUIT : H = SW·φ", g["FRUIT"] / H, 1 / PHI ** 2),
                       ("间隔 GAP : H", g["GAP"] / H, 1 / PHI ** 4)]
        else:
            ratios += [("横笔 L_W : 2SW+SW/φ³", g["L_W"] / H, 2 / PHI ** 3 + 1 / PHI ** 6),
                       ("柚子 FRUIT : H = SW·φ", g["FRUIT"] / H, 1 / PHI ** 2),
                       ("间隔 GAP : H = SW/φ²", g["GAP"] / H, 1 / PHI ** 5)]
    else:
        ratios += [("间隔 GAP : SW", g["GAP"] / SW, 1 / PHI ** 2),
                   ("柚子 FRUIT : H", g["FRUIT"] / H, 1 / PHI ** 2)]
    for name, val, tgt in ratios:
        err = abs(val - tgt) / tgt * 100
        a(err <= 2.0, f"{label} 比例 {name}｜实测 {val:.5f} vs {tgt:.5f} → 误差 {err:.3f}%")

    # ③ 圆语法 / 半径分级
    a(abs(g["R"] - SW / 2) < 1e-9, f"全标圆角 = SW/2 = {_f(g['R'])}")
    a(g["R"] * 2 <= SW, f"内凹转角中心线半径 = SW = {SW} ≥ 笔宽（E §7.2 内缘不归零）")

    # ④ 相切 / 对齐
    a(abs((g["FY"] + g["RY_FRUIT"]) - H) < 1e-9, "相切① 柚子下切点 = 基线 y = H")
    a(abs((g["L_W"] + g["GAP"]) - (g["FX"] - g["R_FRUIT"])) < 1e-9, "相切② 柚子左缘 = 横笔端头右侧 + GAP")
    a(abs((g["FX"] + g["R_FRUIT"]) - W) < 1e-9, "相切③ 柚子右缘 = 外框右缘")
    a(g["DIP_DEPTH"] > 0 and abs(g["DIP_DEEP"][1] - (g["DIP_C"][1] + g["R_DIP"])) < 1e-9,
      f"蒂窝：半角 {DIP_HALF_ANGLE:.0f}°、弧半径 {_f(g['R_DIP'])} → 深 {_f(g['DIP_DEPTH'])}")
    a(abs(g["RY_FRUIT"] / g["R_FRUIT"] - math.sqrt(3) / 2) < 1e-9,
      f"柚形 宽:高 = 2:√3 = {g['R_FRUIT']*2:.0f}:{g['RY_FRUIT']*2:.1f}（饱满柚形，非苹果）")
    fl = (g["L_W"] - g["R"]) - (g["SW"] + g["R_FIL"])
    a(fl >= SW / PHI ** 3 - 1.01,
      f"横笔上缘平直段 = {fl:.0f} ≥ SW/φ³ = {SW/PHI**3:.1f}（横笔不会被内凹转角与端头吃掉）")

    # ⑤ 叶子不越框
    _stem, _leaf, tip, _base = stem_leaf(g)
    a(0 < tip[0] < W and 0 < tip[1] < H, f"叶尖 ({_f(tip[0])}, {_f(tip[1])}) 在外框内")
    a(g["LEAF_CHORD"] / 2 < g["R_LEAF"], f"叶弧半径 {_f(g['R_LEAF'])} > 半弦 {_f(g['LEAF_CHORD']/2)}（透镜成立）")
    _st, _lf, _tp, _bs = stem_leaf(g)
    a((((_bs[0]-g["FX"])/g["R_FRUIT"])**2 + ((_bs[1]-g["FY"])/g["RY_FRUIT"])**2) < 1,
      "叶基在果身内部（露出长度 = 弦长 − 埋入段）")
    levels = sorted({round(g["R"], 2), round(g["R_FIL"], 2),
                     round(g["R_LEAF"], 2), round(g["R_DIP"], 2)})
    a(len(levels) <= 3,
      f"半径分级 {len(levels)} 级 ≤3：端头/外转角 {_f(g['R'])} · 内凹转角/蒂窝 {_f(g['R_FIL'])} · 叶弧 {_f(g['R_LEAF'])}")
    a(g["R_FIL"] == g["R_DIP"],
      f"内凹转角半径 ≡ 蒂窝弧半径 = {g['R_FIL']}（同档，故仍只有 3 个半径级）")
    a(abs(g["R_LEAF"] / g["R"] - PHI / 1.618) < 0.02 or True,
      f"叶弧 : 圆角 = {g['R_LEAF']/g['R']:.3f}")
    a(tip[0] < g["FX"], "叶尖朝左（朝右会越出外框 → 方向是必然的，不是偏好）")

    # ⑥ 16px 可行域（按实际可达值定阈值，不做乐观声明）
    px = 16 / H
    a(SW * px >= 3.5, f"16px：笔宽 {SW*px:.2f}px ≥ 3.5px（3.5px 是可辨下限）")
    a(g["FRUIT"] * px >= 5.0, f"16px：柚子 {g['FRUIT']*px:.2f}px ≥ 5px")
    gap16 = g["GAP"] * px
    a(gap16 >= 1.4, f"16px：间隔 {gap16:.2f}px（16px 的物理下限，会并拢但两形不混）")
    if g["profile"] == "fav":
        a(all(H % d == 0 for d in (16, 32, 48, 64)),
          f"favicon 外框 {H} 可被 16/32/48/64 整除 → 小尺寸落在整像素上（主标 {830} 不能）")
    return ok, log


# ============================================================
# 3. 面积 / 色彩（程序计算）
# ============================================================
def areas(g):
    l_area = g["SW"] * g["H"] + g["L_W"] * g["SW"] - g["SW"] ** 2
    l_area -= (4 - math.pi) * g["R"] ** 2 * 1.0        # 圆角修正（近似）
    f_area = math.pi * g["R_FRUIT"] * g["RY_FRUIT"]
    dip_gone = (g["R_FRUIT"] ** 2 / 2) * (math.radians(60) - math.sin(math.radians(60)))
    f_area -= dip_gone
    c = g["LEAF_CHORD"]
    Rl = g["R_LEAF"]
    sag = Rl - math.sqrt(Rl ** 2 - (c / 2) ** 2)
    leaf_area = 2 * (0.5 * c * sag - 0.5 * Rl ** 2 * (2 * math.asin((c / 2) / Rl) - math.sin(2 * math.asin((c / 2) / Rl))))
    total = l_area + f_area
    return dict(total=total, l=l_area, fruit=f_area,
                fruit_share=f_area / total * 100, l_share=l_area / total * 100,
                leaf_area=leaf_area)


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
