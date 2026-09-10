import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT = Path("portfolio.json")

FUNDS = [
    ("penzpiaci-2016", "Pénzpiaci 2016 eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/penzpiaci2016eszkozalap.aspx"),
    ("hazai-kotveny", "Hazai kötvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/hazaikotvenyeszkozalap.aspx"),
    ("tallozo", "Tallózó abszolút hozam eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/tallozoabszoluthozameszkozalap.aspx"),
    ("vilagjaro-kotveny", "Világjáró kötvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/vilagjarokotvenyeszkozalap.aspx"),
    ("horizont-15", "Horizont 15+ vegyes eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/horizont15vegyeseszkozalap.aspx"),
    ("horizont-10", "Horizont 10+ vegyes eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/horizont10vegyeseszkozalap.aspx"),
    ("horizont-5", "Horizont 5+ vegyes eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/horizont5vegyeseszkozalap.aspx"),
    ("hazai-reszveny", "Hazai részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/hazaireszvenyeszkozalap.aspx"),
    ("fejlodo-vilag", "Fejlődő világ részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/fejlodovilagreszvenyeszkozalap.aspx"),
    ("fejlett-vilag", "Fejlett világ részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/fejlettvilagreszvenyeszkozalap.aspx"),
    ("vilagmarkak", "Világmárkák részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/vilagmarkakreszvenyeszkozalap.aspx"),
    ("innovacio", "Innováció részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/innovacioreszvenyeszkozalap.aspx"),
    ("fenntarthato", "Fenntartható Világ részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/fenntarthatovilagreszvenyeszkozalap.aspx"),
    ("tudatos-fejlett", "Tudatos fejlett piac részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/tudatosfejlettpiacreszvenyeszkozalap.aspx"),
    ("tavlat-fejlodo", "TávLat fejlődő piac részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/tavlatfejlodopiacreszvenyeszkozalap.aspx"),
    ("kotveny-2027m", "Kötvény 2027/M árfolyamvédett eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/kotveny2027meszkozalap.aspx"),
    ("magyar-piac", "Magyar piac részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/magyarpiacreszvenyeszkozalap.aspx"),
    ("nemzetkozi-markak", "Nemzetközi márkák részvény eszközalap", "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink/nemzetkozimarkakreszvenyeszkozalap.aspx"),
]

PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()

def parse_percent(value):
    return float(value.replace(",", "."))

def extract_reference_index(text):
    match = re.search(r"Referenciaindex\s*:\s*(.*?)(?:Földrajzi kitettség|Szektoriális kitettség|Szektorális kitettség|Devizális kitettség|Eszközalap indulása|Ajánlott)", text, re.I)
    return clean(match.group(1)) if match else None

def extract_chart_labels(page):
    candidates = []

    selectors = [
        "svg text",
        "[aria-label]",
        "[title]",
        "[data-label]",
        "[class*='chart'] text",
        "[class*='portfolio'] text",
    ]

    seen = set()

    for selector in selectors:
        for element in page.locator(selector).all():
            try:
                texts = [
                    element.inner_text(timeout=300),
                    element.get_attribute("aria-label"),
                    element.get_attribute("title"),
                    element.get_attribute("data-label"),
                ]
            except Exception:
                continue

            for raw in texts:
                value = clean(raw)
                if not value or value in seen or "%" not in value:
                    continue
                seen.add(value)

                match = PERCENT_RE.search(value)
                if not match:
                    continue

                name = clean(value[:match.start()].strip(":-–— "))
                percentage = parse_percent(match.group(1))

                if name and 0 < percentage <= 100:
                    candidates.append({
                        "name": name,
                        "percentage": percentage
                    })

    unique = []
    used = set()

    for item in candidates:
        key = (item["name"], item["percentage"])
        if key not in used:
            used.add(key)
            unique.append(item)

    # A chart can expose the same labels through several DOM nodes.
    # Keep the first occurrence of each exact label/value pair.
    return unique

def main():
    if OUTPUT.exists():
        print("portfolio.json már létezik; nincs újralekérés.")
        return

    result = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})

        for index, (fund_id, name, url) in enumerate(FUNDS, start=1):
            print(f"[{index}/18] {name}")
            page.goto(url, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(3000)

            text = clean(page.locator("body").inner_text(timeout=15000))
            reference_index = extract_reference_index(text)
            labels = extract_chart_labels(page)

            # The portfolio pie must contain meaningful data. If the page
            # exposes no percentage labels, fail rather than save invented data.
            total = sum(x["percentage"] for x in labels)

            if len(labels) < 2 or total < 90 or total > 110:
                raise RuntimeError(
                    f"Nem sikerült megbízható portfóliódiagramot kiolvasni: "
                    f"{name}. Talált szeletek: {len(labels)}, összeg: {total:.2f}%"
                )

            result[fund_id] = {
                "name": name,
                "reference_index": reference_index,
                "portfolio": labels,
                "source_url": url,
            }

        browser.close()

    if len(result) != 18:
        raise RuntimeError(f"Várt 18 portfólió, elkészült: {len(result)}")

    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("portfolio.json elkészült.")


if __name__ == "__main__":
    main()
