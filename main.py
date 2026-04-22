from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

# Configuración de logging para Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Modelos de datos
class MatchData(BaseModel):
    match_url: str
    player_url: str
    scraped_at: str

class ScrapeResponse(BaseModel):
    success: bool
    message: str
    matches_count: int

# Configuración para Render
class Config:
    # Intervalos y límites
    SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", 300))  # 5 minutos default
    MAX_MATCHES = int(os.getenv("MAX_MATCHES", 50))
    PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", 60000))
    WAIT_AFTER_LOAD = int(os.getenv("WAIT_AFTER_LOAD", 5000))
    
    # Configuración de navegador para entorno serverless
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    HEADLESS = True
    
    # URLs
    BASE_URL = os.getenv("BASE_URL", "https://www.fctv33hd.best")
    
    # Configuración de Playwright para Render
    PLAYWRIGHT_BROWSERS_PATH = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
    
    # Headers adicionales para evitar bloqueos
    EXTRA_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.8,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

# Almacenamiento con límite de tamaño
class MatchStorage:
    def __init__(self, max_size: int = 100):
        self.matches: deque = deque(maxlen=max_size)
        self.last_update: Optional[datetime] = None
        self.is_scraping: bool = False
        self.lock = threading.Lock()
        self.error_count = 0
        self.success_count = 0
    
    def update(self, new_matches: List[Dict]):
        with self.lock:
            self.matches.clear()
            self.matches.extend(new_matches)
            self.last_update = datetime.now()
            self.success_count += 1
    
    def get_all(self) -> List[Dict]:
        with self.lock:
            return list(self.matches)
    
    def get_by_match_url(self, match_url: str) -> Optional[Dict]:
        with self.lock:
            for match in self.matches:
                if match.get("match_url") == match_url:
                    return match
            return None
    
    def increment_error(self):
        with self.lock:
            self.error_count += 1
    
    def get_stats(self) -> Dict:
        with self.lock:
            return {
                "total_matches": len(self.matches),
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "is_scraping": self.is_scraping,
                "max_capacity": self.matches.maxlen,
                "successful_scrapes": self.success_count,
                "failed_scrapes": self.error_count
            }

storage = MatchStorage(max_size=Config.MAX_MATCHES)

# Lifespan manager para startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Iniciando servidor FastAPI en Render...")
    logger.info(f"Configuración: Intervalo={Config.SCRAPE_INTERVAL}s, Max matches={Config.MAX_MATCHES}")
    
    # Iniciar scraper en thread separado
    scraper_thread = threading.Thread(target=loop_scraper, daemon=True)
    scraper_thread.start()
    logger.info("✅ Scraper thread iniciado")
    
    yield
    
    # Shutdown
    logger.info("🛑 Cerrando servidor...")

# Inicializar FastAPI
app = FastAPI(
    title="Football Match Scraper API",
    description="API para extraer enlaces de partidos de fútbol - Optimizada para Render.com",
    version="2.0.0",
    lifespan=lifespan
)

# Configurar CORS para Render
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Clase mejorada del scraper para Render
class FootballScraper:
    def __init__(self):
        self.base_url = Config.BASE_URL
        self.player_domains = ["player.html", "embed", "live", "stream", "m3u8", "mp4"]
    
    def scrape_matches(self) -> List[Dict]:
        """Función principal de scraping con manejo de errores mejorado"""
        results = []
        browser = None
        
        try:
            logger.info("🕷️ Iniciando Playwright...")
            with sync_playwright() as p:
                # Configuración para entorno headless en Render
                browser = p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-web-security",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--window-size=1920,1080"
                    ]
                )
                
                context = browser.new_context(
                    user_agent=Config.USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale="es-ES",
                    timezone_id="Europe/Madrid",
                    extra_http_headers=Config.EXTRA_HEADERS
                )
                
                page = context.new_page()
                page.set_default_timeout(Config.PAGE_TIMEOUT)
                
                # Paso 1: Obtener lista de partidos
                match_links = self._get_match_links(page)
                logger.info(f"📊 Encontrados {len(match_links)} enlaces de partidos")
                
                if not match_links:
                    logger.warning("⚠️ No se encontraron enlaces de partidos")
                    return []
                
                # Paso 2: Procesar cada partido
                for idx, match_url in enumerate(match_links, 1):
                    logger.info(f"🔄 Procesando partido {idx}/{len(match_links)}")
                    
                    try:
                        player_url = self._extract_player_url(page, match_url)
                        if player_url:
                            results.append({
                                "match_url": match_url,
                                "player_url": player_url,
                                "scraped_at": datetime.now().isoformat()
                            })
                            logger.info(f"✅ Extraído: {player_url[:100]}...")
                        else:
                            logger.warning(f"❌ No se encontró player para: {match_url[:80]}...")
                    
                    except Exception as e:
                        logger.error(f"⚠️ Error procesando partido {idx}: {str(e)}")
                        storage.increment_error()
                        continue
                
                return results
                
        except Exception as e:
            logger.error(f"💥 Error fatal en scraping: {str(e)}")
            storage.increment_error()
            return []
        
        finally:
            if browser:
                browser.close()
                logger.info("🔒 Browser cerrado")
    
    def _get_match_links(self, page) -> List[str]:
        """Extrae enlaces de partidos de la página principal"""
        try:
            logger.info(f"🌐 Navegando a {self.base_url}/es/football.html")
            page.goto(f"{self.base_url}/es/football.html", timeout=Config.PAGE_TIMEOUT)
            page.wait_for_timeout(Config.WAIT_AFTER_LOAD)
            
            # Esperar a que los enlaces estén presentes
            try:
                page.wait_for_selector("a[href*='/football/']", timeout=10000)
            except PlaywrightTimeoutError:
                logger.warning("Timeout esperando selectores, continuando de todas formas...")
            
            links = page.query_selector_all("a[href*='/football/']")
            match_links = []
            
            for a in links[:Config.MAX_MATCHES]:
                href = a.get_attribute("href")
                if href and href not in match_links:
                    # Construir URL completa
                    if href.startswith("http"):
                        full_url = href
                    elif href.startswith("//"):
                        full_url = "https:" + href
                    else:
                        full_url = self.base_url + href if href.startswith("/") else f"{self.base_url}/{href}"
                    
                    match_links.append(full_url)
            
            logger.info(f"🔗 Extraídos {len(match_links)} enlaces únicos")
            return match_links
            
        except PlaywrightTimeoutError as e:
            logger.error(f"⏰ Timeout cargando la página principal: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"💥 Error extrayendo enlaces: {str(e)}")
            return []
    
    def _extract_player_url(self, page, match_url: str) -> Optional[str]:
        """Extrae la URL del reproductor de la página del partido"""
        try:
            page.goto(match_url, timeout=Config.PAGE_TIMEOUT)
            page.wait_for_timeout(Config.WAIT_AFTER_LOAD)
            
            # Buscar iframes
            frames = page.query_selector_all("iframe")
            
            for frame in frames:
                src = frame.get_attribute("src")
                if src:
                    # Normalizar URL
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        src = Config.BASE_URL + src
                    
                    # Verificar si es reproductor
                    if any(keyword in src.lower() for keyword in self.player_domains):
                        return src
            
            # Buscar en otros elementos
            selectors = [
                "video source",
                "[data-src*='player']",
                "[data-url*='stream']",
                "a[href*='player.html']",
                "div[data-player]"
            ]
            
            for selector in selectors:
                elements = page.query_selector_all(selector)
                for elem in elements:
                    src = (elem.get_attribute("src") or 
                          elem.get_attribute("data-src") or 
                          elem.get_attribute("href") or
                          elem.get_attribute("data-url"))
                    if src and any(keyword in src.lower() for keyword in self.player_domains):
                        return src
            
            return None
            
        except PlaywrightTimeoutError:
            logger.debug(f"Timeout en {match_url[:80]}...")
            return None
        except Exception as e:
            logger.debug(f"Error menor extrayendo player: {str(e)}")
            return None

# Instancia del scraper
scraper = FootballScraper()

def scrape_and_update():
    """Ejecuta scraping y actualiza el almacenamiento"""
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
            
    except Exception as e:
        logger.error(f"💥 Error en scrape_and_update: {str(e)}")
        storage.increment_error()
    finally:
        storage.is_scraping = False

def loop_scraper():
    """Loop principal del scraper en background"""
    logger.info("🔄 Loop scraper iniciado")
    first_run = True
    
    while True:
        try:
            # Esperar un poco en el primer inicio
            if first_run:
                logger.info("⏳ Esperando 10 segundos antes del primer scraping...")
                time.sleep(10)
                first_run = False
            
            scrape_and_update()
            
            logger.info(f"💤 Esperando {Config.SCRAPE_INTERVAL} segundos para próximo scraping...")
            
        except Exception as e:
            logger.error(f"💥 Error general en loop_scraper: {str(e)}")
        
        time.sleep(Config.SCRAPE_INTERVAL)

# Endpoints de la API
@app.get("/", tags=["Info"])
async def root():
    """Endpoint principal con información de la API"""
    return {
        "status": "online",
        "api_version": "2.0.0",
        "environment": "Render.com",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "/matches": "GET - Obtener todos los partidos",
            "/matches/{match_url}": "GET - Buscar partido específico",
            "/matches/search": "GET - Buscar por query params",
            "/stats": "GET - Estadísticas del scraper",
            "/scrape/now": "POST - Forzar scraping manual",
            "/health": "GET - Health check"
        }
    }

@app.get("/matches", response_model=List[MatchData], tags=["Matches"])
async def get_all_matches(limit: Optional[int] = None):
    """Obtiene todos los partidos scrapeados"""
    matches = storage.get_all()
    
    if limit and limit > 0:
        matches = matches[:limit]
    
    return matches

@app.get("/matches/search", tags=["Matches"])
async def search_matches(query: str):
    """Busca partidos por URL (búsqueda parcial)"""
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter 'query' is required")
    
    matches = storage.get_all()
    filtered = [
        match for match in matches 
        if query.lower() in match.get("match_url", "").lower()
    ]
    
    return {
        "query": query,
        "total": len(filtered),
        "matches": filtered
    }

@app.get("/matches/{match_url:path}", tags=["Matches"])
async def get_match_by_url(match_url: str):
    """Obtiene un partido específico por su URL"""
    from urllib.parse import unquote
    match_url = unquote(match_url)
    
    match = storage.get_by_match_url(match_url)
    
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    return match

@app.post("/scrape/now", response_model=ScrapeResponse, tags=["Admin"])
async def force_scrape(background_tasks: BackgroundTasks):
    """Fuerza un scraping manual en segundo plano"""
    if storage.is_scraping:
        raise HTTPException(status_code=409, detail="Scraping already in progress")
    
    background_tasks.add_task(scrape_and_update)
    
    return {
        "success": True,
        "message": "Scraping iniciado en segundo plano",
        "matches_count": len(storage.get_all())
    }

@app.get("/stats", tags=["Info"])
async def get_stats():
    """Obtiene estadísticas del scraper"""
    stats = storage.get_stats()
    stats["config"] = {
        "scrape_interval_seconds": Config.SCRAPE_INTERVAL,
        "max_matches": Config.MAX_MATCHES,
        "page_timeout_ms": Config.PAGE_TIMEOUT,
        "base_url": Config.BASE_URL
    }
    stats["server_time"] = datetime.now().isoformat()
    return stats

@app.get("/health", tags=["Info"])
async def health_check():
    """Health check para monitoreo de Render"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "scraping_active": storage.is_scraping,
        "matches_stored": len(storage.get_all()),
        "uptime_seconds": (datetime.now() - storage.last_update).total_seconds() if storage.last_update else 0
    }

# Middleware para logging de requests
@app.middleware("http")
async def log_requests(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Time: {process_time:.3f}s"
    )
    
    return response

# Punto de entrada para Render
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )
