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
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )

        page = context.new_page()

        page.goto("https://www.fctv33hd.best/es/football.html", timeout=60000)

        page.wait_for_timeout(10000)

        # 🔥 buscar elementos clickeables reales
        elements = page.query_selector_all("a")

        for el in elements[:10]:  # limitar para no romper Render
            try:
                href = el.get_attribute("href")

                if href and "football" not in href:
                    continue

                # escuchar requests mientras navegamos
                def handle_request(request):
                    if "player.html" in request.url:
                        results.append({
                            "player": request.url
                        })

                page.on("request", handle_request)

                el.click(timeout=5000)
                page.wait_for_timeout(5000)

                page.go_back()
                page.wait_for_timeout(3000)

            except:
                pass

        browser.close()

    # limpiar duplicados
    unique = []
    seen = set()

    for r in results:
        if r["player"] not in seen:
            seen.add(r["player"])
            unique.append(r)

    DATA["matches"] = unique


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
