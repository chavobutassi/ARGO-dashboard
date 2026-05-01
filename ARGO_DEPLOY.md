# ============================================================
# ARGO — Guía de Deploy Online (Gratis)
# ============================================================
#
# OPCIÓN A: Render.com (recomendado — más estable)
# OPCIÓN B: Streamlit Cloud (más simple, requiere adaptar app)
# OPCIÓN C: Railway.app (alternativa)
#
# Todos tienen tier gratuito suficiente para demos.
# ============================================================


# ── OPCIÓN A: RENDER.COM ────────────────────────────────────
#
# 1. Crear cuenta en render.com
# 2. New → Web Service → conectar tu repositorio GitHub
# 3. Configurar:
#    - Build Command:  pip install -r requirements.txt
#    - Start Command:  python dashboard/app.py
#    - Plan: Free
#
# render.yaml (poner en la raíz del repo):

services:
  - type: web
    name: argo-logistica
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn dashboard.app:server --bind 0.0.0.0:$PORT
    plan: free
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0
      - key: EMPRESA_DEFAULT
        value: transportadora


# ── OPCIÓN B: STREAMLIT CLOUD ───────────────────────────────
#
# 1. Crear cuenta en streamlit.io/cloud
# 2. Conectar repositorio GitHub
# 3. Apuntar al archivo streamlit_app.py (crearlo con el código abajo)
#
# Nota: requiere adaptar el dashboard de Dash a Streamlit
# Ver archivo: dashboard/streamlit_app.py


# ── ARCHIVOS NECESARIOS PARA DEPLOY ─────────────────────────

# requirements.txt (versiones fijas para reproducibilidad):
