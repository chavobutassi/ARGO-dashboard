"""
ARGO — Motor Central
====================
Orquesta el ciclo completo de análisis:
  1. Carga configuración de empresa (config.json)
  2. Recibe lecturas de indicadores
  3. Corre el scorer para cada riesgo
  4. Genera el cuadro de situación operacional
  5. Dispara alertas si corresponde
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.risk_scorer import (
    LecturaIndicador,
    NivelRiesgo,
    ResultadoRiesgo,
    ScorerRiesgo,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ARGO] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M",
)
log = logging.getLogger("argo.engine")


# ──────────────────────────────────────────────
# Estructuras de salida
# ──────────────────────────────────────────────

@dataclass
class CuadroSituacion:
    """
    Equivalente al 'Situation Report' (SITREP) militar.
    Snapshot completo del estado operacional de la empresa.
    """
    empresa: str
    sector: str
    timestamp: datetime
    score_global: float
    nivel_global: NivelRiesgo
    color_global: str
    riesgos: list[ResultadoRiesgo]
    alertas_activas: list[str]
    resumen_ejecutivo: str
    proxima_actualizacion: str = ""

    @property
    def riesgos_criticos(self) -> list[ResultadoRiesgo]:
        return [r for r in self.riesgos if r.nivel == NivelRiesgo.CRITICO]

    @property
    def riesgos_altos(self) -> list[ResultadoRiesgo]:
        return [r for r in self.riesgos if r.nivel == NivelRiesgo.ALTO]

    def to_dict(self) -> dict:
        return {
            "empresa":          self.empresa,
            "sector":           self.sector,
            "timestamp":        self.timestamp.isoformat(),
            "score_global":     self.score_global,
            "nivel_global":     self.nivel_global.value,
            "color_global":     self.color_global,
            "resumen_ejecutivo": self.resumen_ejecutivo,
            "alertas_activas":  self.alertas_activas,
            "riesgos": [
                {
                    "id":           r.id_riesgo,
                    "nombre":       r.nombre,
                    "categoria":    r.categoria,
                    "score":        r.score,
                    "nivel":        r.nivel.value,
                    "color":        r.color,
                    "probabilidad": r.probabilidad_ajustada,
                    "impacto":      r.impacto_ajustado,
                    "indicadores":  r.indicadores_activos,
                    "mensaje":      r.alerta_mensaje,
                }
                for r in sorted(self.riesgos, key=lambda x: x.score, reverse=True)
            ],
        }


# ──────────────────────────────────────────────
# Motor principal
# ──────────────────────────────────────────────

class ArgoEngine:
    """
    Motor central de ARGO.

    Uso básico:
        engine = ArgoEngine("config/transportadora_ejemplo.json")
        lecturas = [
            LecturaIndicador("precipitacion_mm", 45),
            LecturaIndicador("vehiculos_en_taller", 3),
        ]
        sitrep = engine.analizar(lecturas)
        print(sitrep.resumen_ejecutivo)
    """

    VERSION = "1.0.0"

    COLORES_NIVEL = {
        NivelRiesgo.BAJO:    "#639922",
        NivelRiesgo.MEDIO:   "#BA7517",
        NivelRiesgo.ALTO:    "#D85A30",
        NivelRiesgo.CRITICO: "#E24B4A",
    }

    def __init__(self, ruta_config: str, pesos_scorer: dict | None = None):
        self.config      = self._cargar_config(ruta_config)
        self.scorer      = ScorerRiesgo(pesos=pesos_scorer)
        self.empresa     = self.config["empresa"]["nombre"]
        self.sector      = self.config["empresa"]["sector"]
        self.riesgos_cfg = self.config["riesgos"]
        self.alertas_cfg = self.config["alertas"]
        log.info(f"ARGO v{self.VERSION} iniciado — {self.empresa} ({self.sector})")

    # ── Análisis principal ──────────────────────

    def analizar(
        self,
        lecturas: list[LecturaIndicador],
        capacidad_mitigacion: float = 0.5,
    ) -> CuadroSituacion:
        """
        Ejecuta el análisis completo y devuelve el SITREP.

        Args:
            lecturas: valores actuales de los indicadores operacionales
            capacidad_mitigacion: recursos disponibles para mitigar (0.0–1.0)

        Returns:
            CuadroSituacion — el estado operacional completo
        """
        log.info(f"Iniciando análisis — {len(lecturas)} lecturas recibidas")

        resultados = [
            self.scorer.calcular(r, lecturas, capacidad_mitigacion)
            for r in self.riesgos_cfg
        ]

        score_global = self._calcular_score_global(resultados)
        nivel_global = self._clasificar_global(score_global)
        alertas      = self._generar_alertas(resultados, score_global)
        resumen      = self._generar_resumen_ejecutivo(
            resultados, score_global, nivel_global
        )

        sitrep = CuadroSituacion(
            empresa=self.empresa,
            sector=self.sector,
            timestamp=datetime.now(),
            score_global=round(score_global, 3),
            nivel_global=nivel_global,
            color_global=self.COLORES_NIVEL[nivel_global],
            riesgos=resultados,
            alertas_activas=alertas,
            resumen_ejecutivo=resumen,
        )

        log.info(
            f"Análisis completado — Score global: {score_global:.2f} "
            f"[{nivel_global.value}] — Alertas activas: {len(alertas)}"
        )
        return sitrep

    # ── Score global ────────────────────────────

    def _calcular_score_global(self, resultados: list[ResultadoRiesgo]) -> float:
        """
        Score global ponderado.
        Los riesgos críticos tienen triple peso — principio de amenaza prioritaria.
        """
        if not resultados:
            return 0.0

        pesos_nivel = {
            NivelRiesgo.CRITICO: 3.0,
            NivelRiesgo.ALTO:    2.0,
            NivelRiesgo.MEDIO:   1.0,
            NivelRiesgo.BAJO:    0.5,
        }

        suma_ponderada = sum(r.score * pesos_nivel[r.nivel] for r in resultados)
        suma_pesos     = sum(pesos_nivel[r.nivel] for r in resultados)
        return suma_ponderada / suma_pesos

    def _clasificar_global(self, score: float) -> NivelRiesgo:
        if score >= 0.75: return NivelRiesgo.CRITICO
        if score >= 0.55: return NivelRiesgo.ALTO
        if score >= 0.30: return NivelRiesgo.MEDIO
        return NivelRiesgo.BAJO

    # ── Alertas ─────────────────────────────────

    def _generar_alertas(
        self, resultados: list[ResultadoRiesgo], score_global: float
    ) -> list[str]:
        alertas = []
        umbral_alerta   = self.alertas_cfg["score_umbral_alerta"]
        umbral_critico  = self.alertas_cfg["score_umbral_critico"]

        for r in resultados:
            if r.score >= umbral_critico:
                alertas.append(f"🔴 {r.alerta_mensaje}")
            elif r.score >= umbral_alerta:
                alertas.append(f"🟡 {r.alerta_mensaje}")

        if score_global >= umbral_critico:
            alertas.insert(
                0,
                f"⛔ ALERTA GLOBAL: Score operacional crítico ({int(score_global*100)}/100). "
                "Convocar comité de crisis.",
            )
        return alertas

    # ── Resumen ejecutivo ────────────────────────

    def _generar_resumen_ejecutivo(
        self,
        resultados: list[ResultadoRiesgo],
        score: float,
        nivel: NivelRiesgo,
    ) -> str:
        """
        Genera el párrafo de resumen estilo briefing para el nivel ejecutivo.
        """
        criticos = [r for r in resultados if r.nivel == NivelRiesgo.CRITICO]
        altos    = [r for r in resultados if r.nivel == NivelRiesgo.ALTO]
        fecha    = datetime.now().strftime("%d/%m/%Y %H:%M")

        lineas = [
            f"SITREP ARGO — {self.empresa}",
            f"Fecha: {fecha} | Sector: {self.sector.upper()}",
            f"Score operacional global: {int(score*100)}/100 — Nivel: {nivel.value}",
            "",
        ]

        if criticos:
            nombres = ", ".join(r.nombre for r in criticos)
            lineas.append(f"CRÍTICO: {nombres}. Acción inmediata requerida.")
        if altos:
            nombres = ", ".join(r.nombre for r in altos)
            lineas.append(f"ALTO: {nombres}. Revisión y preparación de respuesta.")
        if not criticos and not altos:
            lineas.append("Operación dentro de parámetros normales. Monitoreo de rutina.")

        lineas += [
            "",
            f"Total de riesgos monitoreados: {len(resultados)} | "
            f"Críticos: {len(criticos)} | Altos: {len(altos)}",
        ]
        return "\n".join(lineas)

    # ── Utilidades ───────────────────────────────

    def _cargar_config(self, ruta: str) -> dict:
        path = Path(ruta)
        if not path.exists():
            raise FileNotFoundError(f"Config no encontrado: {ruta}")
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        log.info(f"Config cargado: {path.name}")
        return config

    def exportar_sitrep(self, sitrep: CuadroSituacion, ruta_salida: str) -> None:
        """Guarda el SITREP como JSON para consumo del dashboard o API."""
        path = Path(ruta_salida)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sitrep.to_dict(), f, ensure_ascii=False, indent=2)
        log.info(f"SITREP exportado: {path}")
