# Generali eszközalapok

A GitHub Pages oldal a Generali „Forint alapú eszközalapok II.” 18 eszközalapját kezeli.

## Fájlok

- `index.html` – weboldal, keresés, YTD, referenciaindex, statikus portfóliódiagram, dark mode
- `scraper.py` – YTD-adatok automatikus frissítése
- `portfolio_init.py` – a Generali oldalairól egyszer, Playwrighttal lekéri a referenciaindexet és a portfóliódiagramot
- `.github/workflows/update.yml` – napi 3 frissítés

A portfólióadatok v3 formátumban egyszer készülnek el. A következő futások nem töltik le újra őket.
