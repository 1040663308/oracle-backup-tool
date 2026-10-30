# -*- coding: utf-8 -*-
"""生成应用图标 assets/icon.ico（数据库 + 向下箭头 = 备份）"""
import os
import sys

from PIL import Image, ImageDraw

SIZE = 1024  # 超采样画布


def lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rounded_rect(draw, box, radius, color):
    draw.rounded_rectangle(box, radius=radius, fill=color)


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 渐变圆角背景
    top_color = (37, 99, 235)    # #2563EB
    bottom_color = (30, 58, 138)  # #1E3A8A
    pad = 40
    steps = 256
    for i in range(steps):
        t = i / (steps - 1)
        y0 = pad + (SIZE - 2 * pad) * i / steps
        y1 = pad + (SIZE - 2 * pad) * (i + 1) / steps + 1
        d.rectangle([pad, y0, SIZE - pad, y1], fill=lerp_color(top_color, bottom_color, t))
    # 圆角化：用蒙版
    mask = Image.new("L", (SIZE, SIZE), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([pad, pad, SIZE - pad, SIZE - pad], radius=180, fill=255)
    bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bg.paste(img, (0, 0), mask)
    img = bg
    d = ImageDraw.Draw(img)

    # ---- 数据库圆柱 ----
    cx = SIZE / 2
    cyl_w = 560
    top_y = 180
    bot_y = 700
    ellipse_h = 130
    x1, x2 = cx - cyl_w / 2, cx + cyl_w / 2
    white = (255, 255, 255, 245)
    shade = (219, 234, 254, 255)  # 浅蓝侧面

    # 圆柱主体
    d.rectangle([x1, top_y + ellipse_h / 2, x2, bot_y], fill=shade)
    # 中间两条横带（数据库层次感）
    band_y1 = top_y + (bot_y - top_y) * 0.36
    band_y2 = top_y + (bot_y - top_y) * 0.66
    d.ellipse([x1, band_y1 - ellipse_h / 2, x2, band_y1 + ellipse_h / 2],
              outline=(147, 197, 253, 255), width=14)
    d.ellipse([x1, band_y2 - ellipse_h / 2, x2, band_y2 + ellipse_h / 2],
              outline=(147, 197, 253, 255), width=14)
    # 底部椭圆（后半）
    d.ellipse([x1, bot_y - ellipse_h / 2, x2, bot_y + ellipse_h / 2],
              fill=(191, 219, 254, 255))
    # 顶部椭圆
    d.ellipse([x1, top_y - ellipse_h / 2, x2, top_y + ellipse_h / 2], fill=white)

    # ---- 向下箭头（备份到本地） ----
    arrow_top = 760
    arrow_cx = cx
    shaft_w = 90
    head_w = 220
    head_h = 170
    shaft_bottom = arrow_top + 130
    d.rectangle([arrow_cx - shaft_w / 2, arrow_top,
                 arrow_cx + shaft_w / 2, shaft_bottom], fill=white)
    d.polygon([
        (arrow_cx - head_w / 2, shaft_bottom),
        (arrow_cx + head_w / 2, shaft_bottom),
        (arrow_cx, shaft_bottom + head_h),
    ], fill=white)

    return img


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(os.path.dirname(here), "assets")
    os.makedirs(assets, exist_ok=True)
    img = draw_icon()
    out = os.path.join(assets, "icon.ico")
    img.resize((256, 256), Image.LANCZOS).save(
        out, format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # 同时输出 PNG 备用
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(assets, "icon.png"))
    print("图标已生成:", out)


if __name__ == "__main__":
    sys.exit(main())
