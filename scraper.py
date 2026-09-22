import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

MAIN_URL = (
    "https://www.generali.hu/ugyfelszolgalat/informaciok/"
    "befektetesek/eszkozalapjaink.aspx"
)

OUTPUT_FILE = Path("funds.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

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


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def norm(text):
    return clean(text).casefold()


def parse_hungarian_float(val_str):
    if not val_str:
        return None

    s = (
        str(val_str)
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace(",", ".")
        .replace("%", "")
        .replace("HUF", "")
        .replace("Ft", "")
        .strip()
    )

    match = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def discover_fund_urls():
    response = requests.get(MAIN_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    wanted = {norm(name): (fund_id, name) for fund_id, name in FUNDS}
    found = {}

    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" ", strip=True))
        key = norm(text)

        if key in wanted:
            fund_id, name = wanted[key]
            found[fund_id] = {
                "id": fund_id,
                "name": name,
                "url": urljoin(MAIN_URL, a["href"]),
            }

    missing = [name for fund_id, name in FUNDS if fund_id not in found]
    if missing:
        raise RuntimeError("Hiányzó alapok: " + ", ".join(missing))

    return [found[fund_id] for fund_id, _ in FUNDS]


def extract_price_and_date(soup, page_text):
    """
    Kikeresi a legfrissebb árfolyamot (akár 5-6 tizedesjegyig)
    és a hozzá tartozó dátumot a grafikonból vagy a HTML mezőkből.
    """
    chart_price = None
    chart_date = None

    # 1. Keresés a beágyazott JavaScript diagram adathalmazban (dataProvider)
    for script in soup.find_all("script"):
        script_text = script.string or ""
        if not script_text:
            continue

        if "dataProvider" in script_text or "amCharts" in script_text:
            # Rugalmas keresés minden lehetséges kulcsra: date/datum és value/price/arfolyam/netto
            entries = re.findall(
                r'\{[^{}]*?(?:date|datum)[\'"]?\s*:\s*[\'"]?(\d{4}[.\-/]\d{2}[.\-/]\d{2})[^{}]*?(?:value|price|arfolyam|netto)[\'"]?\s*:\s*([0-9]+(?:[.,][0-9]+)?)[^{}]*?\}',
                script_text,
                re.IGNORECASE,
            )
            if entries:
                # Dátum szerint növekvő sorrendbe rakjuk, hogy garantáltan a legkésőbbi legyen az utolsó
                entries.sort(key=lambda x: x[0].replace("-", "").replace(".", "").replace("/", ""))
                last_entry = entries[-1]
                chart_date = last_entry[0].replace("-", ".").replace("/", ".")
                chart_price = float(last_entry[1].replace(",", "."))
                break

    # 2. Ha a scriptből nem jött, keresés a HTML táblázatból / szövegből (pl. 'Árfolyam: 2,13471 HUF')
    if chart_price is None:
        # Kifejezetten a 4-6 tizedesjegyes devizaértékekre célzott minta
        price_patterns = [
            r"(?:aktuális\s*)?(?:árfolyam|nettó\s*eszközérték)\s*[:\-–]?\s*(\d+[.,]\d{2,6})\s*(?:huf|ft)?",
            r"(\d+[.,]\d{4,6})\s*(?:huf|ft)",
        ]
        for pattern in price_patterns:
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            if matches:
                # Az utolsó vagy legfrissebb találat
                parsed = parse_hungarian_float(matches[0])
                if parsed and parsed > 0:
                    chart_price = parsed
                    break

    # 3. Dátum pótlása, ha a diagramból nem jött át
    if not chart_date:
        dates = re.findall(r"\b(20\d{2}[.-]\d{2}[.-]\d{2})\b", page_text)
        if dates:
            # A legkésőbbi dátumot választjuk
            chart_date = sorted([d.replace("-", ".") for d in dates])[-1]

    return chart_price, chart_date


def scrape_fund_data(fund):
    response = requests.get(fund["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    # 1. Árfolyam és Dátum kinyerése
    price_val, date_val = extract_price_and_date(soup, page_text)

    # 2. YTD hozam kinyerése
    ytd_val = None
    for tr in soup.find_all("tr"):
        row_text = clean(tr.get_text(" ", strip=True))
        if re.search(r"(?:év\s*elejétől|ytd)", row_text, re.I):
            tds = tr.find_all(["td", "th"])
            for td in reversed(tds):
                td_txt = clean(td.get_text(strip=True))
                parsed = parse_hungarian_float(td_txt)
                if parsed is not None:
                    ytd_val = parsed
                    break
        if ytd_val is not None:
            break

    if ytd_val is None:
        ytd_match = re.search(
            r"(?:év\s*elejétől|ytd)[^0-9\-+−–—]*([−–—\-+]?\d+(?:[.,]\d+)?)\s*%",
            page_text,
            re.I,
        )
        if ytd_match:
            ytd_val = parse_hungarian_float(ytd_match.group(1))

    return {
        "id": fund["id"],
        "name": fund["name"],
        "url": fund["url"],
        "date": date_val,
        "ytd": ytd_val,
        "price": price_val,
    }


def main():
    print("Eszközalapok linkjeinek felderítése...")
    fund_list = discover_fund_urls()

    results = []
    for i, fund in enumerate(fund_list, 1):
        print(f"[{i}/18] Adatok lekérése: {fund['name']}...")
        data = scrape_fund_data(fund)
        print(f"       -> Árfolyam: {data['price']} HUF | YTD: {data['ytd']}% | Dátum: {data['date']}")
        results.append(data)

    if len(results) != 18:
        raise RuntimeError("Nem sikerült mind a 18 alapot lekérni.")

    OUTPUT_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print("Sikeres futás: funds.json elmentve.")


if __name__ == "__main__":
    main()
