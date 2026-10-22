# -*- coding: utf-8 -*-
"""从用户提供的吉祥物图生成网站 Logo 资产。
步骤：① 按行/列投影找到吉祥物主体（自动剔除底部「faye long」文字）
     ② 从边界洪泛填充把米白背景抠成透明（体内高光被深棕描边包住，不会误伤）
     ③ 输出：页眉透明 PNG（紧贴裁剪）+ favicon（方形白底，多尺寸 ICO/PNG）
"""
import os
from collections import deque

from PIL import Image

SRC = r"C:\Users\kuhn\.workbuddy\clipboard-images\clipboard-2026-10-15T15-08-33-067Z-aaecfd28.jpg"
OUT = r"D:\code\FayeLong\frontend\public"

TOL = 46          # 背景判定：与背景色的 RGB 欧氏距离
GAP = 18          # 行/列投影中判定「两块内容之间有空隙」的最小空白行数


def dist2(c, ref):
    return (c[0] - ref[0]) ** 2 + (c[1] - ref[1]) ** 2 + (c[2] - ref[2]) ** 2


def bands(profile, gap):
    """把 1 维投影切成内容带，返回 [(start, end)]（end 不含）。"""
    out, s = [], None
    empty = 0
    for i, v in enumerate(profile):
        if v > 0:
            if s is None:
                s = i
            empty = 0
        else:
            if s is not None:
                empty += 1
                if empty >= gap:
                    out.append((s, i - empty + 1))
                    s = None
    if s is not None:
        out.append((s, len(profile)))
    return out


def main():
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    px = im.load()

    # ── 背景色 = 四边中位数 ──
    border = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)] + \
             [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
    border.sort(key=lambda c: sum(c))
    bg = border[len(border) // 2]
    print(f"原图 {w}×{h}，背景色 ≈ #{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}")

    lim = TOL * TOL
    is_fg = [[dist2(px[x, y], bg) > lim for x in range(w)] for y in range(h)]

    # ── 行投影 → 内容带（最上面那块大带 = 吉祥物；下面的带 = 文字，丢弃） ──
    row = [sum(1 for x in range(w) if is_fg[y][x]) for y in range(h)]
    rb = bands(row, GAP)
    rb = [b for b in rb if b[1] - b[0] > 8]
    print("行带：", rb)
    top = max(rb, key=lambda b: (b[1] - b[0]) * sum(row[b[0]:b[1]]))
    if len(rb) > 1:
        dropped = [b for b in rb if b != top]
        print(f"丢弃内容带（含底部文字）：{dropped}")

    # ── 在主体带内做列投影裁剪 ──
    col = [sum(1 for y in range(top[0], top[1]) if is_fg[y][x]) for x in range(w)]
    cb = [b for b in bands(col, GAP) if b[1] - b[0] > 8]
    print("列带：", cb)
    left, right = cb[0][0], cb[-1][1]
    # 行向再收一次（去顶部/底部零散噪点）
    rows = [y for y in range(top[0], top[1]) if any(is_fg[y][x] for x in range(left, right))]
    y0, y1 = rows[0], rows[-1] + 1
    print(f"主体裁剪框：x {left}..{right}  y {y0}..{y1}")

    # ── 洪泛填充抠背景（从裁剪框边界向内） ──
    cw, ch = right - left, y1 - y0
    alpha = [[255] * cw for _ in range(ch)]
    seen = [[False] * cw for _ in range(ch)]
    q = deque()
    for x in range(cw):
        for y in (0, ch - 1):
            q.append((x, y))
    for y in range(ch):
        for x in (0, cw - 1):
            q.append((x, y))
    n_bg = 0
    while q:
        x, y = q.popleft()
        if seen[y][x]:
            continue
        seen[y][x] = True
        if dist2(px[left + x, y0 + y], bg) > lim:
            continue                     # 撞到前景，停
        alpha[y][x] = 0
        n_bg += 1
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < cw and 0 <= ny < ch and not seen[ny][nx]:
                q.append((nx, ny))
    print(f"背景像素 {n_bg} / {cw*ch}（{(n_bg/(cw*ch))*100:.1f}%）")

    # ── 边缘羽化：与透明区相邻的前景像素，按与背景色的距离给中间 alpha ──
    soft_lo, soft_hi = lim * 4, lim * 16      # 距离² 的软过渡区间
    feather = 0
    for y in range(ch):
        for x in range(cw):
            if alpha[y][x] == 0:
                continue
            edge = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < cw and 0 <= ny < ch and alpha[ny][nx] == 0:
                    edge = True
                    break
            if edge:
                d = dist2(px[left + x, y0 + y], bg)
                if d < soft_hi:
                    a = max(0, min(255, int(255 * (d - soft_lo) / (soft_hi - soft_lo))))
                    if a < alpha[y][x]:
                        alpha[y][x] = a
                        feather += 1
    print(f"羽化像素 {feather}")

    out = Image.new("RGBA", (cw, ch))
    op = out.load()
    for y in range(ch):
        for x in range(cw):
            c = px[left + x, y0 + y]
            op[x, y] = (c[0], c[1], c[2], alpha[y][x])

    os.makedirs(OUT, exist_ok=True)
    out.save(os.path.join(OUT, "logo.png"), optimize=True)
    print(f"logo.png（透明 · 紧贴裁剪）{out.size}")

    # ── favicon：方形白底，主体占 84% ──
    S = 512
    sq = Image.new("RGBA", (S, S), (255, 255, 255, 255))
    scale = S * 0.84 / max(out.size)
    m = out.resize((max(1, round(out.size[0] * scale)), max(1, round(out.size[1] * scale))), Image.LANCZOS)
    sq.alpha_composite(m, ((S - m.size[0]) // 2, (S - m.size[1]) // 2))
    rgb = sq.convert("RGB")
    rgb.save(os.path.join(OUT, "apple-touch-icon.png"), optimize=True)          # 512（180 由浏览器缩放）
    sq.resize((32, 32), Image.LANCZOS).save(os.path.join(OUT, "favicon-32.png"), optimize=True)
    sq.resize((16, 16), Image.LANCZOS).save(os.path.join(OUT, "favicon-16.png"), optimize=True)
    sq.resize((48, 48), Image.LANCZOS).save(
        os.path.join(OUT, "favicon.ico"),
        sizes=[(16, 16), (32, 32), (48, 48)], append_images=[
            sq.resize((16, 16), Image.LANCZOS), sq.resize((32, 32), Image.LANCZOS)], optimize=True)
    print("favicon.ico(16/32/48) + favicon-32/16.png + apple-touch-icon.png 已写出")

    # 校验：透明图边缘应无白色残留（四角 alpha=0）
    corners = [op[0, 0], op[cw - 1, 0], op[0, ch - 1], op[cw - 1, ch - 1]]
    assert all(c[3] == 0 for c in corners), f"四角未透明：{corners}"
    print("四角透明 ✓")


if __name__ == "__main__":
    main()
