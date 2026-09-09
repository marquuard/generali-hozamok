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


# -------------------------------------------------------------------
# CSAK A "FORINT ALAPÚ ESZKÖZALAPOK II." CSOPORT
# -------------------------------------------------------------------
#
# Ezek a Generali oldalán jelenleg a II. csoport alatt szereplő
# eszközalapok.
#
# A név csak szűrésre szolgál.
# A hozzájuk tartozó aktuális URL-t továbbra is a Generali
# főoldaláról vesszük fel.
#

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


def normalize_fund_name(name):

    return clean_text(name)


def extract_fund_links(html):

    parser = LinkParser()

    parser.feed(html)

    funds = {}

    for href, name in parser.links:

        if not name:
            continue

        name = normalize_fund_name(name)

        # -----------------------------------------------------------
        # A LEGFONTOSABB SZŰRÉS:
        #
        # Csak a Forint II. csoportban szereplő neveket engedjük át.
        # -----------------------------------------------------------

        if name not in ALLOWED_FUND_NAMES:
            continue

        url = normalize_url(href)

        if not url:
            continue

        if not is_fund_url(url):
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

        return float(value)

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
        "Generali – Forint alapú "
        "eszközalapok II. frissítése"
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
        "Forint II. csoportban talált "
        f"eszközalapok: {len(fund_links)}"
    )

    if not fund_links:

        raise RuntimeError(
            "A Generali oldalán nem találtam "
            "Forint alapú eszközalapok II. "
            "csoportjába tartozó eszközalapokat."
        )

    # Biztonsági ellenőrzés:
    #
    # A Generali oldalán jelenleg 18 alapnak kell
    # lennie ebben a csoportban.
    #
    # Ha ettől eltérő számot kapunk, az Action
    # hibával leáll, így nem írunk hibás adatot
    # a funds.json fájlba.
    if len(fund_links) != len(ALLOWED_FUND_NAMES):

        raise RuntimeError(
            "A várt Forint II. eszközalapok száma "
            f"{len(ALLOWED_FUND_NAMES)}, "
            f"de a Generali oldalán "
            f"{len(fund_links)} található."
        )

    results = []

    for number, (url, name) in enumerate(
        fund_links.items(),
        start=1,
    ):

        print()
        print(
            f"[{number}/{len(fund_links)}] "
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
                    "  YTD adat nem található."
                )

                continue

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

            print(
                "  HIBA: "
                f"{type(error).__name__}: "
                f"{error}"
            )

    results.sort(
        key=lambda item:
        item["name"].casefold()
    )

    if not results:

        raise RuntimeError(
            "Egyetlen Forint II. "
            "eszközalap YTD adata sem "
            "volt feldolgozható."
        )

    # További biztonsági ellenőrzés:
    #
    # Ha valamelyik alap adatlekérése nem sikerült,
    # nem írjuk felül a korábbi funds.json-t.
    if len(results) != len(ALLOWED_FUND_NAMES):

        missing = (
            ALLOWED_FUND_NAMES
            - {
                item["name"]
                for item in results
            }
        )

        missing_text = ", ".join(
            sorted(missing)
        )

        raise RuntimeError(
            "Nem sikerült minden Forint II. "
            "eszközalap YTD adatát feldolgozni.\n"
            "Hiányzó alap(ok): "
            + missing_text
        )

    # Először ideiglenes fájlba írunk.
    #
    # Csak sikeres teljes feldolgozás után
    # cseréljük le a funds.json-t.
    temporary_file = (
        OUTPUT_FILE + ".tmp"
    )

    with open(
        temporary_file,
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

    import os

    os.replace(
        temporary_file,
        OUTPUT_FILE,
    )

    print()
    print("=" * 60)

    print(
        f"Sikeresen feldolgozva: "
        f"{len(results)} eszközalap"
    )

    print(
        f"Mentett fájl: {OUTPUT_FILE}"
    )

    print()
    print(
        "A funds.json kizárólag a "
        "Forint alapú eszközalapok II. "
        "csoportját tartalmazza."
    )


if __name__ == "__main__":
    scrape()
