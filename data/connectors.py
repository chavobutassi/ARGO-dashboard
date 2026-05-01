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
        Retorna precios en USD por tonelada (convertidos desde contratos estándar).

        Símbolos Yahoo Finance:
          ZS=F  → Soja   (cents/bushel) × 0.0367 → USD/tn
          ZC=F  → Maíz   (cents/bushel) × 0.0394 → USD/tn
          ZW=F  → Trigo  (cents/bushel) × 0.0367 → USD/tn
          CL=F  → Petróleo WTI (USD/barril)
          BZ=F  → Petróleo Brent (USD/barril)
        """
        clave = "commodities"
        if cached := self._from_cache(clave):
            return cached

        simbolos = {
            "ZS=F": ("soja",          0.0367),
            "ZC=F": ("maiz",          0.0394),
            "ZW=F": ("trigo",         0.0367),
            "CL=F": ("petroleo_wti",  1.0),
            "BZ=F": ("petroleo_brent",1.0),
        }

        datos: dict = {"timestamp": datetime.now().isoformat()}
        errores = 0

        for simbolo, (nombre, factor) in simbolos.items():
            try:
                url = (
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
                    "?interval=1d&range=1d"
                )
                resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
                resp.raise_for_status()
                resultado = resp.json()
                precio_raw = (
                    resultado["chart"]["result"][0]
                    ["meta"]["regularMarketPrice"]
                )
                datos[nombre] = round(precio_raw * factor, 2)
                log.info(f"Commodity OK — {nombre}: {datos[nombre]}")
            except Exception as e:
                log.warning(f"Commodity {nombre} no disponible ({e})")
                errores += 1

        if errores == len(simbolos):
            return self._fallback_commodities()

        datos["fuente"] = "Yahoo Finance (tiempo real)"
        self._to_cache(clave, datos)
        return datos

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
            url = "https://api.bcra.gob.ar/estadisticas/v3.0/datosvariable/1/1/1"
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS, verify=False)
            resp.raise_for_status()
            resultado = resp.json()
            valor = resultado["results"][0]["valor"]

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
            url = (
                "https://datos.gob.ar/api/3/action/datastore_search"
                "?resource_id=80ac25de-a44a-4445-9215-0bbc5c6e9b40"
                "&limit=10&sort=indice_tiempo desc"
            )
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            records = resp.json()["result"]["records"]

            if not records:
                raise ValueError("Sin registros en SEPA")

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
            log.warning(f"Combustibles SEPA no disponible ({e}) — usando fallback")
            return {
                "gasoil_ars_litro":      1350.0,
                "nafta_super_ars_litro": 1450.0,
                "fuente": "fallback — valor de referencia",
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
        return {
            "soja":           320.0,
            "maiz":           185.0,
            "trigo":          210.0,
            "petroleo_wti":    78.0,
            "petroleo_brent":  82.0,
            "fuente":         "fallback — valores de referencia",
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
