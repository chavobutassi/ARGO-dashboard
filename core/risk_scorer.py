"""
ARGO — Motor de Scoring de Riesgo Operacional
==============================================
Metodología basada en evaluación táctica de amenazas:
  - Probabilidad de ocurrencia (P)
  - Impacto sobre la operación (I)
  - Velocidad de materialización (V)
  - Capacidad de mitigación propia (M)

Score final = f(P, I, V, M) normalizado [0.0 — 1.0]
  0.0 — 0.30 → BAJO     (verde)
  0.30 — 0.55 → MEDIO   (amarillo)
  0.55 — 0.75 → ALTO    (naranja)
  0.75 — 1.00 → CRÍTICO (rojo)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class NivelRiesgo(Enum):
    BAJO     = "BAJO"
    MEDIO    = "MEDIO"
    ALTO     = "ALTO"
    CRITICO  = "CRITICO"


COLORES_NIVEL = {
    NivelRiesgo.BAJO:    "#639922",
    NivelRiesgo.MEDIO:   "#BA7517",
    NivelRiesgo.ALTO:    "#D85A30",
    NivelRiesgo.CRITICO: "#E24B4A",
}


@dataclass
class LecturaIndicador:
    """Valor actual de un indicador operacional."""
    nombre: str
    valor: float
    timestamp: datetime = field(default_factory=datetime.now)
    fuente: str = "manual"


@dataclass
class ResultadoRiesgo:
    """Resultado del scoring para un riesgo individual."""
    id_riesgo: str
    nombre: str
    categoria: str
    score: float                  # 0.0 – 1.0
    nivel: NivelRiesgo
    probabilidad_ajustada: float
    impacto_ajustado: float
    indicadores_activos: list[str]
    alerta_mensaje: str
    timestamp: datetime = field(default_factory=datetime.now)
    color: str = ""

    def __post_init__(self):
        self.color = COLORES_NIVEL[self.nivel]


class ScorerRiesgo:
    """
    Motor de scoring individual por riesgo.

    Fórmula táctica:
        score = (P * peso_P) + (I * peso_I) + (V * peso_V) - (M * peso_M)
        Normalizado y clampado entre 0.0 y 1.0.

    Pesos por defecto (calibrados para operaciones):
        P = 0.35  — probabilidad es el driver principal
        I = 0.40  — impacto pesa más en decisión ejecutiva
        V = 0.15  — velocidad afecta tiempo de reacción
        M = 0.10  — capacidad de mitigación reduce el score
    """

    PESOS_DEFAULT = {"P": 0.35, "I": 0.40, "V": 0.15, "M": 0.10}
    ESCALA_NIVEL = [
        (0.75, NivelRiesgo.CRITICO),
        (0.55, NivelRiesgo.ALTO),
        (0.30, NivelRiesgo.MEDIO),
        (0.00, NivelRiesgo.BAJO),
    ]

    def __init__(self, pesos: dict | None = None):
        self.pesos = pesos or self.PESOS_DEFAULT

    def calcular(
        self,
        config_riesgo: dict,
        lecturas: list[LecturaIndicador],
        capacidad_mitigacion: float = 0.5,
    ) -> ResultadoRiesgo:
        """
        Calcula el score de un riesgo dado su configuración y lecturas actuales.

        Args:
            config_riesgo: bloque de riesgo del config.json de la empresa
            lecturas: valores actuales de los indicadores
            capacidad_mitigacion: 0.0 (sin recursos) — 1.0 (recursos completos)

        Returns:
            ResultadoRiesgo con score, nivel y mensaje de alerta
        """
        p_ajustada, indicadores_activos = self._ajustar_probabilidad(
            config_riesgo, lecturas
        )
        i_ajustado = self._ajustar_impacto(config_riesgo, lecturas)
        velocidad   = self._estimar_velocidad(config_riesgo["categoria"])

        score_bruto = (
            p_ajustada          * self.pesos["P"]
            + i_ajustado        * self.pesos["I"]
            + velocidad         * self.pesos["V"]
            - capacidad_mitigacion * self.pesos["M"]
        )
        score = max(0.0, min(1.0, score_bruto))
        nivel = self._clasificar(score)

        return ResultadoRiesgo(
            id_riesgo=config_riesgo["id"],
            nombre=config_riesgo["nombre"],
            categoria=config_riesgo["categoria"],
            score=round(score, 3),
            nivel=nivel,
            probabilidad_ajustada=round(p_ajustada, 3),
            impacto_ajustado=round(i_ajustado, 3),
            indicadores_activos=indicadores_activos,
            alerta_mensaje=self._generar_mensaje(
                config_riesgo["nombre"], score, nivel, indicadores_activos
            ),
        )

    def _ajustar_probabilidad(
        self, config: dict, lecturas: list[LecturaIndicador]
    ) -> tuple[float, list[str]]:
        """
        Ajusta la probabilidad base según los umbrales de los indicadores.
        Si un indicador supera umbral crítico → +0.25
        Si supera umbral de alerta          → +0.12
        """
        p = config["probabilidad_base"]
        umbrales = config.get("umbrales", {})
        activos = []

        lecturas_map = {l.nombre: l.valor for l in lecturas}

        for indicador, niveles in umbrales.items():
            valor = lecturas_map.get(indicador)
            if valor is None:
                continue

            critico = niveles.get("critico")
            alerta  = niveles.get("alerta")

            # Para indicadores donde MENOR valor = más riesgo (temperatura, precipitacion)
            if critico is not None and alerta is not None:
                if critico < alerta:
                    # Escala invertida (ej: temperatura_minima_c — cuanto más bajo, peor)
                    if valor <= critico:
                        p = min(1.0, p + 0.25)
                        activos.append(f"{indicador}={valor} [CRÍTICO]")
                    elif valor <= alerta:
                        p = min(1.0, p + 0.12)
                        activos.append(f"{indicador}={valor} [ALERTA]")
                else:
                    # Escala normal (ej: precipitacion_mm — cuanto más alto, peor)
                    if valor >= critico:
                        p = min(1.0, p + 0.25)
                        activos.append(f"{indicador}={valor} [CRÍTICO]")
                    elif valor >= alerta:
                        p = min(1.0, p + 0.12)
                        activos.append(f"{indicador}={valor} [ALERTA]")

        return p, activos

    def _ajustar_impacto(
        self, config: dict, lecturas: list[LecturaIndicador]
    ) -> float:
        """Impacto base ajustado levemente por cantidad de indicadores en alerta."""
        n_activos = len(self._ajustar_probabilidad(config, lecturas)[1])
        ajuste = min(0.15, n_activos * 0.05)
        return min(1.0, config["impacto_base"] + ajuste)

    def _estimar_velocidad(self, categoria: str) -> float:
        """
        Velocidad de materialización por categoría.
        Cuanto más rápido se materializa un riesgo, menos tiempo hay para reaccionar.
        """
        velocidades = {
            "climatico":      0.85,  # Rápido — fenómeno natural inmediato
            "operacional":    0.70,  # Moderado-rápido
            "abastecimiento": 0.55,  # Moderado
            "mercado":        0.45,  # Gradual
            "personas":       0.35,  # Lento, predecible
            "externo":        0.65,
        }
        return velocidades.get(categoria, 0.50)

    def _clasificar(self, score: float) -> NivelRiesgo:
        for umbral, nivel in self.ESCALA_NIVEL:
            if score >= umbral:
                return nivel
        return NivelRiesgo.BAJO

    def _generar_mensaje(
        self,
        nombre: str,
        score: float,
        nivel: NivelRiesgo,
        indicadores: list[str],
    ) -> str:
        """
        Genera alerta en lenguaje natural — estilo briefing operacional.
        """
        pct = int(score * 100)
        base = f"[{nivel.value}] {nombre} — índice de riesgo: {pct}/100."

        if not indicadores:
            return base + " Sin indicadores activos fuera de umbral."

        ind_texto = ", ".join(i.split("=")[0] for i in indicadores)
        detalle = f" Indicadores activados: {ind_texto}."

        acciones = {
            NivelRiesgo.CRITICO: " Acción inmediata requerida. Activar plan de contingencia.",
            NivelRiesgo.ALTO:    " Revisar plan de mitigación. Escalar a supervisión.",
            NivelRiesgo.MEDIO:   " Monitoreo reforzado. Preparar respuesta.",
            NivelRiesgo.BAJO:    " Seguimiento rutinario.",
        }
        return base + detalle + acciones[nivel]
