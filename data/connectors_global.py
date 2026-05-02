"""
ARGO — Conector de Contexto Global Agropecuario
================================================
Fuentes 100% gratuitas, sin API key:

  - FAOSTAT API     → producción, exportaciones y superficie por país
  - USDA PSD API    → oferta y demanda mundial (WASDE equivalente)
  - World Bank API  → indicadores agrícolas por país
  - Yahoo Finance   → precios CBOT de referencia global

Panel de contexto global: no depende de ninguna empresa.
Muestra el top 10 mundial de productores y el posicionamiento
de Argentina en el mercado global de granos.

Uso básico:
    from data.connectors_global import ConectorGlobal
    g = ConectorGlobal()
    ctx = g.contexto_global()
    ranking = g.ranking_productores("soja")
    señales = g.señales_mercado_mundial()
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("argo.global")

TIMEOUT = 12
HEADERS = {"User-Agent": "ARGO-GlobalConnector/1.0"}

# ── Códigos FAO por cultivo ───────────────────────────────────
FAO_CULTIVOS = {
    "soja":   "236",   # Soybeans
    "maiz":   "56",    # Maize
    "trigo":  "15",    # Wheat
    "arroz":  "27",    # Rice paddy
    "girasol":"267",   # Sunflower seed
}

# ── Códigos ISO3 países clave ─────────────────────────────────
PAISES_CLAVE = {
    "ARG": "Argentina",
    "BRA": "Brasil",
    "USA": "Estados Unidos",
    "CHN": "China",
    "IND": "India",
    "RUS": "Rusia",
    "CAN": "Canadá",
    "AUS": "Australia",
    "UKR": "Ucrania",
    "FRA": "Francia",
    "DEU": "Alemania",
    "PAR": "Paraguay",
    "URY": "Uruguay",
}

# ── Códigos World Bank indicadores agrícolas ──────────────────
WB_INDICADORES = {
    "AG.LND.AGRI.ZS":  "tierra_agricola_pct",      # % tierra agrícola
    "AG.YLD.CREL.KG":  "rendimiento_cereales_kg_ha", # Rendimiento cereales kg/ha
    "AG.PRD.FOOD.XD":  "indice_produccion_alimentos", # Índice producción alimentos
    "TX.VAL.AGRI.ZS.UN": "exportaciones_agro_pct",  # % exportaciones agro
}


class ConectorGlobal:
    """
    Conector de contexto global agropecuario.
    Provee el marco mundial para interpretar datos locales de Argentina.
    """

    def __init__(self, cache_minutos: int = 60):
        self._cache: dict = {}
        self._cache_minutos = cache_minutos

    # ── TOP 10 PRODUCTORES — FAOSTAT ─────────────────────────

    def ranking_productores(self, cultivo: str = "soja", año: int = 2022) -> list[dict]:
        """
        Top 10 países productores de un cultivo según FAO.
        cultivo: "soja" | "maiz" | "trigo" | "arroz" | "girasol"
        """
        clave = f"fao_ranking_{cultivo}_{año}"
        if cached := self._from_cache(clave):
            return cached

        codigo = FAO_CULTIVOS.get(cultivo, "236")

        try:
            url = (
                "https://faostat.fao.org/api/v1/en/data/QCL"
                f"?item={codigo}"
                f"&year={año}"
                "&element=5510"
                "&area_group=countries"
                "&output_type=objects"
            )
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            raw = resp.json().get("data", [])

            # Ordenar por producción descendente
            datos = []
            for item in raw:
                try:
                    pais   = item.get("Area", "")
                    valor  = float(item.get("Value", 0))
                    if valor > 0:
                        datos.append({
                            "pais":           pais,
                            "produccion_tn":  valor,
                            "produccion_mm":  round(valor / 1_000_000, 2),
                        })
                except (ValueError, TypeError):
                    continue

            datos.sort(key=lambda x: x["produccion_tn"], reverse=True)
            top10 = datos[:10]

            # Agregar posición y % del total
            total = sum(d["produccion_tn"] for d in top10)
            for i, d in enumerate(top10):
                d["posicion"]   = i + 1
                d["pct_global"] = round((d["produccion_tn"] / total) * 100, 1) if total else 0
                d["es_argentina"] = "Argentina" in d["pais"]

            self._to_cache(clave, top10)
            log.info(f"FAO ranking OK — {cultivo}: {len(top10)} países")
            return top10

        except Exception as e:
            log.warning(f"FAO ranking no disponible ({e}) — usando fallback")
            return self._fallback_ranking(cultivo)

    # ── OFERTA Y DEMANDA MUNDIAL — USDA PSD ──────────────────

    def oferta_demanda_usda(self, cultivo: str = "soja") -> dict:
        """
        Datos de oferta y demanda mundial del USDA (Public Dataset).
        Incluye producción global, stocks y comercio mundial.
        """
        clave = f"usda_psd_{cultivo}"
        if cached := self._from_cache(clave):
            return cached

        # Códigos USDA por cultivo
        usda_commodities = {
            "soja":  "2222000",
            "maiz":  "0440100",
            "trigo": "0410000",
        }
        commodity_code = usda_commodities.get(cultivo, "2222000")

        try:
            url = (
                "https://apps.fas.usda.gov/psdonline/api/psd/commodity"
                f"/{commodity_code}"
            )
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            raw = resp.json()

            # Tomar el año más reciente
            años = sorted(set(r.get("marketYear", 0) for r in raw), reverse=True)
            año_actual = años[0] if años else datetime.now().year

            datos_año = [r for r in raw if r.get("marketYear") == año_actual]

            # Agregar atributos clave
            atributos = {}
            nombres_attr = {
                "Production":           "produccion_global_mm_tn",
                "TotalSupply":          "oferta_total_mm_tn",
                "Exports":              "exportaciones_mm_tn",
                "Imports":              "importaciones_mm_tn",
                "EndingStocks":         "stocks_finales_mm_tn",
                "StocksToUsage":        "ratio_stocks_uso_pct",
            }
            for r in datos_año:
                attr = r.get("attributeDescription", "")
                val  = r.get("value", 0)
                if attr in nombres_attr and val:
                    atributos[nombres_attr[attr]] = round(float(val) / 1000, 2)

            resultado = {
                "cultivo":     cultivo,
                "año":         año_actual,
                "fuente":      "USDA PSD (Public Sector Data)",
                "timestamp":   datetime.now().isoformat(),
                **atributos,
            }

            # Señal de mercado basada en ratio stocks/uso
            ratio = atributos.get("ratio_stocks_uso_pct", 0)
            if ratio < 15:
                resultado["señal_stocks"] = "AJUSTADO"
                resultado["señal_color"]  = "#E24B4A"
                resultado["señal_desc"]   = "Stocks mundiales bajos — presión alcista en precios"
            elif ratio < 25:
                resultado["señal_stocks"] = "MODERADO"
                resultado["señal_color"]  = "#BA7517"
                resultado["señal_desc"]   = "Stocks en rango normal — mercado equilibrado"
            else:
                resultado["señal_stocks"] = "HOLGADO"
                resultado["señal_color"]  = "#639922"
                resultado["señal_desc"]   = "Stocks abundantes — presión bajista en precios"

            self._to_cache(clave, resultado)
            log.info(f"USDA PSD OK — {cultivo} {año_actual}: stocks ratio={ratio}%")
            return resultado

        except Exception as e:
            log.warning(f"USDA PSD no disponible ({e}) — usando fallback")
            return self._fallback_usda(cultivo)

    # ── INDICADORES WORLD BANK ────────────────────────────────

    def indicadores_world_bank(self, paises: list[str] | None = None) -> dict:
        """
        Indicadores agrícolas clave por país desde World Bank Open Data.
        Retorna datos del año más reciente disponible.
        """
        clave = "world_bank_agro"
        if cached := self._from_cache(clave):
            return cached

        if paises is None:
            paises = ["ARG", "BRA", "USA", "CHN", "IND"]

        resultado: dict = {"timestamp": datetime.now().isoformat(), "paises": {}}

        for iso3 in paises:
            nombre = PAISES_CLAVE.get(iso3, iso3)
            resultado["paises"][iso3] = {"nombre": nombre}

            for indicador, campo in WB_INDICADORES.items():
                try:
                    url = (
                        f"https://api.worldbank.org/v2/country/{iso3}"
                        f"/indicator/{indicador}"
                        "?format=json&mrv=1&per_page=1"
                    )
                    resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
                    resp.raise_for_status()
                    data = resp.json()
                    if len(data) > 1 and data[1]:
                        valor = data[1][0].get("value")
                        año   = data[1][0].get("date")
                        if valor is not None:
                            resultado["paises"][iso3][campo] = round(float(valor), 2)
                            resultado["paises"][iso3]["año_dato"] = año
                except Exception:
                    pass

        resultado["fuente"] = "World Bank Open Data"
        self._to_cache(clave, resultado)
        return resultado

    # ── PRECIOS GLOBALES CBOT ─────────────────────────────────

    def precios_globales_cbot(self) -> dict:
        """
        Precios de referencia global desde CBOT (Chicago) vía Yahoo Finance.
        Incluye variación diaria y tendencia.
        """
        clave = "cbot_global"
        if cached := self._from_cache(clave):
            return cached

        simbolos = {
            "ZS=F": ("soja",   0.0367, "USD/tn"),
            "ZC=F": ("maiz",   0.0394, "USD/tn"),
            "ZW=F": ("trigo",  0.0367, "USD/tn"),
            "CL=F": ("wti",    1.0,    "USD/barril"),
            "BZ=F": ("brent",  1.0,    "USD/barril"),
        }

        datos: dict = {"timestamp": datetime.now().isoformat()}

        for simbolo, (nombre, factor, unidad) in simbolos.items():
            try:
                url = (
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
                    "?interval=1d&range=5d"
                )
                resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
                resp.raise_for_status()
                meta   = resp.json()["chart"]["result"][0]["meta"]
                precio = meta["regularMarketPrice"] * factor
                prev   = meta.get("chartPreviousClose", meta["regularMarketPrice"]) * factor
                cambio = round(precio - prev, 2)
                cambio_pct = round((cambio / prev) * 100, 2) if prev else 0

                datos[nombre] = {
                    "precio":      round(precio, 2),
                    "cambio":      cambio,
                    "cambio_pct":  cambio_pct,
                    "unidad":      unidad,
                    "tendencia":   "↑" if cambio > 0 else "↓" if cambio < 0 else "→",
                    "color":       "#639922" if cambio > 0 else "#E24B4A" if cambio < 0 else "#BA7517",
                }
                log.info(f"CBOT {nombre}: {round(precio,2)} {unidad} ({cambio_pct:+.1f}%)")
            except Exception as e:
                log.warning(f"CBOT {nombre} no disponible ({e})")

        datos["fuente"] = "Yahoo Finance / CBOT Chicago"
        self._to_cache(clave, datos)
        return datos

    # ── SEÑALES DE MERCADO MUNDIAL ────────────────────────────

    def señales_mercado_mundial(self) -> list[dict]:
        """
        Cruza datos globales y genera señales interpretadas para el usuario.
        Retorna lista de señales ordenadas por impacto en Argentina.
        """
        señales = []

        try:
            precios = self.precios_globales_cbot()
            usda_soja = self.oferta_demanda_usda("soja")
            usda_maiz = self.oferta_demanda_usda("maiz")

            # Señal 1: Tendencia de precio soja Chicago
            soja = precios.get("soja", {})
            if soja:
                cpct = soja.get("cambio_pct", 0)
                if abs(cpct) >= 1.5:
                    señales.append({
                        "titulo": f"Soja Chicago {soja['tendencia']} {abs(cpct):.1f}%",
                        "descripcion": (
                            f"Precio de referencia global en USD {soja['precio']}/tn. "
                            f"{'Movimiento alcista favorece exportaciones argentinas.'  if cpct > 0 else 'Caída impacta precio en Rosario.'}"
                        ),
                        "impacto":    "ALTO",
                        "color":      soja["color"],
                        "categoria":  "Precio",
                    })

            # Señal 2: Estado de stocks mundiales de soja
            señal_stock = usda_soja.get("señal_stocks")
            if señal_stock:
                señales.append({
                    "titulo":      f"Stocks mundiales soja: {señal_stock}",
                    "descripcion": usda_soja.get("señal_desc", ""),
                    "impacto":     "ALTO" if señal_stock == "AJUSTADO" else "MEDIO",
                    "color":       usda_soja.get("señal_color", "#BA7517"),
                    "categoria":   "Oferta global",
                })

            # Señal 3: Tendencia trigo (competidor en mercado mundial)
            trigo = precios.get("trigo", {})
            if trigo and abs(trigo.get("cambio_pct", 0)) >= 1.0:
                cpct = trigo.get("cambio_pct", 0)
                señales.append({
                    "titulo": f"Trigo Chicago {trigo['tendencia']} {abs(cpct):.1f}%",
                    "descripcion": (
                        f"Precio referencia USD {trigo['precio']}/tn. "
                        "Trigo competidor directo de Argentina en mercados de exportación."
                    ),
                    "impacto":   "MEDIO",
                    "color":     trigo["color"],
                    "categoria": "Precio",
                })

            # Señal 4: Petróleo (impacto en costos logísticos)
            wti = precios.get("wti", {})
            if wti and abs(wti.get("cambio_pct", 0)) >= 2.0:
                cpct = wti.get("cambio_pct", 0)
                señales.append({
                    "titulo": f"Petróleo WTI {wti['tendencia']} {abs(cpct):.1f}%",
                    "descripcion": (
                        f"USD {wti['precio']}/barril. "
                        f"{'Sube el costo del gasoil y fletes.' if cpct > 0 else 'Baja presión sobre costos logísticos.'}"
                    ),
                    "impacto":   "MEDIO",
                    "color":     "#D85A30" if cpct > 0 else "#639922",
                    "categoria": "Logística",
                })

            # Señal 5: Posición de Argentina en ranking soja
            ranking_soja = self.ranking_productores("soja")
            pos_arg = next((r for r in ranking_soja if r.get("es_argentina")), None)
            if pos_arg:
                señales.append({
                    "titulo": f"Argentina #{pos_arg['posicion']} productor mundial de soja",
                    "descripcion": (
                        f"{pos_arg['produccion_mm']} MM tn — {pos_arg['pct_global']}% de la producción global. "
                        "Cualquier variación en clima o política cambiaria impacta directamente el precio mundial."
                    ),
                    "impacto":   "MEDIO",
                    "color":     "#378ADD",
                    "categoria": "Posición global",
                })

            # Señal 6: Maíz — comparar tendencia vs soja
            maiz = precios.get("maiz", {})
            soja_precio = soja.get("precio", 0)
            maiz_precio = maiz.get("precio", 0)
            if soja_precio and maiz_precio:
                ratio_sm = round(soja_precio / maiz_precio, 2)
                if ratio_sm > 2.5:
                    señales.append({
                        "titulo": f"Relación soja/maíz: {ratio_sm}x — favorable a soja",
                        "descripcion": (
                            f"Ratio precio soja/maíz en {ratio_sm}x. "
                            "Por encima de 2.3x conviene priorizar soja en la rotación de cultivos."
                        ),
                        "impacto":   "MEDIO",
                        "color":     "#639922",
                        "categoria": "Estrategia cultivo",
                    })
                elif ratio_sm < 2.0:
                    señales.append({
                        "titulo": f"Relación soja/maíz: {ratio_sm}x — favorable a maíz",
                        "descripcion": (
                            f"Ratio precio soja/maíz en {ratio_sm}x. "
                            "Por debajo de 2.0x el maíz ofrece mejor retorno relativo por hectárea."
                        ),
                        "impacto":   "MEDIO",
                        "color":     "#BA7517",
                        "categoria": "Estrategia cultivo",
                    })

            # Señal 7: Brent vs WTI (spread logístico)
            brent = precios.get("brent", {})
            if wti and brent:
                spread = round(brent.get("precio", 0) - wti.get("precio", 0), 2)
                if spread > 5:
                    señales.append({
                        "titulo": f"Spread Brent-WTI: USD {spread}/barril",
                        "descripcion": (
                            "Spread elevado indica tensión en mercados de crudo internacional. "
                            "Impacto potencial en costos de exportación marítima."
                        ),
                        "impacto":   "BAJO",
                        "color":     "#BA7517",
                        "categoria": "Logística",
                    })

        except Exception as e:
            log.warning(f"Error generando señales globales: {e}")

        return señales

    # ── SNAPSHOT GLOBAL COMPLETO ──────────────────────────────

    def contexto_global(self, cultivo: str = "soja") -> dict:
        """
        Snapshot completo de contexto global.
        Combina ranking FAO, USDA, World Bank y CBOT.
        """
        log.info("Iniciando contexto global agropecuario...")
        return {
            "timestamp":      datetime.now().isoformat(),
            "cultivo":        cultivo,
            "ranking_fao":    self.ranking_productores(cultivo),
            "usda":           self.oferta_demanda_usda(cultivo),
            "precios_cbot":   self.precios_globales_cbot(),
            "world_bank":     self.indicadores_world_bank(),
            "señales":        self.señales_mercado_mundial(),
        }

    # ── Cache ─────────────────────────────────────────────────

    def _to_cache(self, clave: str, datos):
        self._cache[clave] = {"datos": datos, "ts": datetime.now()}

    def _from_cache(self, clave: str):
        entry = self._cache.get(clave)
        if not entry:
            return None
        if datetime.now() - entry["ts"] > timedelta(minutes=self._cache_minutos):
            return None
        return entry["datos"]

    # ── Fallbacks ─────────────────────────────────────────────

    def _fallback_ranking(self, cultivo: str) -> list[dict]:
        rankings = {
            "soja": [
                {"posicion": 1, "pais": "Brasil",          "produccion_mm": 155.0, "pct_global": 34.9, "es_argentina": False},
                {"posicion": 2, "pais": "Estados Unidos",  "produccion_mm": 116.0, "pct_global": 26.1, "es_argentina": False},
                {"posicion": 3, "pais": "Argentina",       "produccion_mm":  50.0, "pct_global": 11.3, "es_argentina": True},
                {"posicion": 4, "pais": "China",           "produccion_mm":  20.3, "pct_global":  4.6, "es_argentina": False},
                {"posicion": 5, "pais": "India",           "produccion_mm":  13.0, "pct_global":  2.9, "es_argentina": False},
                {"posicion": 6, "pais": "Paraguay",        "produccion_mm":  9.8,  "pct_global":  2.2, "es_argentina": False},
                {"posicion": 7, "pais": "Canadá",          "produccion_mm":  6.4,  "pct_global":  1.4, "es_argentina": False},
                {"posicion": 8, "pais": "Uruguay",         "produccion_mm":  2.8,  "pct_global":  0.6, "es_argentina": False},
                {"posicion": 9, "pais": "Bolivia",         "produccion_mm":  2.5,  "pct_global":  0.6, "es_argentina": False},
                {"posicion":10, "pais": "Rusia",           "produccion_mm":  2.1,  "pct_global":  0.5, "es_argentina": False},
            ],
            "maiz": [
                {"posicion": 1, "pais": "Estados Unidos",  "produccion_mm": 390.0, "pct_global": 32.0, "es_argentina": False},
                {"posicion": 2, "pais": "China",           "produccion_mm": 277.0, "pct_global": 22.7, "es_argentina": False},
                {"posicion": 3, "pais": "Brasil",          "produccion_mm": 137.0, "pct_global": 11.2, "es_argentina": False},
                {"posicion": 4, "pais": "Argentina",       "produccion_mm":  55.0, "pct_global":  4.5, "es_argentina": True},
                {"posicion": 5, "pais": "Ucrania",         "produccion_mm":  27.0, "pct_global":  2.2, "es_argentina": False},
                {"posicion": 6, "pais": "India",           "produccion_mm":  23.0, "pct_global":  1.9, "es_argentina": False},
                {"posicion": 7, "pais": "México",          "produccion_mm":  22.0, "pct_global":  1.8, "es_argentina": False},
                {"posicion": 8, "pais": "Sudáfrica",       "produccion_mm":  16.0, "pct_global":  1.3, "es_argentina": False},
                {"posicion": 9, "pais": "Rumania",         "produccion_mm":  13.0, "pct_global":  1.1, "es_argentina": False},
                {"posicion":10, "pais": "Indonesia",       "produccion_mm":  11.0, "pct_global":  0.9, "es_argentina": False},
            ],
            "trigo": [
                {"posicion": 1, "pais": "China",           "produccion_mm": 138.0, "pct_global": 17.9, "es_argentina": False},
                {"posicion": 2, "pais": "India",           "produccion_mm": 108.0, "pct_global": 14.0, "es_argentina": False},
                {"posicion": 3, "pais": "Rusia",           "produccion_mm":  92.0, "pct_global": 11.9, "es_argentina": False},
                {"posicion": 4, "pais": "Estados Unidos",  "produccion_mm":  45.0, "pct_global":  5.8, "es_argentina": False},
                {"posicion": 5, "pais": "Canadá",          "produccion_mm":  35.0, "pct_global":  4.5, "es_argentina": False},
                {"posicion": 6, "pais": "Francia",         "produccion_mm":  32.0, "pct_global":  4.1, "es_argentina": False},
                {"posicion": 7, "pais": "Ucrania",         "produccion_mm":  24.0, "pct_global":  3.1, "es_argentina": False},
                {"posicion": 8, "pais": "Pakistán",        "produccion_mm":  26.0, "pct_global":  3.4, "es_argentina": False},
                {"posicion": 9, "pais": "Australia",       "produccion_mm":  25.0, "pct_global":  3.2, "es_argentina": False},
                {"posicion":10, "pais": "Argentina",       "produccion_mm":  22.0, "pct_global":  2.9, "es_argentina": True},
            ],
            "girasol": [
                {"posicion": 1, "pais": "Ucrania",         "produccion_mm":  11.2, "pct_global": 29.0, "es_argentina": False},
                {"posicion": 2, "pais": "Rusia",           "produccion_mm":  15.1, "pct_global": 39.0, "es_argentina": False},
                {"posicion": 3, "pais": "Argentina",       "produccion_mm":   3.8, "pct_global":  9.8, "es_argentina": True},
                {"posicion": 4, "pais": "China",           "produccion_mm":   2.9, "pct_global":  7.5, "es_argentina": False},
                {"posicion": 5, "pais": "Rumania",         "produccion_mm":   2.1, "pct_global":  5.4, "es_argentina": False},
                {"posicion": 6, "pais": "Bulgaria",        "produccion_mm":   1.4, "pct_global":  3.6, "es_argentina": False},
                {"posicion": 7, "pais": "Hungría",         "produccion_mm":   1.2, "pct_global":  3.1, "es_argentina": False},
                {"posicion": 8, "pais": "Francia",         "produccion_mm":   0.9, "pct_global":  2.3, "es_argentina": False},
                {"posicion": 9, "pais": "Turquía",         "produccion_mm":   0.7, "pct_global":  1.8, "es_argentina": False},
                {"posicion":10, "pais": "Serbia",          "produccion_mm":   0.5, "pct_global":  1.3, "es_argentina": False},
            ],
        }
        return rankings.get(cultivo, rankings["soja"])

    def _fallback_usda(self, cultivo: str) -> dict:
        return {
            "cultivo":               cultivo,
            "año":                   2024,
            "produccion_global_mm_tn": 390.0 if cultivo == "soja" else 1200.0,
            "stocks_finales_mm_tn":    100.0,
            "ratio_stocks_uso_pct":    25.0,
            "señal_stocks":           "MODERADO",
            "señal_color":            "#BA7517",
            "señal_desc":             "Stocks en rango normal — mercado equilibrado",
            "fuente":                 "fallback — valores de referencia",
            "timestamp":              datetime.now().isoformat(),
        }


# ── Demo ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  ARGO — Contexto Global Agropecuario\n")
    g = ConectorGlobal()

    print("  Top 5 productores mundiales de soja (FAO)...")
    ranking = g.ranking_productores("soja")
    for r in ranking[:5]:
        flag = "◀ ARGENTINA" if r["es_argentina"] else ""
        print(f"    #{r['posicion']} {r['pais']:<20} {r['produccion_mm']:>6.1f} MM tn  "
              f"({r['pct_global']}% global) {flag}")

    print("\n  Precios CBOT Chicago...")
    precios = g.precios_globales_cbot()
    for grano in ("soja", "maiz", "trigo"):
        p = precios.get(grano, {})
        if p:
            print(f"    {grano:<8} USD {p['precio']:>7.2f}/tn  "
                  f"{p['tendencia']} {p['cambio_pct']:+.1f}%")

    print("\n  USDA — Oferta y demanda mundial soja...")
    usda = g.oferta_demanda_usda("soja")
    print(f"    Producción global:  {usda.get('produccion_global_mm_tn', 'N/D')} MM tn")
    print(f"    Stocks finales:     {usda.get('stocks_finales_mm_tn', 'N/D')} MM tn")
    print(f"    Ratio stocks/uso:   {usda.get('ratio_stocks_uso_pct', 'N/D')}%")
    print(f"    Señal:              {usda.get('señal_stocks')} — {usda.get('señal_desc')}")

    print("\n  Señales de mercado mundial...")
    señales = g.señales_mercado_mundial()
    for s in señales:
        print(f"    [{s['impacto']:<5}] {s['titulo']}")
        print(f"           {s['descripcion']}")
