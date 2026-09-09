import hashlib
import json
import re
import time

from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request
from urllib.request import urlopen


BASE_URL = "https://www.generali.hu"

FUNDS_URL = (
    "https://www.generali.hu/"
    "ugyfelszolgalat/informaciok/befektetesek/"
    "eszkozalapjaink.aspx"
)

OUTPUT_FILE = "funds.json"

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; GeneraliFundTracker/1.0)"
)


# ============================================================
# FORINT ALAPÚ ESZKÖZALAPOK II.
# ============================================================

ALLOWED_FUND_NAMES = {
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
}


class LinkParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.links = []

        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "a":
            return

        attributes = dict(attrs)

        href = attributes.get("href")

        if href:
            self.current_href = href
            self.current_text = []

    def handle_data(self, data):

        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag):

        if tag.lower() != "a":
            return

        if self.current_href is None:
            return

        text = clean_text(
            " ".join(self.current_text)
        )

        self.links.append(
            (
                self.current_href,
                text
            )
        )

        self.current_href = None
        self.current_text = []


def fetch(url):

    print(f"GET {url}")

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml"
            ),
            "Accept-Language": (
                "hu-HU,hu;q=0.9,en;q=0.5"
            ),
        },
    )

    with urlopen(
        request,
        timeout=30,
    ) as response:

        data = response.read()

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        return data.decode(
            charset,
            errors="replace",
        )


def clean_text(text):

    text = unescape(text)

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def html_to_text(html):

    html = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    html = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        html,
    )

    return clean_text(text)


def normalize_url(url):

    url = url.strip()

    absolute_url = urljoin(
        BASE_URL,
        url,
    )

    if not absolute_url.lower().startswith(
        "https://www.generali.hu/"
    ):
        return None

    return absolute_url


def is_fund_url(url):

    if not url:
        return False

    lower_url = url.lower()

    required_path = (
        "/ugyfelszolgalat/informaciok/"
        "befektetesek/eszkozalapjaink/"
    )

    if required_path not in lower_url:
        return False

    if lower_url.endswith(
        "eszkozalapjaink.aspx"
    ):
        return False

    return lower_url.endswith(".aspx")


def extract_fund_links(html):

    parser = LinkParser()

    parser.feed(html)

    funds = {}

    for href, name in parser.links:

        if not name:
            continue

        url = normalize_url(href)

        if not url:
            continue

        if not is_fund_url(url):
            continue

        # Csak a Forint II. szekcióban szereplő,
        # pontosan engedélyezett neveket tartjuk meg.
        if name not in ALLOWED_FUND_NAMES:
            continue

        funds[url] = name

    return funds


def extract_ytd(text):

    patterns = [

        (
            r"Év\s+elejétől\s+számított\s+hozam"
            r"\s*\(nem\s+évesített\)"
            r"\s*(-?\d+(?:[,.]\d+)?)\s*%"
        ),

        (
            r"Év\s+elejétől\s+számított\s+hozam"
            r".{0,150}?"
            r"(-?\d+(?:[,.]\d+)?)\s*%"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match is None:
            continue

        value = match.group(1)

        value = value.replace(
            ",",
            ".",
        )

        try:
            return float(value)
        except ValueError:
            return None

    # Ha a Generali "-" értéket ad,
    # akkor az azt jelenti, hogy nincs YTD adat.
    return None


def extract_date(text):

    patterns = [

        (
            r"(\d{4}\.\d{1,2}\.\d{1,2})"
            r"\s*értéknapon"
        ),

        (
            r"értéknapon\s*"
            r"(\d{4}\.\d{1,2}\.\d{1,2})"
        ),

        (
            r"értéknapja\s*"
            r"(\d{4}\.\d{1,2}\.\d{1,2})"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


def create_id(name, url):

    raw = (
        name.strip().lower()
        + "|"
        + url.lower()
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:16]


def scrape():

    print()
    print(
        "Generali Forint II. eszközalapok frissítése"
    )
    print("=" * 60)

    main_html = fetch(
        FUNDS_URL
    )

    fund_links = extract_fund_links(
        main_html
    )

    print()
    print(
        f"Forint II. eszközalap-linkek: "
        f"{len(fund_links)}"
    )

    # A főoldalról mind a 18 alapot meg kell találni.
    # Ez továbbra is valódi ellenőrzés, hogy ne változott-e
    # meg a Generali oldal szerkezete.
    if len(fund_links) != len(ALLOWED_FUND_NAMES):

        found_names = set(
            fund_links.values()
        )

        missing = sorted(
            ALLOWED_FUND_NAMES - found_names,
            key=str.casefold,
        )

        extra = sorted(
            found_names - ALLOWED_FUND_NAMES,
            key=str.casefold,
        )

        print()
        print(
            "FIGYELEM: a Generali főoldalán nem "
            "pontosan a várt 18 Forint II. alap "
            "található."
        )

        if missing:
            print()
            print("Hiányzó alap(ok):")

            for name in missing:
                print(
                    f"  - {name}"
                )

        if extra:
            print()
            print("Ismeretlen alap(ok):")

            for name in extra:
                print(
                    f"  - {name}"
                )

        raise RuntimeError(
            "A Forint II. eszközalapok listája "
            "nem egyezik a várt 18 alapból álló "
            "listával."
        )

    results = []

    # Név szerint dolgozzuk fel őket, így a kimenet
    # mindig stabil sorrendű lesz.
    funds_to_process = sorted(
        fund_links.items(),
        key=lambda item: item[1].casefold(),
    )

    for number, (url, name) in enumerate(
        funds_to_process,
        start=1,
    ):

        print()
        print(
            f"[{number}/{len(funds_to_process)}] "
            f"{name}"
        )

        try:

            html = fetch(url)

            text = html_to_text(
                html
            )

            ytd = extract_ytd(
                text
            )

            date = extract_date(
                text
            )

            if ytd is None:

                print(
                    "  YTD: nincs adat"
                )

            else:

                print(
                    f"  YTD: {ytd}%"
                )

            if date:

                print(
                    f"  Dátum: {date}"
                )

            results.append(
                {
                    "id": create_id(
                        name,
                        url,
                    ),
                    "name": name,
                    "ytd": ytd,
                    "date": date,
                    "url": url,
                }
            )

            time.sleep(0.25)

        except Exception as error:

            # Ha az egyedi oldal technikai okból nem
            # tölthető be, az alap akkor is bekerül.
            # Így a weboldalon látszani fog, hogy
            # jelenleg nincs hozzá adat.
            print(
                "  HIBA az alap oldalának "
                "feldolgozásakor: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            results.append(
                {
                    "id": create_id(
                        name,
                        url,
                    ),
                    "name": name,
                    "ytd": None,
                    "date": None,
                    "url": url,
                }
            )

    results.sort(
        key=lambda item:
        item["name"].casefold()
    )

    if len(results) != len(ALLOWED_FUND_NAMES):

        raise RuntimeError(
            "Nem sikerült létrehozni mind a 18 "
            "Forint II. eszközalap rekordját."
        )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            results,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write("\n")

    print()
    print("=" * 60)

    print(
        f"Sikeresen feldolgozva: "
        f"{len(results)} eszközalap"
    )

    missing_ytd = [
        item["name"]
        for item in results
        if item["ytd"] is None
    ]

    if missing_ytd:

        print()
        print(
            "YTD adattal nem rendelkező alap(ok):"
        )

        for name in missing_ytd:

            print(
                f"  - {name}"
            )

    print()
    print(
        f"Mentett fájl: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    scrape()
