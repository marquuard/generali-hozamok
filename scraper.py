import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

MAIN_URL = "https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink.aspx"
OUTPUT_FILE = "funds.json"

ALLOWED_FUND_NAMES = [
    "Pénzpiaci 2016 eszközalap",
    "Hazai kötvény eszközalap",
    "Tallózó abszolút hozam eszközalap",
    "Világjáró kötvény eszközalap",
    "Horizont 15+ vegyes eszközalap",
    "Horizont 10+ vegyes eszközalap",
    "Horizont 5+ vegyes eszközalap",
    "Hazai részvény eszközalap",
    "Fejlődő világ részvény eszközalap",
    "Fejlett világ részvény eszközalap",
    "Világmárkák részvény eszközalap",
    "Innováció részvény eszközalap",
    "Fenntartható Világ részvény eszközalap",
    "Tudatos fejlett piac részvény eszközalap",
    "TávLat fejlődő piac részvény eszközalap",
    "Kötvény 2027/M árfolyamvédett eszközalap",
    "Magyar piac részvény eszközalap",
    "Nemzetközi márkák részvény eszközalap",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GeneraliFundTracker/1.0)"
}

session = requests.Session()
session.headers.update(HEADERS)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_name(text):
    return clean(text).casefold()


def extract_fund_links(html):
    soup = BeautifulSoup(html, "html.parser")
    allowed = {normalize_name(x): x for x in ALLOWED_FUND_NAMES}
    found = {}

    for a in soup.find_all("a", href=True):
        name = clean(a.get_text(" ", strip=True))
        key = normalize_name(name)
        if key in allowed:
            found[allowed[key]] = urljoin(MAIN_URL, a["href"])

    missing = [x for x in ALLOWED_FUND_NAMES if x not in found]
    if missing:
        raise RuntimeError(
            "Hiányzó eszközalap-link(ek): " + ", ".join(missing)
        )

    if len(found) != 18:
        raise RuntimeError(f"Várt 18 eszközalap, talált: {len(found)}")

    return found


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

    links = extract_fund_links(response.text)

    records = []

    for index, (name, url) in enumerate(links.items(), start=1):
        print(f"[{index}/18] {name}")

        try:
            page = session.get(url, timeout=30)
            page.raise_for_status()
            text = BeautifulSoup(page.text, "html.parser").get_text(" ", strip=True)

            ytd = extract_ytd(text)
            date = extract_date(text)

            record = {
                "id": re.sub(r"[^a-z0-9]+", "-", normalize_name(name)).strip("-"),
                "name": name,
                "ytd": ytd,
                "date": date,
                "url": url,
            }

            if ytd is None:
                print("  YTD: nincs adat")
            else:
                print(f"  YTD: {ytd}%")

            records.append(record)

        except Exception as exc:
            print(f"  HIBA: {exc}")
            records.append({
                "id": re.sub(r"[^a-z0-9]+", "-", normalize_name(name)).strip("-"),
                "name": name,
                "ytd": None,
                "date": datetime.now().strftime("%Y.%m.%d"),
                "url": url,
            })

    if len(records) != 18:
        raise RuntimeError(f"A feldolgozás eredménye nem 18 rekord: {len(records)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    print(f"Kész: {OUTPUT_FILE}, {len(records)} rekord")


if __name__ == "__main__":
    main()
