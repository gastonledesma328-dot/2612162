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

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", 600))  # 10 minutos
    MAX_MATCHES = int(os.getenv("MAX_MATCHES", 20))  # Reducido para evitar timeouts
    PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", 30000))  # 30 segundos
    WAIT_AFTER_LOAD = int(os.getenv("WAIT_AFTER_LOAD", 3000))  # 3 segundos
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
    
    def update(self, new_matches: List[Dict]):
        with self.lock:
            self.matches.clear()
            self.matches.extend(new_matches)
            self.last_update = datetime.now()
            self.success_count += 1
    
    def get_all(self) -> List[Dict]:
        with self.lock:
            return list(self.matches)
    
    def increment_error(self, error_msg: str = None):
        with self.lock:
            self.error_count += 1
            if error_msg:
                self.last_error = error_msg[:200]
    
    def get_stats(self) -> Dict:
        with self.lock:
            return {
                "total_matches": len(self.matches),
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "is_scraping": self.is_scraping,
                "max_capacity": self.matches.maxlen,
                "successful_scrapes": self.success_count,
                "failed_scrapes": self.error_count,
                "last_error": self.last_error
            }

storage = MatchStorage(max_size=Config.MAX_MATCHES)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Iniciando servidor FastAPI en Render...")
    logger.info(f"Configuración: Intervalo={Config.SCRAPE_INTERVAL}s, Max matches={Config.MAX_MATCHES}")
    
    # Pequeña espera antes de iniciar el scraper
    await asyncio.sleep(5)
    
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
            logger.info("🕷️ Iniciando Playwright...")
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--single-process",  # Útil en entornos con recursos limitados
                    ],
                    timeout=30000
                )
                
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=True
                )
                
                page = context.new_page()
                page.set_default_timeout(Config.PAGE_TIMEOUT)
                
                # Intentar cargar la página principal
                logger.info(f"🌐 Navegando a {self.base_url}/es/football.html")
                try:
                    response = page.goto(f"{self.base_url}/es/football.html", wait_until="domcontentloaded")
                    logger.info(f"Respuesta: {response.status if response else 'No response'}")
                except Exception as e:
                    logger.error(f"Error cargando página principal: {str(e)}")
                    storage.increment_error(f"Error cargando página: {str(e)[:100]}")
                    return []
                
                page.wait_for_timeout(Config.WAIT_AFTER_LOAD)
                
                # Buscar enlaces de partidos
                links = page.query_selector_all("a")
                match_links = []
                
                for a in links:
                    href = a.get_attribute("href")
                    if href and "/football/" in href:
                        if href.startswith("/"):
                            full_url = self.base_url + href
                        elif href.startswith("http"):
                            full_url = href
                        else:
                            continue
                        
                        if full_url not in match_links:
                            match_links.append(full_url)
                
                logger.info(f"📊 Encontrados {len(match_links)} enlaces de partidos")
                
                if not match_links:
                    storage.increment_error("No se encontraron enlaces de partidos")
                    return []
                
                # Limitar número de partidos
                match_links = match_links[:Config.MAX_MATCHES]
                
                # Procesar cada partido
                for idx, match_url in enumerate(match_links, 1):
                    logger.info(f"🔄 Procesando partido {idx}/{len(match_links)}")
                    
                    try:
                        # Navegar al partido
                        page.goto(match_url, wait_until="domcontentloaded", timeout=Config.PAGE_TIMEOUT)
                        page.wait_for_timeout(2000)
                        
                        # Buscar iframes
                        frames = page.query_selector_all("iframe")
                        player_url = None
                        
                        for frame in frames:
                            src = frame.get_attribute("src")
                            if src and ("player" in src.lower() or "embed" in src.lower() or "live" in src.lower()):
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
                            logger.info(f"✅ Extraído: {player_url[:80]}...")
                        else:
                            logger.warning(f"❌ No se encontró player para: {match_url[:80]}...")
                    
                    except Exception as e:
                        logger.error(f"⚠️ Error procesando partido {idx}: {str(e)}")
                        continue
                
                return results
                
        except Exception as e:
            logger.error(f"💥 Error fatal en scraping: {str(e)}")
            logger.error(traceback.format_exc())
            storage.increment_error(str(e)[:100])
            return []
        
        finally:
            if browser:
                browser.close()
                logger.info("🔒 Browser cerrado")

scraper = FootballScraper()

def scrape_and_update():
    if storage.is_scraping:
        logger.warning("⚠️ Scraping ya en progreso, omitiendo...")
        return
    
    storage.is_scraping = True
    try:
        logger.info("🚀 Iniciando ciclo de scraping...")
        results = scraper.scrape_matches()
        
        if results:
            storage.update(results)
            logger.info(f"✨ Scraping completado: {len(results)} partidos encontrados")
        else:
            logger.warning("⚠️ No se encontraron resultados en el scraping")
            storage.increment_error("No se encontraron resultados")
            
    except Exception as e:
        logger.error(f"💥 Error en scrape_and_update: {str(e)}")
        logger.error(traceback.format_exc())
        storage.increment_error(str(e)[:100])
    finally:
        storage.is_scraping = False

def loop_scraper():
    logger.info("🔄 Loop scraper iniciado")
    first_run = True
    
    while True:
        try:
            if first_run:
                logger.info("⏳ Esperando 15 segundos antes del primer scraping...")
                time.sleep(15)
                first_run = False
            
            scrape_and_update()
            
            logger.info(f"💤 Esperando {Config.SCRAPE_INTERVAL} segundos...")
            
        except Exception as e:
            logger.error(f"💥 Error general en loop_scraper: {str(e)}")
            time.sleep(60)
        
        time.sleep(Config.SCRAPE_INTERVAL)

@app.get("/")
async def root():
    return {
        "status": "online",
        "api_version": "2.0.0",
        "environment": "Render.com",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "/matches": "GET - Obtener todos los partidos",
            "/stats": "GET - Estadísticas del scraper",
            "/scrape/now": "POST - Forzar scraping manual",
            "/health": "GET - Health check"
        }
    }

@app.get("/matches")
async def get_all_matches(limit: Optional[int] = None):
    matches = storage.get_all()
    if limit and limit > 0:
        matches = matches[:limit]
    return matches

@app.get("/stats")
async def get_stats():
    stats = storage.get_stats()
    stats["config"] = {
        "scrape_interval_seconds": Config.SCRAPE_INTERVAL,
        "max_matches": Config.MAX_MATCHES,
        "page_timeout_ms": Config.PAGE_TIMEOUT,
        "base_url": Config.BASE_URL
    }
    stats["server_time"] = datetime.now().isoformat()
    return stats

@app.post("/scrape/now")
async def force_scrape(background_tasks: BackgroundTasks):
    if storage.is_scraping:
        return {"status": "already_scraping", "message": "Scraping already in progress"}
    
    background_tasks.add_task(scrape_and_update)
    return {"status": "started", "message": "Scraping iniciado en segundo plano"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "scraping_active": storage.is_scraping,
        "matches_stored": len(storage.get_all())
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
