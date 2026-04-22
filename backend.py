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

        # 🔥 interceptar requests
        def handle_request(request):
            url = request.url

            if "player.html" in url and "mdata=" in url:
                results.append({
                    "player": url
                })

        page.on("request", handle_request)

        page.goto("https://www.fctv33hd.best/es/football.html", timeout=60000)

        # esperar que cargue todo
        page.wait_for_timeout(15000)

        browser.close()

    # eliminar duplicados
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
