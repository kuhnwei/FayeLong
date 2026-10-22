# -*- coding: utf-8 -*-
"""
把 SVG（或 HTML）光栅化为 PNG —— 无第三方依赖，走本机 Chrome headless。
用途：① 交付 PNG 梯队 ② blueprint 光栅化 ③ 压力测试用图（模糊/剪影/单色）
用法：python rasterize.py <输入.svg|.html> <输出.png> <宽> <高>
                        [--bg=#FFF] [--blur=4] [--mono=black|white]
"""
import os
import subprocess
import sys
import tempfile

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _page(src, w, h, bg=None, blur=None, mono=None):
    if src.lower().endswith(".html"):
        with open(src, encoding="utf-8") as fh:
            return fh.read()
    with open(src, encoding="utf-8") as fh:
        svg = fh.read()
    svg = svg.split("-->", 1)[-1].strip() if svg.lstrip().startswith("<!--") else svg
    css = ["html,body{margin:0;padding:0;background:transparent}",
           f"svg{{display:block;width:{w}px;height:{h}px}}"]
    if bg:
        css.append(f"body{{background:{bg}}}")
    if blur:
        css.append(f"svg{{filter:blur({blur}px)}}")
    if mono == "black":
        css.append("svg path{fill:#000 !important}")
    elif mono == "white":
        css.append("svg path{fill:#fff !important}")
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            + "".join(css) + "</style></head><body>" + svg + "</body></html>")


def rasterize(src, out_png, w, h, bg=None, blur=None, mono=None):
    out_png = os.path.abspath(out_png)
    tmp = tempfile.mkdtemp(prefix="fyl-raster-")
    page = os.path.join(tmp, "page.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(_page(src, w, h, bg, blur, mono))
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--hide-scrollbars", "--force-device-scale-factor=1",
           "--virtual-time-budget=3000",
           f"--user-data-dir={os.path.join(tmp, 'profile')}",
           f"--window-size={w},{h}", f"--screenshot={out_png}",
           "file:///" + page.replace("\\", "/")]
    import time
    for _ in range(3):                      # Chrome 首启偶发不落盘 / 落盘滞后 → 重试 + 轮询
        if os.path.exists(out_png):
            os.remove(out_png)
        subprocess.run(cmd, capture_output=True)
        for _ in range(80):                 # 最多等 8s
            if os.path.exists(out_png) and os.path.getsize(out_png) > 100:
                return out_png
            time.sleep(0.1)
    raise RuntimeError(f"光栅化失败：{out_png}")


if __name__ == "__main__":
    a = sys.argv[1:]
    kw = {k.split("=")[0].lstrip("-"): k.split("=", 1)[1]
          for k in a if k.startswith("--") and "=" in k}
    pos = [k for k in a if not k.startswith("--")]
    rasterize(pos[0], pos[1], int(pos[2]), int(pos[3]), bg=kw.get("bg"),
              blur=float(kw["blur"]) if "blur" in kw else None, mono=kw.get("mono"))
    print("ok", pos[1])
