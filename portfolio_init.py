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
    """Eltávolítja a sütis panelt és a hátteret."""
    try:
        btn = page.locator("button:has-text('Mindegyik engedélyezése'), a:has-text('Mindegyik engedélyezése')").first
        if btn.is_visible():
            btn.click(timeout=1500)
            page.wait_for_timeout(500)
    except Exception:
        pass

    try:
        page.evaluate(
            """
            () => {
              const selectors = [
                '#onetrust-banner-sdk',
                '.onetrust-pc-dark-filter',
                '[class*="cookie"]',
                '[id*="cookie"]',
                '.modal-backdrop',
                '.fade.show'
              ];
              selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => el.remove());
              });
              document.body.style.overflow = 'auto';
            }
            """
        )
    except Exception:
        pass


def isolate_and_style_chart_container(page):
    """
    1. Megkeresi a kördiagramot tartalmazó legszűkebb dobozt (Cím + Diagram + Jelmagyarázat).
    2. Kizár minden felesleges külső szekciót (Hozamok gomb, Fogalommagyarázat).
    3. Beállítja az átlátszó hátteret és a világos/sötét módban is olvasható kontrasztot.
    """
    return page.evaluate(
        """
        () => {
          // 1. Kördiagram SVG megkeresése (textContent-et vizsgálunk, mert innerText nem lát az SVG-be)
          const svgs = [...document.querySelectorAll('svg')];
          let donutSvg = svgs.find(s => s.textContent && s.textContent.includes('%'));
          
          if (!donutSvg && svgs.length > 0) {
            donutSvg = svgs[svgs.length - 1];
          }

          if (!donutSvg) return null;

          // 2. Felfelé lépkedés a DOM-ban a legszűkebb közös szülő konténerhez
          let curr = donutSvg.parentElement;
          let target = curr;

          while (curr && curr !== document.body && curr !== document.documentElement) {
            const text = curr.textContent || '';
            
            // Ha elérjük a szomszédos modulokat, MEG KELL ÁLLNI az előző szintnél!
            if (
              text.includes('FOGALOMMAGYARÁZAT') ||
              text.includes('HOZAMOK MEGJELENÍTÉSE') ||
              text.includes('Eszközalap árfolyama és nettó eszközértéke') ||
              text.includes('Alapvető információk') ||
              text.includes('Dokumentumok')
            ) {
              break;
            }
            target = curr;
            curr = curr.parentElement;
          }

          if (!target) return null;

          // 3. Hátterek törlése (transzparens PNG elérése)
          document.documentElement.style.setProperty('background', 'transparent', 'important');
          document.body.style.setProperty('background', 'transparent', 'important');

          let p = target;
          while (p) {
            p.style.setProperty('background', 'transparent', 'important');
            p.style.setProperty('background-color', 'transparent', 'important');
            p.style.setProperty('background-image', 'none', 'important');
            p.style.setProperty('box-shadow', 'none', 'important');
            p = p.parentElement;
          }

          // A dobozon belül is eltávolítjuk a fehér háttereket, kivéve a kis színes négyzeteket
          target.querySelectorAll('*').forEach(el => {
            const r = el.getBoundingClientRect();
            // A jelmagyarázat színes négyzeteit nem bántjuk
            if (r.width > 0 && r.width <= 25 && r.height > 0 && r.height <= 25) {
              return;
            }
            el.style.setProperty('background', 'transparent', 'important');
            el.style.setProperty('background-color', 'transparent', 'important');
            el.style.setProperty('background-image', 'none', 'important');
            el.style.setProperty('box-shadow', 'none', 'important');
          });

          // 4. Fehér kontúr / text-shadow a szövegeknek: sötét és világos témában is éles marad
          const styleId = '__isolated_chart_style';
          if (!document.getElementById(styleId)) {
            const style = document.createElement('style');
            style.id = styleId;
            style.innerHTML = `
              #__isolated_chart_box text,
              #__isolated_chart_box tspan {
                paint-order: stroke fill !important;
                stroke: rgba(255, 255, 255, 0.95) !important;
                stroke-width: 3.5px !important;
                stroke-linecap: round !important;
                stroke-linejoin: round !important;
                font-weight: bold !important;
              }
              #__isolated_chart_box h1,
              #__isolated_chart_box h2,
              #__isolated_chart_box h3,
              #__isolated_chart_box h4,
              #__isolated_chart_box p,
              #__isolated_chart_box span,
              #__isolated_chart_box div,
              #__isolated_chart_box b,
              #__isolated_chart_box strong {
                text-shadow:
                  -1.5px -1.5px 0 #ffffff,
                   1.5px -1.5px 0 #ffffff,
                  -1.5px  1.5px 0 #ffffff,
                   1.5px  1.5px 0 #ffffff,
                   0px 0px 4px #ffffff,
                   0px 0px 8px rgba(255, 255, 255, 0.9) !important;
              }
              #__isolated_chart_box polyline,
              #__isolated_chart_box path.amcharts-pie-tick {
                filter: drop-shadow(0px 0px 1px #ffffff) !important;
              }
            `;
            document.head.appendChild(style);
          }

          target.id = '__isolated_chart_box';
          target.scrollIntoView({ block: 'center', inline: 'center' });
          return '#__isolated_chart_box';
        }
        """
    )


def screenshot_chart_block(page, output_file):
    dismiss_cookie_banner(page)

    selector = isolate_and_style_chart_container(page)

    if selector:
        try:
            locator = page.locator(selector)
            locator.scroll_into_view_if_needed()
            page.wait_for_timeout(400)
            dismiss_cookie_banner(page)

            locator.screenshot(
                path=str(output_file),
                omit_background=True,
                animations="disabled"
            )

            if output_file.exists() and output_file.stat().st_size >= 1000:
                print(f"   Csak a tiszta diagram és jelmagyarázat mentve: {output_file.name}")
                return
        except Exception as e:
            print(f"   Szelektoros mentési hiba ({e}), tartalék vágás...")

    # Végső fallback kizárólag a diagram SVG-re
    try:
        svg_elem = page.locator("svg:has-text('%')").last
        svg_elem.screenshot(path=str(output_file), omit_background=True)
    except Exception:
        page.screenshot(path=str(output_file), omit_background=True, full_page=False)


def main():
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    funds = discover()
    result = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            device_scale_factor=1
        )
        page = context.new_page()

        # Süti inicializálás még az első alap megnyitása előtt
        try:
            page.goto(MAIN_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)
            dismiss_cookie_banner(page)
        except Exception:
            pass

        for number, fund in enumerate(funds, 1):
            print(f"[{number}/18] {fund['name']}")

            page.goto(
                fund["url"],
                wait_until="domcontentloaded",
                timeout=90000
            )

            # Megvárjuk az amCharts rajzolást
            page.wait_for_timeout(4000)
            dismiss_cookie_banner(page)

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
            # Csak a kördiagram + jelmagyarázat mentése
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
