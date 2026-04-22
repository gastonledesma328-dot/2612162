from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
import threading
import time
import logging
from datetime import datetime
from contextlib import asynccontextmanager
import os
from collections import deque
import requests
from bs4 import BeautifulSoup
import re

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    BASE_URL = os.getenv("BASE_URL", "https://www.fctv33hd.best")
    MAX_MATCHES = int(os.getenv("MAX_MATCHES", "20"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

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
    """Scraping usando requests + BeautifulSoup (sin Playwright)"""
    results = []
    
    try:
        storage.add_log("🌐 Iniciando scraping con requests...")
        session = requests.Session()
        session.headers.update({
            'User-Agent': Config.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        # Paso 1: Obtener página principal de fútbol
        football_url = f"{Config.BASE_URL}/es/football.html"
        storage.add_log(f"📡 Obteniendo: {football_url}")
        
        try:
            response = session.get(football_url, timeout=Config.REQUEST_TIMEOUT)
            response.raise_for_status()
            storage.add_log(f"✅ Respuesta recibida (status: {response.status_code})")
        except requests.RequestException as e:
            storage.add_log(f"❌ Error obteniendo página: {str(e)[:80]}")
            return []
        
        # Parsear HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        storage.add_log("🔍 Parseando HTML...")
        
        # Buscar enlaces de partidos
        match_urls = []
        
        # Estrategia 1: Buscar enlaces que contengan '/football/'
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/football/' in href and href not in match_urls:
                if href.startswith('/'):
                    full_url = Config.BASE_URL + href
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                if 'football' in full_url and full_url not in match_urls:
                    match_urls.append(full_url)
        
        storage.add_log(f"📊 Enlaces de partidos encontrados: {len(match_urls)}")
        
        if not match_urls:
            storage.set_error("No se encontraron enlaces de partidos")
            return []
        
        # Limitar cantidad
        match_urls = match_urls[:Config.MAX_MATCHES]
        
        # Paso 2: Procesar cada partido
        for idx, match_url in enumerate(match_urls, 1):
            storage.add_log(f"🔄 Procesando {idx}/{len(match_urls)}")
            
            try:
                # Obtener página del partido
                match_response = session.get(match_url, timeout=Config.REQUEST_TIMEOUT)
                match_response.raise_for_status()
                
                match_soup = BeautifulSoup(match_response.text, 'html.parser')
                
                # Buscar iframes
                player_url = None
                
                # Buscar en iframes
                for iframe in match_soup.find_all('iframe'):
                    src = iframe.get('src', '')
                    if src and any(keyword in src.lower() for keyword in ['player', 'embed', 'live', 'stream']):
                        if src.startswith('//'):
                            src = 'https:' + src
                        player_url = src
                        break
                
                # Si no hay iframe, buscar en otros elementos
                if not player_url:
                    # Buscar en divs con data attributes
                    for div in match_soup.find_all(['div', 'section'], attrs={'data-src': True, 'data-url': True}):
                        src = div.get('data-src') or div.get('data-url')
                        if src and any(keyword in src.lower() for keyword in ['player', 'embed', 'live']):
                            player_url = src
                            break
                    
                    # Buscar en scripts
                    if not player_url:
                        scripts = match_soup.find_all('script')
                        for script in scripts:
                            if script.string:
                                # Buscar URLs de player en scripts
                                match = re.search(r'(https?://[^\s"\']+player[^\s"\']+)', script.string)
                                if match:
                                    player_url = match.group(1)
                                    break
                
                if player_url:
                    results.append({
                        "match_url": match_url,
                        "player_url": player_url,
                        "scraped_at": datetime.now().isoformat()
                    })
                    storage.add_log(f"  ✅ Player encontrado: {player_url[:60]}...")
                else:
                    storage.add_log(f"  ⚠️ No se encontró player")
                    
            except requests.RequestException as e:
                storage.add_log(f"  ❌ Error en {match_url[:50]}: {str(e)[:50]}")
                continue
            except Exception as e:
                storage.add_log(f"  ❌ Error inesperado: {str(e)[:50]}")
                continue
        
        storage.add_log(f"✨ Scraping completado: {len(results)} players encontrados")
        return results
        
    except Exception as e:
        error_msg = str(e)
        storage.add_log(f"💥 Error fatal: {error_msg[:100]}")
        storage.set_error(error_msg)
        return []

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
            # Si no hay resultados, intentar con URL alternativa
            storage.add_log("🔄 Intentando con URL base alternativa...")
            original_base = Config.BASE_URL
            Config.BASE_URL = "https://fctv33hd.best"
            results = scrape_matches()
            if results:
                storage.update(results)
            else:
                Config.BASE_URL = original_base
            
    except Exception as e:
        storage.add_log(f"💥 Error en run_scraper: {str(e)}")
        storage.set_error(str(e))
    finally:
        storage.is_scraping = False
        storage.add_log("🏁 Scraping finalizado")

# Inicializar FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.add_log("🚀 Servidor iniciando...")
    storage.add_log("⏳ Ejecutando scraping inicial...")
    
    # Ejecutar scraping en segundo plano
    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    
    yield
    
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
        return {"status": "already_scraping", "message": "Espera a que termine el scraping actual"}
    
    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    return {"status": "started", "message": "Scraping iniciado en segundo plano"}

@app.get("/logs")
async def get_logs():
    return {"logs": list(storage.debug_logs)}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "scraping_active": storage.is_scraping,
        "matches_stored": len(storage.get_all()),
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
