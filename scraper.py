import json
import re
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

MAIN_URL="https://www.generali.hu/ugyfelszolgalat/informaciok/befektetesek/eszkozalapjaink.aspx"
OUTPUT_FILE="funds.json"
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
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; GeneraliFundTracker/5.0)"}
s=requests.Session(); s.headers.update(HEADERS)

def clean(x): return re.sub(r"\s+"," ",x or "").strip()
def norm(x): return clean(x).casefold()

def links():
    r=s.get(MAIN_URL,timeout=30); r.raise_for_status()
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

def ytd(text):
    t=clean(text)
    for p in [
        r"Év elejétől számított hozam\s*\(nem évesített\)\s*[:\-]?\s*([+\-]?\d+(?:[.,]\d+)?)\s*%",
        r"Év elejétől számított hozam\s*[:\-]?\s*([+\-]?\d+(?:[.,]\d+)?)\s*%",
    ]:
        m=re.search(p,t,re.I)
        if m: return float(m.group(1).replace(",",".")) 
    return None

def date(text):
    t=clean(text)
    for p in [r"Értéknap\s*[:\-]?\s*(\d{4}\.\d{1,2}\.\d{1,2})",
              r"Utolsó értéknap\s*[:\-]?\s*(\d{4}\.\d{1,2}\.\d{1,2})",
              r"(\d{4}\.\d{2}\.\d{2})"]:
        m=re.search(p,t)
        if m:return m.group(1)
    return datetime.now().strftime("%Y.%m.%d")

def main():
    out=[]
    for n,f in enumerate(links(),1):
        print(f"[{n}/18] {f['name']}")
        try:
            r=s.get(f["url"],timeout=30); r.raise_for_status()
            text=BeautifulSoup(r.text,"html.parser").get_text(" ",strip=True)
            out.append({"id":f["id"],"name":f["name"],"ytd":ytd(text),"date":date(text),"url":f["url"]})
        except Exception as e:
            print(" HIBA:",e)
            out.append({"id":f["id"],"name":f["name"],"ytd":None,"date":datetime.now().strftime("%Y.%m.%d"),"url":f["url"]})
    if len(out)!=18: raise RuntimeError("Nem 18 rekord.")
    with open(OUTPUT_FILE,"w",encoding="utf-8") as fp: json.dump(out,fp,ensure_ascii=False,indent=2)
if __name__=="__main__": main()
