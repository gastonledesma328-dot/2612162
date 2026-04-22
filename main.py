from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright
from typing import List, Dict, Optional
import threading
import time
import logging
from datetime import datetime
from contextlib import asynccontextmanager
import os
from collections import deque
import traceback

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    BASE_URL = "https://www.fctv33hd.best"
    MAX_MATCHES = 20
    PAGE_TIMEOUT = 45000
    HEADLESS = True

class MatchStorage:
    def __init__(self):
        self.matches = []
        self.last_update = None
        self.is_scraping = False
        self.error_count = 0
        self.success_count = 0
        self.last_error = None
        self.debug_logs = deque(maxlen=50)
    
    def add_log(self, msg: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.debug_logs.append(f"{timestamp} - {msg}")
        logger.info(msg)
    
    def update(self, new_matches: List[Dict]):
        self.matches = new_matches
        self.last_update = datetime.now()
        self.success_count += 1
        self.add_log(f"✅ Actualizados {len(new_matches)} partidos")
    
    def get_all(self):
        """Retorna todos los partidos"""
        return self.matches
    
    def get_by_match_url(self, match_url: str):
        """Busca un partido por URL"""
        for match in self.matches:
            if match.get("match_url") == match_url:
                return match
        return None
    
    def set_error(self, error_msg: str):
        self.error_count += 1
        self.last_error = error_msg[:200]
        self.add_log(f"❌ Error: {error_msg[:100]}")
    
    def get_stats(self):
        return {
            "total_matches": len(self.matches),
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "is_scraping": self.is_scraping,
            "successful_scrapes": self.success_count,
            "failed_scrapes": self.error_count,
            "last_error": self.last_error,
            "recent_logs": list(self.debug_logs)[-20:]  # Últimos 20 logs
        }

storage = MatchStorage()

def scrape_matches():
    """Función de scraping simplificada y robusta"""
    results = []
    browser = None
    
    try:
        storage.add_log("🕷️ Iniciando Playwright...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=Config.HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            
            page = browser.new_page()
            page.set_default_timeout(Config.PAGE_TIMEOUT)
            
            # Intentar cargar la página
            football_url = f"{Config.BASE_URL}/es/football.html"
            storage.add_log(f"🌐 Cargando: {football_url}")
            
            try:
                response = page.goto(football_url, wait_until="domcontentloaded")
                storage.add_log(f"📡 Respuesta: {response.status if response else 'N/A'}")
            except Exception as e:
                storage.add_log(f"❌ No se pudo cargar la página: {str(e)[:80]}")
                return []
            
            # Esperar un momento
            time.sleep(3)
            
            # Buscar enlaces de partidos
            storage.add_log("🔍 Buscando enlaces...")
            links = page.query_selector_all("a")
            storage.add_log(f"🔗 Total enlaces: {len(links)}")
            
            match_urls = []
            for a in links:
                href = a.get_attribute("href")
                if href and "football" in href.lower() and "/es/football/" in href:
                    if href.startswith("/"):
                        full_url = Config.BASE_URL + href
                    elif href.startswith("http"):
                        full_url = href
                    else:
                        continue
                    
                    if full_url not in match_urls:
                        match_urls.append(full_url)
            
            storage.add_log(f"📊 Partidos encontrados: {len(match_urls)}")
            
            if not match_urls:
                storage.set_error("No se encontraron enlaces de partidos")
                return []
            
            # Limitar cantidad
            match_urls = match_urls[:Config.MAX_MATCHES]
            
            # Procesar cada partido
            for idx, match_url in enumerate(match_urls, 1):
                storage.add_log(f"🔄 Procesando {idx}/{len(match_urls)}")
                
                try:
                    page.goto(match_url, wait_until="domcontentloaded")
                    time.sleep(2)
                    
                    # Buscar iframes
                    iframes = page.query_selector_all("iframe")
                    player_url = None
                    
                    for iframe in iframes:
                        src = iframe.get_attribute("src")
                        if src and ("player" in src.lower() or "embed" in src.lower()):
                            if src.startswith("//"):
                                src = "https:" + src
                            player_url = src
                            break
                    
                    if player_url:
                        results.append({
                            "match_url": match_url,
                            "player_url": player_url,
                            "scraped_at": datetime.now().isoformat()
                        })
                        storage.add_log(f"  ✅ Player encontrado")
                    else:
                        storage.add_log(f"  ⚠️ Sin player")
                        
                except Exception as e:
                    storage.add_log(f"  ❌ Error: {str(e)[:50]}")
                    continue
            
            storage.add_log(f"✨ Completado: {len(results)} players encontrados")
            return results
            
    except Exception as e:
        error_msg = str(e)
        storage.add_log(f"💥 Error fatal: {error_msg[:100]}")
        storage.set_error(error_msg)
        return []
    
    finally:
        if browser:
            browser.close()
            storage.add_log("🔒 Browser cerrado")

def run_scraper():
    """Ejecuta el scraping y actualiza el almacenamiento"""
    if storage.is_scraping:
        storage.add_log("⚠️ Scraping ya en curso")
        return
    
    storage.is_scraping = True
    try:
        storage.add_log("🚀 Iniciando scraping...")
        results = scrape_matches()
        
        if results:
            storage.update(results)
        else:
            storage.add_log("⚠️ No se obtuvieron resultados")
            
    except Exception as e:
        storage.add_log(f"💥 Error: {str(e)}")
        storage.set_error(str(e))
    finally:
        storage.is_scraping = False

# Inicializar FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - ejecutar scraping inmediatamente
    storage.add_log("🚀 Servidor iniciando...")
    storage.add_log("⏳ Ejecutando scraping inicial...")
    
    # Ejecutar scraping en un hilo separado
    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    
    yield
    
    # Shutdown
    storage.add_log("🛑 Servidor cerrando")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoints
@app.get("/")
async def root():
    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "/matches": "GET - Ver partidos",
            "/stats": "GET - Estadísticas",
            "/scrape": "POST - Forzar scraping",
            "/logs": "GET - Ver logs",
            "/health": "GET - Health check"
        }
    }

@app.get("/matches")
async def get_matches():
    """Obtiene todos los partidos"""
    return storage.get_all()

@app.get("/stats")
async def get_stats():
    """Obtiene estadísticas del scraper"""
    return storage.get_stats()

@app.post("/scrape")
async def force_scrape():
    """Fuerza un scraping manual"""
    if storage.is_scraping:
        return {"status": "already_scraping", "message": "Espera a que termine el actual"}
    
    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    return {"status": "started", "message": "Scraping iniciado"}

@app.get("/logs")
async def get_logs():
    """Obtiene los logs de depuración"""
    return {"logs": list(storage.debug_logs)}

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "scraping": storage.is_scraping,
        "matches": len(storage.get_all())
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
