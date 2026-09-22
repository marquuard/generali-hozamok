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

RATES_URL = (
    "https://www.generali.hu/ugyfelszolgalat/informaciok/"
    "befektetesek/arfolyamok.aspx"
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


def fetch_central_prices():
    """
    Megkísérli a Generali központi árfolyamtáblázatából kinyerni az összes alap legfrissebb árfolyamát.
    """
    prices = {}
    try:
        resp = requests.get(RATES_URL, headers=HEADERS, timeout=25)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tr in soup.find_all("tr"):
                row_text = clean(tr.get_text(" ", strip=True))
                row_norm = norm(row_text)
                for fund_id, name in FUNDS:
                    if norm(name) in row_norm:
                        tds = tr.find_all(["td", "th"])
                        for td in reversed(tds):
                            val = parse_hungarian_float(td.get_text(strip=True))
                            if val is not None and val > 0:
                                prices[fund_id] = val
                                break
    except Exception as e:
        print(f"Központi árfolyamtábla lekérési figyelmeztetés: {e}")
    return prices


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


def scrape_fund_page(fund, central_price):
    response = requests.get(fund["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()

    raw_html = response.text
    soup = BeautifulSoup(raw_html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    price_val = central_price
    date_val = None

    # 1. Keresés az aloldal összes script tagjében (nyers HTML-ben is)
    if price_val is None:
        # Minden szám ami dátumhoz kapcsolódik a kódban
        matches = re.findall(
            r'(\d{4}[.\-/]\d{2}[.\-/]\d{2})[^\d]{1,60}([0-9]+(?:[.,][0-9]{2,6}))',
            raw_html
        )
        if matches:
            matches.sort(key=lambda x: x[0].replace("-", "").replace(".", "").replace("/", ""))
            date_val = matches[-1][0].replace("-", ".").replace("/", ".")
            price_val = float(matches[-1][1].replace(",", "."))

    # 2. Ha még mindig nincs árfolyam, táblázatok és szöveg vizsgálata
    if price_val is None:
        patterns = [
            r"(?:árfolyam|nettó\s*eszközérték)[^\d]{1,25}(\d+[.,]\d{2,6})",
            r"(\d+[.,]\d{4,6})\s*(?:huf|ft)"
        ]
        for pat in patterns:
            m = re.search(pat, page_text, re.IGNORECASE)
            if m:
                val = parse_hungarian_float(m.group(1))
                if val and val > 0:
                    price_val = val
                    break

    # Dátum kinyerése
    if not date_val:
        dates = re.findall(r"\b(20\d{2}[.-]\d{2}[.-]\d{2})\b", page_text)
        if dates:
            date_val = sorted([d.replace("-", ".") for d in dates])[-1]

    # 3. YTD hozam kinyerése
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
    print("Központi árfolyamtáblázat lekérdezése...")
    central_prices = fetch_central_prices()
    if central_prices:
        print(f"Sikerült {len(central_prices)} árfolyamot előzetesen kinyerni a központi oldalról.")

    print("Eszközalapok linkjeinek felderítése...")
    fund_list = discover_fund_urls()

    results = []
    for i, fund in enumerate(fund_list, 1):
        print(f"[{i}/18] Adatok lekérése: {fund['name']}...")
        preset_price = central_prices.get(fund["id"])
        data = scrape_fund_page(fund, preset_price)
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
