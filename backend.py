from fastapi import FastAPI
from playwright.sync_api import sync_playwright
import threading
import time

app = FastAPI()

DATA = {
    "matches": []
}

def scrape():
    global DATA

    matches = []
    players = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )

        page = context.new_page()

        # 🔹 PASO 1: obtener partidos
        page.goto("https://www.fctv33hd.best/es/football.html", timeout=60000)
        page.wait_for_timeout(8000)

        links = page.query_selector_all("a[href*='/football/']")

        for a in links[:10]:  # limitamos por Render
            try:
                href = a.get_attribute("href")

                if not href:
                    continue

                full_url = "https://www.fctv33hd.best" + href

                matches.append(full_url)

            except:
                pass

        # 🔹 PASO 2: entrar a cada partido y capturar player
        for match in matches:
            try:
                page.goto(match, timeout=60000)
                page.wait_for_timeout(8000)

                # buscar iframe
                iframe = page.query_selector("iframe")

                if iframe:
                    src = iframe.get_attribute("src")

                    if src and "player" in src:
                        players.append({
                            "match": match,
                            "player": src
                        })

            except:
                pass

        browser.close()

    DATA["matches"] = players

def loop_scraper():
    while True:
        try:
            scrape()
            print("Scrape actualizado:", len(DATA["matches"]))
        except Exception as e:
            print("Error:", e)

        time.sleep(300)  # cada 5 minutos


threading.Thread(target=loop_scraper, daemon=True).start()


@app.get("/")
def home():
    return {"status": "ok"}


@app.get("/matches")
def get_matches():
    return DATA
