import json
import re
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

try:
    import pytesseract
except ImportError:
    pytesseract = None

OUTPUT = Path('portfolio.json')
IMAGE_DIR = Path('portfolio_images')

FUNDS = [
    ('penzpiaci-2016', 'Pénzpiaci 2016 eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/penzpiaci2016eszkozalap.aspx'),
    ('hazai-kotveny', 'Hazai kötvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/hazaikotvenyeszkozalap.aspx'),
    ('tallozo', 'Tallózó abszolút hozam eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/tallozoabszoluthozameszkozalap.aspx'),
    ('vilagjaro-kotveny', 'Világjáró kötvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/vilagjarokotvenyeszkozalap.aspx'),
    ('horizont-15', 'Horizont 15+ vegyes eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/horizont15vegyeseszkozalap.aspx'),
    ('horizont-10', 'Horizont 10+ vegyes eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/horizont10vegyeseszkozalap.aspx'),
    ('horizont-5', 'Horizont 5+ vegyes eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/horizont5vegyeseszkozalap.aspx'),
    ('hazai-reszveny', 'Hazai részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/hazaireszvenyeszkozalap.aspx'),
    ('fejlodo-vilag', 'Fejlődő világ részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/fejlodovilagreszvenyeszkozalap.aspx'),
    ('fejlett-vilag', 'Fejlett világ részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/fejlettvilagreszvenyeszkozalap.aspx'),
    ('vilagmarkak', 'Világmárkák részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/vilagmarkakreszvenyeszkozalap.aspx'),
    ('innovacio', 'Innováció részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/innovacioreszvenyeszkozalap.aspx'),
    ('fenntarthato', 'Fenntartható Világ részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/fenntarthatovilagreszvenyeszkozalap.aspx'),
    ('tudatos-fejlett', 'Tudatos fejlett piac részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/tudatosfejlettpiacreszvenyeszkozalap.aspx'),
    ('tavlat-fejlodo', 'TávLat fejlődő piac részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/tavlatfejlodopiacreszvenyeszkozalap.aspx'),
    ('kotveny-2027m', 'Kötvény 2027/M árfolyamvédett eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/kotveny2027meszkozalap.aspx'),
    ('magyar-piac', 'Magyar piac részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/magyarpiacreszvenyeszkozalap.aspx'),
    ('nemzetkozi-markak', 'Nemzetközi márkák részvény eszközalap', 'https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/nemzetkozimarkakreszvenyeszkozalap.aspx'),
]


def clean(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def extract_reference_index(text):
    match = re.search(
        r'Referenciaindex\s*:\s*(.*?)(?:Földrajzi kitettség|Szektoriális kitettség|Szektorális kitettség|Devizális kitettség|Eszközalap indulása|Ajánlott)',
        text,
        re.I,
    )
    return clean(match.group(1)) if match else None


def extract_portfolio_date(page):
    # The chart itself normally contains the date in its rendered pixels.
    # Keep a best-effort date from visible text if the page exposes it.
    text = clean(page.locator('body').inner_text(timeout=15000))
    matches = re.findall(r'20\d{2}\.\d{2}\.\d{2}', text)
    return matches[-1] if matches else None


def visual_candidates(page):
    candidates = []
    selectors = ['img', 'canvas', 'svg']

    for selector in selectors:
        elements = page.locator(selector).all()
        for element in elements:
            try:
                box = element.bounding_box()
                if not box or box['width'] < 250 or box['height'] < 140:
                    continue
                if box['y'] < 0 or box['y'] > 1000:
                    continue

                attrs = ' '.join(filter(None, [
                    element.get_attribute('src'),
                    element.get_attribute('alt'),
                    element.get_attribute('class'),
                    element.get_attribute('id'),
                    element.get_attribute('title'),
                ])).lower()

                area = box['width'] * box['height']
                score = area / 1000

                keywords = ('portfolio', 'portfol', 'chart', 'diagram', 'eszközalap', 'eszkoz', 'befektet')
                if any(word in attrs for word in keywords):
                    score += 5000

                # The portfolio chart is normally a large centered visual.
                center_distance = abs((box['x'] + box['width'] / 2) - 720)
                score -= center_distance / 10

                candidates.append((score, element, box, attrs))
            except Exception:
                continue

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def save_best_visual(page, fund_id):
    candidates = visual_candidates(page)
    if not candidates:
        return None

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = IMAGE_DIR / f'{fund_id}.png'

    # Try the best few candidates. A screenshot of the element is preferred
    # because it works for <img>, SVG and canvas alike.
    for rank, (_, element, box, attrs) in enumerate(candidates[:8], start=1):
        try:
            element.screenshot(path=str(target))
            if target.exists() and target.stat().st_size > 5000:
                print(f'  Portfólióvizuál: {selector_description(element)} ({box["width"]:.0f}x{box["height"]:.0f})')
                return target.as_posix()
        except Exception as exc:
            print(f'  Jelölt {rank} nem menthető: {exc}')

    return None


def selector_description(element):
    try:
        return clean(' '.join(filter(None, [
            element.get_attribute('alt'),
            element.get_attribute('class'),
            element.get_attribute('id'),
            element.get_attribute('src'),
        ])))[:180] or 'vizuális elem'
    except Exception:
        return 'vizuális elem'



def save_ocr_fallback(page, fund_id):
    """Fallback for charts rendered in pixels without img/svg/canvas DOM nodes."""
    if pytesseract is None:
        return None

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    full_path = IMAGE_DIR / f"_{fund_id}_full.png"
    target = IMAGE_DIR / f"{fund_id}.png"

    try:
        page.screenshot(path=str(full_path), full_page=True)
        image = Image.open(full_path).convert("RGB")
        data = pytesseract.image_to_data(image, config="--psm 11", output_type=pytesseract.Output.DICT)

        boxes = []
        for i, raw in enumerate(data["text"]):
            value = clean(raw)
            if not re.search(r"\d+[.,]\d+\s*%", value):
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
            # The portfolio chart is near the top of the fund page.
            if y <= 800 and w > 0 and h > 0:
                boxes.append((x, y, w, h))

        if len(boxes) < 2:
            full_path.unlink(missing_ok=True)
            return None

        min_x = max(0, min(x for x, y, w, h in boxes) - 240)
        min_y = max(0, min(y for x, y, w, h in boxes) - 110)
        max_x = min(image.width, max(x + w for x, y, w, h in boxes) + 240)
        max_y = min(image.height, max(y + h for x, y, w, h in boxes) + 110)

        crop = image.crop((min_x, min_y, max_x, max_y))
        crop.save(target, format="PNG")
        full_path.unlink(missing_ok=True)

        if target.exists() and target.stat().st_size > 5000:
            print(f"  Portfólióvizuál OCR fallback: {target}")
            return target.as_posix()
    except Exception as exc:
        print(f"  OCR fallback sikertelen: {exc}")
        full_path.unlink(missing_ok=True)

    return None

def main():
    if OUTPUT.exists():
        print('portfolio.json már létezik; nincs újralekérés.')
        return

    result = {}
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1200}, device_scale_factor=1)

        for index, (fund_id, name, url) in enumerate(FUNDS, start=1):
            print(f'[{index}/18] {name}')
            page.goto(url, wait_until='networkidle', timeout=90000)
            page.wait_for_timeout(4000)

            text = clean(page.locator('body').inner_text(timeout=15000))
            reference_index = extract_reference_index(text)
            portfolio_date = extract_portfolio_date(page)
            image_path = save_best_visual(page, fund_id)
            if not image_path:
                image_path = save_ocr_fallback(page, fund_id)

            if not image_path:
                # Do not manufacture portfolio data. Keep the reference index
                # and let the website clearly show that the static chart was
                # not found. This prevents the whole Pages deployment from
                # being blocked by one visual implementation detail.
                print('  Portfóliódiagram nem található automatikusan.')

            result[fund_id] = {
                'name': name,
                'reference_index': reference_index,
                'portfolio_date': portfolio_date,
                'portfolio_image': image_path,
                'source_url': url,
            }

        browser.close()

    if len(result) != 18:
        raise RuntimeError(f'Várt 18 portfólió, elkészült: {len(result)}')

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('portfolio.json elkészült.')


if __name__ == '__main__':
    main()
