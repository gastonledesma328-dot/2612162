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
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )

        page = context.new_page()

        page.goto("https://www.fctv33hd.best/es/football.html", timeout=60000)
        page.wait_for_timeout(5000)

        links = page.query_selector_all("a")

        matches = []

        for a in links:
            try:
                href = a.get_attribute("href")
                text = a.inner_text()

                if href and "player" in href:
                    matches.append({
                        "title": text.strip(),
                        "player": href
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
