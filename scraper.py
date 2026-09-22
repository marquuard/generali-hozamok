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


def extract_chart_data(soup):
    """
    Kikeresi a grafikon JavaScript tömbjét,
    és visszaadja a legutolsó érvényes árfolyamot és dátumot.
    """
    for script in soup.find_all("script"):
        script_text = script.string or ""
        if not script_text:
            continue

        if "dataProvider" in script_text or "amCharts" in script_text:
            # Dátum és lebegőpontos szám párok kinyerése a dataProvider tömbből
            entries = re.findall(
                r'\{[^{}]*?(?:date|datum)[\'"]?\s*:\s*[\'"]?(\d{4}[.\-/]\d{2}[.\-/]\d{2})[^{}]*?(?:value|price|arfolyam|netto)[\'"]?\s*:\s*([0-9]+(?:[.,][0-9]+)?)[^{}]*?\}',
                script_text,
                re.IGNORECASE,
            )
            if entries:
                last_entry = entries[-1]
                chart_date = last_entry[0].replace("-", ".").replace("/", ".")
                chart_price = float(last_entry[1].replace(",", "."))
                return chart_price, chart_date

            # Alternatív minta: lebegőpontos value értékek listája
            val_matches = re.findall(
                r'[\'"]?(?:value|price|arfolyam)[\'"]?\s*:\s*([0-9]+(?:[.,][0-9]+)?)',
                script_text,
                re.IGNORECASE,
            )
            if val_matches:
                try:
                    return float(val_matches[-1].replace(",", ".")), None
                except ValueError:
                    pass

    return None, None


def scrape_fund_data(fund):
    response = requests.get(fund["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    # 1. Grafikonból a legutolsó árfolyam és dátum kinyerése
    chart_price, chart_date = extract_chart_data(soup)

    price_val = chart_price
    date_val = chart_date

    # Ha a grafikonból nem jött dátum, kinyerjük a szövegből
    if not date_val:
        date_match = re.search(r"\b(20\d{2}[.-]\d{2}[.-]\d{2})\b", page_text)
        date_val = date_match.group(1).replace("-", ".") if date_match else None

    # Fallback árfolyam-keresés, ha a grafikon scriptje nem tartalmazta
    if price_val is None:
        for tr in soup.find_all("tr"):
            row_text = clean(tr.get_text(" ", strip=True))
            if re.search(r"(?:aktuális\s*árfolyam|árfolyam|nettó\s*eszközérték)", row_text, re.I) and not re.search(r"deviza", row_text, re.I):
                tds = tr.find_all(["td", "th"])
                for td in reversed(tds):
                    td_txt = clean(td.get_text(strip=True))
                    parsed = parse_hungarian_float(td_txt)
                    if parsed is not None and parsed > 0:
                        price_val = parsed
                        break
            if price_val is not None:
                break

    if price_val is None:
        price_match = re.search(
            r"(?:aktuális\s*)?(?:árfolyam|nettó\s*eszközérték)\s*[:\-–]?\s*(\d+(?:[.,]\d+)?)\s*(?:huf|ft)?",
            page_text,
            re.I,
        )
        if price_match:
            price_val = parse_hungarian_float(price_match.group(1))

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
    print("Sikeres futás: funds.json elmentve (grafikonból kiolvasott árfolyamokkal).")


if __name__ == "__main__":
    main()
