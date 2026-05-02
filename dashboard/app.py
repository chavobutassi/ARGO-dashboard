"""
Argo — Dashboard Visual (Fase 3)
=================================
Paneles incorporados:
  1. KPIs con sparkline de tendencia histórica
  2. Bullet chart vs objetivo  (reemplaza gauge)
  3. Semáforo por categoría de riesgo  (nuevo)
  4. Panel leading vs lagging            (nuevo)
  5. Pareto de impacto acumulado         (nuevo)
  6. Escenarios Monte Carlo              (nuevo)
  7. Matriz probabilidad × impacto       (existente)
  8. SITREP ejecutivo                    (existente)

Corre con:  python dashboard/app.py
Abre:       http://localhost:8050
"""
import os
import json
import sys
from pathlib import Path
from datetime import datetime

import plotly.graph_objects as go
import pandas as pd

import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc

# ── Resolución de rutas robusta ─────────────────────────────
# Soporta: python dashboard/app.py  |  python app.py  |  módulo anidado
_here = Path(__file__).resolve().parent
_ROOT = _here  # se actualiza al encontrar core/
for _candidate in [_here.parent, _here, _here.parent.parent]:
    if (_candidate / "core").is_dir():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        _ROOT = _candidate   # raíz real del proyecto
        break

def _cfg(relpath: str) -> str:
    """Convierte un path relativo de config en absoluto desde la raíz del proyecto."""
    return str(_ROOT / relpath)

try:
    from core.engine import ArgoEngine
    from core.risk_scorer import LecturaIndicador, NivelRiesgo
except ImportError as e:
    raise ImportError(
        f"\n\nArgo no puede importar el motor central: {e}\n"
        f"Corré desde la raíz del proyecto:  python dashboard/app.py\n"
        f"y verificá que exista  core/engine.py  y  core/risk_scorer.py\n"
    ) from e

try:
    from core.simulador import SimuladorMonteCarlo
    MONTECARLO_DISPONIBLE = True
except ImportError:
    MONTECARLO_DISPONIBLE = False
    print("[Argo] Aviso: simulador.py no encontrado — panel Monte Carlo desactivado.")

try:
    from data.connectors import ConectorDatos
    CONECTORES_DISPONIBLE = True
except (ImportError, SyntaxError) as _e:
    CONECTORES_DISPONIBLE = False
    if isinstance(_e, SyntaxError):
        print("[Argo] Aviso: data/connectors.py tiene un problema de encoding.")
        print("       Reemplazalo con el archivo limpio generado por Argo.")
    else:
        print("[Argo] Aviso: connectors.py no encontrado en data/ — usando lecturas_default.")

try:
    from data.connectors_agro import ConectorAgro, ZONAS_AGRO
    _conector_agro: "ConectorAgro | None" = ConectorAgro()
    AGRO_DISPONIBLE = True
except (ImportError, Exception) as _e:
    AGRO_DISPONIBLE = False
    _conector_agro = None
    print(f"[Argo] Aviso: connectors_agro.py no disponible — panel agro desactivado. ({_e})")


# ── Paleta Argo ────────────────────────────────────────────
COLORES = {
    "CRITICO":       "#E24B4A",
    "ALTO":          "#D85A30",
    "MEDIO":         "#BA7517",
    "BAJO":          "#639922",
    "fondo":         "transparent",
    "fondo_critico": "rgba(226, 75, 74, 0.15)",
    "fondo_alto":    "rgba(216, 90, 48, 0.15)",
    "fondo_medio":   "rgba(186, 117, 23, 0.15)",
    "fondo_bajo":    "rgba(99, 153, 34, 0.15)",
    "card":          "rgba(255, 255, 255, 0.05)",
    "borde":         "rgba(55, 138, 221, 0.25)",
    "texto":         "#E8E6E0",
    "texto2":        "#8A8880",
    "azul":          "#378ADD",
}

import logging
log = logging.getLogger("Argo.dashboard")

NIVEL_ORDEN = {"CRITICO": 4, "ALTO": 3, "MEDIO": 2, "BAJO": 1}

# Coordenadas geográficas de cada empresa y su provincia
EMPRESA_COORDS = {
    "Transportadora del Sur S.A.":       (-38.72, -62.27, "Buenos Aires"),
    "Cooperativa Agropecuaria Pampa Sur": (-32.95, -60.64, "Santa Fe"),
    "YPF Vaca Muerta":                   (-38.95, -68.06, "Neuquén"),
    "Andreani Logística S.A.":           (-34.62, -58.38, "Buenos Aires"),
    "ACA Agropecuaria Coop. Ltda.":      (-32.95, -60.64, "Santa Fe"),
    "Pan American Energy S.A.":          (-38.65, -69.20, "Neuquén"),
    "Livent Argentina S.A. (Fenix)":     (-23.63, -67.49, "Jujuy"),
    "Coto CICSA":                        (-34.55, -58.45, "Buenos Aires"),
    "Swiss Medical S.A.":                (-34.60, -58.50, "Buenos Aires"),
}

# Riesgo base por provincia (agregado de todas las empresas conocidas)
PROV_RIESGO_BASE = {
    "Buenos Aires": ("MEDIO", 41),
    "Ciudad Autónoma de Buenos Aires": ("MEDIO", 41),
    "Santa Fe":     ("MEDIO", 58),
    "Neuquén":      ("ALTO",  61),
    "Jujuy":        ("ALTO",  65),
}

# Cache del GeoJSON de provincias (se carga una vez al inicio)
_GEOJSON_CACHE: dict = {}

def _cargar_geojson_provincias() -> dict:
    global _GEOJSON_CACHE
    if _GEOJSON_CACHE:
        return _GEOJSON_CACHE
    try:
        import requests as _req
        r = _req.get(
            "https://apis.datos.gob.ar/georef/api/provincias?formato=geojson&max=30",
            timeout=8
        )
        _GEOJSON_CACHE = r.json()
        log.info(f"GeoJSON provincias cargado: {len(_GEOJSON_CACHE.get('features', []))} provincias")
    except Exception as e:
        log.warning(f"GeoJSON provincias no disponible ({e}) — mapa en modo scatter")
        _GEOJSON_CACHE = {}
    return _GEOJSON_CACHE

# Instancia global del conector (con cache de 30 min)
_conector: "ConectorDatos | None" = ConectorDatos() if CONECTORES_DISPONIBLE else None


def _merge_lecturas(
    lecturas_reales: list,
    defaults: dict,
) -> tuple[list, dict]:
    """
    Combina datos reales de APIs con valores internos/manuales.
    Los datos reales tienen prioridad donde están disponibles.
    Retorna (lista_lecturas, fuentes) donde fuentes={nombre: "real"|"default"}.
    """
    mapa = {l.nombre: l for l in lecturas_reales}
    fuentes: dict[str, str] = {l.nombre: "real" for l in lecturas_reales}

    for nombre, valor in defaults.items():
        if nombre not in mapa:
            mapa[nombre] = LecturaIndicador(nombre, float(valor), fuente="default")
            fuentes[nombre] = "default"

    return list(mapa.values()), fuentes


# ── Helpers de estilo ───────────────────────────────────────
def _card(extra: dict | None = None) -> dict:
    base = {
        "backgroundColor": COLORES["card"],
        "border": f"0.5px solid {COLORES['borde']}",
        "borderRadius": "12px",
        "padding": "16px 18px",
    }
    if extra:
        base.update(extra)
    return base

def _lbl(texto: str) -> html.Div:
    return html.Div(texto, style={
        "fontSize": "11px", "color": COLORES["texto2"], "fontWeight": "500",
        "textTransform": "uppercase", "letterSpacing": "0.05em", "marginBottom": "10px",
    })


# ── Empresas + config pre-cargado ───────────────────────────
EMPRESAS: dict = {
    # ── Logística ───────────────────────────────────────
    "transportadora": {
        "label": "Transportadora del Sur S.A.",
        "config": _cfg("config/transportadora_ejemplo.json"),
        "color": "#378ADD",
        "lat": -38.72, "lon": -62.27, "lugar": "Bahía Blanca",
        "lecturas_default": {
            "precipitacion_mm": 65.0,
            "viento_kmh": 55.0,
            "temperatura_c": 18.0,
            "precio_gasoil_ars": 1350.0,
            "vehiculos_en_taller": 3.0,
            "conductores_disponibles": 11.0,
            "conductores_sin_reemplazo": 1.0,
        },
    },
    "agro": {
        "label": "Cooperativa Agropecuaria Pampa Sur",
        "config": _cfg("config/agro_ejemplo.json"),
        "color": "#639922",
        "lat": -37.32, "lon": -63.24, "lugar": "Santa Rosa, La Pampa",
        "lecturas_default": {
            "precipitacion_acumulada_mm": 12.0,
            "indice_sequia_palmer": -2.4,
            "temperatura_minima_c": 1.5,
            "precio_soja_usd_tn": 305.0,
            "precio_maiz_usd_tn": 178.0,
            "camiones_disponibles": 4.0,
            "capacidad_silo_libre_tn": 1200.0,
        },
    },
    "ypf": {
        "label": "YPF Vaca Muerta",
        "config": _cfg("config/ypf_vaca_muerta.json"),
        "color": "#E24B4A",
        "lat": -38.95, "lon": -68.07, "lugar": "Neuquén, Vaca Muerta",
        "lecturas_default": {
            "equipos_produccion_fuera_servicio": 1.0,
            "petroleo_wti_usd": 72.0,
            "viento_kmh": 45.0,
            "temperatura_c": 12.0,
            "ausentismo_pct": 8.0,
        },
    },
    # ── Energía ─────────────────────────────────────────
    "pan_american": {
        "label": "Pan American Energy S.A.",
        "config": _cfg("config/pan_american.json"),
        "color": "#D85A30",
        "lat": -38.9516, "lon": -68.0591, "lugar": "Neuquén, Vaca Muerta",
        "lecturas_default": {
            "equipos_produccion_fuera_servicio": 2.0,
            "petroleo_wti_usd": 74.5,
            "viento_kmh": 38.0,
            "temperatura_c": 8.0,
            "ausentismo_pct": 7.0,
            "horas_paro_acumuladas": 0.0,
        },
    },
    # ── Logística ───────────────────────────────────────
    "andreani": {
        "label": "Andreani Logística S.A.",
        "config": _cfg("config/andreani.json"),
        "color": "#378ADD",
        "lat": -34.6037, "lon": -58.3816, "lugar": "Buenos Aires (GBA)",
        "lecturas_default": {
            "precipitacion_mm": 8.0, "viento_kmh": 22.0, "temperatura_c": 17.0,
            "precio_gasoil_ars": 1420.0, "vehiculos_en_taller": 6.0,
            "conductores_disponibles": 108.0, "conductores_sin_reemplazo": 3.0,
        },
    },
    # ── Agro ────────────────────────────────────────────
    "aca_agro": {
        "label": "ACA Agropecuaria Coop. Ltda.",
        "config": _cfg("config/aca_agro.json"),
        "color": "#639922",
        "lat": -32.9468, "lon": -60.6393, "lugar": "Rosario, Santa Fe",
        "lecturas_default": {
            "precipitacion_acumulada_mm": 38.0, "indice_sequia_palmer": -0.8,
            "temperatura_minima_c": 9.0, "precio_soja_usd_tn": 318.0,
            "precio_maiz_usd_tn": 182.0, "camiones_disponibles": 14.0,
            "capacidad_silo_libre_tn": 4200.0,
        },
    },
    # ── Minería ─────────────────────────────────────────
    "livent": {
        "label": "Livent Argentina S.A. (Fenix)",
        "config": _cfg("config/livent.json"),
        "color": "#534AB7",
        "lat": -23.6345, "lon": -67.4891, "lugar": "Puna Atacameña, Jujuy",
        "lecturas_default": {
            "equipos_fuera_servicio": 1.0, "viento_kmh": 52.0, "temperatura_c": -3.0,
            "incidentes_mes": 0.0, "dias_sin_accidentes": 142.0,
            "tasa_rotacion_mensual_pct": 3.2, "precio_litio_usd_tn": 11500.0,
        },
    },
    # ── Retail ──────────────────────────────────────────
    "coto": {
        "label": "Coto CICSA",
        "config": _cfg("config/coto.json"),
        "color": "#1D9E75",
        "lat": -34.6037, "lon": -58.3816, "lugar": "Buenos Aires (GBA)",
        "lecturas_default": {
            "skus_en_quiebre_pct": 4.5, "proveedores_con_demora": 2.0,
            "variacion_demanda_pct": 8.0, "sucursales_sin_sistema": 0.0,
            "tipo_cambio": 1085.0,
        },
    },
    # ── Salud ───────────────────────────────────────────
    "swiss_medical": {
        "label": "Swiss Medical S.A.",
        "config": _cfg("config/swiss_medical.json"),
        "color": "#D4537E",
        "lat": -34.5875, "lon": -58.3974, "lugar": "Buenos Aires (CABA)",
        "lecturas_default": {
            "insumos_bajo_stock_critico": 1.0, "ocupacion_uci_pct": 68.0,
            "espera_guardia_min": 28.0, "medicos_faltantes_guardia": 0.0,
            "ausentismo_enfermeria_pct": 8.5, "sistemas_criticos_caidos": 0.0,
            "pacientes_febriles_guardia": 12.0,
        },
    },
}

# ── Solo empresas agro en el selector ───────────────────────
EMPRESAS_AGRO_IDS = {"agro", "aca_agro"}

# Pre-cargar configs para acceso rápido en callbacks
for _key, _emp in EMPRESAS.items():
    try:
        with open(_emp["config"], encoding="utf-8") as _f:
            _emp["config_data"] = json.load(_f)
    except Exception:
        _emp["config_data"] = {}

# ── Zonas agrícolas de Argentina para el mapa ────────────────
ZONAS_AGRO_MAPA = [
    {"nombre": "Pampa Húmeda Norte",  "lat": -33.0, "lon": -61.0,
     "cultivo": "Soja",  "aptitud": "Alta",  "flete_ars_tn": 14000, "color": "#639922", "size": 22},
    {"nombre": "Pampa Húmeda Centro", "lat": -35.0, "lon": -62.0,
     "cultivo": "Soja/Maíz", "aptitud": "Alta", "flete_ars_tn": 16000, "color": "#639922", "size": 22},
    {"nombre": "Santa Fe Centro",     "lat": -31.5, "lon": -61.5,
     "cultivo": "Soja",  "aptitud": "Alta",  "flete_ars_tn": 12000, "color": "#639922", "size": 20},
    {"nombre": "Entre Ríos",          "lat": -32.0, "lon": -58.5,
     "cultivo": "Soja/Trigo", "aptitud": "Alta", "flete_ars_tn": 18000, "color": "#639922", "size": 18},
    {"nombre": "Córdoba Sur",         "lat": -33.5, "lon": -63.5,
     "cultivo": "Soja",  "aptitud": "Alta",  "flete_ars_tn": 20000, "color": "#639922", "size": 20},
    {"nombre": "Córdoba Norte",       "lat": -30.5, "lon": -63.5,
     "cultivo": "Maíz",  "aptitud": "Media", "flete_ars_tn": 24000, "color": "#BA7517", "size": 16},
    {"nombre": "Buenos Aires Norte",  "lat": -35.0, "lon": -60.0,
     "cultivo": "Trigo/Soja", "aptitud": "Alta", "flete_ars_tn": 15000, "color": "#639922", "size": 18},
    {"nombre": "Buenos Aires Sur",    "lat": -38.0, "lon": -60.5,
     "cultivo": "Trigo/Girasol", "aptitud": "Media", "flete_ars_tn": 22000, "color": "#BA7517", "size": 16},
    {"nombre": "La Pampa Este",       "lat": -36.5, "lon": -64.5,
     "cultivo": "Trigo",  "aptitud": "Media", "flete_ars_tn": 26000, "color": "#BA7517", "size": 14},
    {"nombre": "La Pampa Oeste",      "lat": -37.5, "lon": -67.0,
     "cultivo": "Ganadería", "aptitud": "Baja", "flete_ars_tn": 32000, "color": "#D85A30", "size": 12},
    {"nombre": "Chaco",               "lat": -27.0, "lon": -61.0,
     "cultivo": "Soja",  "aptitud": "Media", "flete_ars_tn": 34000, "color": "#BA7517", "size": 14},
    {"nombre": "Santiago del Estero", "lat": -28.0, "lon": -63.5,
     "cultivo": "Soja",  "aptitud": "Media", "flete_ars_tn": 30000, "color": "#BA7517", "size": 14},
    {"nombre": "Tucumán",             "lat": -27.0, "lon": -65.5,
     "cultivo": "Soja/Caña", "aptitud": "Media", "flete_ars_tn": 32000, "color": "#BA7517", "size": 13},
    {"nombre": "Puerto Rosario ⚓",   "lat": -32.95, "lon": -60.64,
     "cultivo": "Destino exportación", "aptitud": "—", "flete_ars_tn": 0,
     "color": "#378ADD", "size": 18},
]


# ── Métricas bullet por sector ──────────────────────────────
def _metricas_bullet(empresa_id: str, lecturas_dict: dict) -> list[dict]:
    """
    Retorna [{nombre, valor, objetivo}] según el sector.
    valor y objetivo en escala 0-100.
    """
    cfg = EMPRESAS[empresa_id].get("config_data", {})
    sector = cfg.get("empresa", {}).get("sector", "")
    cap = cfg.get("unidad_operacional", {})
    obj = cap.get("umbral_critico", 0.85) * 100   # ej: 0.85 → 85

    if sector == "logistica":
        cap_total = cap.get("capacidad_total", 14)
        en_taller = lecturas_dict.get("vehiculos_en_taller", 0)
        conductores = lecturas_dict.get("conductores_disponibles", cap_total)
        sin_reemplazo = lecturas_dict.get("conductores_sin_reemplazo", 0)
        flota = ((cap_total - en_taller) / max(cap_total, 1)) * 100
        cond_pct = (conductores / max(cap_total, 1)) * 100
        cobertura = max(0, (1 - sin_reemplazo / max(conductores, 1))) * 100
        return [
            {"nombre": "Flota operativa",         "valor": round(flota, 1),    "objetivo": obj},
            {"nombre": "Conductores disponibles",  "valor": round(cond_pct, 1), "objetivo": obj},
            {"nombre": "Cobertura de reemplazos",  "valor": round(cobertura, 1),"objetivo": obj},
        ]

    elif sector == "agro":
        camiones = lecturas_dict.get("camiones_disponibles", 4)
        silo = lecturas_dict.get("capacidad_silo_libre_tn", 0)
        precip = lecturas_dict.get("precipitacion_acumulada_mm", 10)
        log_pct = min(100, (camiones / 8) * 100)
        silo_pct = min(100, (silo / 2000) * 100)
        hidrico = min(100, (precip / 30) * 100)
        return [
            {"nombre": "Logística de cosecha",    "valor": round(log_pct, 1),  "objetivo": obj},
            {"nombre": "Capacidad silo libre",     "valor": round(silo_pct, 1), "objetivo": 80.0},
            {"nombre": "Índice hídrico mensual",   "valor": round(hidrico, 1),  "objetivo": obj},
        ]

    elif sector == "energia":
        cap_total = cap.get("capacidad_total", 48)
        fuera = lecturas_dict.get("equipos_produccion_fuera_servicio", 0)
        ausentismo = lecturas_dict.get("ausentismo_pct", 5)
        prod = ((cap_total - fuera) / max(cap_total, 1)) * 100
        personal = max(0, 100 - ausentismo * 5)
        return [
            {"nombre": "Producción diaria",       "valor": round(prod, 1),    "objetivo": obj},
            {"nombre": "Disponibilidad equipos",  "valor": round(prod, 1),    "objetivo": obj},
            {"nombre": "Presencia de personal",   "valor": round(personal, 1),"objetivo": obj},
        ]

    return []


# ── Leading / Lagging desde sitrep + config ─────────────────
def _leading_lagging(sitrep_data: dict, empresa_id: str) -> tuple[list, list]:
    """
    Leading: indicadores monitoreados que NO dispararon alerta.
    Lagging: indicadores que ya cruzaron su umbral.
    """
    cfg = EMPRESAS[empresa_id].get("config_data", {})
    riesgos_cfg = cfg.get("riesgos", [])

    # Índice de indicadores disparados desde el sitrep
    disparados: set[str] = set()
    lagging: list[dict] = []

    for r in sitrep_data.get("riesgos", []):
        for ind_str in r.get("indicadores", []):
            nombre_ind = ind_str.split("=")[0]
            estado = "CRÍTICO" if "[CRÍTICO]" in ind_str else "ALERTA"
            if nombre_ind not in disparados:
                disparados.add(nombre_ind)
                lagging.append({
                    "nombre": nombre_ind.replace("_", " ").capitalize(),
                    "estado": estado,
                    "riesgo": r["nombre"],
                    "color": COLORES["CRITICO"] if estado == "CRÍTICO" else COLORES["ALTO"],
                })

    # Indicadores monitoreados que no dispararon → leading
    monitoreados: set[str] = set()
    leading: list[dict] = []

    for r_cfg in riesgos_cfg:
        for ind_nombre in r_cfg.get("indicadores", []):
            if ind_nombre not in disparados and ind_nombre not in monitoreados:
                monitoreados.add(ind_nombre)
                leading.append({
                    "nombre": ind_nombre.replace("_", " ").capitalize(),
                    "estado": "OK",
                    "riesgo": r_cfg["nombre"],
                    "color": COLORES["BAJO"],
                })

    return leading, lagging


# ── Figura: Bullet chart ────────────────────────────────────
def _fig_bullet(metricas: list[dict]) -> go.Figure:
    if not metricas:
        return go.Figure()

    fig = go.Figure()
    nombres = [m["nombre"] for m in metricas]
    n = len(metricas)

    for i, m in enumerate(metricas):
        v   = m["valor"]
        obj = m["objetivo"]
        zona_media = obj * 0.75   # límite zona roja / amarilla

        # Zonas de fondo
        for x0, x1, color in [
            (0,          zona_media, COLORES["fondo_critico"]),
            (zona_media, obj,        COLORES["fondo_medio"]),
            (obj,        100,        COLORES["fondo_bajo"]),
        ]:
            fig.add_shape(type="rect",
                          x0=x0, x1=x1, y0=i - 0.35, y1=i + 0.35,
                          fillcolor=color, line_width=0, layer="below")

        # Color de la barra según posición vs objetivo
        if v >= obj:
            c_barra = COLORES["BAJO"]
        elif v >= zona_media:
            c_barra = COLORES["MEDIO"]
        else:
            c_barra = COLORES["ALTO"]

        fig.add_trace(go.Bar(
            x=[v], y=[m["nombre"]],
            orientation="h",
            marker_color=c_barra,
            marker_line_width=0,
            width=0.45,
            showlegend=False,
            hovertemplate=(
                f"<b>{m['nombre']}</b><br>"
                f"Actual: {v:.1f}%<br>"
                f"Objetivo: {obj:.1f}%<extra></extra>"
            ),
        ))

        # Línea de objetivo
        fig.add_shape(type="line",
                      x0=obj, x1=obj, y0=i - 0.48, y1=i + 0.48,
                      line=dict(color=COLORES["texto"], width=2))

        # Etiqueta de valor
        fig.add_annotation(
            x=v + 1.5, y=m["nombre"],
            text=f"<b>{v:.0f}%</b>",
            showarrow=False,
            font=dict(size=11, color=c_barra),
            xanchor="left",
        )

    fig.update_layout(
        margin=dict(l=180, r=60, t=4, b=4),
        height=max(120, n * 80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        barmode="relative",
        xaxis=dict(range=[0, 110], showgrid=True, gridcolor=COLORES["borde"],
                   gridwidth=0.5, ticksuffix="%", tickfont={"size": 10},
                   showline=False),
        yaxis=dict(showgrid=False, tickfont={"size": 12},
                   categoryorder="array", categoryarray=nombres),
        font={"family": "system-ui"},
    )
    return fig


# ── Figura: Sparkline ───────────────────────────────────────
def _fig_spark(scores: list, color: str) -> go.Figure:
    fig = go.Figure()
    if len(scores) < 2:
        return fig
    xs = list(range(len(scores)))
    fig.add_trace(go.Scatter(
        x=xs, y=[s * 100 for s in scores],
        mode="lines",
        line=dict(color=color, width=1.8, shape="spline"),
        showlegend=False,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=[xs[-1]], y=[scores[-1] * 100],
        mode="markers",
        marker=dict(color=color, size=5),
        showlegend=False,
        hoverinfo="skip",
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=36,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, range=[0, 100]),
    )
    return fig


# ── App ─────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    assets_folder=str(Path(__file__).parent / "assets"),
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    title="Argo Estrategias Analiticas — Inteligencia Operacional",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1.0"}],
)
server = app.server

# ── Layout ──────────────────────────────────────────────────
app.layout = html.Div(
    style={"backgroundColor": COLORES["fondo"], "minHeight": "100vh",
           "fontFamily": "system-ui, sans-serif"},
    children=[

        # ── Header ──────────────────────────────────────────
        html.Div(
            style={
                "backgroundColor": COLORES["card"],
                "borderBottom": f"1px solid {COLORES['borde']}",
                "padding": "14px 28px",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "space-between",
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "14px"},
                    children=[
                        html.Img(
                            src="/assets/ARGO_img.png",
                            style={
                                "height": "42px",
                                "width": "auto",
                                "objectFit": "contain",
                            },
                        ),
                        html.Div(
                            style={
                                "borderLeft": f"1px solid {COLORES['borde']}",
                                "paddingLeft": "14px",
                                "display": "flex",
                                "flexDirection": "column",
                                "justifyContent": "center",
                            },
                            children=[
                                html.Div("Inteligencia Operacional", style={
                                    "fontSize": "12px", "fontWeight": "500",
                                    "color": COLORES["texto"],
                                    "letterSpacing": "0.02em",
                                }),
                                html.Div("motor de análisis operacional", style={
                                    "fontSize": "10px",
                                    "color": COLORES["texto2"],
                                }),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "10px"},
                    children=[
                        dcc.Dropdown(
                            id="empresa-selector",
                            options=[{"label": v["label"], "value": k}
                                     for k, v in EMPRESAS.items()
                                     if k in EMPRESAS_AGRO_IDS],
                            value="agro",
                            clearable=False,
                            style={"width": "300px", "fontSize": "13px"},
                        ),
                        html.Button(
                            "Analizar",
                            id="btn-analizar",
                            style={
                                "backgroundColor": COLORES["azul"],
                                "color": "#fff",
                                "border": "none",
                                "borderRadius": "8px",
                                "padding": "8px 18px",
                                "fontSize": "13px",
                                "cursor": "pointer",
                                "fontWeight": "500",
                            },
                        ),
                        html.Div(id="datasource-badge"),
                    ],
                ),
            ],
        ),

        # ── Contenido principal ──────────────────────────────
        html.Div(style={"padding": "20px 28px"}, children=[

            # ═══════════════════════════════════════════════════
            # ZONA 1 — OPERADOR   ¿Hay algo urgente ahora?
            # ═══════════════════════════════════════════════════
            html.Div(
                style={
                    "display": "flex", "alignItems": "center",
                    "gap": "10px", "marginBottom": "10px",
                },
                children=[
                    html.Div(style={
                        "width": "4px", "height": "18px",
                        "backgroundColor": COLORES["ALTO"], "borderRadius": "2px",
                    }),
                    html.Div("Zona 1 — Operador", style={
                        "fontSize": "11px", "fontWeight": "500",
                        "color": COLORES["texto2"], "textTransform": "uppercase",
                        "letterSpacing": "0.08em",
                    }),
                    html.Div("¿hay algo que requiera atención ahora?", style={
                        "fontSize": "11px", "color": COLORES["texto2"],
                    }),
                ],
            ),
            html.Div(
                className="Argo-zona1",
                style={"marginBottom": "28px"},
                children=[
                    html.Div(id="panel-score",   style=_card()),
                    html.Div(id="panel-alertas", style=_card()),
                    html.Div(id="panel-mapa",
                             style=_card({"padding": "8px 10px"})),
                    html.Div(id="panel-semaforo", style=_card()),
                ],
            ),

            # ═══════════════════════════════════════════════════
            # ZONA 2 — GERENCIA   ¿Dónde está el problema?
            # ═══════════════════════════════════════════════════
            html.Div(
                style={
                    "display": "flex", "alignItems": "center",
                    "gap": "10px", "marginBottom": "10px",
                },
                children=[
                    html.Div(style={
                        "width": "4px", "height": "18px",
                        "backgroundColor": COLORES["azul"], "borderRadius": "2px",
                    }),
                    html.Div("Zona 2 — Gerencia", style={
                        "fontSize": "11px", "fontWeight": "500",
                        "color": COLORES["texto2"], "textTransform": "uppercase",
                        "letterSpacing": "0.08em",
                    }),
                    html.Div("¿dónde está el problema y qué hago?", style={
                        "fontSize": "11px", "color": COLORES["texto2"],
                    }),
                ],
            ),
            html.Div(id="panel-situacion",
                     style=_card({"marginBottom": "14px"})),
            html.Div(id="kpi-row", className="Argo-kpi-row",
                     style={"marginBottom": "14px"}),
            html.Div(
                className="Argo-zona2-paneles",
                style={"marginBottom": "28px"},
                children=[
                    html.Div(id="panel-pareto",          style=_card()),
                    html.Div(id="panel-leading-lagging", style=_card()),
                    html.Div(id="panel-bullet",          style=_card()),
                ],
            ),

            # ═══════════════════════════════════════════════════
            # ZONA AGRO — Decisión de venta agropecuaria
            # Solo visible para empresas del sector agro
            # ═══════════════════════════════════════════════════
            html.Div(
                id="zona-agro-wrapper",
                style={"marginBottom": "14px"},
                children=[
                    html.Div(
                        style={
                            "display": "flex", "alignItems": "center",
                            "gap": "12px", "marginBottom": "12px",
                        },
                        children=[
                            html.Div(style={
                                "width": "4px", "height": "18px",
                                "backgroundColor": COLORES["BAJO"], "borderRadius": "2px",
                            }),
                            html.Div("Zona Agro — Decisión de venta", style={
                                "fontSize": "11px", "fontWeight": "500",
                                "color": COLORES["texto2"], "textTransform": "uppercase",
                                "letterSpacing": "0.08em",
                            }),
                        ],
                    ),
                    html.Div(id="panel-agro-decision", style=_card()),
                ],
            ),

            # ═══════════════════════════════════════════════════
            # ZONA 3 — ANÁLISIS   Escenarios y detalle
            # ═══════════════════════════════════════════════════
            html.Div(
                style={"display": "flex", "alignItems": "center",
                       "gap": "12px", "marginBottom": "12px"},
                children=[
                    html.Div(style={
                        "width": "4px", "height": "18px",
                        "backgroundColor": COLORES["borde"], "borderRadius": "2px",
                    }),
                    html.Div("Zona 3 — Análisis profundo", style={
                        "fontSize": "11px", "fontWeight": "500",
                        "color": COLORES["texto2"], "textTransform": "uppercase",
                        "letterSpacing": "0.08em",
                    }),
                    html.Button(
                        "▼  Ver análisis completo",
                        id="btn-zona3",
                        style={
                            "fontSize": "11px", "color": COLORES["texto2"],
                            "backgroundColor": "transparent",
                            "border": f"0.5px solid {COLORES['borde']}",
                            "borderRadius": "6px", "padding": "4px 12px",
                            "cursor": "pointer",
                        },
                    ),
                ],
            ),
            html.Div(id="zona3-contenido", style={"display": "none"}, children=[
                html.Div(
                    className="Argo-zona3-top",
                    style={"marginBottom": "14px"},
                    children=[
                        html.Div(id="panel-ranking",    style=_card()),
                        html.Div(id="panel-montecarlo", style=_card()),
                    ],
                ),
                html.Div(
                    className="Argo-zona3-bottom",
                    style={"marginBottom": "14px"},
                    children=[
                        html.Div(id="panel-matriz", style=_card()),
                        html.Div(id="panel-sitrep", style=_card()),
                    ],
                ),
            ]),
        ]),

        # Stores
        dcc.Store(id="store-sitrep"),
        dcc.Store(id="store-montecarlo"),
        dcc.Store(id="store-history"),
        dcc.Store(id="store-datasource"),
        dcc.Interval(id="auto-refresh", interval=300_000, n_intervals=0),
    ],
)


# ════════════════════════════════════════════════════════════
# CALLBACKS
# ════════════════════════════════════════════════════════════

# ── 1. Análisis principal ────────────────────────────────────
@app.callback(
    Output("store-sitrep",      "data"),
    Output("store-montecarlo",  "data"),
    Output("store-history",     "data"),
    Output("store-datasource",  "data"),
    Input("btn-analizar",  "n_clicks"),
    Input("auto-refresh",  "n_intervals"),
    State("empresa-selector", "value"),
    State("store-history",    "data"),
    prevent_initial_call=False,
)
def correr_analisis(n_clicks, n_intervals, empresa_id, history_data):
    emp = EMPRESAS[empresa_id]

    # ── Datos: intenta APIs públicas, completa con defaults internos
    fuentes: dict = {}
    if CONECTORES_DISPONIBLE and _conector:
        try:
            snap = _conector.snapshot_completo(
                lat=emp.get("lat", -34.6037),
                lon=emp.get("lon", -58.3816),
                lugar=emp.get("lugar", "Argentina"),
            )
            lecturas_reales = _conector.snapshot_a_lecturas(snap)
            lecturas, fuentes = _merge_lecturas(lecturas_reales, emp["lecturas_default"])
            log.info(f"Datos reales: {sum(1 for v in fuentes.values() if v=='real')} "
                     f"/ {len(fuentes)} indicadores desde APIs")
        except Exception as e:
            log.warning(f"Fallo al obtener datos reales ({e}) — usando defaults")
            lecturas = [LecturaIndicador(k, v)
                        for k, v in emp["lecturas_default"].items()]
            fuentes = {k: "default" for k in emp["lecturas_default"]}
    else:
        lecturas = [LecturaIndicador(k, v)
                    for k, v in emp["lecturas_default"].items()]
        fuentes = {k: "default" for k in emp["lecturas_default"]}

    # ── Engine
    engine = ArgoEngine(emp["config"])
    sitrep = engine.analizar(lecturas, capacidad_mitigacion=0.55)
    sitrep_dict = sitrep.to_dict()
    sitrep_dict["fuentes"] = fuentes   # guardamos origen de cada indicador

    # ── Monte Carlo (3 000 sim para velocidad en dashboard)
    mc_dict: dict = {}
    if MONTECARLO_DISPONIBLE:
        try:
            sim = SimuladorMonteCarlo(emp["config"])
            resultado_mc = sim.simular(lecturas, n_simulaciones=3_000)
            mc_dict = resultado_mc.to_dict()
        except Exception as e:
            mc_dict = {"error": str(e)}

    # ── Historial (por empresa, últimos 12 puntos)
    if history_data is None:
        history_data = {}

    hist = history_data.get(empresa_id, {
        "scores": [], "n_criticos": [], "n_altos": [], "n_alertas": [],
    })
    hist["scores"].append(sitrep_dict["score_global"])
    hist["n_criticos"].append(sum(1 for r in sitrep_dict["riesgos"]
                                  if r["nivel"] == "CRITICO"))
    hist["n_altos"].append(sum(1 for r in sitrep_dict["riesgos"]
                               if r["nivel"] == "ALTO"))
    hist["n_alertas"].append(len(sitrep_dict.get("alertas_activas", [])))
    for k in hist:
        hist[k] = hist[k][-12:]

    history_data[empresa_id] = hist
    # ── Resumen de fuentes para el badge
    n_real    = sum(1 for v in fuentes.values() if v == "real")
    n_total   = len(fuentes)
    datasource = {
        "n_real":   n_real,
        "n_total":  n_total,
        "fuentes":  fuentes,
        "timestamp": sitrep_dict["timestamp"],
        "conectores": CONECTORES_DISPONIBLE,
    }

    return sitrep_dict, mc_dict, history_data, datasource


# ── 2. KPI row con sparklines ────────────────────────────────
@app.callback(
    Output("kpi-row", "children"),
    Input("store-sitrep", "data"),
    Input("store-history", "data"),
    State("empresa-selector", "value"),
)
def actualizar_kpis(data, history_data, empresa_id):
    if not data:
        return []

    riesgos  = data["riesgos"]
    n_crit   = sum(1 for r in riesgos if r["nivel"] == "CRITICO")
    n_alto   = sum(1 for r in riesgos if r["nivel"] == "ALTO")
    score    = data["score_global"]
    n_alert  = len(data.get("alertas_activas", []))

    hist = (history_data or {}).get(empresa_id, {})

    def _tendencia(serie: list) -> str:
        if len(serie) < 2:
            return ""
        delta = serie[-1] - serie[-2]
        if abs(delta) < 0.005:
            return "sin cambio"
        arrow = "↑" if delta > 0 else "↓"
        return f"{arrow} {abs(delta)*100:.0f} pts vs anterior"

    def kpi_card(titulo, valor_str, color, subtitulo, spark_data, spark_color):
        spark = []
        if spark_data and len(spark_data) >= 2:
            fig = _fig_spark(spark_data, spark_color)
            spark = [dcc.Graph(figure=fig, config={"displayModeBar": False},
                               style={"height": "36px", "marginTop": "6px"})]
        return html.Div(style=_card({"padding": "14px 18px"}), children=[
            html.Div(titulo, style={
                "fontSize": "11px", "color": COLORES["texto2"],
                "fontWeight": "500", "textTransform": "uppercase",
                "letterSpacing": "0.05em", "marginBottom": "6px",
            }),
            html.Div(valor_str, style={
                "fontSize": "28px", "fontWeight": "600",
                "color": color, "lineHeight": "1",
            }),
            html.Div(subtitulo, style={
                "fontSize": "11px", "color": COLORES["texto2"], "marginTop": "3px",
            }),
            *spark,
        ])

    scores_hist = hist.get("scores", [])
    crit_hist   = hist.get("n_criticos", [])

    return [
        kpi_card(
            "Score operacional",
            f"{int(score*100)}/100",
            COLORES[data["nivel_global"]],
            f"Nivel {data['nivel_global']}",
            scores_hist,
            COLORES[data["nivel_global"]],
        ),
        kpi_card(
            "Críticos",
            str(n_crit),
            COLORES["CRITICO"],
            _tendencia(crit_hist) or "acción inmediata",
            crit_hist,
            COLORES["CRITICO"],
        ),
        kpi_card(
            "Altos",
            str(n_alto),
            COLORES["ALTO"],
            "revisión requerida",
            hist.get("n_altos", []),
            COLORES["ALTO"],
        ),
        kpi_card(
            "Alertas activas",
            str(n_alert),
            COLORES["azul"],
            f"{len(riesgos)} riesgos monitoreados",
            hist.get("n_alertas", []),
            COLORES["azul"],
        ),
    ]


# ── 3. Bullet chart ──────────────────────────────────────────
@app.callback(
    Output("panel-bullet", "children"),
    Input("store-sitrep", "data"),
    State("empresa-selector", "value"),
)
def actualizar_bullet(data, empresa_id):
    if not data:
        return []

    lecturas_dict = EMPRESAS[empresa_id]["lecturas_default"]
    metricas = _metricas_bullet(empresa_id, lecturas_dict)
    if not metricas:
        return [_lbl("Bullet chart"), html.Div("Sin métricas para este sector.",
                style={"fontSize": "12px", "color": COLORES["texto2"]})]

    fig = _fig_bullet(metricas)

    leyenda = html.Div(
        style={"display": "flex", "gap": "12px", "marginTop": "8px",
               "flexWrap": "wrap"},
        children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"},
                     children=[
                         html.Div(style={"width": "20px", "height": "6px",
                                         "borderRadius": "2px", "backgroundColor": c}),
                         html.Div(l, style={"fontSize": "10px",
                                            "color": COLORES["texto2"]}),
                     ])
            for l, c in [
                ("zona crítica", COLORES["fondo_critico"]),
                ("zona alerta",  COLORES["fondo_medio"]),
                ("zona ok",      COLORES["fondo_bajo"]),
            ]
        ] + [
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"},
                     children=[
                         html.Div(style={"width": "2px", "height": "12px",
                                         "backgroundColor": COLORES["texto"]}),
                         html.Div("objetivo", style={"fontSize": "10px",
                                                     "color": COLORES["texto2"]}),
                     ])
        ],
    )
    return [_lbl("Desempeño vs objetivo"),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            leyenda]


# ── 4. Ranking ───────────────────────────────────────────────
@app.callback(Output("panel-ranking", "children"), Input("store-sitrep", "data"))
def actualizar_ranking(data):
    if not data:
        return []
    riesgos = sorted(data["riesgos"], key=lambda r: r["score"], reverse=True)
    df = pd.DataFrame([{
        "Riesgo":   r["nombre"],
        "Score":    round(r["score"] * 100),
        "Nivel":    r["nivel"],
        "Color":    COLORES[r["nivel"]],
    } for r in riesgos])

    fig = go.Figure()
    for _, row in df.iterrows():
        fig.add_trace(go.Bar(
            x=[row["Score"]], y=[row["Riesgo"]],
            orientation="h",
            marker_color=row["Color"], marker_line_width=0,
            text=f"  {row['Nivel']}  {row['Score']}/100",
            textposition="inside",
            textfont={"size": 11, "color": "#fff"},
            showlegend=False,
            hovertemplate=f"<b>{row['Riesgo']}</b><br>Score: {row['Score']}/100<br>Nivel: {row['Nivel']}<extra></extra>",
        ))
    fig.update_layout(
        margin=dict(l=0, r=10, t=0, b=0),
        height=max(160, len(riesgos) * 52),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(range=[0, 100], showgrid=True, gridcolor=COLORES["borde"],
                   gridwidth=0.5, tickfont={"size": 10}),
        yaxis=dict(showgrid=False, tickfont={"size": 12}),
        barmode="relative", bargap=0.3, font={"family": "system-ui"},
    )
    return [_lbl("Ranking de riesgos"),
            dcc.Graph(figure=fig, config={"displayModeBar": False})]


# ── 5. Alertas ───────────────────────────────────────────────
@app.callback(Output("panel-alertas", "children"), Input("store-sitrep", "data"))
def actualizar_alertas(data):
    if not data:
        return []
    alertas = data.get("alertas_activas", [])
    items = []
    if not alertas:
        items.append(html.Div("Sin alertas activas",
            style={"fontSize": "13px", "color": COLORES["texto2"],
                   "textAlign": "center", "padding": "20px 0"}))
    else:
        for alerta in alertas:
            es_crit  = "CRÍTICO" in alerta or "⛔" in alerta or "🔴" in alerta
            color_bg = COLORES["fondo_critico"] if es_crit else COLORES["fondo_medio"]
            color_tx = "#791F1F" if es_crit else "#633806"
            texto = alerta.replace("🔴 ","").replace("🟡 ","").replace("⛔ ","")
            items.append(html.Div(texto, style={
                "backgroundColor": color_bg, "color": color_tx,
                "fontSize": "11px", "borderRadius": "8px",
                "padding": "10px 12px", "marginBottom": "8px", "lineHeight": "1.5",
            }))
    return [_lbl(f"Alertas activas ({len(alertas)})"), *items]


# ── 6. Semáforo por categoría ────────────────────────────────
@app.callback(Output("panel-semaforo", "children"), Input("store-sitrep", "data"))
def actualizar_semaforo(data):
    if not data:
        return []

    # Peor nivel por categoría
    cat_nivel: dict[str, int] = {}
    for r in data["riesgos"]:
        cat = r["categoria"]
        nivel_n = NIVEL_ORDEN.get(r["nivel"], 0)
        cat_nivel[cat] = max(cat_nivel.get(cat, 0), nivel_n)

    orden_inv = {v: k for k, v in NIVEL_ORDEN.items()}
    filas = []
    for cat, nivel_n in sorted(cat_nivel.items(),
                                key=lambda x: x[1], reverse=True):
        nivel = orden_inv[nivel_n]
        filas.append(html.Div(
            style={"display": "flex", "alignItems": "center", "gap": "8px",
                   "padding": "7px 0",
                   "borderBottom": f"0.5px solid {COLORES['borde']}"},
            children=[
                html.Div(style={
                    "width": "10px", "height": "10px", "borderRadius": "50%",
                    "backgroundColor": COLORES[nivel], "flexShrink": "0",
                }),
                html.Div(cat.capitalize(),
                         style={"fontSize": "12px", "flex": "1",
                                "color": COLORES["texto"]}),
                html.Div(nivel,
                         style={"fontSize": "10px", "fontWeight": "500",
                                "color": COLORES[nivel]}),
            ],
        ))

    return [_lbl("Estado por categoría"), *filas]


# ── 7. Leading / Lagging ─────────────────────────────────────
@app.callback(
    Output("panel-leading-lagging", "children"),
    Input("store-sitrep", "data"),
    State("empresa-selector", "value"),
)
def actualizar_leading_lagging(data, empresa_id):
    if not data:
        return []

    leading, lagging = _leading_lagging(data, empresa_id)

    def tipo_badge(tipo, color_bg, color_txt):
        return html.Span(tipo, style={
            "fontSize": "9px", "fontWeight": "500", "padding": "2px 5px",
            "borderRadius": "3px", "letterSpacing": "0.03em",
            "backgroundColor": color_bg, "color": color_txt,
            "whiteSpace": "nowrap",
        })

    def fila(nombre, tipo_node, estado, color_estado):
        return html.Div(
            style={
                "display": "flex", "alignItems": "center",
                "justifyContent": "space-between",
                "gap": "8px", "padding": "5px 8px",
                "borderRadius": "6px", "marginBottom": "4px",
                "backgroundColor": COLORES["fondo"],
            },
            children=[
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px"},
                         children=[
                             tipo_node,
                             html.Div(nombre, style={"fontSize": "12px",
                                                     "color": COLORES["texto"]}),
                         ]),
                html.Div(estado, style={"fontSize": "11px", "fontWeight": "600",
                                        "color": color_estado, "flexShrink": "0"}),
            ],
        )

    filas_lagging = [fila(
        l["nombre"],
        tipo_badge("LAGGING", COLORES["fondo_critico"], "#A32D2D"),
        l["estado"], l["color"],
    ) for l in lagging] or [html.Div("Sin disparos activos",
        style={"fontSize": "11px", "color": COLORES["texto2"]})]

    filas_leading = [fila(
        l["nombre"],
        tipo_badge("LEADING", "#E6F1FB", "#185FA5"),
        "OK", COLORES["BAJO"],
    ) for l in leading] or [html.Div("Sin datos",
        style={"fontSize": "11px", "color": COLORES["texto2"]})]

    col_lagging = html.Div([
        html.Div("Reactivos (lagging)", style={
            "fontSize": "10px", "fontWeight": "500", "color": "#A32D2D",
            "textTransform": "uppercase", "letterSpacing": "0.06em",
            "marginBottom": "8px",
        }),
        *filas_lagging,
    ], style={"flex": "1"})

    col_leading = html.Div([
        html.Div("Proactivos (leading)", style={
            "fontSize": "10px", "fontWeight": "500", "color": "#185FA5",
            "textTransform": "uppercase", "letterSpacing": "0.06em",
            "marginBottom": "8px",
        }),
        *filas_leading,
    ], style={"flex": "1", "paddingTop": "16px",
              "borderTop": f"0.5px solid {COLORES['borde']}"})

    return [
        _lbl("Indicadores leading vs lagging"),
        html.Div(style={"display": "flex", "flexDirection": "column", "gap": "16px"},
                 children=[col_lagging, col_leading]),
    ]


# ── 8. Pareto ────────────────────────────────────────────────
@app.callback(Output("panel-pareto", "children"), Input("store-sitrep", "data"))
def actualizar_pareto(data):
    if not data:
        return []

    riesgos = sorted(data["riesgos"], key=lambda r: r["score"], reverse=True)
    total_score = sum(r["score"] for r in riesgos) or 1

    filas = []
    acum = 0
    for r in riesgos:
        pct = r["score"] / total_score * 100
        acum += pct
        color = COLORES[r["nivel"]]
        nombre_corto = r["nombre"][:22] + "…" if len(r["nombre"]) > 22 else r["nombre"]
        filas.append(html.Div(
            style={"display": "flex", "alignItems": "center", "gap": "8px",
                   "marginBottom": "8px"},
            children=[
                html.Div(r["nombre"],
                         style={"fontSize": "12px", "color": COLORES["texto"],
                                "flex": "1", "lineHeight": "1.3"}),
                html.Div(style={"flex": "1", "height": "8px", "borderRadius": "3px",
                                "backgroundColor": COLORES["fondo"],
                                "position": "relative"},
                         children=[html.Div(style={
                             "width": f"{pct:.0f}%", "height": "100%",
                             "borderRadius": "3px", "backgroundColor": color,
                         })]),
                html.Div(f"{pct:.0f}%",
                         style={"fontSize": "10px", "color": color,
                                "fontWeight": "500", "width": "30px",
                                "textAlign": "right"}),
            ],
        ))

    top_n = next((i + 1 for i, r in enumerate(
        sorted(data["riesgos"], key=lambda x: x["score"], reverse=True))
        if sum(rr["score"] for rr in data["riesgos"][:i+1]) / total_score >= 0.7), len(riesgos))

    return [
        _lbl("Pareto de impacto"),
        *filas,
        html.Div(
            f"Los {top_n} primeros concentran el 70% del riesgo total",
            style={"fontSize": "10px", "color": COLORES["texto2"],
                   "marginTop": "8px", "paddingTop": "8px",
                   "borderTop": f"0.5px solid {COLORES['borde']}"},
        ),
    ]


# ── 9. Matriz ────────────────────────────────────────────────
@app.callback(Output("panel-matriz", "children"), Input("store-sitrep", "data"))
def actualizar_matriz(data):
    if not data:
        return []
    riesgos = data["riesgos"]
    fig = go.Figure()
    for x0, x1, y0, y1, color in [
        (0.0, 0.3,  0.0, 0.3,  COLORES["fondo_bajo"]),
        (0.3, 0.55, 0.0, 0.55, COLORES["fondo_medio"]),
        (0.55,0.75, 0.0, 0.75, COLORES["fondo_alto"]),
        (0.75,1.0,  0.0, 1.0,  COLORES["fondo_critico"]),
    ]:
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
                      fillcolor=color, line_width=0, layer="below")
    for r in riesgos:
        fig.add_trace(go.Scatter(
            x=[r["probabilidad"]], y=[r["impacto"]],
            mode="markers+text",
            marker=dict(size=max(14, int(r["score"] * 28)),
                        color=COLORES[r["nivel"]],
                        line=dict(color="#fff", width=2), opacity=0.92),
            text=[r["nombre"].split(" ")[0][:12]],
            textposition="top center",
            textfont=dict(size=10, color=COLORES["texto"]),
            name=r["nombre"],
            hovertemplate=(
                f"<b>{r['nombre']}</b><br>"
                f"Probabilidad: {r['probabilidad']:.2f}<br>"
                f"Impacto: {r['impacto']:.2f}<br>"
                f"Score: {int(r['score']*100)}/100<br>"
                f"Nivel: {r['nivel']}<extra></extra>"
            ),
        ))
    fig.update_layout(
        margin=dict(l=40, r=20, t=20, b=40),
        height=300,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(title="Probabilidad", range=[0, 1],
                   gridcolor=COLORES["borde"], gridwidth=0.5, tickformat=".0%"),
        yaxis=dict(title="Impacto", range=[0, 1],
                   gridcolor=COLORES["borde"], gridwidth=0.5, tickformat=".0%"),
        font={"family": "system-ui", "size": 11},
        hovermode="closest",
    )
    return [
        _lbl("Matriz probabilidad × impacto"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        html.Div(
            style={"display": "flex", "gap": "12px", "marginTop": "8px",
                   "justifyContent": "center"},
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "5px"},
                    children=[
                        html.Div(style={"width": "10px", "height": "10px",
                                        "borderRadius": "50%", "backgroundColor": c}),
                        html.Div(l, style={"fontSize": "11px",
                                           "color": COLORES["texto2"]}),
                    ]
                )
                for l, c in [
                    ("Bajo",   COLORES["BAJO"]),
                    ("Medio",  COLORES["MEDIO"]),
                    ("Alto",   COLORES["ALTO"]),
                    ("Crítico",COLORES["CRITICO"]),
                ]
            ],
        ),
    ]


# ── 10. SITREP ───────────────────────────────────────────────
@app.callback(Output("panel-sitrep", "children"), Input("store-sitrep", "data"))
def actualizar_sitrep(data):
    if not data:
        return []
    lineas = data["resumen_ejecutivo"].split("\n")
    items = [_lbl("SITREP Ejecutivo")]
    for linea in lineas:
        if not linea.strip():
            items.append(html.Div(style={"height": "6px"}))
        elif linea.startswith("SITREP") or linea.startswith("Argo"):
            items.append(html.Div(linea, style={
                "fontSize": "14px", "fontWeight": "600",
                "color": COLORES["texto"], "marginBottom": "4px",
            }))
        elif linea.startswith("CRÍTICO"):
            items.append(html.Div(linea, style={
                "fontSize": "12px", "color": COLORES["CRITICO"],
                "fontWeight": "500", "backgroundColor": COLORES["fondo_critico"],
                "padding": "8px 10px", "borderRadius": "6px", "marginBottom": "6px",
            }))
        elif linea.startswith("ALTO"):
            items.append(html.Div(linea, style={
                "fontSize": "12px", "color": COLORES["ALTO"],
                "fontWeight": "500", "backgroundColor": COLORES["fondo_alto"],
                "padding": "8px 10px", "borderRadius": "6px", "marginBottom": "6px",
            }))
        else:
            items.append(html.Div(linea, style={
                "fontSize": "12px", "color": COLORES["texto2"], "lineHeight": "1.6",
            }))
    return items


# ── 11. Monte Carlo ──────────────────────────────────────────
@app.callback(
    Output("panel-montecarlo", "children"),
    Input("store-montecarlo", "data"),
)
def actualizar_montecarlo(mc):
    if not mc or "error" in mc or not mc.get("percentiles"):
        return [_lbl("Escenarios Monte Carlo"),
                html.Div("Simulación no disponible.",
                         style={"fontSize": "12px", "color": COLORES["texto2"]})]

    p   = mc["percentiles"]
    prb = mc["probabilidades"]
    esc = mc["escenarios"]

    def escenario_card(titulo, valor_frac, nivel):
        v = int(valor_frac * 100)
        color = COLORES[nivel]
        return html.Div(style={
            "textAlign": "center", "padding": "0 12px",
            "borderRight": f"0.5px solid {COLORES['borde']}",
        }, children=[
            html.Div(titulo, style={
                "fontSize": "10px", "color": COLORES["texto2"],
                "fontWeight": "500", "textTransform": "uppercase",
                "letterSpacing": "0.05em", "marginBottom": "4px",
            }),
            html.Div(f"{v}", style={
                "fontSize": "26px", "fontWeight": "600",
                "color": color, "lineHeight": "1",
            }),
            html.Div("/100", style={"fontSize": "11px", "color": COLORES["texto2"]}),
            html.Div(nivel, style={
                "fontSize": "10px", "color": color,
                "backgroundColor": COLORES[f"fondo_{nivel.lower()}"],
                "padding": "2px 8px", "borderRadius": "999px",
                "display": "inline-block", "marginTop": "4px",
            }),
        ])

    # Determinar nivel de cada percentil
    def _nivel(v):
        if v >= 0.75: return "CRITICO"
        if v >= 0.55: return "ALTO"
        if v >= 0.30: return "MEDIO"
        return "BAJO"

    prob_filas = []
    for label, key, nivel in [
        ("BAJO    < 30",  "bajo",    "BAJO"),
        ("MEDIO   30–55", "medio",   "MEDIO"),
        ("ALTO    55–75", "alto",    "ALTO"),
        ("CRÍTICO > 75",  "critico", "CRITICO"),
    ]:
        pct = int(prb.get(key, 0) * 100)
        color = COLORES[nivel]
        prob_filas.append(html.Div(
            style={"display": "flex", "alignItems": "center",
                   "gap": "10px", "marginBottom": "6px"},
            children=[
                html.Div(label, style={"fontSize": "11px",
                                       "color": COLORES["texto"],
                                       "width": "110px"}),
                html.Div(style={"flex": "1", "height": "8px",
                                "borderRadius": "3px",
                                "backgroundColor": COLORES["fondo"],
                                "position": "relative"},
                         children=[html.Div(style={
                             "width": f"{pct}%", "height": "100%",
                             "borderRadius": "3px", "backgroundColor": color,
                         })]),
                html.Div(f"{pct}%", style={"fontSize": "11px",
                                           "fontWeight": "500",
                                           "color": color, "width": "32px",
                                           "textAlign": "right"}),
            ],
        ))

    return [
        _lbl("Escenarios Monte Carlo — 3 000 simulaciones"),
        html.Div(
            style={"display": "grid",
                   "gridTemplateColumns": "repeat(4, 1fr)",
                   "gap": "0", "marginBottom": "20px"},
            children=[
                escenario_card("Optimista P10",   esc["optimista"],  _nivel(esc["optimista"])),
                escenario_card("Esperado P50",     esc["esperado"],   _nivel(esc["esperado"])),
                escenario_card("Adverso P90",      esc["pesimista"],  _nivel(esc["pesimista"])),
                html.Div(style={"textAlign": "center", "padding": "0 12px"}, children=[
                    html.Div("Catástrofe P99", style={
                        "fontSize": "10px", "color": COLORES["texto2"],
                        "fontWeight": "500", "textTransform": "uppercase",
                        "letterSpacing": "0.05em", "marginBottom": "4px",
                    }),
                    html.Div(str(int(esc["catastrofe"] * 100)), style={
                        "fontSize": "26px", "fontWeight": "600",
                        "color": COLORES["CRITICO"], "lineHeight": "1",
                    }),
                    html.Div("/100", style={"fontSize": "11px", "color": COLORES["texto2"]}),
                    html.Div(_nivel(esc["catastrofe"]), style={
                        "fontSize": "10px", "color": COLORES["CRITICO"],
                        "backgroundColor": COLORES["fondo_critico"],
                        "padding": "2px 8px", "borderRadius": "999px",
                        "display": "inline-block", "marginTop": "4px",
                    }),
                ]),
            ],
        ),

        html.Div(
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                   "gap": "0 40px"},
            children=[
                html.Div([
                    html.Div("Distribución por nivel", style={
                        "fontSize": "11px", "color": COLORES["texto2"],
                        "fontWeight": "500", "textTransform": "uppercase",
                        "letterSpacing": "0.05em", "marginBottom": "10px",
                    }),
                    *prob_filas,
                ]),
                html.Div([
                    html.Div("Recomendación táctica", style={
                        "fontSize": "11px", "color": COLORES["texto2"],
                        "fontWeight": "500", "textTransform": "uppercase",
                        "letterSpacing": "0.05em", "marginBottom": "8px",
                    }),
                    html.Div(
                        mc.get("recomendacion", ""),
                        style={
                            "fontSize": "12px", "lineHeight": "1.7",
                            "color": COLORES["texto"],
                            "backgroundColor": COLORES["fondo"],
                            "padding": "12px 14px", "borderRadius": "8px",
                        },
                    ),
                ]),
            ],
        ),
    ]


# ── 12. Badge de fuente de datos ────────────────────────────
@app.callback(
    Output("datasource-badge", "children"),
    Input("store-datasource", "data"),
)
def actualizar_datasource_badge(ds):
    if not ds:
        return []

    n_real  = ds.get("n_real", 0)
    n_total = ds.get("n_total", 1)
    conectores = ds.get("conectores", False)

    if not conectores:
        return [html.Div(
            "datos simulados",
            style={
                "fontSize": "11px", "color": COLORES["texto2"],
                "backgroundColor": COLORES["fondo"],
                "border": f"0.5px solid {COLORES['borde']}",
                "borderRadius": "999px", "padding": "4px 10px",
            },
        )]

    pct = int(n_real / max(n_total, 1) * 100)
    es_real = n_real > 0
    color_bg  = COLORES["fondo_bajo"]  if es_real else COLORES["fondo_medio"]
    color_txt = "#3B6D11"              if es_real else "#854F0B"
    icono     = "● "

    ts = ds.get("timestamp", "")
    hora = ts[11:16] if len(ts) >= 16 else ""

    return [html.Div(
        f"{icono}{n_real}/{n_total} indicadores en tiempo real"
        + (f"  —  {hora}" if hora else ""),
        style={
            "fontSize": "11px", "fontWeight": "500",
            "color": color_txt,
            "backgroundColor": color_bg,
            "border": f"0.5px solid {color_txt}40",
            "borderRadius": "999px", "padding": "4px 12px",
            "whiteSpace": "nowrap",
        },
    )]


# ── Z1. Mapa agropecuario por zonas ─────────────────────────
@app.callback(
    Output("panel-mapa", "children"),
    Input("store-sitrep", "data"),
    State("empresa-selector", "value"),
)
def actualizar_mapa(data, empresa_id):
    fig = go.Figure()

    lats     = [z["lat"]     for z in ZONAS_AGRO_MAPA]
    lons     = [z["lon"]     for z in ZONAS_AGRO_MAPA]
    colores  = [z["color"]   for z in ZONAS_AGRO_MAPA]
    sizes    = [z["size"]    for z in ZONAS_AGRO_MAPA]
    textos   = [
        f"<b>{z['nombre']}</b><br>"
        f"Cultivo: {z['cultivo']}<br>"
        f"Aptitud: {z['aptitud']}<br>"
        + (f"Flete a Rosario: ${z['flete_ars_tn']:,}/tn" if z['flete_ars_tn'] > 0 else "Puerto de referencia")
        for z in ZONAS_AGRO_MAPA
    ]

    # Empresa activa
    emp = EMPRESAS.get(empresa_id, {})
    emp_lat = emp.get("lat")
    emp_lon = emp.get("lon")
    emp_label = emp.get("label", "")

    # Zonas
    fig.add_trace(go.Scattermapbox(
        lat=lats, lon=lons,
        mode="markers",
        marker=dict(size=sizes, color=colores, opacity=0.82),
        hovertext=textos,
        hoverinfo="text",
        name="Zonas",
    ))

    # Empresa activa destacada
    if emp_lat and emp_lon:
        fig.add_trace(go.Scattermapbox(
            lat=[emp_lat], lon=[emp_lon],
            mode="markers+text",
            marker=dict(size=16, color="#378ADD",
                        symbol="star"),
            text=[emp_label.split()[0]],
            textposition="top right",
            textfont=dict(size=10, color="#378ADD"),
            hovertext=[f"<b>{emp_label}</b>"],
            hoverinfo="text",
            name="Empresa",
        ))

    fig.update_layout(
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=-33.5, lon=-62.0),
            zoom=3.8,
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=230,
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        hoverlabel=dict(bgcolor="#0D1B2A", bordercolor=COLORES["borde"],
                        font=dict(size=11, color="#E8E6E0", family="system-ui")),
    )

    # Leyenda compacta
    leyenda = html.Div(
        style={"display": "flex", "gap": "12px", "marginTop": "6px",
               "flexWrap": "wrap"},
        children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"},
                     children=[
                         html.Div(style={"width": "8px", "height": "8px",
                                         "borderRadius": "50%", "backgroundColor": "#639922"}),
                         html.Div("Alta aptitud", style={"fontSize": "10px",
                                                          "color": COLORES["texto2"]}),
                     ]),
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"},
                     children=[
                         html.Div(style={"width": "8px", "height": "8px",
                                         "borderRadius": "50%", "backgroundColor": "#BA7517"}),
                         html.Div("Media aptitud", style={"fontSize": "10px",
                                                           "color": COLORES["texto2"]}),
                     ]),
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"},
                     children=[
                         html.Div(style={"width": "8px", "height": "8px",
                                         "borderRadius": "50%", "backgroundColor": "#D85A30"}),
                         html.Div("Baja aptitud", style={"fontSize": "10px",
                                                          "color": COLORES["texto2"]}),
                     ]),
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"},
                     children=[
                         html.Div(style={"width": "8px", "height": "8px",
                                         "borderRadius": "50%", "backgroundColor": "#378ADD"}),
                         html.Div("Puerto Rosario", style={"fontSize": "10px",
                                                            "color": COLORES["texto2"]}),
                     ]),
        ]
    )

    label = html.Div("Zonas agrícolas · aptitud de suelo · flete a Rosario", style={
        "fontSize": "10px", "fontWeight": "500",
        "color": COLORES["texto2"], "textTransform": "uppercase",
        "letterSpacing": "0.08em", "marginBottom": "4px",
    })

    return [label, dcc.Graph(figure=fig, config={"displayModeBar": False}), leyenda]


# ── Z1. Score grande ────────────────────────────────────────
@app.callback(Output("panel-score", "children"), Input("store-sitrep", "data"))
def actualizar_score(data):
    if not data:
        return []
    score  = int(data["score_global"] * 100)
    nivel  = data["nivel_global"]
    color  = COLORES[nivel]
    fondo  = COLORES[f"fondo_{nivel.lower()}"]
    empresa = data["empresa"].split(" ")[0]  # primera palabra

    barra_pct = score  # 0-100
    return [
        html.Div(empresa, style={
            "fontSize": "11px", "color": COLORES["texto2"],
            "fontWeight": "500", "textTransform": "uppercase",
            "letterSpacing": "0.05em", "marginBottom": "8px",
        }),
        html.Div(str(score), style={
            "fontSize": "64px", "fontWeight": "600",
            "color": color, "lineHeight": "1", "marginBottom": "2px",
        }),
        html.Div("/100", style={
            "fontSize": "13px", "color": COLORES["texto2"], "marginBottom": "12px",
        }),
        html.Div(style={
            "height": "6px", "borderRadius": "3px",
            "backgroundColor": COLORES["borde"], "marginBottom": "10px",
        }, children=[
            html.Div(style={
                "width": f"{barra_pct}%", "height": "100%",
                "borderRadius": "3px", "backgroundColor": color,
            })
        ]),
        html.Div(nivel, style={
            "display": "inline-block",
            "backgroundColor": fondo,
            "color": color,
            "fontSize": "11px", "fontWeight": "500",
            "padding": "3px 12px", "borderRadius": "999px",
        }),
    ]


# ── Z2. Párrafo de situación ─────────────────────────────────
@app.callback(Output("panel-situacion", "children"), Input("store-sitrep", "data"))
def actualizar_situacion(data):
    if not data:
        return []

    score   = int(data["score_global"] * 100)
    nivel   = data["nivel_global"]
    riesgos = data["riesgos"]
    empresa = data["empresa"]

    criticos = [r for r in riesgos if r["nivel"] == "CRITICO"]
    altos    = [r for r in riesgos if r["nivel"] == "ALTO"]

    # Categoría con mayor score acumulado
    cat_score: dict[str, float] = {}
    for r in riesgos:
        cat_score[r["categoria"]] = cat_score.get(r["categoria"], 0) + r["score"]
    top_cat = max(cat_score, key=cat_score.get) if cat_score else "operacional"

    # Construir el párrafo
    partes = []

    # Frase 1: estado general
    if nivel == "CRITICO":
        partes.append(f"{empresa} opera en estado CRÍTICO ({score}/100). Se requiere acción inmediata.")
    elif nivel == "ALTO":
        partes.append(f"{empresa} opera con riesgo ALTO ({score}/100). Revisión de contingencias necesaria.")
    elif nivel == "MEDIO":
        partes.append(f"{empresa} opera dentro de parámetros de alerta ({score}/100). Monitoreo activo.")
    else:
        partes.append(f"{empresa} opera en condiciones normales ({score}/100).")

    # Frase 2: dónde está el foco
    if criticos:
        nombres = " y ".join(r["nombre"] for r in criticos[:2])
        partes.append(f"Foco crítico en {nombres}.")
    elif altos:
        nombres = " y ".join(r["nombre"] for r in altos[:2])
        partes.append(f"Atención elevada en {nombres}.")

    # Frase 3: factor dominante
    partes.append(
        f"El factor {top_cat} concentra el mayor peso de riesgo ({int(cat_score.get(top_cat,0)*100/max(sum(cat_score.values()),1))}% del total)."
    )

    # Frase 4: acción recomendada
    if nivel in ("CRITICO", "ALTO"):
        partes.append("Acción recomendada: activar protocolo de respuesta y escalar a supervisión.")
    elif nivel == "MEDIO":
        partes.append("Acción recomendada: reforzar monitoreo de indicadores leading.")
    else:
        partes.append("Continuar con monitoreo de rutina.")

    texto = "  ".join(partes)
    color_borde = COLORES[nivel]
    color_fondo = COLORES[f"fondo_{nivel.lower()}"]

    return [html.Div(style={
        "borderLeft": f"3px solid {color_borde}",
        "paddingLeft": "14px",
        "display": "flex", "flexDirection": "column", "gap": "2px",
    }, children=[
        html.Div("Situación operacional", style={
            "fontSize": "10px", "fontWeight": "500", "color": COLORES["texto2"],
            "textTransform": "uppercase", "letterSpacing": "0.06em",
            "marginBottom": "4px",
        }),
        html.Div(texto, style={
            "fontSize": "13px", "lineHeight": "1.7", "color": COLORES["texto"],
        }),
    ])]


# ── Z3. Toggle zona análisis ─────────────────────────────────
@app.callback(
    Output("zona3-contenido", "style"),
    Output("btn-zona3", "children"),
    Input("btn-zona3", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_zona3(n_clicks):
    abierta = (n_clicks or 0) % 2 == 1
    estilo = {"display": "block"} if abierta else {"display": "none"}
    texto  = "▲  Ocultar análisis" if abierta else "▼  Ver análisis completo"
    return estilo, texto


# ── Agro. Panel de decisión de venta ────────────────────────
@app.callback(
    Output("panel-agro-decision",  "children"),
    Output("zona-agro-wrapper",    "style"),
    Input("empresa-selector",      "value"),
    Input("store-sitrep",          "data"),
)
def actualizar_panel_agro(empresa_id, _sitrep):
    EMPRESAS_AGRO = {"agro", "aca_agro"}
    oculto  = {"display": "none"}
    visible = {"marginBottom": "14px"}

    if empresa_id not in EMPRESAS_AGRO or not AGRO_DISPONIBLE:
        return [], oculto

    empresa = EMPRESAS.get(empresa_id, {})
    lat = empresa.get("lat", -33.0)
    lon = empresa.get("lon", -63.0)

    zona = "pampa_humeda"
    lugar = empresa.get("lugar", "").lower()
    if "pampa" in lugar:
        zona = "la_pampa"
    elif "santa fe" in lugar or "rosario" in lugar:
        zona = "santa_fe_centro"
    elif "córdoba" in lugar or "cordoba" in lugar:
        zona = "cordoba_sur"
    elif "entre ríos" in lugar or "entre rios" in lugar:
        zona = "entre_rios"

    try:
        snap     = _conector_agro.snapshot_agro(lat, lon, zona)
        decision = _conector_agro.score_decision_venta(snap, grano="soja", zona=zona)
    except Exception as e:
        log.warning(f"Panel agro error: {e}")
        return [_lbl("Decisión agropecuaria"),
                html.Div("Datos no disponibles temporalmente.",
                         style={"fontSize": "12px", "color": COLORES["texto2"]})], visible

    score         = decision["score"]
    recomendacion = decision["recomendacion"]
    descripcion   = decision["descripcion"]
    factores      = decision["factores"]
    clima         = snap.get("clima", {})
    precios       = snap.get("precios", {})
    tc            = snap.get("tipo_cambio", {})
    logistica     = snap.get("logistica", {})

    color_rec = {"VENDER": COLORES["BAJO"], "ESPERAR": COLORES["MEDIO"],
                 "ATENCION": COLORES["CRITICO"]}.get(recomendacion, COLORES["MEDIO"])
    fondo_rec = {"VENDER": COLORES["fondo_bajo"], "ESPERAR": COLORES["fondo_medio"],
                 "ATENCION": COLORES["fondo_critico"]}.get(recomendacion, COLORES["fondo_medio"])

    # ── Cabecera: score + badge ──────────────────────────────
    header = html.Div(
        style={"display": "flex", "alignItems": "flex-start",
               "justifyContent": "space-between", "marginBottom": "14px"},
        children=[
            html.Div([
                _lbl("Decisión de venta — Soja"),
                html.Div(style={"display": "flex", "alignItems": "baseline", "gap": "6px"},
                         children=[
                             html.Div(str(score), style={
                                 "fontSize": "52px", "fontWeight": "600",
                                 "color": color_rec, "lineHeight": "1",
                             }),
                             html.Div("/100", style={"fontSize": "13px",
                                                     "color": COLORES["texto2"]}),
                         ]),
                html.Div(style={
                    "height": "5px", "borderRadius": "3px",
                    "backgroundColor": COLORES["borde"], "margin": "10px 0",
                }, children=[
                    html.Div(style={"width": f"{score}%", "height": "100%",
                                    "borderRadius": "3px", "backgroundColor": color_rec})
                ]),
            ]),
            html.Div(recomendacion, style={
                "backgroundColor": fondo_rec, "color": color_rec,
                "fontSize": "13px", "fontWeight": "600",
                "padding": "8px 18px", "borderRadius": "8px",
                "letterSpacing": "0.06em",
                "border": f"1px solid {color_rec}",
                "alignSelf": "flex-start",
            }),
        ]
    )

    # ── Descripción ──────────────────────────────────────────
    desc_div = html.Div(descripcion, style={
        "fontSize": "12px", "color": COLORES["texto2"],
        "lineHeight": "1.6", "marginBottom": "16px",
        "borderLeft": f"2px solid {color_rec}", "paddingLeft": "10px",
    })

    # ── KPIs rápidos ─────────────────────────────────────────
    soja_usd = precios.get("soja_rosario_usd_tn", "N/D")
    tc_val   = tc.get("usd_oficial_ars", "N/D")
    lluvia   = clima.get("lluvia_acumulada_7d_mm", "N/D")
    heladas  = clima.get("dias_helada_7d", 0)
    ventana  = clima.get("ventana_cosecha_ok", False)
    gasoil   = logistica.get("gasoil_ars_litro", "N/D")

    def _kpi(label, valor, color=None):
        return html.Div(style={
            "backgroundColor": COLORES["fondo"], "borderRadius": "8px",
            "padding": "10px 12px", "flex": "1",
        }, children=[
            html.Div(label, style={
                "fontSize": "10px", "color": COLORES["texto2"],
                "textTransform": "uppercase", "letterSpacing": "0.05em",
                "marginBottom": "4px",
            }),
            html.Div(str(valor), style={
                "fontSize": "15px", "fontWeight": "600",
                "color": color or COLORES["texto"],
            }),
        ])

    kpis = html.Div(style={"display": "flex", "gap": "8px", "marginBottom": "16px",
                            "flexWrap": "wrap"}, children=[
        _kpi("Soja Rosario",    f"USD {soja_usd}/tn"),
        _kpi("USD Oficial",     f"${tc_val}"),
        _kpi("Lluvia 7d",       f"{lluvia} mm"),
        _kpi("Gasoil",          f"${gasoil}/L"),
        _kpi("Ventana cosecha",
             "Abierta" if ventana else "Cerrada",
             COLORES["BAJO"] if ventana else COLORES["CRITICO"]),
        _kpi("Heladas 7d",
             f"{heladas} días",
             COLORES["CRITICO"] if heladas > 0 else COLORES["BAJO"]),
    ])

    # ── Factores detallados ──────────────────────────────────
    def _fila_factor(f):
        pts_str = f.get("puntos", "")
        try:
            pts_num = int(pts_str.split("/")[0])
            pts_max = int(pts_str.split("/")[1])
            pct_pts = (pts_num / pts_max) * 100
        except Exception:
            pct_pts = 50
        c = (COLORES["BAJO"] if pct_pts >= 70
             else COLORES["MEDIO"] if pct_pts >= 40
             else COLORES["CRITICO"])
        return html.Div(style={
            "display": "flex", "alignItems": "center", "gap": "10px",
            "padding": "8px 0", "borderBottom": f"0.5px solid {COLORES['borde']}",
        }, children=[
            html.Div(style={"width": "8px", "height": "8px", "borderRadius": "50%",
                            "backgroundColor": c, "flexShrink": "0"}),
            html.Div(f["factor"], style={"fontSize": "12px", "color": COLORES["texto"],
                                         "flex": "1"}),
            html.Div(f.get("valor", ""), style={"fontSize": "11px",
                                                 "color": COLORES["texto2"],
                                                 "whiteSpace": "nowrap"}),
            html.Div(pts_str, style={"fontSize": "11px", "fontWeight": "600",
                                      "color": c, "whiteSpace": "nowrap",
                                      "minWidth": "40px", "textAlign": "right"}),
        ])

    factores_div = html.Div([
        _lbl("Factores evaluados"),
        *[_fila_factor(f) for f in factores],
    ])

    # ── Alertas climáticas ───────────────────────────────────
    alertas = []
    if clima.get("alerta_helada"):
        alertas.append(html.Div(
            f"⚠ Alerta helada — {heladas} días proyectados en los próximos 7 días. "
            "Evaluar cobertura de cultivos en pie.",
            style={
                "backgroundColor": COLORES["fondo_critico"],
                "border": f"1px solid {COLORES['CRITICO']}",
                "borderRadius": "8px", "padding": "10px 14px", "marginTop": "14px",
                "fontSize": "12px", "color": COLORES["CRITICO"],
            }
        ))
    elif clima.get("alerta_sequia"):
        alertas.append(html.Div(
            "⚠ Alerta sequía — precipitación baja y humedad reducida. "
            "Monitorear stress hídrico del cultivo.",
            style={
                "backgroundColor": COLORES["fondo_medio"],
                "border": f"1px solid {COLORES['MEDIO']}",
                "borderRadius": "8px", "padding": "10px 14px", "marginTop": "14px",
                "fontSize": "12px", "color": COLORES["MEDIO"],
            }
        ))

    return [header, desc_div, kpis, factores_div, *alertas], visible
r

# ── Entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"\n  Argo Dashboard — iniciando en http://localhost:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port)