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

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )

        page = context.new_page()

        page.goto("https://www.fctv33hd.best/es/football.html", timeout=60000)

        # esperar que cargue JS
        page.wait_for_timeout(10000)

        matches = []

        # 🔥 buscar bloques de partidos (ajustable)
        items = page.query_selector_all("div, li")

        for item in items:
            try:
                text = item.inner_text().strip()

                # filtramos cosas vacías o irrelevantes
                if len(text) < 5:
                    continue

                # buscar si tiene onclick o evento
                onclick = item.get_attribute("onclick")

                if onclick:
                    matches.append({
                        "title": text,
                        "player": onclick
                    })

            except:
                pass

        DATA["matches"] = matches

        browser.close()


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
