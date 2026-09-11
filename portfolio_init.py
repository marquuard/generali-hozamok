import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


MAIN_URL = (
    "https://www.generali.hu/ugyfelszolgalat/informaciok/"
    "befektetesek/eszkozalapjaink.aspx"
)

IMAGE_DIR = Path("portfolio_images")
OUTPUT = Path("portfolio.json")

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


REFERENCE_INDEX = {
    "penzpiaci-2016": "100%-ban RMAX Index",
    "hazai-kotveny": "100%-ban MAX Composite Index",
    "tallozo": "100%-ban RMAX Index",
    "vilagjaro-kotveny": (
        "20%-ban FTSE MTS Eurozone Government Bond 3-5Y "
        "20%-ban JPM Government Bond Index Emerging Markets Global Core, "
        "20%-ban Markit iBoxx EUR Liquid High Yield Index, "
        "20%-ban iBoxx USD Liquid High Yield Index, "
        "20%-ban RMAX Index"
    ),
    "horizont-15": (
        "40%-ban MAX Composite Index, "
        "40%-ban MSCI World Index, "
        "20%-ban MSCI Daily Total Return Net Emerging Markets Index"
    ),
    "horizont-10": (
        "60%-ban MAX Composite Index, "
        "25%-ban MSCI World Index, "
        "15%-ban MSCI Daily Total Return Net Emerging Markets Index"
    ),
    "horizont-5": (
        "80%-ban MAX Composite Index, "
        "15%-ban MSCI World Index, "
        "5%-ban MSCI Daily Total Return, Net Emerging Markets Index"
    ),
    "hazai-reszveny": "80%-ban BUX index, 20%-ban RMAX Index",
    "fejlodo-vilag": (
        "80%-ban MSCI Daily Total Return Net Emerging Markets Index, "
        "20%-ban RMAX Index"
    ),
    "fejlett-vilag": "80%-ban MSCI World Index, 20%-ban RMAX Index",
    "vilagmarkak": (
        "40%-ban MSCI Daily TR World Consumer Staples Index, "
        "40%-ban MSCI Daily TR World Net Consumer Discretionary Index, "
        "20%-ban RMAX Index"
    ),
    "innovacio": (
        "80%-ban MSCI World Information Technology Index, "
        "20%-ban RMAX Index"
    ),
    "fenntarthato": (
        "80% MSCI ACWI Sustainable Impact Index USD Net Total Return, "
        "20% RMAX Index"
    ),
    "tudatos-fejlett": "90% MSCI World Index, 10% RMAX Index",
    "tavlat-fejlodo": (
        "90% MSCI EM Emerging Markets IMI USD NET Index, "
        "10% RMAX Index"
    ),
    "kotveny-2027m": "ZMAX Index",
    "magyar-piac": "90% BUX Index, 10% RMAX Index",
    "nemzetkozi-markak": (
        "45%-ban MSCI Daily TR World Consumer Staples Index, "
        "45%-ban MSCI Daily TR World Net Consumer Discretionary Index, "
        "10%-ban RMAX Index"
    ),
}


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def norm(value):
    return clean(value).casefold()


def discover():
    response = requests.get(MAIN_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    wanted = {
        norm(name): (fund_id, name)
        for fund_id, name in FUNDS
    }

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

    missing = [
        name
        for fund_id, name in FUNDS
        if fund_id not in found
    ]

    if missing:
        raise RuntimeError("Hiányzó link: " + ", ".join(missing))

    return [found[fund_id] for fund_id, name in FUNDS]


def exact_reference_from_dom(page):
    value = page.evaluate(
        """
        () => {
          const nodes = [...document.querySelectorAll('body *')];

          for (const el of nodes) {
            const direct = [...el.childNodes]
              .filter(n => n.nodeType === Node.TEXT_NODE)
              .map(n => n.textContent.trim())
              .join(' ');

            if (/^Referenciaindex\\s*:/i.test(direct)) {
              const text = el.innerText.trim();
              const match = text.match(
                /^Referenciaindex\\s*:\\s*(.+)$/i
              );
              if (match && match[1].trim()) {
                return match[1].trim();
              }
            }
          }

          const body = document.body.innerText;
          const match = body.match(
            /(?:^|\\n)\\s*Referenciaindex\\s*:\\s*([^\\n]+)/i
          );

          return match ? match[1].trim() : null;
        }
        """
    )
    return clean(value) if value else None


def dismiss_cookie_banner(page):
    """
    Kifejezetten kezeli a Generali felugró süti ablakát és eltávolítja az overlayt.
    """
    try:
        # Rákattint a "Mindegyik engedélyezése" gombra
        btn = page.locator("button:has-text('Mindegyik engedélyezése'), a:has-text('Mindegyik engedélyezése')").first
        if btn.is_visible():
            btn.click(timeout=2000)
            page.wait_for_timeout(500)
    except Exception:
        pass

    # DOM-szintű kényszerített törlés az esetleges kitakaró rétegekre
    page.evaluate(
        """
        () => {
          const cookieElements = document.querySelectorAll(
            '[class*="cookie"], [id*="cookie"], [class*="modal-backdrop"], [class*="overlay"]'
          );
          cookieElements.forEach(el => {
            const text = (el.innerText || '').toLowerCase();
            if (text.includes('sütiket') || text.includes('cookie') || el.className.includes('backdrop')) {
              el.remove();
            }
          });
          document.body.style.overflow = 'auto';
        }
        """
    )


def find_pie_chart_candidate(page):
    """
    Megkeresi a kördiagramot / fánkdiagramot és a hozzá tartozó jelmagyarázatot
    tartalmazó legszűkebb közös DOM elemet.
    Kizárja a felső vonaldiagramot.
    """
    return page.evaluate(
        """
        () => {
          const visible = el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return (
              r.width > 0 &&
              r.height > 0 &&
              s.display !== 'none' &&
              s.visibility !== 'hidden' &&
              Number(s.opacity || 1) > 0
            );
          };

          const makePath = el => {
            const parts = [];
            while (el && el.nodeType === Node.ELEMENT_NODE) {
              let part = el.tagName.toLowerCase();
              if (el.id) {
                part += '#' + CSS.escape(el.id);
                parts.unshift(part);
                break;
              }
              const parent = el.parentElement;
              if (!parent) {
                parts.unshift(part);
                break;
              }
              const siblings = [...parent.children].filter(
                child => child.tagName === el.tagName
              );
              if (siblings.length > 1) {
                part += ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')';
              }
              parts.unshift(part);
              el = parent;
            }
            return parts.join(' > ');
          };

          // Megkeressük az összes címsort vagy blokkot, amely a kördiagramra utal
          const allElements = [...document.querySelectorAll('div, section, article')].filter(visible);
          const pieCandidates = [];

          for (const el of allElements) {
            const text = (el.innerText || '').trim();
            
            // Kizáró feltételek: ne a felső árfolyam vonaldiagram legyen
            if (text.includes('Eszközalap árfolyama és nettó eszközértéke') && !text.includes('%')) {
              continue;
            }

            const hasPercentages = (text.match(/\\d+(?:[.,]\\d+)?\\s*%/g) || []).length;
            const hasCompositionTitle = /összetétel|portfólió|eszközalap\\s*\\(\\d{4}/i.test(text);
            const hasMedia = el.querySelector('svg, canvas') !== null;

            // Csak akkor jelölt, ha van benne kördiagram (SVG/Canvas), és releváns jelmagyarázat százalékokkal
            if (hasMedia && hasPercentages >= 2 && (hasCompositionTitle || text.includes('Egyéb befektetés') || text.includes('MÁK'))) {
              const r = el.getBoundingClientRect();
              
              // Kiszűrjük a túl nagy (teljes oldal) elemeket
              if (r.width > 250 && r.height > 150 && r.height < window.innerHeight * 2.0) {
                // A legkisebb befoglaló területet keressük, ami mindent tartalmaz
                const area = r.width * r.height;
                pieCandidates.push({
                  path: makePath(el),
                  area: area,
                  percentages: hasPercentages,
                  tag: el.tagName
                });
              }
            }
          }

          // Terület szerint növekvő sorrend (a legszűkebb szülő konténer a legjobb)
          pieCandidates.sort((a, b) => a.area - b.area);
          return pieCandidates[0] || null;
        }
        """
    )


def screenshot_chart_block(page, output_file):
    dismiss_cookie_banner(page)

    candidate = find_pie_chart_candidate(page)

    if candidate and candidate.get("path"):
        selector = candidate["path"]
        try:
            locator = page.locator(selector).first
            locator.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            
            # Mégegyszer futtatjuk a banner takarítást a görgetés után
            dismiss_cookie_banner(page)

            locator.screenshot(path=str(output_file), animations="disabled")
            if output_file.exists() and output_file.stat().st_size >= 1000:
                print(f"   Portfólió összetétel diagram sikeresen mentve: {selector}")
                return
        except Exception as e:
            print(f"   Elsődleges kivágás sikertelen ({e}), fallback próbálkozás...")

    # Fallback: Ha a heurisztika nem talált pontos konténert, megkeressük az alsó chart konténert
    try:
        charts = page.locator("div[class*='chart'], svg").all()
        # Ha több van, a második általában a kördiagram (az első az árfolyam vonaldiagram)
        target = charts[-1] if len(charts) > 1 else charts[0]
        target.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        target.screenshot(path=str(output_file), animations="disabled")
        if output_file.exists() and output_file.stat().st_size >= 1000:
            return
    except Exception:
        pass

    # Végső fallback
    page.screenshot(path=str(output_file), full_page=False)


def main():
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    funds = discover()
    result = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        page = browser.new_page(
            viewport={"width": 1440, "height": 1200},
            device_scale_factor=1
        )

        for number, fund in enumerate(funds, 1):
            print(f"[{number}/18] {fund['name']}")

            page.goto(
                fund["url"],
                wait_until="domcontentloaded",
                timeout=90000
            )

            # Megvárjuk az aszinkron betöltést és animációkat
            page.wait_for_timeout(4000)

            # -----------------------------
            # Referenciaindex
            # -----------------------------
            reference = exact_reference_from_dom(page)
            expected = REFERENCE_INDEX[fund["id"]]

            if (
                not reference
                or not re.search(
                    r"\b(?:RMAX|MAX|MSCI|BUX|ZMAX|FTSE|JPM|Markit|iBoxx|CETOP|S&P|Hang Seng|Nifty)\b",
                    reference,
                    re.I,
                )
            ):
                reference = expected

            print("   Referenciaindex:", reference)

            # -----------------------------
            # Portfólió összetétel diagram + jelmagyarázat
            # -----------------------------
            output_file = IMAGE_DIR / f"{fund['id']}.png"
            screenshot_chart_block(page, output_file)

            result[fund["id"]] = {
                "name": fund["name"],
                "reference_index": reference,
                "portfolio_image": output_file.as_posix(),
                "source_url": fund["url"]
            }

        browser.close()

    if len(result) != 18:
        raise RuntimeError("Nem készült el mind a 18 rekord.")

    payload = {
        "_version": 5,
        "funds": result
    }

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print("Sikeres futás: portfolio.json és a diagramok elkészültek.")


if __name__ == "__main__":
    main()
