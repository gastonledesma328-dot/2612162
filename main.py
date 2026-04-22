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
from urllib.parse import urljoin, urlparse

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    # URLs base que funcionan
    BASE_URLS = [
        "https://nia21bp.2wruedoublej4l6adjective.sbs",
        "https://may01bp.2f17ubowlsjn46easier.cfd"
    ]
    MAX_MATCHES = int(os.getenv("MAX_MATCHES", "30"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    # Headers mejorados para evitar bloqueo
    HEADERS = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    }

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
    """Scraping usando las URLs que funcionan"""
    results = []
    
    try:
        storage.add_log("🌐 Iniciando scraping con requests...")
        session = requests.Session()
        session.headers.update(Config.HEADERS)
        
        # Probar cada URL base
        for base_url in Config.BASE_URLS:
            storage.add_log(f"📡 Probando URL base: {base_url}")
            
            # Intentar obtener la página de fútbol
            football_url = f"{base_url}/es/football.html"
            
            try:
                response = session.get(football_url, timeout=Config.REQUEST_TIMEOUT)
                
                if response.status_code == 200:
                    storage.add_log(f"✅ Conexión exitosa con {base_url}")
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Buscar enlaces de partidos
                    match_links = []
                    
                    # Buscar enlaces que contengan /football/
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if '/football/' in href:
                            # Construir URL completa
                            if href.startswith('/'):
                                full_url = urljoin(base_url, href)
                            elif href.startswith('http'):
                                full_url = href
                            else:
                                full_url = f"{base_url}/{href}"
                            
                            if full_url not in match_links:
                                match_links.append(full_url)
                    
                    storage.add_log(f"📊 Encontrados {len(match_links)} enlaces de partidos")
                    
                    if match_links:
                        # Limitar cantidad
                        match_links = match_links[:Config.MAX_MATCHES]
                        
                        # Procesar cada partido
                        for idx, match_url in enumerate(match_links, 1):
                            storage.add_log(f"🔄 Procesando {idx}/{len(match_links)}")
                            
                            try:
                                match_response = session.get(match_url, timeout=Config.REQUEST_TIMEOUT)
                                if match_response.status_code == 200:
                                    match_soup = BeautifulSoup(match_response.text, 'html.parser')
                                    
                                    # Buscar iframe del reproductor
                                    player_url = None
                                    
                                    # Buscar en iframes
                                    for iframe in match_soup.find_all('iframe'):
                                        src = iframe.get('src', '')
                                        if src:
                                            if src.startswith('//'):
                                                src = 'https:' + src
                                            
                                            # Buscar player en la URL
                                            if any(keyword in src.lower() for keyword in ['player', 'embed', 'live', 'stream']):
                                                player_url = src
                                                break
                                    
                                    # Si no encontró en iframe, buscar en scripts
                                    if not player_url:
                                        scripts = match_soup.find_all('script')
                                        for script in scripts:
                                            if script.string:
                                                # Buscar patrones de URL de player
                                                patterns = [
                                                    r'(https?://[^\s"\']+player[^\s"\']+)',
                                                    r'(https?://[^\s"\']+embed[^\s"\']+)',
                                                    r'(https?://[^\s"\']+live[^\s"\']+)',
                                                    r'(https?://[^\s"\']+stream[^\s"\']+)'
                                                ]
                                                for pattern in patterns:
                                                    match = re.search(pattern, script.string)
                                                    if match:
                                                        player_url = match.group(1)
                                                        break
                                            if player_url:
                                                break
                                    
                                    if player_url:
                                        results.append({
                                            "match_url": match_url,
                                            "player_url": player_url,
                                            "scraped_at": datetime.now().isoformat(),
                                            "source_base": base_url
                                        })
                                        storage.add_log(f"  ✅ Player encontrado")
                                    else:
                                        storage.add_log(f"  ⚠️ Sin player")
                                else:
                                    storage.add_log(f"  ❌ HTTP {match_response.status_code}")
                                    
                            except Exception as e:
                                storage.add_log(f"  ❌ Error: {str(e)[:50]}")
                                continue
                        
                        if results:
                            break  # Salir si encontramos resultados
                    else:
                        storage.add_log(f"⚠️ No se encontraron enlaces en {base_url}")
                else:
                    storage.add_log(f"❌ {base_url} respondió con {response.status_code}")
                    
            except requests.RequestException as e:
                storage.add_log(f"❌ Error con {base_url}: {str(e)[:80]}")
                continue
        
        if results:
            storage.add_log(f"✨ Scraping completado: {len(results)} players encontrados")
        else:
            storage.add_log("⚠️ No se encontraron resultados en ninguna URL")
            
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
