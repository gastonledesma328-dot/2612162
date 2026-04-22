from fastapi import FastAPI
from playwright.sync_api import sync_playwright
import threading
import time

app = FastAPI()

DATA = {"matches": []}


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

        # PASO 1
        page.goto("https://www.fctv33hd.best/es/football.html", timeout=60000)
        page.wait_for_timeout(8000)

        links = page.query_selector_all("a[href*='/football/']")
        match_links = []

        for a in links[:10]:
            href = a.get_attribute("href")
            if href:
                match_links.append("https://www.fctv33hd.best" + href)

        # PASO 2
        for match in match_links:
            try:
                page.goto(match, timeout=60000)
                page.wait_for_timeout(8000)

                frames = page.query_selector_all("iframe")

                for f in frames:
                    src = f.get_attribute("src")
                    if src and "player.html" in src:
                        results.append({
                            "match": match,
                            "player": src
                        })

            except Exception as e:
                print("Error:", e)

        browser.close()

    DATA["matches"] = results


def loop_scraper():
    while True:
        try:
            scrape()
            print("Scrape OK:", len(DATA["matches"]))
        except Exception as e:
            print("Error general:", e)

        time.sleep(300)


threading.Thread(target=loop_scraper, daemon=True).start()


@app.get("/")
def home():
    return {"status": "ok"}


@app.get("/matches")
def matches():
    return DATA
