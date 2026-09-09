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
        "Generali eszközalapok frissítése"
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
        f"Talált eszközalap oldalak: "
        f"{len(fund_links)}"
    )

    if not fund_links:

        raise RuntimeError(
            "A Generali főoldalán nem "
            "találtam eszközalap-linkeket."
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

            # Rövid szünet, hogy ne terheljük
            # feleslegesen a forrásszervert.
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
            "Egyetlen eszközalap YTD adata "
            "sem volt feldolgozható."
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

    print(
        f"Mentett fájl: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    scrape()
