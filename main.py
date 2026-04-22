from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel
from typing import List, Dict, Optional
import threading
import time
import logging
from datetime import datetime
from contextlib import asynccontextmanager
import os
from collections import deque
import asyncio
import traceback
import sys

# Configuración de logging más detallada
logging.basicConfig(
    level=logging.DEBUG,  # Cambiado a DEBUG para más detalles
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", 600))
    MAX_MATCHES = int(os.getenv("MAX_MATCHES", 10))  # Reducido para pruebas
    PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", 60000))
    WAIT_AFTER_LOAD = int(os.getenv("WAIT_AFTER_LOAD", 5000))
    BASE_URL = os.getenv("BASE_URL", "https://www.fctv33hd.best")
    HEADLESS = True

class MatchStorage:
    def __init__(self, max_size: int = 100):
        self.matches: deque = deque(maxlen=max_size)
        self.last_update: Optional[datetime] = None
        self.is_scraping: bool = False
        self.lock = threading.Lock()
        self.error_count = 0
        self.success_count = 0
        self.last_error: Optional[str] = None
        self.debug_logs: deque = deque(maxlen=20)
    
    def add_debug_log(self, msg: str):
        with self.lock:
            self.debug_logs.append(f"{datetime.now().strftime('%H:%M:%S')} - {msg}")
            logger.debug(msg)
    
    def update(self, new_matches: List[Dict]):
        with self.lock:
            self.matches.clear()
            self.matches.extend(new_matches)
            self.last_update = datetime.now()
            self.success_count += 1
            self.add_debug_log(f"✅ Actualizados {len(new_matches)} partidos")
    
    def increment_error(self, error_msg: str = None):
        with self.lock:
            self.error_count += 1
            if error_msg:
                self.last_error = error_msg[:200]
                self.add_debug_log(f"❌ Error: {error_msg[:100]}")
    
    def get_stats(self) -> Dict:
        with self.lock:
            return {
                "total_matches": len(self.matches),
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "is_scraping": self.is_scraping,
                "max_capacity": self.matches.maxlen,
                "successful_scrapes": self.success_count,
                "failed_scrapes": self.error_count,
                "last_error": self.last_error,
                "recent_logs": list(self.debug_logs)
            }

storage = MatchStorage(max_size=Config.MAX_MATCHES)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Iniciando servidor FastAPI en Render...")
    storage.add_debug_log("Servidor iniciado")
    
    # Esperar a que el servidor esté listo
    await asyncio.sleep(3)
    
    scraper_thread = threading.Thread(target=loop_scraper, daemon=True)
    scraper_thread.start()
    logger.info("✅ Scraper thread iniciado")
    
    yield
    
    logger.info("🛑 Cerrando servidor...")

app = FastAPI(
    title="Football Match Scraper API",
    description="API para extraer enlaces de partidos de fútbol",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FootballScraper:
    def __init__(self):
        self.base_url = Config.BASE_URL
    
    def scrape_matches(self) -> List[Dict]:
        results = []
        browser = None
        
        try:
            storage.add_debug_log("🕷️ Iniciando Playwright...")
            logger.info("🕷️ Iniciando Playwright...")
            
            with sync_playwright() as p:
                storage.add_debug_log("Playwright iniciado, lanzando Chromium...")
                
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]
                )
                
                storage.add_debug_log("Chromium lanzado, creando contexto...")
                
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=True
                )
                
                page = context.new_page()
                page.set_default_timeout(Config.PAGE_TIMEOUT)
                
                # Probar conectividad básica
                storage.add_debug_log(f"🌐 Navegando a {self.base_url}")
                logger.info(f"🌐 Navegando a {self.base_url}")
                
                try:
                    # Primero probar si el sitio responde
                    response = page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
                    storage.add_debug_log(f"Respuesta: {response.status if response else 'No response'}")
                    logger.info(f"Respuesta página principal: {response.status if response else 'No response'}")
                except Exception as e:
                    storage.add_debug_log(f"❌ Error cargando sitio: {str(e)[:100]}")
                    logger.error(f"Error cargando sitio: {str(e)}")
                    return []
                
                # Intentar con la página de fútbol
                football_url = f"{self.base_url}/es/football.html"
                storage.add_debug_log(f"🌐 Navegando a {football_url}")
                logger.info(f"🌐 Navegando a {football_url}")
                
                try:
                    response = page.goto(football_url, wait_until="domcontentloaded", timeout=30000)
                    storage.add_debug_log(f"Respuesta football: {response.status if response else 'No response'}")
                    
                    if response and response.status != 200:
                        storage.add_debug_log(f"⚠️ Respuesta no OK: {response.status}")
                except Exception as e:
                    storage.add_debug_log(f"❌ Error en football: {str(e)[:100]}")
                    logger.error(f"Error en football: {str(e)}")
                    return []
                
                # Esperar y obtener el HTML
                page.wait_for_timeout(Config.WAIT_AFTER_LOAD)
                
                # Obtener el título para verificar que cargó
                try:
                    title = page.title()
                    storage.add_debug_log(f"📄 Título de página: {title[:50]}")
                    logger.info(f"Título: {title}")
                except:
                    storage.add_debug_log("⚠️ No se pudo obtener título")
                
                # Buscar enlaces
                storage.add_debug_log("🔍 Buscando enlaces de partidos...")
                links = page.query_selector_all("a")
                storage.add_debug_log(f"🔗 Total enlaces encontrados: {len(links)}")
                
                match_links = []
                for a in links:
                    href = a.get_attribute("href")
                    if href and "football" in href.lower():
                        if href.startswith("/"):
                            full_url = self.base_url + href
                        elif href.startswith("http"):
                            full_url = href
                        else:
                            continue
                        
                        if full_url not in match_links:
                            match_links.append(full_url)
                
                storage.add_debug_log(f"📊 Enlaces de fútbol: {len(match_links)}")
                logger.info(f"Encontrados {len(match_links)} enlaces de partidos")
                
                if not match_links:
                    # Mostrar algunos ejemplos de enlaces para depuración
                    sample_links = [a.get_attribute("href") for a in links[:10] if a.get_attribute("href")]
                    storage.add_debug_log(f"Ejemplos de enlaces: {sample_links[:3]}")
                    storage.increment_error("No se encontraron enlaces de partidos")
                    return []
                
                match_links = match_links[:Config.MAX_MATCHES]
                
                for idx, match_url in enumerate(match_links, 1):
                    storage.add_debug_log(f"🔄 Procesando {idx}/{len(match_links)}")
                    logger.info(f"Procesando partido {idx}/{len(match_links)}")
                    
                    try:
                        page.goto(match_url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(2000)
                        
                        frames = page.query_selector_all("iframe")
                        storage.add_debug_log(f"  Iframes encontrados: {len(frames)}")
                        
                        player_url = None
                        for frame in frames:
                            src = frame.get_attribute("src")
                            if src:
                                if src.startswith("//"):
                                    src = "https:" + src
                                if any(k in src.lower() for k in ["player", "embed", "live", "stream"]):
                                    player_url = src
                                    break
                        
                        if player_url:
                            results.append({
                                "match_url": match_url,
                                "player_url": player_url,
                                "scraped_at": datetime.now().isoformat()
                            })
                            storage.add_debug_log(f"  ✅ Encontrado player")
                        else:
                            storage.add_debug_log(f"  ❌ Sin player")
                    
                    except Exception as e:
                        storage.add_debug_log(f"  ⚠️ Error: {str(e)[:50]}")
                        continue
                
                storage.add_debug_log(f"✨ Scraping completado: {len(results)} resultados")
                return results
                
        except Exception as e:
            error_msg = str(e)
            storage.add_debug_log(f"💥 Error fatal: {error_msg[:100]}")
            logger.error(f"Error fatal: {error_msg}")
            logger.error(traceback.format_exc())
            storage.increment_error(error_msg[:100])
            return []
        
        finally:
            if browser:
                browser.close()
                storage.add_debug_log("🔒 Browser cerrado")

scraper = FootballScraper()

def scrape_and_update():
    if storage.is_scraping:
        logger.warning("Scraping ya en progreso")
        return
    
    storage.is_scraping = True
    try:
        logger.info("🚀 Iniciando ciclo de scraping...")
        storage.add_debug_log("🚀 Inicio ciclo scraping")
        
        results = scraper.scrape_matches()
        
        if results:
            storage.update(results)
            logger.info(f"✅ Scraping completado: {len(results)} partidos")
        else:
            logger.warning("⚠️ No se encontraron resultados")
            storage.increment_error("No se encontraron resultados")
            
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        storage.increment_error(str(e)[:100])
    finally:
        storage.is_scraping = False

def loop_scraper():
    logger.info("Loop scraper iniciado")
    time.sleep(15)
    
    while True:
        try:
            scrape_and_update()
            logger.info(f"Esperando {Config.SCRAPE_INTERVAL} segundos...")
        except Exception as e:
            logger.error(f"Error en loop: {str(e)}")
            time.sleep(60)
        
        time.sleep(Config.SCRAPE_INTERVAL)

# Endpoints
@app.get("/")
async def root():
    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "/matches": "GET - Todos los partidos",
            "/stats": "GET - Estadísticas detalladas",
            "/scrape/now": "POST - Forzar scraping",
            "/health": "GET - Health check",
            "/debug/logs": "GET - Ver logs de depuración"
        }
    }

@app.get("/matches")
async def get_all_matches(limit: Optional[int] = None):
    matches = storage.get_all()
    if limit:
        matches = matches[:limit]
    return matches

@app.get("/stats")
async def get_stats():
    return storage.get_stats()

@app.post("/scrape/now")
async def force_scrape(background_tasks: BackgroundTasks):
    if storage.is_scraping:
        return {"status": "already_scraping"}
    
    background_tasks.add_task(scrape_and_update)
    return {"status": "started"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "scraping_active": storage.is_scraping,
        "matches_stored": len(storage.get_all())
    }

@app.get("/debug/logs")
async def get_debug_logs():
    """Endpoint de depuración para ver logs internos"""
    return {"logs": list(storage.debug_logs)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
