#!/usr/bin/env bash

echo "Instalando navegadores..."
playwright install --with-deps

echo "Iniciando API..."
uvicorn backend:app --host 0.0.0.0 --port $PORT
