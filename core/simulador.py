"""
ARGO — Simulador de Escenarios (Monte Carlo)
=============================================
Responde la pregunta clave del análisis operacional:
  "¿Qué pasa si varios riesgos se activan al mismo tiempo?"

Metodología:
  - N simulaciones (default 10.000)
  - En cada simulación, cada riesgo tiene P% de activarse
  - Cuando se activa, su score sube entre umbral_alerta y 1.0
  - Se calcula el score global resultante
  - Se construye la distribución de resultados

Salida:
  - Percentiles clave (P10, P50, P90, P95, P99)
  - Probabilidad de superar cada nivel de alerta
  - Escenario más probable vs escenario catastrófico
  - Recomendación táctica
"""

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.risk_scorer import NivelRiesgo, ScorerRiesgo, LecturaIndicador, COLORES_NIVEL


@dataclass
class ResultadoSimulacion:
    """Resultado completo del análisis Monte Carlo."""
    n_simulaciones: int
    scores: list[float]

    # Percentiles
    p10: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0

    # Probabilidades de superar cada nivel
    prob_bajo:    float = 0.0
    prob_medio:   float = 0.0
    prob_alto:    float = 0.0
    prob_critico: float = 0.0

    # Escenarios
    escenario_optimista:  float = 0.0
    escenario_esperado:   float = 0.0
    escenario_pesimista:  float = 0.0
    escenario_catastrofe: float = 0.0

    recomendacion: str = ""

    def __post_init__(self):
        arr = np.array(self.scores)
        self.p10 = float(np.percentile(arr, 10))
        self.p25 = float(np.percentile(arr, 25))
        self.p50 = float(np.percentile(arr, 50))
        self.p75 = float(np.percentile(arr, 75))
        self.p90 = float(np.percentile(arr, 90))
        self.p95 = float(np.percentile(arr, 95))
        self.p99 = float(np.percentile(arr, 99))

        self.prob_bajo    = float(np.mean(arr < 0.30))
        self.prob_medio   = float(np.mean((arr >= 0.30) & (arr < 0.55)))
        self.prob_alto    = float(np.mean((arr >= 0.55) & (arr < 0.75)))
        self.prob_critico = float(np.mean(arr >= 0.75))

        self.escenario_optimista  = self.p10
        self.escenario_esperado   = self.p50
        self.escenario_pesimista  = self.p90
        self.escenario_catastrofe = self.p99

        self.recomendacion = self._generar_recomendacion()

    def _generar_recomendacion(self) -> str:
        if self.prob_critico > 0.20:
            return (
                f"ALERTA ESTRATÉGICA: {int(self.prob_critico*100)}% de probabilidad de "
                f"alcanzar nivel CRÍTICO. Activar plan de contingencia preventivo. "
                f"Escenario catastrófico implica score {int(self.p99*100)}/100."
            )
        elif self.prob_alto > 0.35:
            return (
                f"PRECAUCIÓN: {int(self.prob_alto*100)}% de probabilidad de nivel ALTO. "
                f"Reforzar monitoreo y preparar respuesta. Score esperado: {int(self.p50*100)}/100."
            )
        elif self.p90 < 0.55:
            return (
                f"SITUACIÓN CONTROLADA: Incluso en el peor 10% de escenarios, "
                f"el score se mantiene en {int(self.p90*100)}/100. Monitoreo rutinario suficiente."
            )
        else:
            return (
                f"MONITOREO REFORZADO: Score esperado {int(self.p50*100)}/100. "
                f"Escenario adverso puede alcanzar {int(self.p90*100)}/100. Revisar mitigaciones."
            )

    def imprimir_reporte(self):
        print("\n" + "="*58)
        print("  ARGO — ANÁLISIS MONTE CARLO")
        print("="*58)
        print(f"  Simulaciones ejecutadas: {self.n_simulaciones:,}")
        print()
        print("  DISTRIBUCIÓN DE SCORES GLOBALES")
        print(f"  {'Optimista  (P10):':<22} {int(self.p10*100):>3}/100")
        print(f"  {'Esperado   (P50):':<22} {int(self.p50*100):>3}/100")
        print(f"  {'Adverso    (P90):':<22} {int(self.p90*100):>3}/100")
        print(f"  {'Catástrofe (P99):':<22} {int(self.p99*100):>3}/100")
        print()
        print("  PROBABILIDAD POR NIVEL DE ALERTA")
        print(f"  {'BAJO    (< 30):':<22} {int(self.prob_bajo*100):>3}%")
        print(f"  {'MEDIO   (30–55):':<22} {int(self.prob_medio*100):>3}%")
        print(f"  {'ALTO    (55–75):':<22} {int(self.prob_alto*100):>3}%")
        print(f"  {'CRÍTICO (> 75):':<22} {int(self.prob_critico*100):>3}%")
        print()
        print(f"  RECOMENDACIÓN TÁCTICA:")
        for linea in _wrap(self.recomendacion, 54):
            print(f"  {linea}")
        print("="*58)

    def to_dict(self) -> dict:
        return {
            "n_simulaciones": self.n_simulaciones,
            "percentiles": {
                "p10": round(self.p10, 3),
                "p25": round(self.p25, 3),
                "p50": round(self.p50, 3),
                "p75": round(self.p75, 3),
                "p90": round(self.p90, 3),
                "p95": round(self.p95, 3),
                "p99": round(self.p99, 3),
            },
            "probabilidades": {
                "bajo":    round(self.prob_bajo, 3),
                "medio":   round(self.prob_medio, 3),
                "alto":    round(self.prob_alto, 3),
                "critico": round(self.prob_critico, 3),
            },
            "escenarios": {
                "optimista":  round(self.escenario_optimista, 3),
                "esperado":   round(self.escenario_esperado, 3),
                "pesimista":  round(self.escenario_pesimista, 3),
                "catastrofe": round(self.escenario_catastrofe, 3),
            },
            "recomendacion": self.recomendacion,
        }


class SimuladorMonteCarlo:
    """
    Simula N escenarios aleatorios para una empresa y calcula
    la distribución de riesgos operacionales resultantes.
    """

    PESOS_NIVEL = {
        NivelRiesgo.CRITICO: 3.0,
        NivelRiesgo.ALTO:    2.0,
        NivelRiesgo.MEDIO:   1.0,
        NivelRiesgo.BAJO:    0.5,
    }

    def __init__(self, ruta_config: str, seed: Optional[int] = None):
        path = Path(ruta_config)
        with open(path, encoding="utf-8") as f:
            self.config = json.load(f)
        self.empresa  = self.config["empresa"]["nombre"]
        self.riesgos  = self.config["riesgos"]
        self.scorer   = ScorerRiesgo()
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

    def simular(
        self,
        lecturas_base: list[LecturaIndicador],
        n_simulaciones: int = 10_000,
        capacidad_mitigacion_media: float = 0.5,
        varianza_mitigacion: float = 0.15,
    ) -> ResultadoSimulacion:
        """
        Ejecuta N simulaciones Monte Carlo.

        En cada simulación:
          - Cada riesgo tiene P% de "activarse" (score sube)
          - La capacidad de mitigación varía aleatoriamente
          - Se calcula el score global resultante

        Args:
            lecturas_base: valores actuales de indicadores (punto de partida)
            n_simulaciones: número de escenarios a simular
            capacidad_mitigacion_media: promedio de recursos disponibles
            varianza_mitigacion: cuánto varía la capacidad entre escenarios
        """
        scores_globales = []

        for _ in range(n_simulaciones):
            # Capacidad de mitigación varía por escenario (recursos no siempre disponibles)
            cap_mit = float(np.clip(
                np.random.normal(capacidad_mitigacion_media, varianza_mitigacion),
                0.0, 1.0
            ))

            # Simular activación de riesgos
            lecturas_sim = self._perturbar_lecturas(lecturas_base)
            resultados   = [
                self.scorer.calcular(r, lecturas_sim, cap_mit)
                for r in self.riesgos
            ]

            score_global = self._score_global(resultados)
            scores_globales.append(score_global)

        return ResultadoSimulacion(
            n_simulaciones=n_simulaciones,
            scores=scores_globales,
        )

    def simular_escenario_especifico(
        self,
        lecturas_base: list[LecturaIndicador],
        riesgos_activados: list[str],
        intensidad: float = 0.85,
    ) -> dict:
        """
        Simula un escenario donde ciertos riesgos se activan con máxima intensidad.
        Útil para responder: "¿Qué pasa si fallan simultáneamente X e Y?"

        Args:
            riesgos_activados: lista de IDs de riesgo a forzar (ej: ["RLOG-001", "RLOG-002"])
            intensidad: qué tan fuerte se activan (0.0–1.0)
        """
        lecturas_forzadas = self._forzar_activacion(
            lecturas_base, riesgos_activados, intensidad
        )
        resultados = [
            self.scorer.calcular(r, lecturas_forzadas, capacidad_mitigacion=0.25)
            for r in self.riesgos
        ]
        score = self._score_global(resultados)
        nivel = self._clasificar(score)

        return {
            "escenario": "Activación simultánea forzada",
            "riesgos_activados": riesgos_activados,
            "score_resultante": round(score, 3),
            "nivel": nivel.value,
            "ranking": sorted(
                [{"id": r.id_riesgo, "nombre": r.nombre, "score": r.score, "nivel": r.nivel.value}
                 for r in resultados],
                key=lambda x: x["score"], reverse=True
            ),
        }

    # ── Utilidades internas ─────────────────────────────────

    def _perturbar_lecturas(
        self, lecturas: list[LecturaIndicador]
    ) -> list[LecturaIndicador]:
        """Añade ruido gaussiano a cada lectura para simular variabilidad real."""
        perturbadas = []
        for l in lecturas:
            ruido = np.random.normal(0, abs(l.valor) * 0.15 + 0.01)
            nuevo_val = max(0.0, l.valor + ruido)
            perturbadas.append(LecturaIndicador(l.nombre, nuevo_val, fuente="simulacion"))
        return perturbadas

    def _forzar_activacion(
        self,
        lecturas: list[LecturaIndicador],
        ids_activar: list[str],
        intensidad: float,
    ) -> list[LecturaIndicador]:
        """
        Fuerza valores de indicadores al extremo crítico para los riesgos seleccionados.
        """
        lecturas_mod = list(lecturas)
        riesgos_map  = {r["id"]: r for r in self.riesgos}

        for rid in ids_activar:
            cfg = riesgos_map.get(rid)
            if not cfg:
                continue
            for indicador, niveles in cfg.get("umbrales", {}).items():
                critico = niveles.get("critico", 0)
                alerta  = niveles.get("alerta", 0)
                # Forzar el valor al lado más crítico del umbral
                if critico < alerta:
                    valor_forzado = critico * (1 - intensidad * 0.3)
                else:
                    valor_forzado = critico * (1 + intensidad * 0.3)

                # Reemplazar o agregar la lectura
                lecturas_mod = [
                    LecturaIndicador(indicador, valor_forzado, fuente="forzado")
                    if l.nombre == indicador else l
                    for l in lecturas_mod
                ]
                if not any(l.nombre == indicador for l in lecturas_mod):
                    lecturas_mod.append(
                        LecturaIndicador(indicador, valor_forzado, fuente="forzado")
                    )
        return lecturas_mod

    def _score_global(self, resultados) -> float:
        if not resultados:
            return 0.0
        suma = sum(r.score * self.PESOS_NIVEL[r.nivel] for r in resultados)
        pesos = sum(self.PESOS_NIVEL[r.nivel] for r in resultados)
        return suma / pesos

    def _clasificar(self, score: float) -> NivelRiesgo:
        if score >= 0.75: return NivelRiesgo.CRITICO
        if score >= 0.55: return NivelRiesgo.ALTO
        if score >= 0.30: return NivelRiesgo.MEDIO
        return NivelRiesgo.BAJO


def _wrap(texto: str, ancho: int) -> list[str]:
    palabras = texto.split()
    lineas, actual = [], ""
    for p in palabras:
        if len(actual) + len(p) + 1 <= ancho:
            actual += (" " if actual else "") + p
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas


# ── Demo ────────────────────────────────────────────────────
if __name__ == "__main__":
    from core.risk_scorer import LecturaIndicador

    print("\n  ARGO — Simulador Monte Carlo")
    print("  Empresa: Transportadora del Sur S.A.\n")

    sim = SimuladorMonteCarlo("config/transportadora_ejemplo.json", seed=42)

    lecturas = [
        LecturaIndicador("precipitacion_mm",         65.0),
        LecturaIndicador("viento_kmh",                55.0),
        LecturaIndicador("precio_gasoil_ars",       1350.0),
        LecturaIndicador("vehiculos_en_taller",        3.0),
        LecturaIndicador("conductores_sin_reemplazo",  1.0),
    ]

    # Análisis general
    resultado = sim.simular(lecturas, n_simulaciones=10_000)
    resultado.imprimir_reporte()

    # Escenario específico: clima extremo + combustible al mismo tiempo
    print("\n  ESCENARIO CRÍTICO: ¿Qué pasa si falla el clima Y el combustible?")
    esc = sim.simular_escenario_especifico(
        lecturas,
        riesgos_activados=["RLOG-001", "RLOG-002"],
        intensidad=0.9,
    )
    print(f"  Score resultante: {int(esc['score_resultante']*100)}/100 — {esc['nivel']}")
    print("  Ranking en ese escenario:")
    for r in esc["ranking"]:
        print(f"    [{r['nivel']:8s}] {int(r['score']*100):3d}/100  {r['nombre']}")
