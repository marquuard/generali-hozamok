import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

MAIN_URL = "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink.aspx"
OUTPUT_FILE = "funds.json"

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
    "User-Agent": "Mozilla/5.0 (compatible; GeneraliFundTracker/2.0)"
}

session = requests.Session()
session.headers.update(HEADERS)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_name(text):
    return clean(text).casefold()


def extract_fund_links(html):
    soup = BeautifulSoup(html, "html.parser")
    wanted = {normalize_name(name): (fund_id, name) for fund_id, name in FUNDS}
    found = {}

    for a in soup.find_all("a", href=True):
        name = clean(a.get_text(" ", strip=True))
        key = normalize_name(name)

        if key in wanted:
            fund_id, canonical_name = wanted[key]
            found[fund_id] = {
                "id": fund_id,
                "name": canonical_name,
                "url": urljoin(MAIN_URL, a["href"]),
            }

    missing = [name for fund_id, name in FUNDS if fund_id not in found]
    if missing:
        raise RuntimeError(
            "Hiányzó eszközalap-link(ek): " + ", ".join(missing)
        )

    if len(found) != 18:
        raise RuntimeError(f"Várt 18 eszközalap, talált: {len(found)}")

    return [found[fund_id] for fund_id, _ in FUNDS]


def parse_hungarian_number(value):
    if value is None:
        return None

    text = value.replace("\xa0", " ").strip()
    text = re.sub(r"[^0-9,\-+.%]", "", text)
    text = text.replace("%", "").replace(".", "").replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def extract_ytd(text):
    compact = clean(text)

    patterns = [
        r"Év elejétől számított hozam\s*\(nem évesített\)\s*[:\-]?\s*([+\-]?\d+(?:[.,]\d+)?)\s*%",
        r"Év elejétől számított hozam\s*[:\-]?\s*([+\-]?\d+(?:[.,]\d+)?)\s*%",
    ]

    for pattern in patterns:
        match = re.search(pattern, compact, re.IGNORECASE)
        if match:
            return parse_hungarian_number(match.group(1))

    return None


def extract_date(text):
    compact = clean(text)

    patterns = [
        r"Értéknap\s*[:\-]?\s*(\d{4}\.\d{1,2}\.\d{1,2})",
        r"Utolsó értéknap\s*[:\-]?\s*(\d{4}\.\d{1,2}\.\d{1,2})",
        r"(\d{4}\.\d{2}\.\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            return match.group(1)

    return datetime.now().strftime("%Y.%m.%d")


def main():
    response = session.get(MAIN_URL, timeout=30)
    response.raise_for_status()

    funds = extract_fund_links(response.text)
    records = []

    for index, fund in enumerate(funds, start=1):
        print(f"[{index}/18] {fund['name']}")

        try:
            page = session.get(fund["url"], timeout=30)
            page.raise_for_status()
            text = BeautifulSoup(page.text, "html.parser").get_text(
                " ", strip=True
            )

            ytd = extract_ytd(text)
            date = extract_date(text)

            record = {
                "id": fund["id"],
                "name": fund["name"],
                "ytd": ytd,
                "date": date,
                "url": fund["url"],
            }

            if ytd is None:
                print("  YTD: nincs adat")
            else:
                print(f"  YTD: {ytd}%")

            records.append(record)

        except Exception as exc:
            print(f"  HIBA: {exc}")
            records.append({
                "id": fund["id"],
                "name": fund["name"],
                "ytd": None,
                "date": datetime.now().strftime("%Y.%m.%d"),
                "url": fund["url"],
            })

    if len(records) != 18:
        raise RuntimeError(
            f"A feldolgozás eredménye nem 18 rekord: {len(records)}"
        )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    print(f"Kész: {OUTPUT_FILE}, {len(records)} rekord")


if __name__ == "__main__":
    main()
