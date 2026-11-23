import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest import mock
import requests
from data.connectors_agro import ConectorAgro, limpiar_manuales

class R:
    def __init__(s, p, st=200): s._p, s.status_code = p, st
    def json(s): return s._p
    def raise_for_status(s):
        if s.status_code >= 400: raise requests.HTTPError(str(s.status_code))

calls = []
def get(url, **kw):
    calls.append(("GET", url, kw.get("headers", {}).get("Authorization")))
    if "/symbol/I.SOJA" in url: return R({"indexValue": 338.5, "name": "I.SOJA"})
    if "/symbol/I.MAIZ" in url: return R({"indexValue": 171.2})
    if "/symbol/I.TRIGO" in url: return R({"indexValue": 205.0})
    if "dolarapi" in url: return R({"compra": 1560, "venta": 1590})
    if "ZS=F" in url: return R({"chart": {"result": [{"meta": {"regularMarketPrice": 1224.75}}]}})
    raise requests.ConnectionError("x")
def post(url, **kw):
    calls.append(("POST", url, kw["json"]))
    return R({"access": "TOK", "refresh": "R"})

# 1) sin credenciales -> sin dato, sin llamadas a MATBA
os.environ.pop("MATBA_USER", None); os.environ.pop("MATBA_PASSWORD", None)
with mock.patch("requests.get", side_effect=get), mock.patch("requests.post", side_effect=post):
    d = ConectorAgro().precios_futuros_matba()
    print("1) sin creds:", d["fuente"], "| precio:", d.get("soja_rosario_usd_tn"))
    assert "soja_rosario_usd_tn" not in d and not calls

# 2) con credenciales -> token + 3 índices, token cacheado
os.environ["MATBA_USER"], os.environ["MATBA_PASSWORD"] = "u", "p"
with mock.patch("requests.get", side_effect=get), mock.patch("requests.post", side_effect=post):
    ag = ConectorAgro()
    d = ag.precios_futuros_matba(); ag._cache.pop("matba_futuros")
    d2 = ag.precios_futuros_matba()
    print("2) con creds:", {k: v for k, v in d.items() if "usd" in k}, "| POST token:", sum(1 for c in calls if c[0]=="POST"))
    assert d["soja_rosario_usd_tn"] == 338.5 and sum(1 for c in calls if c[0]=="POST") == 1
    assert ("GET", "https://api.matbarofex.com.ar/v2/symbol/I.SOJA", "Bearer TOK") in calls

# 3) 401 -> sin dato y token descartado
def get401(url, **kw): return R({}, 401) if "matbarofex" in url else get(url, **kw)
with mock.patch("requests.get", side_effect=get401), mock.patch("requests.post", side_effect=post):
    ag = ConectorAgro(); d = ag.precios_futuros_matba()
    print("3) 401:", d["fuente"], "| token en cache:", "matba_token" in ag._cache)
    assert "soja_rosario_usd_tn" not in d and "matba_token" not in ag._cache

# 4) retenciones manuales
print("4) limpiar:", limpiar_manuales({"ret_soja_pct": "24", "ret_maiz_pct": 150, "ret_trigo_pct": -1, "ret_girasol_pct": 0}))
with mock.patch("requests.get", side_effect=get), mock.patch("requests.post", side_effect=post):
    ag = ConectorAgro()
    base = ag.snapshot_agro(manuales=None)
    man  = ag.snapshot_agro(manuales={"ret_soja_pct": 24})
    again = ag.snapshot_agro(manuales=None)
    print("   soja neto ARS/tn  default:", base["tipo_cambio"].get("soja_precio_neto_ars_tn"), "| ret 24%:", man["tipo_cambio"].get("soja_precio_neto_ars_tn"))
    print("   origen:", man["tipo_cambio"]["origen_retenciones"])
    assert man["tipo_cambio"]["soja_precio_neto_ars_tn"] > base["tipo_cambio"]["soja_precio_neto_ars_tn"]
    assert again["tipo_cambio"]["retenciones"]["soja"] == 0.33   # no contamina la cache
print("TODO OK")
