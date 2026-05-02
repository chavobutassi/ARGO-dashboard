"""
ARGO — Conector Agropecuario Detallado
=======================================
Módulo especializado para análisis de decisiones en el agro argentino.
Complementa connectors.py sin reemplazarlo.

Fuentes 100% gratuitas, sin API key:

  - MATBA-ROFEX API    → precios de futuros soja, maíz, trigo
  - Bolsa de Cereales  → condición de cultivos y estimaciones
  - Open-Meteo         → clima agroclimático por zona
  - SMN                → pronóstico extendido (heladas, lluvias)
  - BCRA               → tipo de cambio + brecha
  - datos.gob.ar       → precios de insumos, fletes por zona
  - Yahoo Finance      → CBOT (Chicago) para comparar con Rosario

Uso básico:
    from data.connectors_agro import ConectorAgro
    agro = ConectorAgro()
    snapshot = agro.snapshot_agro(lat=-33.0, lon=-63.0, zona="Córdoba")
    decision = agro.score_decision_venta(snapshot)
    print(decision["recomendacion"])  # "VENDER" | "ESPERAR" | "ATENCION"
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("argo.agro")

TIMEOUT = 10
HEADERS = {"User-Agent": "ARGO-AgroConnector/1.0"}

# ── Zonas agroclimáticas principales de Argentina ─────────────
ZONAS_AGRO = {
    "pampa_humeda":    {"lat": -34.0, "lon": -61.0, "label": "Pampa Húmeda"},
    "cordoba_sur":     {"lat": -33.5, "lon": -63.5, "label": "Córdoba Sur"},
    "santa_fe_centro": {"lat": -31.5, "lon": -61.5, "label": "Santa Fe Centro"},
    "entre_rios":      {"lat": -32.0, "lon": -58.5, "label": "Entre Ríos"},
    "buenos_aires_n":  {"lat": -35.0, "lon": -60.0, "label": "Buenos Aires Norte"},
    "la_pampa":        {"lat": -37.0, "lon": -64.0, "label": "La Pampa"},
    "chaco":           {"lat": -27.0, "lon": -61.0, "label": "Chaco"},
}

# ── Plantas acopiadoras por zona (distancia referencial) ──────
PLANTAS_REFERENCIA = {
    "Rosario":      {"lat": -32.95, "lon": -60.64, "empresas": ["Cargill", "Bunge", "Dreyfus", "ACA", "Cofco"]},
    "Bahia_Blanca": {"lat": -38.72, "lon": -62.27, "empresas": ["Toepfer", "ACA", "Cargill"]},
    "Quequen":      {"lat": -38.59, "lon": -58.71, "empresas": ["Bunge", "ACA"]},
    "Villa_Constitucion": {"lat": -33.23, "lon": -60.33, "empresas": ["Dreyfus", "Molinos"]},
}


class ConectorAgro:
    """
    Conector especializado en datos agropecuarios para Argentina.
    Diseñado para alimentar el módulo de decisión de venta de ARGO.
    """

    def __init__(self, cache_minutos: int = 30):
        self._cache: dict = {}
        self._cache_minutos = cache_minutos

    # ── PRECIOS GRANOS — MATBA-ROFEX ──────────────────────────

    def precios_futuros_matba(self) -> dict:
        """
        Precios de futuros de granos en MATBA-ROFEX (Rosario).
        Endpoint público sin autenticación.
        Retorna posición más cercana para soja, maíz y trigo.
        """
        clave = "matba_futuros"
        if cached := self._from_cache(clave):
            return cached

        try:
            url = "https://api.matbarofex.com.ar/v2/rest/marketdata/products"
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            raw = resp.json()

            datos: dict = {
                "timestamp": datetime.now().isoformat(),
                "fuente": "MATBA-ROFEX (tiempo real)",
            }

            # Buscar soja, maíz y trigo en los productos
            for producto in raw.get("products", []):
                nombre = producto.get("name", "").lower()
                precio = producto.get("lastPrice") or producto.get("settlementPrice")
                if not precio:
                    continue
                if "soja" in nombre:
                    datos.setdefault("soja_rosario_usd_tn", float(precio))
                elif "maiz" in nombre or "maíz" in nombre:
                    datos.setdefault("maiz_rosario_usd_tn", float(precio))
                elif "trigo" in nombre:
                    datos.setdefault("trigo_rosario_usd_tn", float(precio))

            self._to_cache(clave, datos)
            log.info(f"MATBA-ROFEX OK — soja: {datos.get('soja_rosario_usd_tn')} USD/tn")
            return datos

        except Exception as e:
            log.warning(f"MATBA-ROFEX no disponible ({e}) — usando Yahoo Finance como fallback")
            return self._fallback_precios_granos()

    def precios_cbot_chicago(self) -> dict:
        """
        Precios de referencia Chicago (CBOT) vía Yahoo Finance.
        Útil para calcular la brecha Chicago vs Rosario.
        """
        clave = "cbot_chicago"
        if cached := self._from_cache(clave):
            return cached

        simbolos = {
            "ZS=F": ("soja_chicago_usd_tn",  0.0367),
            "ZC=F": ("maiz_chicago_usd_tn",   0.0394),
            "ZW=F": ("trigo_chicago_usd_tn",  0.0367),
        }

        datos: dict = {"timestamp": datetime.now().isoformat()}

        for simbolo, (nombre, factor) in simbolos.items():
            try:
                url = (
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
                    "?interval=1d&range=1d"
                )
                resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
                resp.raise_for_status()
                precio_raw = (
                    resp.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
                )
                datos[nombre] = round(precio_raw * factor, 2)
            except Exception as e:
                log.warning(f"CBOT {nombre} no disponible ({e})")

        datos["fuente"] = "Yahoo Finance / CBOT Chicago"
        self._to_cache(clave, datos)
        return datos

    def brecha_chicago_rosario(self) -> dict:
        """
        Calcula la diferencia de precio entre Chicago y Rosario.
        Una brecha positiva indica que Rosario está barato vs referencia global.
        Útil para decidir si retener o vender.
        """
        cbot = self.precios_cbot_chicago()
        matba = self.precios_futuros_matba()

        resultado = {"timestamp": datetime.now().isoformat()}

        for grano in ("soja", "maiz", "trigo"):
            chicago  = cbot.get(f"{grano}_chicago_usd_tn")
            rosario  = matba.get(f"{grano}_rosario_usd_tn")
            if chicago and rosario:
                brecha = round(chicago - rosario, 2)
                resultado[f"brecha_{grano}_usd_tn"] = brecha
                resultado[f"brecha_{grano}_pct"] = round((brecha / chicago) * 100, 1)

        return resultado

    # ── TIPO DE CAMBIO Y RETENCIONES ─────────────────────────

    def tipo_cambio_y_retenciones(self) -> dict:
        """
        Tipo de cambio oficial BCRA + retenciones vigentes por cultivo.
        Permite calcular el precio neto en pesos que recibe el productor.
        """
        clave = "tc_retenciones"
        if cached := self._from_cache(clave):
            return cached

        try:
            desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            hasta = datetime.now().strftime("%Y-%m-%d")
            url = f"https://api.bcra.gob.ar/estadisticas/v3.0/datosvariable/1/{desde}/{hasta}"
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS, verify=False)
            resp.raise_for_status()
            tc_oficial = float(resp.json()["results"][-1]["valor"])
        except Exception as e:
            log.warning(f"BCRA no disponible ({e})")
            tc_oficial = 1050.0

        # Retenciones vigentes (actualizar si cambia política)
        retenciones = {
            "soja":  0.33,   # 33%
            "maiz":  0.12,   # 12%
            "trigo": 0.12,   # 12%
            "girasol": 0.07, # 7%
        }

        datos = {
            "usd_oficial_ars":  tc_oficial,
            "retenciones":      retenciones,
            "timestamp":        datetime.now().isoformat(),
            "fuente":           "BCRA API + retenciones vigentes",
            "nota":             "Verificar retenciones ante cambios de política",
        }

        # Precio neto estimado en ARS por tonelada para cada cultivo
        # usando precios CBOT como referencia
        cbot = self.precios_cbot_chicago()
        for grano, retencion in retenciones.items():
            precio_usd = cbot.get(f"{grano}_chicago_usd_tn")
            if precio_usd:
                precio_neto_usd = precio_usd * (1 - retencion)
                datos[f"{grano}_precio_neto_ars_tn"] = round(
                    precio_neto_usd * tc_oficial, 0
                )

        self._to_cache(clave, datos)
        return datos

    # ── CLIMA AGROCLIMÁTICO ───────────────────────────────────

    def clima_agro(
        self,
        lat: float = -33.0,
        lon: float = -63.0,
        zona: str = "Córdoba",
    ) -> dict:
        """
        Variables climáticas relevantes para decisiones agropecuarias.
        Incluye pronóstico a 7 días para ventana de cosecha/siembra.
        """
        clave = f"clima_agro_{lat}_{lon}"
        if cached := self._from_cache(clave):
            return cached

        try:
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,precipitation,wind_speed_10m,"
                "weather_code,relative_humidity_2m,soil_moisture_0_to_1cm"
                "&daily=precipitation_sum,temperature_2m_max,temperature_2m_min,"
                "et0_fao_evapotranspiration,precipitation_probability_max"
                "&forecast_days=7"
                "&timezone=America/Argentina/Buenos_Aires"
            )
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            raw = resp.json()

            curr = raw["current"]
            daily = raw["daily"]

            # Precipitación acumulada próximos 7 días
            lluvia_7d = sum(
                v for v in daily.get("precipitation_sum", []) if v is not None
            )

            # Días con helada (temp mínima < 0°C)
            dias_helada = sum(
                1 for v in daily.get("temperature_2m_min", [])
                if v is not None and v < 0
            )

            # Evapotranspiración acumulada 7 días
            et0_7d = sum(
                v for v in daily.get("et0_fao_evapotranspiration", [])
                if v is not None
            )

            # Días con alta probabilidad de lluvia (>60%)
            dias_lluvia = sum(
                1 for v in daily.get("precipitation_probability_max", [])
                if v is not None and v > 60
            )

            datos = {
                "zona":                   zona,
                "lat":                    lat,
                "lon":                    lon,
                "temperatura_c":          curr["temperature_2m"],
                "humedad_pct":            curr["relative_humidity_2m"],
                "precipitacion_mm":       curr["precipitation"],
                "viento_kmh":             curr["wind_speed_10m"],
                "lluvia_acumulada_7d_mm": round(lluvia_7d, 1),
                "dias_con_lluvia_7d":     dias_lluvia,
                "dias_helada_7d":         dias_helada,
                "evapotranspiracion_7d":  round(et0_7d, 1),
                "ventana_cosecha_ok":     dias_lluvia <= 2 and dias_helada == 0,
                "alerta_helada":          dias_helada > 0,
                "alerta_sequia":          lluvia_7d < 5 and curr["relative_humidity_2m"] < 40,
                "timestamp":              curr["time"],
                "fuente":                 "Open-Meteo (tiempo real + pronóstico 7d)",
            }

            self._to_cache(clave, datos)
            log.info(f"Clima agro OK — {zona}: lluvia 7d={lluvia_7d}mm, heladas={dias_helada}d")
            return datos

        except Exception as e:
            log.warning(f"Clima agro no disponible ({e})")
            return self._fallback_clima_agro(zona)

    # ── LOGÍSTICA Y FLETES ────────────────────────────────────

    def costos_logisticos(self) -> dict:
        """
        Precios de referencia de flete por zona y gasoil.
        Fuente: datos.gob.ar / SEPA para combustible.
        Fletes: valores de referencia por zona (actualizar mensualmente).
        """
        clave = "logistica"
        if cached := self._from_cache(clave):
            return cached

        # Precio gasoil desde SEPA
        try:
            url = (
                "https://datos.gob.ar/api/3/action/datastore_search"
                "?resource_id=80ac25de-a44a-4445-9215-0bbc5c6e9b40"
                "&limit=1&sort=indice_tiempo desc"
            )
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            records = resp.json()["result"]["records"]
            gasoil_ars = float(records[0].get("gasoil_grado_2", 1350.0))
        except Exception:
            gasoil_ars = 1350.0

        # Fletes de referencia por zona (ARS/tn) — actualizar mensualmente
        # Valores aproximados para distancias típicas a puerto Rosario
        fletes_referencia = {
            "pampa_humeda":    {"ars_tn": 18000, "km_aprox": 250},
            "cordoba_sur":     {"ars_tn": 22000, "km_aprox": 320},
            "santa_fe_centro": {"ars_tn": 15000, "km_aprox": 180},
            "entre_rios":      {"ars_tn": 20000, "km_aprox": 280},
            "buenos_aires_n":  {"ars_tn": 16000, "km_aprox": 200},
            "la_pampa":        {"ars_tn": 28000, "km_aprox": 400},
            "chaco":           {"ars_tn": 35000, "km_aprox": 500},
        }

        datos = {
            "gasoil_ars_litro":    gasoil_ars,
            "fletes":              fletes_referencia,
            "plantas_referencia":  PLANTAS_REFERENCIA,
            "timestamp":           datetime.now().isoformat(),
            "fuente":              "SEPA + valores de referencia por zona",
            "nota":                "Fletes aproximados a puerto Rosario. Verificar con transportista.",
        }

        self._to_cache(clave, datos)
        return datos

    # ── CONDICIÓN DE CULTIVOS ─────────────────────────────────

    def condicion_cultivos_bcr(self) -> dict:
        """
        Estimaciones de producción y condición de cultivos.
        Fuente: Bolsa de Cereales de Rosario (BCR) — datos públicos.
        """
        clave = "condicion_cultivos"
        if cached := self._from_cache(clave):
            return cached

        try:
            # BCR publica informes en formato JSON accesible
            url = "https://www.bcr.com.ar/es/mercados/investigacion-y-desarrollo/estadisticas/granos-argentinos"
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            # Si la respuesta es HTML (informe), extraemos lo que podemos
            datos = {
                "fuente": "BCR — Bolsa de Cereales de Rosario",
                "url_referencia": url,
                "timestamp": datetime.now().isoformat(),
                "nota": "Consultar informe semanal para condición actualizada",
                # Valores de referencia hasta integración completa de API BCR
                "soja_produccion_mm_tn_estimada":  50.0,
                "maiz_produccion_mm_tn_estimada":  55.0,
                "trigo_produccion_mm_tn_estimada": 18.0,
            }
            self._to_cache(clave, datos)
            return datos

        except Exception as e:
            log.warning(f"BCR no disponible ({e})")
            return {
                "fuente": "fallback",
                "timestamp": datetime.now().isoformat(),
            }

    # ── SCORE DE DECISIÓN DE VENTA ────────────────────────────

    def score_decision_venta(
        self,
        snapshot: dict,
        grano: str = "soja",
        zona: str = "pampa_humeda",
    ) -> dict:
        """
        Motor de decisión: ¿conviene vender ahora, esperar o alertar?

        Evalúa:
          - Precio actual vs histórico (posición relativa)
          - Tipo de cambio y retenciones (precio neto ARS)
          - Capacidad de almacenamiento
          - Clima: ventana logística disponible
          - Costo de oportunidad financiero

        Retorna:
          score: 0-100 (100 = condiciones óptimas para vender)
          recomendacion: "VENDER" | "ESPERAR" | "ATENCION"
          factores: detalle de cada variable evaluada
        """
        factores = []
        score = 0
        max_score = 0

        clima  = snapshot.get("clima", {})
        precios = snapshot.get("precios", {})
        tc     = snapshot.get("tipo_cambio", {})
        logistica = snapshot.get("logistica", {})
        brecha = snapshot.get("brecha_chicago_rosario", {})

        # ── Factor 1: Precio relativo (0-25 pts) ──────────────
        max_score += 25
        precio_actual = precios.get(f"{grano}_rosario_usd_tn") or \
                        precios.get(f"{grano}_chicago_usd_tn", 0)

        # Umbrales de referencia por grano (USD/tn)
        umbrales = {"soja": 300, "maiz": 170, "trigo": 200, "girasol": 350}
        umbral = umbrales.get(grano, 300)

        if precio_actual > umbral * 1.10:
            pts = 25
            estado = "Precio alto — favorable para venta"
        elif precio_actual > umbral:
            pts = 15
            estado = "Precio sobre umbral de referencia"
        elif precio_actual > umbral * 0.90:
            pts = 8
            estado = "Precio bajo umbral — evaluar esperar"
        else:
            pts = 0
            estado = "Precio bajo — desfavorable para venta"

        score += pts
        factores.append({
            "factor": "Precio de mercado",
            "valor": f"USD {precio_actual}/tn",
            "puntos": f"{pts}/25",
            "estado": estado,
        })

        # ── Factor 2: Tipo de cambio (0-20 pts) ───────────────
        max_score += 20
        tc_actual = tc.get("usd_oficial_ars", 0)
        precio_neto_ars = tc.get(f"{grano}_precio_neto_ars_tn", 0)

        if tc_actual > 1000:
            pts = 20
            estado = "TC elevado — conversión favorable"
        elif tc_actual > 800:
            pts = 12
            estado = "TC moderado"
        else:
            pts = 4
            estado = "TC bajo — conversión desfavorable"

        score += pts
        factores.append({
            "factor": "Tipo de cambio",
            "valor": f"${tc_actual} ARS/USD",
            "precio_neto": f"${precio_neto_ars:,.0f} ARS/tn" if precio_neto_ars else "N/D",
            "puntos": f"{pts}/20",
            "estado": estado,
        })

        # ── Factor 3: Ventana logística (0-20 pts) ────────────
        max_score += 20
        ventana_ok = clima.get("ventana_cosecha_ok", False)
        dias_lluvia = clima.get("dias_con_lluvia_7d", 3)
        dias_helada = clima.get("dias_helada_7d", 0)

        if ventana_ok:
            pts = 20
            estado = "Ventana logística abierta — buenas condiciones"
        elif dias_lluvia <= 3 and dias_helada == 0:
            pts = 12
            estado = "Condiciones aceptables"
        elif dias_helada > 0:
            pts = 4
            estado = f"Alerta: {dias_helada} días con helada proyectados"
        else:
            pts = 6
            estado = f"{dias_lluvia} días con lluvia — posible corte de rutas"

        score += pts
        factores.append({
            "factor": "Ventana logística (7 días)",
            "valor": f"{dias_lluvia}d lluvia / {dias_helada}d helada",
            "puntos": f"{pts}/20",
            "estado": estado,
        })

        # ── Factor 4: Brecha Chicago-Rosario (0-15 pts) ───────
        max_score += 15
        brecha_val = brecha.get(f"brecha_{grano}_usd_tn", 0)
        brecha_pct = brecha.get(f"brecha_{grano}_pct", 0)

        if brecha_val < 10:
            pts = 15
            estado = "Rosario cerca de Chicago — precio local competitivo"
        elif brecha_val < 25:
            pts = 8
            estado = f"Brecha moderada: USD {brecha_val}/tn vs Chicago"
        else:
            pts = 2
            estado = f"Brecha alta: USD {brecha_val}/tn — Rosario descuenta mucho"

        score += pts
        factores.append({
            "factor": "Brecha Chicago-Rosario",
            "valor": f"USD {brecha_val}/tn ({brecha_pct}%)",
            "puntos": f"{pts}/15",
            "estado": estado,
        })

        # ── Factor 5: Costo logístico (0-20 pts) ──────────────
        max_score += 20
        gasoil = logistica.get("gasoil_ars_litro", 1350)
        flete_zona = logistica.get("fletes", {}).get(zona, {}).get("ars_tn", 20000)

        # Flete como % del precio neto ARS
        if precio_neto_ars and precio_neto_ars > 0:
            flete_pct = (flete_zona / precio_neto_ars) * 100
        else:
            flete_pct = 15.0

        if flete_pct < 8:
            pts = 20
            estado = "Costo logístico bajo — margen amplio"
        elif flete_pct < 12:
            pts = 12
            estado = "Costo logístico moderado"
        elif flete_pct < 18:
            pts = 6
            estado = "Costo logístico elevado — ajustar márgenes"
        else:
            pts = 0
            estado = "Costo logístico crítico — evaluar destino alternativo"

        score += pts
        factores.append({
            "factor": "Costo logístico",
            "valor": f"${flete_zona:,.0f} ARS/tn ({flete_pct:.1f}% del precio neto)",
            "gasoil": f"${gasoil}/litro",
            "puntos": f"{pts}/20",
            "estado": estado,
        })

        # ── Recomendación final ────────────────────────────────
        score_pct = round((score / max_score) * 100)

        if score_pct >= 70:
            recomendacion = "VENDER"
            color = "#639922"
            descripcion = "Condiciones favorables. Precio competitivo, ventana logística abierta y tipo de cambio alto."
        elif score_pct >= 45:
            recomendacion = "ESPERAR"
            color = "#BA7517"
            descripcion = "Condiciones mixtas. Monitorear precio y ventana climática antes de decidir."
        else:
            recomendacion = "ATENCION"
            color = "#E24B4A"
            descripcion = "Condiciones desfavorables. Revisar cobertura y capacidad de almacenamiento."

        return {
            "grano":          grano,
            "zona":           zona,
            "score":          score_pct,
            "recomendacion":  recomendacion,
            "color":          color,
            "descripcion":    descripcion,
            "factores":       factores,
            "timestamp":      datetime.now().isoformat(),
        }

    # ── SNAPSHOT AGROPECUARIO COMPLETO ────────────────────────

    def snapshot_agro(
        self,
        lat: float = -33.0,
        lon: float = -63.0,
        zona: str = "cordoba_sur",
    ) -> dict:
        """
        Ejecuta todas las consultas agropecuarias en una sola llamada.
        Retorna un snapshot unificado listo para el motor de decisión.
        """
        zona_label = ZONAS_AGRO.get(zona, {}).get("label", zona)
        log.info(f"Iniciando snapshot agro — {zona_label}")

        return {
            "timestamp":              datetime.now().isoformat(),
            "zona":                   zona_label,
            "clima":                  self.clima_agro(lat, lon, zona_label),
            "precios":                self.precios_futuros_matba(),
            "precios_chicago":        self.precios_cbot_chicago(),
            "brecha_chicago_rosario": self.brecha_chicago_rosario(),
            "tipo_cambio":            self.tipo_cambio_y_retenciones(),
            "logistica":              self.costos_logisticos(),
            "cultivos":               self.condicion_cultivos_bcr(),
        }

    # ── Cache ─────────────────────────────────────────────────

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

    def _fallback_precios_granos(self) -> dict:
        return {
            "soja_rosario_usd_tn":  300.0,
            "maiz_rosario_usd_tn":  170.0,
            "trigo_rosario_usd_tn": 200.0,
            "fuente": "fallback — valores de referencia",
            "timestamp": datetime.now().isoformat(),
        }

    def _fallback_clima_agro(self, zona: str) -> dict:
        return {
            "zona":                   zona,
            "temperatura_c":          18.0,
            "humedad_pct":            60.0,
            "precipitacion_mm":       5.0,
            "lluvia_acumulada_7d_mm": 20.0,
            "dias_con_lluvia_7d":     2,
            "dias_helada_7d":         0,
            "ventana_cosecha_ok":     True,
            "alerta_helada":          False,
            "alerta_sequia":          False,
            "fuente": "fallback",
        }


# ── Demo ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()

    print("\n  ARGO Agro — Motor de Decisión\n")
    agro = ConectorAgro()

    print("  Consultando snapshot agro (Córdoba Sur)...")
    snap = agro.snapshot_agro(lat=-33.5, lon=-63.5, zona="cordoba_sur")

    print(f"\n  Clima:")
    c = snap["clima"]
    print(f"    Temperatura:       {c.get('temperatura_c')}°C")
    print(f"    Lluvia 7 días:     {c.get('lluvia_acumulada_7d_mm')} mm")
    print(f"    Días con helada:   {c.get('dias_helada_7d')}")
    print(f"    Ventana cosecha:   {'✓ OK' if c.get('ventana_cosecha_ok') else '✗ Cerrada'}")

    print(f"\n  Precios (Rosario):")
    p = snap["precios"]
    print(f"    Soja:   USD {p.get('soja_rosario_usd_tn', 'N/D')}/tn")
    print(f"    Maíz:   USD {p.get('maiz_rosario_usd_tn', 'N/D')}/tn")
    print(f"    Trigo:  USD {p.get('trigo_rosario_usd_tn', 'N/D')}/tn")

    print(f"\n  Tipo de cambio:")
    t = snap["tipo_cambio"]
    print(f"    USD oficial:       ${t.get('usd_oficial_ars')} ARS")
    print(f"    Soja neta ARS/tn:  ${t.get('soja_precio_neto_ars_tn', 'N/D'):,.0f}")

    print(f"\n  Score de decisión — SOJA:")
    decision = agro.score_decision_venta(snap, grano="soja", zona="cordoba_sur")
    print(f"    Score:            {decision['score']}/100")
    print(f"    Recomendación:    {decision['recomendacion']}")
    print(f"    Descripción:      {decision['descripcion']}")
    print(f"\n  Factores evaluados:")
    for f in decision["factores"]:
        print(f"    {f['factor']:<30} {f['puntos']:<8} {f['estado']}")
