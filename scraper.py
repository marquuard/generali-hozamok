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
HISTORY_FILE = Path("history.json")

# JSONBin beállítások a darabszámok lekéréséhez az összérték számításához
JSONBIN_BIN_ID = "6aab1846ac6210605ad64a79"
JSONBIN_API_KEY = "$2a$10$.wAFrVJnX1moDh4euoeNHeKCtJcmocpcCp07W8Q1aXqirBfMKGslu"

DEFAULT_UNITS = {
    "tallozo": 114542.676,
    "horizont-10": 207670.400,
    "hazai-reszveny": 214985.923,
    "innovacio": 152078.356,
}

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


def extract_chart_data(raw_html):
    """
    Kifejezetten a Generali chartData tömbjéből nyeri ki a legutolsó
    Rate (árfolyam) és date (new Date) értékeket.
    """
    chart_price = None
    chart_date = None

    match = re.search(r'var\s+chartData\s*=\s*\[(.*?)\];', raw_html, re.DOTALL)
    blob = match.group(1) if match else raw_html

    entries = re.findall(
        r'date:\s*new\s+Date\((\d{4}),\s*(\d{1,2}),\s*(\d{1,2})\)[^}]*?Rate:\s*([0-9]+(?:\.[0-9]+)?)',
        blob,
    )

    if entries:
        last_entry = entries[-1]
        year = last_entry[0]
        month = int(last_entry[1]) + 1
        day = int(last_entry[2])
        chart_date = f"{year}.{month:02d}.{day:02d}"
        chart_price = float(last_entry[3])

    return chart_price, chart_date


def scrape_fund_data(fund):
    response = requests.get(fund["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()

    raw_html = response.text
    soup = BeautifulSoup(raw_html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    # 1. Pontos árfolyam és dátum kinyerése a chartData tömbből
    price_val, date_val = extract_chart_data(raw_html)

    if not date_val:
        date_match = re.search(r"\b(20\d{2}[.-]\d{2}[.-]\d{2})\b", page_text)
        date_val = date_match.group(1).replace("-", ".") if date_match else None

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


def fetch_active_units():
    try:
        res = requests.get(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
            headers={"X-Master-Key": JSONBIN_API_KEY},
            timeout=15,
        )
        if res.status_code == 200:
            data = res.json()
            return data.get("record", DEFAULT_UNITS)
    except Exception as e:
        print(f"JSONBin lekérési figyelmeztetés: {e}")
    return DEFAULT_UNITS


def update_history(results):
    """
    Kiszámítja az aktuális összértéket, és bejegyzi a history.json-ba dátum szerint.
    """
    units = fetch_active_units()
    price_map = {f["id"]: f["price"] for f in results if f.get("price") is not None}

    # Legfrissebb dátum keresése az alapok között
    dates = [f["date"] for f in results if f.get("date")]
    current_date = sorted(dates)[-1] if dates else "Ismeretlen"

    total_huf = 0
    for fund_id, unit_count in units.items():
        p = price_map.get(fund_id)
        if p:
            total_huf += float(unit_count) * float(p)

    if total_huf <= 0:
        print("A portfólió összértéke 0 maradt, history nem frissült.")
        return

    total_huf_rounded = round(total_huf)
    print(f"Portfólió aktuális összértéke: {total_huf_rounded:,} HUF ({current_date})")

    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = []

    # Ellenőrizzük, hogy erre a dátumra van-e már bejegyzés
    existing_idx = next((i for i, h in enumerate(history) if h.get("date") == current_date), None)
    if existing_idx is not None:
        history[existing_idx]["value"] = total_huf_rounded
    else:
        history.append({
            "date": current_date,
            "value": total_huf_rounded
        })

    # Dátum szerint növekvő sorrendbe rendezés
    history.sort(key=lambda x: x["date"].replace("-", "").replace(".", ""))

    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print("Sikeresen rögzítve a history.json-ba.")


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

    # Portfólió vagyongörbe történetének frissítése
    update_history(results)


if __name__ == "__main__":
    main()
