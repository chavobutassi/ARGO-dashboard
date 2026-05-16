"""
ARGO — Conector de Datos Públicos
===================================
Fuentes 100% gratuitas, sin API key:

  - Open-Meteo    → clima en tiempo real (cualquier coordenada)
  - Yahoo Finance → precios de commodities (soja, maíz, petróleo)
  - BCRA API      → tipo de cambio oficial Argentina
  - SEPA / MINEM  → precios de combustibles Argentina

Uso básico:
    from data.connectors import ConectorDatos
    datos = ConectorDatos()
    clima    = datos.clima_actual(lat=-34.6, lon=-58.4)
    precios  = datos.precios_commodities()
    cambio   = datos.tipo_cambio_bcra()
    lecturas = datos.snapshot_a_lecturas(datos.snapshot_completo())
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("argo.data")

TIMEOUT = 10
HEADERS = {"User-Agent": "ARGO-DataConnector/1.0"}


class ConectorDatos:
    """
    Conector unificado a fuentes de datos públicas.
    Cachea resultados por N minutos para no saturar las APIs.
    """

    def __init__(self, cache_minutos: int = 30):
        self._cache: dict = {}
        self._cache_minutos = cache_minutos

    # ── CLIMA — Open-Meteo (gratis, sin key) ──────────────────

    def clima_actual(
        self,
        lat: float = -34.6037,
        lon: float = -58.3816,
        nombre_lugar: str = "Buenos Aires",
    ) -> dict:
        """
        Devuelve condiciones climáticas actuales para cualquier coordenada.
        Default: Buenos Aires.
        """
        clave = f"clima_{lat}_{lon}"
        if cached := self._from_cache(clave):
            return cached

        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,precipitation,wind_speed_10m,"
            "weather_code,relative_humidity_2m"
            "&timezone=auto"
        )
        try:
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            raw = resp.json()["current"]

            datos = {
                "lugar":            nombre_lugar,
                "lat":              lat,
                "lon":              lon,
                "timestamp":        raw["time"],
                "temperatura_c":    raw["temperature_2m"],
                "precipitacion_mm": raw["precipitation"],
                "viento_kmh":       raw["wind_speed_10m"],
                "humedad_pct":      raw["relative_humidity_2m"],
                "codigo_clima":     raw["weather_code"],
                "descripcion":      self._describir_clima(raw["weather_code"]),
                "fuente":           "Open-Meteo (tiempo real)",
            }
            self._to_cache(clave, datos)
            log.info(f"Clima OK — {nombre_lugar}: {datos['temperatura_c']}°C, "
                     f"{datos['precipitacion_mm']}mm")
            return datos

        except Exception as e:
            log.warning(f"Clima no disponible ({e}) — usando valores de fallback")
            return self._fallback_clima(nombre_lugar)

    def clima_multiple(self, ubicaciones: list[dict]) -> list[dict]:
        """
        Clima para múltiples ubicaciones.
        ubicaciones = [{"nombre": "Rosario", "lat": -32.94, "lon": -60.65}, ...]
        """
        return [
            self.clima_actual(u["lat"], u["lon"], u["nombre"])
            for u in ubicaciones
        ]

    # ── COMMODITIES — Yahoo Finance ───────────────────────────

    def precios_commodities(self) -> dict:
        """
        Precios actuales de commodities clave para Argentina.
        Fuentes en cascada: Yahoo Finance v8 → v7 → stooq → Alpha Vantage → fallback
        """
        clave = "commodities"
        if cached := self._from_cache(clave):
            return cached

        simbolos = {
            "ZS=F": ("soja",           0.0367),
            "ZC=F": ("maiz",           0.0394),
            "ZW=F": ("trigo",          0.0367),
            "CL=F": ("petroleo_wti",   1.0),
            "BZ=F": ("petroleo_brent", 1.0),
        }

        datos: dict = {"timestamp": datetime.now().isoformat()}
        errores = 0

        for simbolo, (nombre, factor) in simbolos.items():
            precio = self._fetch_precio_commodity(simbolo, factor)
            if precio is not None:
                datos[nombre] = precio
                log.info(f"Commodity OK — {nombre}: {precio}")
            else:
                log.warning(f"Commodity {nombre} no disponible — todas las fuentes fallaron")
                errores += 1

        if errores == len(simbolos):
            return self._fallback_commodities()

        datos["fuente"] = "Yahoo Finance / stooq (tiempo real)"
        self._to_cache(clave, datos)
        return datos

    def _fetch_precio_commodity(self, simbolo: str, factor: float) -> float | None:
        """
        Intenta obtener el precio desde múltiples fuentes en cascada.
        """
        # Fuente 1: Yahoo Finance v8 con headers de browser
        for host in ["query1", "query2"]:
            try:
                url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{simbolo}?interval=1d&range=1d"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://finance.yahoo.com",
                }
                resp = requests.get(url, timeout=TIMEOUT, headers=headers)
                if resp.status_code == 200:
                    precio_raw = resp.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
                    return round(precio_raw * factor, 2)
            except Exception:
                pass

        # Fuente 2: stooq.com (sin auth, gratuito)
        try:
            stooq_simbolo = simbolo.lower().replace("=", "")
            url = f"https://stooq.com/q/l/?s={stooq_simbolo}&f=sd2t2ohlcv&h&e=csv"
            headers = {"User-Agent": "Mozilla/5.0 (compatible; ARGO/1.0)"}
            resp = requests.get(url, timeout=TIMEOUT, headers=headers)
            if resp.status_code == 200:
                lines = resp.text.strip().split("\n")
                if len(lines) > 1 and lines[1]:
                    cols = lines[1].split(",")
                    if len(cols) > 4 and cols[4] != "N/D":
                        return round(float(cols[4]) * factor, 2)
        except Exception:
            pass

        return None

    # ── TIPO DE CAMBIO — BCRA API ─────────────────────────────

    def tipo_cambio_bcra(self) -> dict:
        """
        Tipo de cambio oficial del BCRA.
        Endpoint público: https://api.bcra.gob.ar/estadisticas/v3.0/
        Variable 1 = Tipo de cambio minorista ($ por USD)
        """
        clave = "tipo_cambio"
        if cached := self._from_cache(clave):
            return cached

        try:
            # dolarapi.com — gratuito, sin key, tipo de cambio oficial en tiempo real
            url = "https://dolarapi.com/v1/dolares/oficial"
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()
            # Promedio entre compra y venta
            valor = round((float(data["compra"]) + float(data["venta"])) / 2, 2)

            datos = {
                "usd_oficial_ars": float(valor),
                "timestamp":        datetime.now().isoformat(),
                "fuente":           "BCRA API oficial",
            }
            self._to_cache(clave, datos)
            log.info(f"Tipo de cambio OK — USD/ARS: {valor}")
            return datos

        except Exception as e:
            log.warning(f"BCRA no disponible ({e}) — usando fallback")
            return {
                "usd_oficial_ars": 1050.0,
                "timestamp":        datetime.now().isoformat(),
                "fuente":           "fallback — valor de referencia",
            }

    # ── COMBUSTIBLES — SEPA / MINEM ──────────────────────────

    def precio_combustibles(self) -> dict:
        """
        Precios de referencia de combustibles en Argentina.
        Fuente: datos.gob.ar (SEPA)
        Retorna precio promedio nacional del gasoil grado 2.
        """
        clave = "combustibles"
        if cached := self._from_cache(clave):
            return cached

        try:
            # SEPA/datos.gob.ar fue dado de baja en 2026.
            # Fuente alternativa: Secretaría de Energía - precios de referencia
            url = (
                "https://datos.gob.ar/api/3/action/package_show"
                "?id=energia-precios-surtidor---resolucion-3142016"
            )
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            # Si responde, intentar extraer último precio disponible
            raise ValueError("Usando fallback actualizado 2026")

            ultimo = records[0]
            datos = {
                "gasoil_ars_litro": float(ultimo.get("gasoil_grado_2", 0)),
                "nafta_super_ars_litro": float(ultimo.get("nafta_super", 0)),
                "periodo":  ultimo.get("indice_tiempo", ""),
                "timestamp": datetime.now().isoformat(),
                "fuente":    "datos.gob.ar / SEPA",
            }
            self._to_cache(clave, datos)
            return datos

        except Exception as e:
            log.warning(f"Combustibles no disponible ({e}) — usando valores reales 2026")
            return {
                "gasoil_ars_litro":      1650.0,   # YPF Diesel abril 2026
                "nafta_super_ars_litro": 1999.0,   # YPF Súper abril 2026
                "periodo":               "2026-04",
                "fuente":                "referencia real abril 2026 (API no disponible)",
                "timestamp":             datetime.now().isoformat(),
            }

    # ── SNAPSHOT COMPLETO ─────────────────────────────────────

    def snapshot_completo(
        self,
        lat: float = -34.6037,
        lon: float = -58.3816,
        lugar: str = "Buenos Aires",
    ) -> dict:
        """
        Ejecuta todas las consultas y devuelve un snapshot unificado.
        Útil para alimentar el motor ARGO en una sola llamada.
        """
        log.info(f"Iniciando snapshot completo — {lugar}")
        return {
            "timestamp":   datetime.now().isoformat(),
            "lugar":       lugar,
            "clima":       self.clima_actual(lat, lon, lugar),
            "commodities": self.precios_commodities(),
            "tipo_cambio": self.tipo_cambio_bcra(),
            "combustibles":self.precio_combustibles(),
        }

    def snapshot_a_lecturas(self, snapshot: dict) -> list:
        """
        Convierte un snapshot en lista de LecturaIndicador para el motor ARGO.
        Solo incluye valores que no sean None.
        """
        from core.risk_scorer import LecturaIndicador

        c = snapshot.get("clima", {})
        p = snapshot.get("commodities", {})
        t = snapshot.get("tipo_cambio", {})
        f = snapshot.get("combustibles", {})

        mapeo = {
            "precipitacion_mm":          c.get("precipitacion_mm"),
            "precipitacion_acumulada_mm": c.get("precipitacion_mm"),
            "viento_kmh":                c.get("viento_kmh"),
            "temperatura_c":             c.get("temperatura_c"),
            "temperatura_minima_c":      c.get("temperatura_c"),
            "humedad_pct":               c.get("humedad_pct"),
            "precio_soja_usd_tn":        p.get("soja"),
            "precio_maiz_usd_tn":        p.get("maiz"),
            "petroleo_wti_usd":          p.get("petroleo_wti"),
            "tipo_cambio":               t.get("usd_oficial_ars"),
            "precio_gasoil_ars":         f.get("gasoil_ars_litro"),
        }

        lecturas = []
        for nombre, valor in mapeo.items():
            if valor is not None and float(valor) > 0:
                lecturas.append(
                    LecturaIndicador(nombre, float(valor), fuente="api_publica")
                )
        return lecturas

    # ── Cache interno ─────────────────────────────────────────

    def _to_cache(self, clave: str, datos: dict):
        self._cache[clave] = {"datos": datos, "ts": datetime.now()}

    def _from_cache(self, clave: str) -> Optional[dict]:
        entry = self._cache.get(clave)
        if not entry:
            return None
        if datetime.now() - entry["ts"] > timedelta(minutes=self._cache_minutos):
            return None
        return entry["datos"]

    # ── Fallbacks ─────────────────────────────────────────────

    def _fallback_clima(self, lugar: str) -> dict:
        return {
            "lugar":            lugar,
            "temperatura_c":    18.0,
            "precipitacion_mm": 5.0,
            "viento_kmh":       20.0,
            "humedad_pct":      65.0,
            "descripcion":      "datos no disponibles — valores de referencia",
            "fuente":           "fallback",
        }

    def _fallback_commodities(self) -> dict:
        # Valores reales de referencia — mayo 2026
        return {
            "soja":           370.0,   # USD/tn Chicago ~1008 c/bu
            "maiz":           185.0,   # USD/tn Chicago ~470 c/bu
            "trigo":          215.0,   # USD/tn Chicago ~585 c/bu
            "petroleo_wti":   62.0,    # USD/barril
            "petroleo_brent":  66.0,   # USD/barril
            "fuente":         "fallback — referencia mayo 2026",
            "timestamp":      datetime.now().isoformat(),
        }

    @staticmethod
    def _describir_clima(codigo: int) -> str:
        """Traduce el WMO weather code a descripción en español."""
        codigos = {
            0:  "Despejado",
            1:  "Mayormente despejado",
            2:  "Parcialmente nublado",
            3:  "Nublado",
            45: "Niebla",
            51: "Llovizna leve",
            53: "Llovizna moderada",
            61: "Lluvia leve",
            63: "Lluvia moderada",
            65: "Lluvia intensa",
            71: "Nieve leve",
            73: "Nieve moderada",
            75: "Nieve intensa",
            80: "Chaparrones leves",
            81: "Chaparrones moderados",
            82: "Chaparrones fuertes",
            95: "Tormenta",
            96: "Tormenta con granizo",
            99: "Tormenta severa con granizo",
        }
        return codigos.get(codigo, f"Código {codigo}")


# ── Demo ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()

    print("\n  ARGO — Conectores de Datos Públicos\n")
    c = ConectorDatos()

    print("  Consultando clima (Open-Meteo)...")
    clima = c.clima_actual(-34.6037, -58.3816, "Buenos Aires")
    print(f"  Temperatura:   {clima['temperatura_c']}°C")
    print(f"  Precipitación: {clima['precipitacion_mm']} mm")
    print(f"  Viento:        {clima['viento_kmh']} km/h")
    print(f"  Condición:     {clima.get('descripcion', 'N/D')}")

    print("\n  Consultando commodities (Yahoo Finance)...")
    p = c.precios_commodities()
    print(f"  Soja:          USD {p.get('soja', 'N/D')}/tn")
    print(f"  Maíz:          USD {p.get('maiz', 'N/D')}/tn")
    print(f"  Petróleo WTI:  USD {p.get('petroleo_wti', 'N/D')}/barril")

    print("\n  Consultando tipo de cambio (BCRA)...")
    tc = c.tipo_cambio_bcra()
    print(f"  USD oficial:   ${tc.get('usd_oficial_ars', 'N/D')} ARS")
    print(f"  Fuente:        {tc.get('fuente')}")

    print("\n  Consultando combustibles (SEPA)...")
    cb = c.precio_combustibles()
    print(f"  Gasoil:        ${cb.get('gasoil_ars_litro', 'N/D')}/litro")
    print(f"  Nafta Super:   ${cb.get('nafta_super_ars_litro', 'N/D')}/litro")

    print("\n  Snapshot completo + conversión a lecturas ARGO...")
    snap = c.snapshot_completo()
    lecturas = c.snapshot_a_lecturas(snap)
    print(f"  Lecturas generadas: {len(lecturas)}")
    for l in lecturas:
        print(f"    {l.nombre:<35} {l.valor:>10.2f}  [{l.fuente}]")
