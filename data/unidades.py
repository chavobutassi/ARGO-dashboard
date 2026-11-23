"""
ARGO — Conversión de unidades de granos CBOT.

Yahoo Finance (ZS=F, ZC=F, ZW=F) y stooq cotizan los futuros de CBOT en
CENTAVOS DE USD POR BUSHEL (ej. soja 1225 = USD 12,25/bu), no en USD/tn.

    USD/tn = (centavos/bu / 100) * bushels_por_tonelada

Bushels por tonelada métrica:
    soja  = trigo = 36,7437   (bushel de 60 lb)
    maíz          = 39,3680   (bushel de 56 lb)

Factor centavos/bu → USD/tn:
    soja  = trigo = 0,367437
    maíz          = 0,393680

(Los valores anteriores 0,0367 / 0,0394 estaban 10 veces por debajo: dividían
por 100 dos veces.)
"""

import logging

log = logging.getLogger("argo.unidades")

BUSHELS_POR_TN = {
    "soja":  36.7437,
    "maiz":  39.3680,
    "trigo": 36.7437,
}

# Factor para multiplicar el precio crudo (centavos/bu) y obtener USD/tn
FACTOR_CENTAVOS_BU_A_USD_TN = {g: round(b / 100, 6) for g, b in BUSHELS_POR_TN.items()}

# Rango de plausibilidad (USD/tn) para detectar errores de unidad a futuro.
# Es amplio a propósito: solo atrapa errores de orden de magnitud.
RANGO_PLAUSIBLE_USD_TN = {
    "soja":  (150.0, 900.0),
    "maiz":  (80.0,  500.0),
    "trigo": (100.0, 600.0),
}


def centavos_bu_a_usd_tn(grano: str, centavos_bu: float) -> float:
    """Convierte un precio CBOT en centavos/bushel a USD/tn."""
    return round(centavos_bu * FACTOR_CENTAVOS_BU_A_USD_TN[grano], 2)


def es_plausible(grano: str, usd_tn: float) -> bool:
    """True si el precio en USD/tn cae en un rango razonable para el grano."""
    rango = RANGO_PLAUSIBLE_USD_TN.get(grano)
    if rango is None:
        return True
    ok = rango[0] <= usd_tn <= rango[1]
    if not ok:
        log.warning(
            f"Precio {grano} USD {usd_tn}/tn fuera de rango plausible "
            f"{rango} — posible error de unidad"
        )
    return ok
