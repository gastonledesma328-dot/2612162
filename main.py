from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright, TimeoutError
from typing import List, Dict, Optional
import threading
import time
import logging
from datetime import datetime
from contextlib import asynccontextmanager
import os
from collections import deque
import traceback
import asyncio

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    BASE_URL = os.getenv("BASE_URL", "https://www.fctv33hd.best")
    MAX_MATCHES = int(os.getenv("MAX_MATCHES", "10"))  # Reducido para pruebas
    PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "30000"))  # 30 segundos
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
        return self.matches
    
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
            "recent_logs": list(self.debug_logs)[-20:]
        }

storage = MatchStorage()

def scrape_matches():
    """Función de scraping con mejor manejo de errores y timeouts"""
    results = []
    browser = None
    
    try:
        storage.add_log("🕷️ Iniciando Playwright...")
        
        with sync_playwright() as p:
            storage.add_log("📦 Playwright iniciado, lanzando Chromium...")
            
            browser = p.chromium.launch(
                headless=Config.HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor"
                ]
            )
            
            storage.add_log("✅ Chromium lanzado, creando contexto...")
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True
            )
            
            page = context.new_page()
            page.set_default_timeout(Config.PAGE_TIMEOUT)
            
            # Intentar cargar la página de fútbol
            football_url = f"{Config.BASE_URL}/es/football.html"
            storage.add_log(f"🌐 Cargando: {football_url}")
            
            try:
                # Usar 'domcontentloaded' para no esperar recursos pesados
                response = page.goto(football_url, wait_until="domcontentloaded", timeout=Config.PAGE_TIMEOUT)
                status = response.status if response else "No response"
                storage.add_log(f"📡 Respuesta: {status}")
                
                if response and response.status != 200:
                    storage.add_log(f"⚠️ El sitio respondió con código {response.status}")
                    
            except TimeoutError:
                storage.add_log("❌ Timeout cargando la página")
                return []
            except Exception as e:
                storage.add_log(f"❌ Error cargando página: {str(e)[:80]}")
                return []
            
            # Esperar un momento para que cargue el JavaScript
            storage.add_log("⏳ Esperando carga de contenido...")
            time.sleep(5)
            
            # Obtener el título para verificar que cargó
            try:
                title = page.title()
                storage.add_log(f"📄 Título de la página: {title[:50]}")
            except:
                storage.add_log("⚠️ No se pudo obtener el título")
            
            # Buscar enlaces de partidos
            storage.add_log("🔍 Buscando enlaces de partidos...")
            
            # Múltiples estrategias para encontrar enlaces
            match_urls = []
            
            # Estrategia 1: Buscar todos los enlaces que contengan 'football'
            links = page.query_selector_all("a")
            storage.add_log(f"🔗 Total de enlaces encontrados: {len(links)}")
            
            for a in links:
                href = a.get_attribute("href")
                if href and ("/football/" in href or "football" in href.lower()):
                    if href.startswith("/"):
                        full_url = Config.BASE_URL + href
                    elif href.startswith("http"):
                        full_url = href
                    else:
                        continue
                    
                    # Filtrar URLs válidas
                    if full_url not in match_urls and "football" in full_url:
                        match_urls.append(full_url)
            
            # Estrategia 2: Si no encontró, buscar con selector específico
            if not match_urls:
                storage.add_log("🔄 Intentando estrategia alternativa...")
                football_links = page.query_selector_all("a[href*='/football/']")
                for a in football_links:
                    href = a.get_attribute("href")
                    if href:
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
                # Mostrar algunos ejemplos para depuración
                sample_links = [a.get_attribute("href") for a in links[:5] if a.get_attribute("href")]
                storage.add_log(f"📝 Ejemplos de enlaces en la página: {sample_links}")
                return []
            
            # Limitar cantidad
            match_urls = match_urls[:Config.MAX_MATCHES]
            
            # Procesar cada partido
            for idx, match_url in enumerate(match_urls, 1):
                storage.add_log(f"🔄 Procesando {idx}/{len(match_urls)}")
                storage.add_log(f"   URL: {match_url[:80]}...")
                
                try:
                    # Navegar al partido
                    page.goto(match_url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(3)  # Esperar a que cargue el reproductor
                    
                    # Buscar iframes
                    iframes = page.query_selector_all("iframe")
                    storage.add_log(f"   Iframes encontrados: {len(iframes)}")
                    
                    player_url = None
                    for iframe in iframes:
                        src = iframe.get_attribute("src")
                        if src:
                            if src.startswith("//"):
                                src = "https:" + src
                            
                            # Verificar si es un reproductor
                            if any(keyword in src.lower() for keyword in ["player", "embed", "live", "stream", "video"]):
                                player_url = src
                                break
                    
                    # Si no encontró en iframes, buscar en otros elementos
                    if not player_url:
                        video_elements = page.query_selector_all("video source, [data-src*='player'], [data-url]")
                        for elem in video_elements:
                            src = elem.get_attribute("src") or elem.get_attribute("data-src") or elem.get_attribute("data-url")
                            if src:
                                player_url = src
                                break
                    
                    if player_url:
                        results.append({
                            "match_url": match_url,
                            "player_url": player_url,
                            "scraped_at": datetime.now().isoformat()
                        })
                        storage.add_log(f"   ✅ Player encontrado")
                    else:
                        storage.add_log(f"   ⚠️ No se encontró player")
                        
                except TimeoutError:
                    storage.add_log(f"   ⏰ Timeout en {match_url[:50]}...")
                    continue
                except Exception as e:
                    storage.add_log(f"   ❌ Error: {str(e)[:50]}")
                    continue
            
            storage.add_log(f"✨ Scraping completado: {len(results)} players encontrados")
            return results
            
    except Exception as e:
        error_msg = str(e)
        storage.add_log(f"💥 Error fatal: {error_msg[:100]}")
        storage.add_log(traceback.format_exc()[:200])
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
        storage.add_log(f"💥 Error en run_scraper: {str(e)}")
        storage.set_error(str(e))
    finally:
        storage.is_scraping = False
        storage.add_log("🏁 Scraping finalizado")

# Inicializar FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    storage.add_log("🚀 Servidor iniciando...")
    storage.add_log("⏳ Ejecutando scraping inicial en segundo plano...")
    
    # Ejecutar scraping en un hilo separado sin bloquear
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
    return storage.get_all()

@app.get("/stats")
async def get_stats():
    return storage.get_stats()

@app.post("/scrape")
async def force_scrape():
    if storage.is_scraping:
        return {"status": "already_scraping", "message": f"Espera a que termine (actualmente {storage.is_scraping})"}
    
    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    return {"status": "started", "message": "Scraping iniciado"}

@app.get("/logs")
async def get_logs():
    return {"logs": list(storage.debug_logs)}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "scraping": storage.is_scraping,
        "matches": len(storage.get_all()),
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
