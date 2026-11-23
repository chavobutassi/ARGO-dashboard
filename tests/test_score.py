import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest import mock
import requests
from data.connectors_agro import ConectorAgro

class R:
    def __init__(s, p, st=200): s._p, s.status_code = p, st
    def json(s): return s._p
    def raise_for_status(s):
        if s.status_code >= 400: raise requests.HTTPError(str(s.status_code))

def serie(minimo, maximo, n=250):
    # serie determinística que recorre el rango (ondas), n ruedas
    return [minimo + (maximo - minimo) * (0.5 + 0.5 * math.sin(i / 7.0)) for i in range(n)]

def yahoo(precio, cierres):
    return R({"chart": {"result": [{"meta": {"regularMarketPrice": precio},
                                    "indicators": {"quote": [{"close": cierres}]}}]}})

def get_factory(precio_soja_c, cierres_c, with_hist=True):
    def get(url, **kw):
        if "ZS=F" in url: return yahoo(precio_soja_c, cierres_c if with_hist else [])
        if "ZC=F" in url: return yahoo(447.75, serie(380, 480))
        if "ZW=F" in url: return yahoo(593.5, serie(520, 640))
        if "dolarapi" in url: return R({"compra": 1560, "venta": 1590})
        if "open-meteo" in url:
            return R({"current": {"temperature_2m": 20, "relative_humidity_2m": 60, "precipitation": 0, "wind_speed_10m": 10, "time": "t"},
                      "daily": {"precipitation_sum": [0]*7, "temperature_2m_min": [8]*7,
                                "et0_fao_evapotranspiration": [3]*7, "precipitation_probability_max": [10]*7}})
        raise requests.ConnectionError("x")
    return get

def run(precio_c, hist, man, with_hist=True):
    ag = ConectorAgro()
    with mock.patch("requests.get", side_effect=get_factory(precio_c, hist, with_hist)):
        snap = ag.snapshot_agro(-33.5, -63.5, "cordoba_sur", manuales=man)
        return snap, ag.score_decision_venta(snap, "soja", "cordoba_sur")

def show(tag, d):
    print(f"{tag}: {d['score']}/100 {d['recomendacion']} (cobertura {d['cobertura_pts']})")
    for f in d["factores"]: print("    ", f["factor"], "|", f["puntos"], "|", f["valor"])

hist = serie(1000, 1300)            # centavos/bu: rango 12m ~ USD 367–478/tn
base = {"soja_rosario_usd_tn": 340, "flete_ars_tn": 38000}

# A) precio alto en el año + Rosario sobre paridad + flete razonable
snap, d = run(1290, hist, base); show("A alto", d)
pa = snap["precios_chicago"]["soja_percentil_12m"]; assert pa >= 70, pa
assert d["recomendacion"] == "VENDER" and d["cobertura_pts"] == 100 - 0  # precio30+brecha20+ventana25+flete25
# B) precio en el piso del año
snap, d = run(1005, hist, base); show("B bajo", d)
assert snap["precios_chicago"]["soja_percentil_12m"] < 20 and d["score"] < 70
# C) Rosario con descuento fuerte vs paridad
snap, d = run(1290, hist, {**base, "soja_rosario_usd_tn": 250}); show("C Rosario descontado", d)
f = [x for x in d["factores"] if x["factor"].startswith("Rosario vs")][0]; assert f["puntos"].startswith("2/") or f["puntos"].startswith("0/") or f["puntos"] == "2/20", f
# D) la retención mueve la paridad: con 0% de retención Rosario 340 queda descontado
snap, d = run(1290, hist, {**base, "ret_soja_pct": 0}); show("D retención 0%", d)
f0 = [x for x in d["factores"] if x["factor"].startswith("Rosario vs")][0]
assert snap["brecha_chicago_rosario"]["ratio_paridad_soja"] < 0.95, snap["brecha_chicago_rosario"]
# E) sin flete cargado -> N/D (no se asume nada)
snap, d = run(1290, hist, {"soja_rosario_usd_tn": 340}); show("E sin flete", d)
assert [x for x in d["factores"] if x["factor"] == "Costo logístico"][0]["puntos"] == "N/D" and d["cobertura_pts"] == 75
# F) sin historia -> factor precio N/D
snap, d = run(1290, hist, base, with_hist=False); show("F sin historia", d)
assert [x for x in d["factores"] if x["factor"].startswith("Precio")][0]["puntos"] == "N/D"
# G) TC informativo no suma
assert [x for x in d["factores"] if x["factor"] == "Tipo de cambio"][0]["puntos"] == "info"
# H) el umbral de Rosario "300" ya no decide: mismo score con Rosario 340 o 400 si ambos >= paridad*1.05 (301.5*1.05=316.6)
_, d1 = run(1290, hist, {**base, "soja_rosario_usd_tn": 340}); _, d2 = run(1290, hist, {**base, "soja_rosario_usd_tn": 400})
assert d1["score"] == d2["score"]
print("TODO OK")
