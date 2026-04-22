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

    results = []

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
        page.wait_for_timeout(12000)

        links = page.query_selector_all("a[href*='/football/']")

        match_links = []

        for a in links[:10]:  # limitar por rendimiento
            href = a.get_attribute("href")
            if href:
                match_links.append("https://www.fctv33hd.best" + href)

        # 🔹 PASO 2: entrar a cada partido
        for match in match_links:
            try:
                page.goto(match, timeout=60000)

                # 🔥 esperar el iframe REAL
                page.wait_for_selector("iframe", timeout=15000)

                frames = page.query_selector_all("iframe")

for f in frames:
    src = f.get_attribute("src")
    if src and "player.html" in src:
        results.append({
            "match": match,
            "player": src
        })

                if iframe:
                    src = iframe.get_attribute("src")

                    if src and "player.html" in src:
                        results.append({
                            "match": match,
                            "player": src
                        })

            except:
                pass

        browser.close()

    DATA["matches"] = results

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
