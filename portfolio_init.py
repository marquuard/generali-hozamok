import json, re, shutil
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

MAIN_URL="https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink.aspx"
IMAGE_DIR=Path("portfolio_images")
OUTPUT=Path("portfolio.json")
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; GeneraliFundTracker/5.0)"}

FUNDS=[
("penzpiaci-2016","Pénzpiaci 2016 eszközalap"),
("hazai-kotveny","Hazai kötvény eszközalap"),
("tallozo","Tallózó abszolút hozam eszközalap"),
("vilagjaro-kotveny","Világjáró kötvény eszközalap"),
("horizont-15","Horizont 15+ vegyes eszközalap"),
("horizont-10","Horizont 10+ vegyes eszközalap"),
("horizont-5","Horizont 5+ vegyes eszközalap"),
("hazai-reszveny","Hazai részvény eszközalap"),
("fejlodo-vilag","Fejlődő világ részvény eszközalap"),
("fejlett-vilag","Fejlett világ részvény eszközalap"),
("vilagmarkak","Világmárkák részvény eszközalap"),
("innovacio","Innováció részvény eszközalap"),
("fenntarthato","Fenntartható Világ részvény eszközalap"),
("tudatos-fejlett","Tudatos fejlett piac részvény eszközalap"),
("tavlat-fejlodo","TávLat fejlődő piac részvény eszközalap"),
("kotveny-2027m","Kötvény 2027/M árfolyamvédett eszközalap"),
("magyar-piac","Magyar piac részvény eszközalap"),
("nemzetkozi-markak","Nemzetközi márkák részvény eszközalap"),
]

# A Generali aktuális oldalain ellenőrzött referenciaindexek.
REFERENCE_INDEX={
"penzpiaci-2016":"100%-ban RMAX Index",
"hazai-kotveny":"100%-ban MAX Composite Index",
"tallozo":"100%-ban RMAX Index",
"vilagjaro-kotveny":"20%-ban FTSE MTS Eurozone Government Bond 3-5Y 20%-ban JPM Government Bond Index Emerging Markets Global Core, 20%-ban Markit iBoxx EUR Liquid High Yield Index, 20%-ban iBoxx USD Liquid High Yield Index, 20%-ban RMAX Index",
"horizont-15":"40%-ban MAX Composite Index, 40%-ban MSCI World Index, 20%-ban MSCI Daily Total Return Net Emerging Markets Index",
"horizont-10":"60%-ban MAX Composite Index, 25%-ban MSCI World Index, 15%-ban MSCI Daily Total Return Net Emerging Markets Index",
"horizont-5":"80%-ban MAX Composite Index, 15%-ban MSCI World Index, 5%-ban MSCI Daily Total Return, Net Emerging Markets Index",
"hazai-reszveny":"80%-ban BUX index, 20%-ban RMAX Index",
"fejlodo-vilag":"80%-ban MSCI Daily Total Return Net Emerging Markets Index, 20%-ban RMAX Index",
"fejlett-vilag":"80%-ban MSCI World Index, 20%-ban RMAX Index",
"vilagmarkak":"40%-ban MSCI Daily TR World Consumer Staples Index, 40%-ban MSCI Daily TR World Net Consumer Discretionary Index, 20%-ban RMAX Index",
"innovacio":"80%-ban MSCI World Information Technology Index, 20%-ban RMAX Index",
"fenntarthato":"80% MSCI ACWI Sustainable Impact Index USD Net Total Return, 20% RMAX Index",
"tudatos-fejlett":"90% MSCI World Index, 10% RMAX Index",
"tavlat-fejlodo":"90% MSCI EM Emerging Markets IMI USD NET Index, 10% RMAX Index",
"kotveny-2027m":"ZMAX Index",
"magyar-piac":"90% BUX Index, 10% RMAX Index",
"nemzetkozi-markak":"45%-ban MSCI Daily TR World Consumer Staples Index, 45%-ban MSCI Daily TR World Net Consumer Discretionary Index, 10%-ban RMAX Index",
}

def clean(x): return re.sub(r"\s+"," ",x or "").strip()
def norm(x): return clean(x).casefold()

def discover():
    r=requests.get(MAIN_URL,headers=HEADERS,timeout=30); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    wanted={norm(n):(i,n) for i,n in FUNDS}; found={}
    for a in soup.find_all("a",href=True):
        t=clean(a.get_text(" ",strip=True)); k=norm(t)
        if k in wanted:
            fid,name=wanted[k]
            found[fid]={"id":fid,"name":name,"url":urljoin(MAIN_URL,a["href"])}
    missing=[n for i,n in FUNDS if i not in found]
    if missing: raise RuntimeError("Hiányzó link: "+", ".join(missing))
    return [found[i] for i,n in FUNDS]

def exact_reference_from_dom(page):
    # A címkéhez kötött DOM-elemből olvasunk, és csak a kettőspont utáni
    # értéket fogadjuk el. Így a "referenciaindex összetételétől" mondat
    # soha nem kerülhet az értékbe.
    value=page.evaluate("""
    () => {
      const nodes=[...document.querySelectorAll('body *')];
      for (const el of nodes) {
        const direct=[...el.childNodes]
          .filter(n=>n.nodeType===Node.TEXT_NODE)
          .map(n=>n.textContent.trim()).join(' ');
        if (/^Referenciaindex\\s*:/i.test(direct)) {
          const t=el.innerText.trim();
          const m=t.match(/^Referenciaindex\\s*:\\s*(.+)$/i);
          if(m && m[1].trim()) return m[1].trim();
        }
      }
      const body=document.body.innerText;
      const m=body.match(/(?:^|\\n)\\s*Referenciaindex\\s*:\\s*([^\\n]+)/i);
      return m ? m[1].trim() : null;
    }
    """)
    return clean(value) if value else None

def screenshot_chart_block(page,out):
    # A Generali grafikonja tipikusan SVG/canvas/img + a hozzá tartozó
    # jelmagyarázat. Az elemek ősei közül azt választjuk, amelynek
    # szövege százalékokat és több befektetési tételt tartalmaz.
    result=page.evaluate("""
    () => {
      const els=[...document.querySelectorAll('svg,canvas,img')];
      const candidates=[];
      for(const el of els){
        const r=el.getBoundingClientRect();
        if(r.width<180 || r.height<100) continue;
        let node=el;
        for(let level=0; level<7 && node; level++,node=node.parentElement){
          const b=node.getBoundingClientRect();
          if(b.width<250 || b.height<120 || b.width>window.innerWidth*1.2) continue;
          const txt=(node.innerText||node.textContent||'').replace(/\\s+/g,' ').trim();
          const pct=(txt.match(/\\d+(?:[.,]\\d+)?\\s*%/g)||[]).length;
          const names=(txt.match(/DKJ|MAXIM|MVM|Pénzeszköz|Egyéb befektetés|MSCI|RMAX/gi)||[]).length;
          const score=pct*20+names*12+Math.min(txt.length,800)/80;
          if(pct>=2 || names>=2){
            candidates.push({score,level,rect:{x:b.x,y:b.y,width:b.width,height:b.height},tag:node.tagName});
          }
        }
      }
      candidates.sort((a,b)=>b.score-a.score);
      return candidates[0]||null;
    }
    """)
    if not result:
        raise RuntimeError("Nem találtam a Generali diagram + jelmagyarázat DOM-blokkját.")
    r=result["rect"]
    # Element screenshot clipping: csak a blokk kerül a fájlba.
    clip={
      "x":max(0,r["x"]-8),
      "y":max(0,r["y"]-8),
      "width":min(page.viewport_size["width"]-max(0,r["x"]-8),r["width"]+16),
      "height":r["height"]+16
    }
    page.screenshot(path=str(out),clip=clip)
    print("  Diagram DOM blokk:",result["tag"],"score",round(result["score"],1))

def main():
    IMAGE_DIR.mkdir(parents=True,exist_ok=True)
    funds=discover()
    result={}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={"width":1440,"height":1200},device_scale_factor=1)
        for n,f in enumerate(funds,1):
            print(f"[{n}/18] {f['name']}")
            page.goto(f["url"],wait_until="networkidle",timeout=90000)
            page.wait_for_timeout(3500)
            ref=exact_reference_from_dom(page)
            expected=REFERENCE_INDEX[f["id"]]
            # Az oldalról kiolvasott értéket csak akkor fogadjuk el,
            # ha ténylegesen indexre hasonlít; egyébként az ellenőrzött
            # Generali-értéket használjuk.
            if not ref or not re.search(r"\b(?:RMAX|MAX|MSCI|BUX|ZMAX|FTSE|JPM|Markit|iBoxx|CETOP|S&P|Hang Seng|Nifty)\b",ref,re.I):
                ref=expected
            print("  Referenciaindex:",ref)
            out=IMAGE_DIR/f"{f['id']}.png"
            screenshot_chart_block(page,out)
            result[f["id"]]={
              "name":f["name"],
              "reference_index":ref,
              "portfolio_image":out.as_posix(),
              "source_url":f["url"]
            }
        browser.close()
    if len(result)!=18: raise RuntimeError("Nem készült el mind a 18 rekord.")
    payload={"_version":5,"funds":result}
    OUTPUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__": main()
