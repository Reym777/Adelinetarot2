from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

SRC = Path(r"c:\Users\eymer\PYTHON DOCS\Adelinemagica\ChatGPT_Image_15_juil._2026__11_14_53-removebg-preview.png")
OUT_DIR = Path(r"c:\Users\eymer\PYTHON DOCS\Adelinemagica\assets\images\zodiac")

SIGNS = [
    "aries",
    "tauro",
    "geminis",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "escorpio",
    "sagitario",
    "capricornio",
    "acuario",
    "piscis",
]

COL_BOUNDS = [(17, 113), (140, 232), (262, 352), (386, 475)]
ROW_BOUNDS = [(17, 166), (189, 338), (359, 486)]

GOLD = (232, 198, 107)
ALPHA_THRESHOLD = 1
SYMBOL_MAX_SIZE = (320, 320)
ANIMAL_MAX_SIZE = (440, 440)


def content_bbox(img: Image.Image, alpha_threshold: int = ALPHA_THRESHOLD):
    pix = img.load()
    w, h = img.size
    min_x, min_y = w, h
    max_x, max_y = -1, -1
    for y in range(h):
        for x in range(w):
            if pix[x, y][3] > alpha_threshold:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < min_x or max_y < min_y:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def alpha_components(img: Image.Image, alpha_threshold: int = ALPHA_THRESHOLD):
    w, h = img.size
    pix = img.load()
    visited = [[False] * w for _ in range(h)]
    out = []

    for y in range(h):
        for x in range(w):
            if visited[y][x] or pix[x, y][3] <= alpha_threshold:
                continue

            stack = [(x, y)]
            visited[y][x] = True
            min_x, max_x = x, x
            min_y, max_y = y, y
            count = 0

            while stack:
                cx, cy = stack.pop()
                count += 1
                if cx < min_x:
                    min_x = cx
                if cx > max_x:
                    max_x = cx
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy

                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h:
                        continue
                    if visited[ny][nx]:
                        continue
                    if pix[nx, ny][3] <= alpha_threshold:
                        continue
                    visited[ny][nx] = True
                    stack.append((nx, ny))

            out.append(
                {
                    "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                    "area": count,
                    "w": (max_x - min_x + 1),
                    "h": (max_y - min_y + 1),
                    "cy": (min_y + max_y) / 2,
                }
            )

    return out


def recolor_gold(img: Image.Image):
    pix = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pix[x, y]
            if a > 0:
                pix[x, y] = (GOLD[0], GOLD[1], GOLD[2], a)
    return img


def enhance_and_scale(img: Image.Image, max_size, sharp_radius: float, sharp_percent: int, sharp_threshold: int):
    out = ImageOps.contain(img, max_size, method=Image.LANCZOS)
    out = out.filter(
        ImageFilter.UnsharpMask(
            radius=sharp_radius,
            percent=sharp_percent,
            threshold=sharp_threshold,
        )
    )
    return out


def crop_y_band(img: Image.Image, y0: int, y1: int, pad: int = 4):
    w, h = img.size
    y0 = max(0, y0 - pad)
    y1 = min(h, y1 + pad)
    band = img.crop((0, y0, w, y1))
    bbox = content_bbox(band)
    if not bbox:
        return band
    return band.crop(bbox)


def crop_bbox(img: Image.Image, bbox, pad: int = 3):
    w, h = img.size
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    part = img.crop((x0, y0, x1, y1))
    b = content_bbox(part)
    if b:
        part = part.crop(b)
    return part


def largest_component_crop(img: Image.Image, min_cy_ratio: float = 0.0, pad: int = 4):
    comps = [c for c in alpha_components(img) if c["area"] >= 14]
    if min_cy_ratio > 0:
        comps = [c for c in comps if c["cy"] >= img.size[1] * min_cy_ratio]
    if not comps:
        b = content_bbox(img)
        if not b:
            return img
        return crop_bbox(img, b, pad=pad)
    best = max(comps, key=lambda c: c["area"])
    return crop_bbox(img, best["bbox"], pad=pad)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    src = Image.open(SRC).convert("RGBA")
    cols = 4
    for i, sign in enumerate(SIGNS):
        row = i // cols
        col = i % cols

        x0, x1 = COL_BOUNDS[col]
        y0, y1 = ROW_BOUNDS[row]

        cell = src.crop((x0, y0, x1, y1))

        ch = cell.size[1]
        symbol_band = cell.crop((0, 0, cell.size[0], max(1, int(ch * 0.34))))
        animal_band = cell.crop((0, int(ch * 0.20), cell.size[0], max(int(ch * 0.90), int(ch * 0.20) + 1)))

        symbol_img = largest_component_crop(symbol_band, min_cy_ratio=0.0, pad=3)
        animal_img = largest_component_crop(animal_band, min_cy_ratio=0.20, pad=4)

        symbol_img = recolor_gold(symbol_img)
        animal_img = recolor_gold(animal_img)

        symbol_img = enhance_and_scale(symbol_img, SYMBOL_MAX_SIZE, sharp_radius=2.2, sharp_percent=260, sharp_threshold=1)
        animal_img = enhance_and_scale(animal_img, ANIMAL_MAX_SIZE, sharp_radius=1.3, sharp_percent=130, sharp_threshold=2)

        symbol_img.save(OUT_DIR / f"{sign}-symbol.png")
        animal_img.save(OUT_DIR / f"{sign}-animal.png")

    print(f"Generated assets in: {OUT_DIR}")


if __name__ == "__main__":
    main()
