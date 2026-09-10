import json
import re
from pathlib import Path
from urllib.parse import urljoin

import cv2
import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image
from playwright.sync_api import sync_playwright

OUTPUT = Path("portfolio.json")
IMAGE_DIR = Path("portfolio_images")
PORTFOLIO_VERSION = 3

MAIN_URL = "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink.aspx"

FUNDS = [
    ("penzpiaci-2016", "Pénzpiaci 2016 eszközalap"),
    ("hazai-kotveny", "Hazai kötvény eszközalap"),
    ("tallozo", "Tallózó abszolút hozam eszközalap"),
    ("vilagjaro-kotveny", "Világjáró kötvény eszközalap"),
    ("horizont-15", "Horizont 15+ vegyes eszközalap"),
    ("horizont-10", "Horizont 10+ vegyes eszközalap"),
    ("horizont-5", "Horizont 5+ vegyes eszközalap"),
    ("hazai-reszveny", "Hazai részvény eszközalap"),
    ("fejlodo-vilag", "Fejlődő világ részvény eszközalap"),
    ("fejlett-vilag", "Fejlett világ részvény eszközalap"),
    ("vilagmarkak", "Világmárkák részvény eszközalap"),
    ("innovacio", "Innováció részvény eszközalap"),
    ("fenntarthato", "Fenntartható Világ részvény eszközalap"),
    ("tudatos-fejlett", "Tudatos fejlett piac részvény eszközalap"),
    ("tavlat-fejlodo", "TávLat fejlődő piac részvény eszközalap"),
    ("kotveny-2027m", "Kötvény 2027/M árfolyamvédett eszközalap"),
    ("magyar-piac", "Magyar piac részvény eszközalap"),
    ("nemzetkozi-markak", "Nemzetközi márkák részvény eszközalap"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GeneraliFundTracker/3.0)"
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize(text):
    return clean(text).casefold()


def discover_links():
    response = requests.get(
        MAIN_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    wanted = {normalize(name): (fund_id, name) for fund_id, name in FUNDS}
    found = {}

    for a in soup.find_all("a", href=True):
        name = clean(a.get_text(" ", strip=True))
        key = normalize(name)

        if key in wanted:
            fund_id, canonical_name = wanted[key]
            found[fund_id] = {
                "id": fund_id,
                "name": canonical_name,
                "url": urljoin(MAIN_URL, a["href"]),
            }

    missing = [
        name for fund_id, name in FUNDS
        if fund_id not in found
    ]

    if missing:
        raise RuntimeError(
            "A Generali főoldaláról hiányzó linkek: "
            + ", ".join(missing)
        )

    return [found[fund_id] for fund_id, _ in FUNDS]


def extract_reference_index(text):
    # Elsőként a normál, látható szövegből próbáljuk.
    lines = [clean(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    for index, line in enumerate(lines):
        if "referenciaindex" not in line.casefold():
            continue

        value = re.sub(
            r"^.*?referenciaindex\s*:?\s*",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()

        if value and value.casefold() != "referenciaindex":
            return value

        for next_line in lines[index + 1:index + 5]:
            if next_line and "eszközalap" not in next_line.casefold():
                return next_line

    # Második próbálkozás a tömörített szövegből.
    compact = clean(text)
    match = re.search(
        r"Referenciaindex\s*:?\s*(.*?)(?="
        r"Eszközalap indulása|Ajánlott befektetési időtáv|"
        r"Hozamelvárás|Tőke-/|$)",
        compact,
        flags=re.IGNORECASE,
    )

    return clean(match.group(1)) if match else None


def find_donut_and_crop(full_path, output_path):
    image = cv2.imread(str(full_path))
    if image is None:
        return False

    height, width = image.shape[:2]

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # A Generali portfóliódiagram sokszínű szeleteit keressük.
    mask = cv2.inRange(
        hsv,
        np.array([0, 45, 55], dtype=np.uint8),
        np.array([179, 255, 255], dtype=np.uint8),
    )

    # Apró zajok eltávolítása.
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    count, labels, stats, centers = cv2.connectedComponentsWithStats(
        mask,
        8,
    )

    candidates = []

    for i in range(1, count):
        x, y, w, h, area = stats[i]

        if area < 2500:
            continue

        if y < 70:
            continue

        if w < 80 or h < 80:
            continue

        # A diagram kör alakú fő vizuálja közel négyzetes.
        ratio = w / max(h, 1)
        if ratio < 0.55 or ratio > 1.8:
            continue

        candidates.append(
            (int(area), x, y, w, h, centers[i])
        )

    if not candidates:
        return False

    candidates.sort(reverse=True, key=lambda item: item[0])

    area, x, y, w, h, center = candidates[0]
    cx, cy = center

    # A diagram körül hagyunk helyet a címkéknek és az alatta lévő
    # színmagyarázatnak is. Így nem csak a tortadiagramot mentjük.
    left = max(0, int(cx - 0.55 * width))
    right = min(width, int(cx + 0.55 * width))
    top = max(0, int(y - 110))
    bottom = min(height, int(y + h + 260))

    # Ha a teljes oldal nagyon hosszú, a diagram környezetét tartsuk
    # kezelhető méretben.
    if bottom - top > 1000:
        bottom = min(height, top + 1000)

    crop = image[top:bottom, left:right]

    if crop.size == 0:
        return False

    ok = cv2.imwrite(str(output_path), crop)
    return bool(ok and output_path.exists() and output_path.stat().st_size > 5000)


def save_dom_visual_fallback(page, output_path):
    candidates = []

    for selector in ["canvas", "svg", "img"]:
        elements = page.locator(selector).all()

        for element in elements:
            try:
                box = element.bounding_box()
                if not box:
                    continue

                w = box["width"]
                h = box["height"]

                if w < 250 or h < 140:
                    continue

                score = w * h

                attrs = " ".join(
                    filter(
                        None,
                        [
                            element.get_attribute("class"),
                            element.get_attribute("id"),
                            element.get_attribute("alt"),
                            element.get_attribute("src"),
                        ],
                    )
                ).casefold()

                if any(
                    word in attrs
                    for word in [
                        "portfol",
                        "chart",
                        "diagram",
                        "eszköz",
                        "eszkoz",
                    ]
                ):
                    score *= 5

                candidates.append((score, element))

            except Exception:
                continue

    candidates.sort(key=lambda item: item[0], reverse=True)

    if not candidates:
        return False

    try:
        candidates[0][1].screenshot(path=str(output_path))
        return (
            output_path.exists()
            and output_path.stat().st_size > 5000
        )
    except Exception:
        return False


def capture_portfolio(page, fund_id):
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    full_path = IMAGE_DIR / f"_{fund_id}_full.png"
    output_path = IMAGE_DIR / f"{fund_id}.png"

    # A diagram esetleges lazy-loadját is kiváltjuk.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1500)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(3000)

    page.screenshot(
        path=str(full_path),
        full_page=True,
    )

    try:
        if find_donut_and_crop(full_path, output_path):
            print(f"  Portfóliódiagram: {output_path}")
            return output_path.as_posix()

        if save_dom_visual_fallback(page, output_path):
            print(f"  Portfóliódiagram DOM fallback: {output_path}")
            return output_path.as_posix()

        raise RuntimeError(
            "A Generali oldalon nem találtam a portfóliódiagram "
            "vizuális elemét."
        )

    finally:
        full_path.unlink(missing_ok=True)


def main():
    # A workflow csak akkor hívja ezt a programot, ha nincs aktuális
    # portfolio.json, ezért ez valóban egyszeri betöltés.
    funds = discover_links()
    result = {}

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            device_scale_factor=1,
        )

        page = context.new_page()

        for index, fund in enumerate(funds, start=1):
            print(f"[{index}/18] {fund['name']}")
            print(f"  URL: {fund['url']}")

            page.goto(
                fund["url"],
                wait_until="networkidle",
                timeout=90000,
            )

            page.wait_for_timeout(4000)

            text = page.locator("body").inner_text(timeout=15000)

            reference_index = extract_reference_index(text)
            if reference_index:
                print(f"  Referenciaindex: {reference_index}")
            else:
                print("  Referenciaindex: nincs adat")

            image_path = capture_portfolio(
                page,
                fund["id"],
            )

            result[fund["id"]] = {
                "name": fund["name"],
                "reference_index": reference_index,
                "portfolio_date": None,
                "portfolio_image": image_path,
                "source_url": fund["url"],
            }

        context.close()
        browser.close()

    if len(result) != 18:
        raise RuntimeError(
            f"Várt 18 eszközalap, elkészült: {len(result)}"
        )

    missing_images = [
        item["name"]
        for item in result.values()
        if not item.get("portfolio_image")
    ]

    if missing_images:
        raise RuntimeError(
            "Hiányzó portfóliódiagram: "
            + ", ".join(missing_images)
        )

    payload = {
        "_version": PORTFOLIO_VERSION,
        "funds": result,
    }

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("portfolio.json elkészült.")


if __name__ == "__main__":
    main()
