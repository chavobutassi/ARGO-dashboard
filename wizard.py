"""
ARGO — Config Wizard
=====================
Genera el config.json de una empresa nueva en 10 preguntas.
No hace falta saber JSON ni programar.

Ejecutar:
    python wizard.py
    → genera: config/{nombre_empresa}.json
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime


# ── Plantillas de riesgos por sector ────────────────────────

RIESGOS_POR_SECTOR = {
    "logistica": [
        {"id": "LOG-001", "nombre": "Corte de ruta por clima", "categoria": "climatico",
         "probabilidad_base": 0.30, "impacto_base": 0.80,
         "fuente_dato": "api_clima",
         "indicadores": ["precipitacion_mm", "viento_kmh"],
         "umbrales": {"precipitacion_mm": {"alerta": 30, "critico": 60},
                      "viento_kmh":       {"alerta": 60, "critico": 90}}},
        {"id": "LOG-002", "nombre": "Escasez o precio de combustible", "categoria": "abastecimiento",
         "probabilidad_base": 0.25, "impacto_base": 0.70,
         "fuente_dato": "manual",
         "indicadores": ["precio_gasoil_ars"],
         "umbrales": {"precio_gasoil_ars": {"alerta": 1200, "critico": 1500}}},
        {"id": "LOG-003", "nombre": "Falla mecánica de flota", "categoria": "operacional",
         "probabilidad_base": 0.20, "impacto_base": 0.65,
         "fuente_dato": "interno",
         "indicadores": ["vehiculos_en_taller"],
         "umbrales": {"vehiculos_en_taller": {"alerta": 2, "critico": 4}}},
        {"id": "LOG-004", "nombre": "Pérdida de conductor/operario clave", "categoria": "personas",
         "probabilidad_base": 0.15, "impacto_base": 0.55,
         "fuente_dato": "interno",
         "indicadores": ["personal_sin_reemplazo"],
         "umbrales": {"personal_sin_reemplazo": {"alerta": 1, "critico": 3}}},
    ],
    "agro": [
        {"id": "AGR-001", "nombre": "Sequía crítica", "categoria": "climatico",
         "probabilidad_base": 0.35, "impacto_base": 0.90,
         "fuente_dato": "api_clima",
         "indicadores": ["precipitacion_acumulada_mm", "indice_sequia_palmer"],
         "umbrales": {"precipitacion_acumulada_mm": {"alerta": 20, "critico": 8},
                      "indice_sequia_palmer":        {"alerta": -2.0, "critico": -3.5}}},
        {"id": "AGR-002", "nombre": "Caída de precio commodity", "categoria": "mercado",
         "probabilidad_base": 0.30, "impacto_base": 0.75,
         "fuente_dato": "api_precios",
         "indicadores": ["precio_soja_usd_tn", "precio_maiz_usd_tn"],
         "umbrales": {"precio_soja_usd_tn": {"alerta": 320, "critico": 270}}},
        {"id": "AGR-003", "nombre": "Helada fuera de temporada", "categoria": "climatico",
         "probabilidad_base": 0.20, "impacto_base": 0.80,
         "fuente_dato": "api_clima",
         "indicadores": ["temperatura_minima_c"],
         "umbrales": {"temperatura_minima_c": {"alerta": 2, "critico": -1}}},
        {"id": "AGR-004", "nombre": "Demora logística de cosecha", "categoria": "operacional",
         "probabilidad_base": 0.25, "impacto_base": 0.65,
         "fuente_dato": "interno",
         "indicadores": ["camiones_disponibles"],
         "umbrales": {"camiones_disponibles": {"alerta": 5, "critico": 2}}},
    ],
    "mineria": [
        {"id": "MIN-001", "nombre": "Falla de equipo crítico", "categoria": "operacional",
         "probabilidad_base": 0.25, "impacto_base": 0.85,
         "fuente_dato": "interno",
         "indicadores": ["equipos_fuera_servicio"],
         "umbrales": {"equipos_fuera_servicio": {"alerta": 1, "critico": 2}}},
        {"id": "MIN-002", "nombre": "Condición climática extrema en yacimiento", "categoria": "climatico",
         "probabilidad_base": 0.30, "impacto_base": 0.75,
         "fuente_dato": "api_clima",
         "indicadores": ["viento_kmh", "temperatura_c"],
         "umbrales": {"viento_kmh": {"alerta": 80, "critico": 110},
                      "temperatura_c": {"alerta": -5, "critico": -15}}},
        {"id": "MIN-003", "nombre": "Incidente de seguridad", "categoria": "operacional",
         "probabilidad_base": 0.15, "impacto_base": 0.90,
         "fuente_dato": "interno",
         "indicadores": ["incidentes_mes"],
         "umbrales": {"incidentes_mes": {"alerta": 2, "critico": 4}}},
        {"id": "MIN-004", "nombre": "Rotación de personal técnico", "categoria": "personas",
         "probabilidad_base": 0.20, "impacto_base": 0.60,
         "fuente_dato": "interno",
         "indicadores": ["tasa_rotacion_mensual_pct"],
         "umbrales": {"tasa_rotacion_mensual_pct": {"alerta": 5, "critico": 10}}},
    ],
    "retail": [
        {"id": "RET-001", "nombre": "Quiebre de stock masivo", "categoria": "abastecimiento",
         "probabilidad_base": 0.35, "impacto_base": 0.75,
         "fuente_dato": "interno",
         "indicadores": ["skus_en_quiebre"],
         "umbrales": {"skus_en_quiebre": {"alerta": 15, "critico": 40}}},
        {"id": "RET-002", "nombre": "Falla de proveedor clave", "categoria": "abastecimiento",
         "probabilidad_base": 0.20, "impacto_base": 0.80,
         "fuente_dato": "interno",
         "indicadores": ["proveedores_con_demora"],
         "umbrales": {"proveedores_con_demora": {"alerta": 2, "critico": 5}}},
        {"id": "RET-003", "nombre": "Pico de demanda no planificado", "categoria": "mercado",
         "probabilidad_base": 0.25, "impacto_base": 0.60,
         "fuente_dato": "interno",
         "indicadores": ["variacion_demanda_pct"],
         "umbrales": {"variacion_demanda_pct": {"alerta": 25, "critico": 50}}},
        {"id": "RET-004", "nombre": "Falla de sistema de caja/ERP", "categoria": "operacional",
         "probabilidad_base": 0.10, "impacto_base": 0.85,
         "fuente_dato": "interno",
         "indicadores": ["sistemas_caidos"],
         "umbrales": {"sistemas_caidos": {"alerta": 1, "critico": 2}}},
    ],
    "salud": [
        {"id": "SAL-001", "nombre": "Quiebre de insumo crítico", "categoria": "abastecimiento",
         "probabilidad_base": 0.30, "impacto_base": 0.95,
         "fuente_dato": "interno",
         "indicadores": ["insumos_bajo_stock_critico"],
         "umbrales": {"insumos_bajo_stock_critico": {"alerta": 3, "critico": 7}}},
        {"id": "SAL-002", "nombre": "Saturación de capacidad UCI", "categoria": "operacional",
         "probabilidad_base": 0.25, "impacto_base": 0.90,
         "fuente_dato": "interno",
         "indicadores": ["ocupacion_uci_pct"],
         "umbrales": {"ocupacion_uci_pct": {"alerta": 85, "critico": 95}}},
        {"id": "SAL-003", "nombre": "Guardia médica incompleta", "categoria": "personas",
         "probabilidad_base": 0.20, "impacto_base": 0.80,
         "fuente_dato": "interno",
         "indicadores": ["medicos_faltantes_guardia"],
         "umbrales": {"medicos_faltantes_guardia": {"alerta": 1, "critico": 3}}},
        {"id": "SAL-004", "nombre": "Falla de sistemas críticos", "categoria": "operacional",
         "probabilidad_base": 0.10, "impacto_base": 0.90,
         "fuente_dato": "interno",
         "indicadores": ["sistemas_criticos_caidos"],
         "umbrales": {"sistemas_criticos_caidos": {"alerta": 1, "critico": 1}}},
    ],
    "energia": [
        {"id": "ENE-001", "nombre": "Falla de equipo de producción", "categoria": "operacional",
         "probabilidad_base": 0.25, "impacto_base": 0.85,
         "fuente_dato": "interno",
         "indicadores": ["equipos_produccion_fuera_servicio"],
         "umbrales": {"equipos_produccion_fuera_servicio": {"alerta": 1, "critico": 2}}},
        {"id": "ENE-002", "nombre": "Caída del precio del barril", "categoria": "mercado",
         "probabilidad_base": 0.30, "impacto_base": 0.70,
         "fuente_dato": "api_precios",
         "indicadores": ["petroleo_wti_usd"],
         "umbrales": {"petroleo_wti_usd": {"alerta": 65, "critico": 50}}},
        {"id": "ENE-003", "nombre": "Condición climática en yacimiento", "categoria": "climatico",
         "probabilidad_base": 0.20, "impacto_base": 0.65,
         "fuente_dato": "api_clima",
         "indicadores": ["viento_kmh", "temperatura_c"],
         "umbrales": {"viento_kmh": {"alerta": 70, "critico": 100}}},
        {"id": "ENE-004", "nombre": "Conflicto laboral / sindical", "categoria": "personas",
         "probabilidad_base": 0.15, "impacto_base": 0.75,
         "fuente_dato": "interno",
         "indicadores": ["ausentismo_pct"],
         "umbrales": {"ausentismo_pct": {"alerta": 10, "critico": 20}}},
    ],
}

SECTORES_VALIDOS = list(RIESGOS_POR_SECTOR.keys())

KPI_POR_SECTOR = {
    "logistica": "OTIF",
    "agro":      "rendimiento_tn_ha",
    "mineria":   "disponibilidad_equipos_pct",
    "retail":    "fill_rate_pct",
    "salud":     "tiempo_respuesta_min",
    "energia":   "produccion_diaria_tn",
}

UNIDAD_POR_SECTOR = {
    "logistica": "vehiculos",
    "agro":      "hectareas",
    "mineria":   "equipos",
    "retail":    "sucursales",
    "salud":     "camas",
    "energia":   "pozos_activos",
}


# ── Wizard ───────────────────────────────────────────────────

class ConfigWizard:
    """
    Guía interactiva para generar el config.json de una empresa nueva.
    """

    def __init__(self, salida_dir: str = "config"):
        self.salida = Path(salida_dir)
        self.salida.mkdir(exist_ok=True)

    def ejecutar(self) -> dict:
        self._encabezado()
        config = {}

        # BLOQUE 1 — Empresa
        print("\n  ── BLOQUE 1 / 3 — Identificación de la empresa ──\n")
        nombre   = self._preguntar("1. Nombre completo de la empresa", "Mi Empresa S.A.")
        sector   = self._preguntar_opcion(
            "2. Sector principal de operación",
            SECTORES_VALIDOS,
        )
        pais     = self._preguntar("3. País de operación", "Argentina")
        email    = self._preguntar("4. Email para alertas críticas", "operaciones@empresa.com")

        # BLOQUE 2 — Operación
        print("\n  ── BLOQUE 2 / 3 — Parámetros operacionales ──\n")
        capacidad = self._preguntar_numero(
            f"5. Capacidad total ({UNIDAD_POR_SECTOR[sector]})", 10
        )
        umbral_op = self._preguntar_numero(
            "6. Umbral de operación normal (% de capacidad, ej: 85)", 85
        )
        frecuencia = self._preguntar_opcion(
            "7. ¿Con qué frecuencia querés el análisis?",
            ["tiempo_real", "diaria", "semanal", "por_turno"],
        )

        # BLOQUE 3 — Riesgo
        print("\n  ── BLOQUE 3 / 3 — Perfil de riesgo ──\n")
        n_riesgos = self._preguntar_numero(
            f"8. ¿Cuántos riesgos querés monitorear? "
            f"(máx {len(RIESGOS_POR_SECTOR[sector])} para {sector})",
            len(RIESGOS_POR_SECTOR[sector]),
        )
        n_riesgos = min(int(n_riesgos), len(RIESGOS_POR_SECTOR[sector]))

        score_alerta  = self._preguntar_numero("9. Score de alerta (0–100)", 50)
        score_critico = self._preguntar_numero("10. Score crítico (0–100)", 75)

        # Construir config
        slug = re.sub(r"[^a-z0-9]", "_", nombre.lower())[:30]
        riesgos_seleccionados = RIESGOS_POR_SECTOR[sector][:int(n_riesgos)]

        config = {
            "empresa": {
                "nombre":       nombre,
                "sector":       sector,
                "pais":         pais,
                "moneda":       "ARS" if pais.lower() in ["argentina", "ar"] else "USD",
                "zona_horaria": "America/Argentina/Buenos_Aires" if pais.lower() in ["argentina", "ar"] else "UTC",
            },
            "unidad_operacional": {
                "nombre":          UNIDAD_POR_SECTOR[sector],
                "kpi_principal":   KPI_POR_SECTOR[sector],
                "capacidad_total": int(capacidad),
                "umbral_critico":  round(umbral_op / 100, 2),
            },
            "riesgos": riesgos_seleccionados,
            "alertas": {
                "canales":                   ["log", "email"],
                "email_destino":             email,
                "frecuencia_chequeo_minutos": self._frecuencia_a_minutos(frecuencia),
                "score_umbral_alerta":        round(score_alerta / 100, 2),
                "score_umbral_critico":       round(score_critico / 100, 2),
            },
            "reporte": {
                "nombre_producto": f"ARGO — {sector.title()}",
                "frecuencia":      frecuencia,
                "incluir_mapa":    True,
                "formato":         "pdf",
            },
            "_meta": {
                "generado_por":    "ARGO Config Wizard v1.0",
                "generado_en":     datetime.now().isoformat(),
            },
        }

        # Guardar
        ruta = self.salida / f"{slug}.json"
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        self._resumen(config, str(ruta))
        return config

    # ── UI helpers ───────────────────────────────────────────

    def _encabezado(self):
        print("\n" + "="*58)
        print("  ARGO — Config Wizard")
        print("  Generá el config de tu empresa en 10 preguntas")
        print("="*58)

    def _preguntar(self, pregunta: str, default: str = "") -> str:
        prompt = f"  {pregunta}"
        if default:
            prompt += f" [{default}]"
        prompt += ": "
        resp = input(prompt).strip()
        return resp if resp else default

    def _preguntar_numero(self, pregunta: str, default: float) -> float:
        while True:
            resp = input(f"  {pregunta} [{default}]: ").strip()
            if not resp:
                return default
            try:
                return float(resp)
            except ValueError:
                print("  Por favor ingresá un número.")

    def _preguntar_opcion(self, pregunta: str, opciones: list) -> str:
        print(f"\n  {pregunta}:")
        for i, op in enumerate(opciones, 1):
            print(f"    {i}. {op}")
        while True:
            resp = input(f"  Elegí un número [1]: ").strip()
            if not resp:
                return opciones[0]
            try:
                idx = int(resp) - 1
                if 0 <= idx < len(opciones):
                    return opciones[idx]
            except ValueError:
                pass
            print(f"  Ingresá un número entre 1 y {len(opciones)}.")

    def _frecuencia_a_minutos(self, freq: str) -> int:
        return {"tiempo_real": 5, "por_turno": 480,
                "diaria": 1440, "semanal": 10080}.get(freq, 60)

    def _resumen(self, config: dict, ruta: str):
        e = config["empresa"]
        u = config["unidad_operacional"]
        print("\n" + "="*58)
        print("  Config generado exitosamente")
        print("="*58)
        print(f"  Empresa:    {e['nombre']}")
        print(f"  Sector:     {e['sector'].upper()}")
        print(f"  Riesgos:    {len(config['riesgos'])} monitoreados")
        print(f"  KPI:        {u['kpi_principal']}")
        print(f"  Alertas a:  {config['alertas']['email_destino']}")
        print(f"\n  Archivo:    {ruta}")
        print(f"\n  Para correr ARGO con esta empresa:")
        print(f"    python main.py --config {ruta}")
        print("="*58 + "\n")


if __name__ == "__main__":
    wizard = ConfigWizard()
    wizard.ejecutar()
