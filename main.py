"""
ARGO — Punto de entrada principal
==================================
Demo que corre el análisis para dos empresas distintas
usando el mismo motor con configuraciones diferentes.

Ejecutar:
    cd argo/
    python main.py
"""

import json
import sys
from pathlib import Path

# Asegura que el directorio raíz esté en el path
sys.path.insert(0, str(Path(__file__).parent))

from core.engine import ArgoEngine
from core.risk_scorer import LecturaIndicador


def demo_transportadora():
    """
    Simulación: transportadora con clima adverso y taller cargado.
    """
    print("\n" + "="*60)
    print("  DEMO 1 — TRANSPORTADORA DEL SUR S.A.")
    print("="*60)

    engine = ArgoEngine("config/transportadora_ejemplo.json")

    # Lecturas simuladas — situación con riesgo climático activo
    lecturas = [
        LecturaIndicador("precipitacion_mm",      65.0,  fuente="api_clima"),
        LecturaIndicador("viento_kmh",             55.0,  fuente="api_clima"),
        LecturaIndicador("temperatura_c",          18.0,  fuente="api_clima"),
        LecturaIndicador("precio_gasoil_ars",    1350.0,  fuente="manual"),
        LecturaIndicador("vehiculos_en_taller",     3.0,  fuente="interno"),
        LecturaIndicador("conductores_disponibles", 11.0, fuente="interno"),
        LecturaIndicador("conductores_sin_reemplazo", 1.0, fuente="interno"),
    ]

    sitrep = engine.analizar(lecturas, capacidad_mitigacion=0.6)

    # Mostrar resumen ejecutivo
    print("\n" + sitrep.resumen_ejecutivo)

    # Mostrar ranking de riesgos
    print("\n--- RANKING DE RIESGOS ---")
    riesgos_ord = sorted(sitrep.riesgos, key=lambda r: r.score, reverse=True)
    for i, r in enumerate(riesgos_ord, 1):
        barra = "█" * int(r.score * 20) + "░" * (20 - int(r.score * 20))
        print(f"  {i}. [{r.nivel.value:8s}] {barra} {int(r.score*100):3d}/100  {r.nombre}")

    # Alertas activas
    if sitrep.alertas_activas:
        print("\n--- ALERTAS ACTIVAS ---")
        for alerta in sitrep.alertas_activas:
            print(f"  {alerta}")

    # Exportar SITREP
    engine.exportar_sitrep(sitrep, "output/sitrep_transportadora.json")
    return sitrep


def demo_cooperativa_agro():
    """
    Simulación: cooperativa agrícola en período de sequía.
    """
    print("\n" + "="*60)
    print("  DEMO 2 — COOPERATIVA AGROPECUARIA PAMPA SUR")
    print("="*60)

    engine = ArgoEngine("config/agro_ejemplo.json")

    # Lecturas simuladas — sequía moderada con precios bajos
    lecturas = [
        LecturaIndicador("precipitacion_acumulada_mm", 12.0, fuente="api_clima"),
        LecturaIndicador("indice_sequia_palmer",        -2.4, fuente="api_clima"),
        LecturaIndicador("temperatura_minima_c",         1.5, fuente="api_clima"),
        LecturaIndicador("precio_soja_usd_tn",         305.0, fuente="api_precios"),
        LecturaIndicador("precio_maiz_usd_tn",         178.0, fuente="api_precios"),
        LecturaIndicador("camiones_disponibles",          4.0, fuente="interno"),
        LecturaIndicador("capacidad_silo_libre_tn",    1200.0, fuente="interno"),
    ]

    sitrep = engine.analizar(lecturas, capacidad_mitigacion=0.4)

    print("\n" + sitrep.resumen_ejecutivo)

    print("\n--- RANKING DE RIESGOS ---")
    riesgos_ord = sorted(sitrep.riesgos, key=lambda r: r.score, reverse=True)
    for i, r in enumerate(riesgos_ord, 1):
        barra = "█" * int(r.score * 20) + "░" * (20 - int(r.score * 20))
        print(f"  {i}. [{r.nivel.value:8s}] {barra} {int(r.score*100):3d}/100  {r.nombre}")

    if sitrep.alertas_activas:
        print("\n--- ALERTAS ACTIVAS ---")
        for alerta in sitrep.alertas_activas:
            print(f"  {alerta}")

    engine.exportar_sitrep(sitrep, "output/sitrep_agro.json")
    return sitrep


def comparar_empresas(s1, s2):
    """Comparativa ejecutiva entre los dos SITREPs."""
    print("\n" + "="*60)
    print("  COMPARATIVA ARGO — AMBAS EMPRESAS")
    print("="*60)
    print(f"\n  {'Empresa':<35} {'Score':>6}  {'Nivel'}")
    print("  " + "-"*55)
    for s in [s1, s2]:
        barra = "█" * int(s.score_global * 20)
        print(f"  {s.empresa:<35} {int(s.score_global*100):>5}%  {s.nivel_global.value}")
    print()


if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════╗")
    print("  ║   ARGO v1.0 — Motor Central          ║")
    print("  ║   Inteligencia Operacional            ║")
    print("  ╚══════════════════════════════════════╝")

    s1 = demo_transportadora()
    s2 = demo_cooperativa_agro()
    comparar_empresas(s1, s2)

    print("\n  SITREPs exportados en /output/")
    print("  Motor ARGO ejecutado correctamente.\n")
