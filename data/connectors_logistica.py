"""
ARGO — Conector de Red Logística Agropecuaria
==============================================
Calcula el puerto de exportación óptimo según zona productora,
cultivo y costos de flete actualizados.

Fuentes:
  - Fletes por zona: valores de referencia actualizados (ARS/tn)
  - Puertos: Rosario, Bahía Blanca, Quequén, Villa Constitución
  - Empresas compradoras por puerto

Uso:
    from data.connectors_logistica import ConectorLogistica
    log = ConectorLogistica()
    resultado = log.puerto_optimo("la_pampa", "trigo")
    print(resultado["puerto_recomendado"])  # "Bahía Blanca"
    print(resultado["ahorro_ars_tn"])       # 10000
"""

from datetime import datetime
from typing import Optional


# ── Definición de la red ──────────────────────────────────────

ZONAS = {
    "pampa_humeda":    {"label": "Pampa Húmeda",       "lat": -33.0, "lon": -61.0, "aptitud": "Alta"},
    "santa_fe_centro": {"label": "Santa Fe Centro",     "lat": -31.5, "lon": -61.5, "aptitud": "Alta"},
    "cordoba_sur":     {"label": "Córdoba Sur",         "lat": -33.5, "lon": -63.5, "aptitud": "Alta"},
    "entre_rios":      {"label": "Entre Ríos",          "lat": -32.0, "lon": -58.5, "aptitud": "Alta"},
    "buenos_aires_n":  {"label": "Buenos Aires Norte",  "lat": -35.0, "lon": -60.0, "aptitud": "Alta"},
    "buenos_aires_s":  {"label": "Buenos Aires Sur",    "lat": -38.0, "lon": -60.5, "aptitud": "Media"},
    "la_pampa":        {"label": "La Pampa",            "lat": -36.5, "lon": -64.5, "aptitud": "Media"},
    "chaco":           {"label": "Chaco / NOA",         "lat": -27.0, "lon": -61.0, "aptitud": "Media"},
    "cordoba_norte":   {"label": "Córdoba Norte",       "lat": -30.5, "lon": -63.5, "aptitud": "Media"},
}

PUERTOS = {
    "rosario": {
        "label":      "Puerto Rosario",
        "lat":        -32.95,
        "lon":        -60.64,
        "rio":        "Paraná",
        "empresas":   ["Cargill", "Bunge", "Dreyfus", "AGD", "ACA", "Cofco", "Molinos"],
        "pct_export": 80,
        "cultivos":   ["soja", "maiz", "girasol", "trigo"],
        "descripcion": "Principal complejo exportador de América del Sur. "
                       "80% de las exportaciones de soja y derivados de Argentina.",
    },
    "bahia_blanca": {
        "label":      "Bahía Blanca",
        "lat":        -38.72,
        "lon":        -62.27,
        "rio":        "Océano Atlántico",
        "empresas":   ["Toepfer", "ACA", "Cargill", "Bunge"],
        "pct_export": 12,
        "cultivos":   ["trigo", "girasol", "maiz"],
        "descripcion": "Segundo puerto más importante. Especializado en trigo "
                       "y girasol del sur de Buenos Aires y La Pampa.",
    },
    "quequen": {
        "label":      "Quequén",
        "lat":        -38.59,
        "lon":        -58.71,
        "rio":        "Océano Atlántico",
        "empresas":   ["Bunge", "ACA", "Toepfer"],
        "pct_export": 5,
        "cultivos":   ["trigo", "girasol"],
        "descripcion": "Puerto del sudeste bonaerense. Especializado en trigo "
                       "de la costa atlántica.",
    },
    "villa_constitucion": {
        "label":      "Villa Constitución",
        "lat":        -33.23,
        "lon":        -60.33,
        "rio":        "Paraná",
        "empresas":   ["Dreyfus", "Molinos"],
        "pct_export": 3,
        "cultivos":   ["soja", "maiz"],
        "descripcion": "Terminal sobre el Paraná, aguas arriba de Rosario. "
                       "Complementa el corredor fluvial.",
    },
}

# ── Fletes ARS/tn por zona → puerto (mayo 2026) ───────────────
# Actualizar mensualmente según referencia Bolsa de Cereales
FLETES: dict[str, dict[str, int]] = {
    "pampa_humeda": {
        "rosario":            14_000,
        "bahia_blanca":       24_000,
        "quequen":            28_000,
        "villa_constitucion": 16_000,
    },
    "santa_fe_centro": {
        "rosario":            12_000,
        "bahia_blanca":       30_000,
        "quequen":            36_000,
        "villa_constitucion": 14_000,
    },
    "cordoba_sur": {
        "rosario":            20_000,
        "bahia_blanca":       26_000,
        "quequen":            32_000,
        "villa_constitucion": 22_000,
    },
    "entre_rios": {
        "rosario":            18_000,
        "bahia_blanca":       36_000,
        "quequen":            40_000,
        "villa_constitucion": 20_000,
    },
    "buenos_aires_n": {
        "rosario":            15_000,
        "bahia_blanca":       20_000,
        "quequen":            22_000,
        "villa_constitucion": 17_000,
    },
    "buenos_aires_s": {
        "rosario":            28_000,
        "bahia_blanca":       16_000,
        "quequen":            14_000,
        "villa_constitucion": 30_000,
    },
    "la_pampa": {
        "rosario":            28_000,
        "bahia_blanca":       18_000,
        "quequen":            22_000,
        "villa_constitucion": 30_000,
    },
    "chaco": {
        "rosario":            34_000,
        "bahia_blanca":       50_000,
        "quequen":            55_000,
        "villa_constitucion": 36_000,
    },
    "cordoba_norte": {
        "rosario":            24_000,
        "bahia_blanca":       30_000,
        "quequen":            36_000,
        "villa_constitucion": 26_000,
    },
}

# Cultivos disponibles por puerto (restricciones reales)
CULTIVOS_POR_PUERTO: dict[str, list[str]] = {
    "rosario":            ["soja", "maiz", "trigo", "girasol"],
    "bahia_blanca":       ["trigo", "girasol", "maiz"],
    "quequen":            ["trigo", "girasol"],
    "villa_constitucion": ["soja", "maiz"],
}


class ConectorLogistica:
    """
    Motor de optimización logística agropecuaria.
    Calcula el puerto más conveniente según zona, cultivo y precio neto.
    """

    def __init__(self):
        self.actualizado = "Mayo 2026"

    def fletes_zona(self, zona: str) -> dict:
        """
        Devuelve todos los fletes disponibles para una zona,
        ordenados de menor a mayor costo.
        """
        fletes_raw = FLETES.get(zona, {})
        zona_info  = ZONAS.get(zona, {})

        fletes_ordenados = []
        for puerto_id, costo in sorted(fletes_raw.items(), key=lambda x: x[1]):
            puerto_info = PUERTOS.get(puerto_id, {})
            fletes_ordenados.append({
                "puerto_id":    puerto_id,
                "puerto_label": puerto_info.get("label", puerto_id),
                "flete_ars_tn": costo,
                "empresas":     puerto_info.get("empresas", []),
                "cultivos":     puerto_info.get("cultivos", []),
                "descripcion":  puerto_info.get("descripcion", ""),
                "lat":          puerto_info.get("lat", 0),
                "lon":          puerto_info.get("lon", 0),
            })

        return {
            "zona_id":    zona,
            "zona_label": zona_info.get("label", zona),
            "lat":        zona_info.get("lat", 0),
            "lon":        zona_info.get("lon", 0),
            "fletes":     fletes_ordenados,
            "timestamp":  datetime.now().isoformat(),
            "fuente":     f"Referencia Bolsa de Cereales — {self.actualizado}",
        }

    def puerto_optimo(
        self,
        zona: str,
        cultivo: str = "soja",
        precio_usd_tn: float = 370.0,
        tc_ars_usd: float = 1390.0,
    ) -> dict:
        """
        Calcula el puerto óptimo para maximizar el precio neto recibido.

        precio_usd_tn: precio en destino (Chicago o Rosario)
        tc_ars_usd:    tipo de cambio ARS/USD actual

        Retorna:
            puerto_recomendado: nombre del puerto más conveniente
            precio_neto_ars_tn: precio neto después de descontar flete
            ahorro_ars_tn: ahorro vs el segundo puerto más conveniente
            comparativa: todos los puertos con precio neto calculado
        """
        fletes = FLETES.get(zona, {})
        if not fletes:
            return {"error": f"Zona '{zona}' no encontrada"}

        precio_bruto_ars = precio_usd_tn * tc_ars_usd
        comparativa = []

        for puerto_id, flete in fletes.items():
            # Solo mostrar puertos que aceptan el cultivo
            cultivos_ok = CULTIVOS_POR_PUERTO.get(puerto_id, [])
            acepta = cultivo in cultivos_ok

            precio_neto = precio_bruto_ars - flete if acepta else None
            puerto_info = PUERTOS.get(puerto_id, {})

            comparativa.append({
                "puerto_id":         puerto_id,
                "puerto_label":      puerto_info.get("label", puerto_id),
                "flete_ars_tn":      flete,
                "acepta_cultivo":    acepta,
                "precio_neto_ars":   round(precio_neto, 0) if precio_neto else None,
                "precio_neto_usd":   round(precio_neto / tc_ars_usd, 2) if precio_neto else None,
                "empresas":          puerto_info.get("empresas", []),
                "descripcion":       puerto_info.get("descripcion", ""),
                "lat":               puerto_info.get("lat", 0),
                "lon":               puerto_info.get("lon", 0),
            })

        # Ordenar por precio neto descendente (solo los que aceptan el cultivo)
        aptos = [p for p in comparativa if p["acepta_cultivo"] and p["precio_neto_ars"]]
        aptos.sort(key=lambda x: x["precio_neto_ars"], reverse=True)

        if not aptos:
            return {
                "error": f"Ningún puerto acepta {cultivo} desde {zona}",
                "comparativa": comparativa,
            }

        mejor    = aptos[0]
        segundo  = aptos[1] if len(aptos) > 1 else None
        ahorro   = mejor["precio_neto_ars"] - segundo["precio_neto_ars"] if segundo else 0

        return {
            "zona_id":              zona,
            "zona_label":           ZONAS.get(zona, {}).get("label", zona),
            "cultivo":              cultivo,
            "precio_bruto_ars_tn":  round(precio_bruto_ars, 0),
            "puerto_recomendado":   mejor["puerto_label"],
            "puerto_id":            mejor["puerto_id"],
            "flete_optimo_ars_tn":  mejor["flete_ars_tn"],
            "precio_neto_ars_tn":   mejor["precio_neto_ars"],
            "precio_neto_usd_tn":   mejor["precio_neto_usd"],
            "ahorro_ars_tn":        round(ahorro, 0),
            "empresas_destino":     mejor["empresas"],
            "comparativa":          comparativa,
            "timestamp":            datetime.now().isoformat(),
            "fuente":               f"Referencia Bolsa de Cereales — {self.actualizado}",
        }

    def red_completa(self) -> dict:
        """
        Devuelve la red logística completa para graficar.
        Nodos: zonas productoras + puertos.
        Arcos: conexiones con costo de flete.
        """
        nodos = []
        arcos = []

        # Nodos zonas
        for zona_id, info in ZONAS.items():
            nodos.append({
                "id":    zona_id,
                "label": info["label"],
                "tipo":  "zona",
                "lat":   info["lat"],
                "lon":   info["lon"],
                "color": "#7EC832" if info["aptitud"] == "Alta" else "#F0A030",
            })

        # Nodos puertos
        for puerto_id, info in PUERTOS.items():
            nodos.append({
                "id":    puerto_id,
                "label": info["label"],
                "tipo":  "puerto",
                "lat":   info["lat"],
                "lon":   info["lon"],
                "color": "#4DA3F0",
            })

        # Arcos con costo
        for zona_id, destinos in FLETES.items():
            for puerto_id, flete in destinos.items():
                # Color según costo relativo
                fletes_zona = list(destinos.values())
                min_f = min(fletes_zona)
                max_f = max(fletes_zona)
                ratio = (flete - min_f) / (max_f - min_f) if max_f > min_f else 0

                color = "#7EC832" if ratio < 0.33 else "#F0A030" if ratio < 0.66 else "#FF5F5E"

                arcos.append({
                    "origen":       zona_id,
                    "destino":      puerto_id,
                    "flete_ars_tn": flete,
                    "color":        color,
                    "optimo":       flete == min_f,
                })

        return {
            "nodos":     nodos,
            "arcos":     arcos,
            "timestamp": datetime.now().isoformat(),
        }


# ── Demo ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  ARGO — Red Logística Agropecuaria\n")
    log = ConectorLogistica()

    zonas_demo = ["pampa_humeda", "la_pampa", "buenos_aires_s", "cordoba_sur"]

    for zona in zonas_demo:
        r = log.puerto_optimo(zona, "soja", precio_usd_tn=370.0, tc_ars_usd=1395.0)
        print(f"  {r['zona_label']}")
        print(f"    Puerto óptimo: {r['puerto_recomendado']}")
        print(f"    Flete:         ${r['flete_optimo_ars_tn']:,}/tn")
        print(f"    Precio neto:   ${r['precio_neto_ars_tn']:,.0f}/tn "
              f"(USD {r['precio_neto_usd_tn']:.2f})")
        if r["ahorro_ars_tn"] > 0:
            print(f"    Ahorro vs 2°:  ${r['ahorro_ars_tn']:,}/tn")
        print()
