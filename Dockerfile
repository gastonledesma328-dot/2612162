FROM python:3.11-slim

# Instalar dependencias del sistema para Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    libgbm1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libnss3 \
    libdrm2 \
    libxkbcommon0 \
    libglib2.0-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements primero (mejor caché)
COPY requirements.txt .

# Instalar dependencias Python con versiones específicas
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    playwright==1.40.0 \
    pydantic==2.5.0 \
    python-multipart==0.0.6

# Instalar Playwright browsers
RUN playwright install chromium && \
    playwright install-deps

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
