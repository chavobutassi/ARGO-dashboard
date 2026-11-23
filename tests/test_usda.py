import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest import mock
import requests
from data.connectors_global import ConectorGlobal

class R:
    def __init__(s, p, st=200): s._p, s.status_code = p, st
    def json(s): return s._p
    def raise_for_status(s):
        if s.status_code >= 400: raise requests.HTTPError(str(s.status_code))

def mk(pascal):
    K = (lambda k: k[0].upper()+k[1:]) if pascal else (lambda k: k)
    commodities = [{K("commodityCode"): "0440000", K("commodityName"): "Corn"},
                   {K("commodityCode"): "2222000", K("commodityName"): "Oilseed, Soybean"},
                   {K("commodityCode"): "0410000", K("commodityName"): "Wheat"}]
    attrs = [{K("attributeId"): 28, K("attributeName"): "Production"},
             {K("attributeId"): 176, K("attributeName"): "Ending Stocks"},
             {K("attributeId"): 125, K("attributeName"): "Domestic Consumption"},
             {K("attributeId"): 88, K("attributeName"): "Exports"}]
    world = [{K("attributeId"): 28, K("value"): 425000.0}, {K("attributeId"): 176, K("value"): 120000.0},
             {K("attributeId"): 125, K("value"): 415000.0}, {K("attributeId"): 88, K("value"): 190000.0}]
    seen = []
    def get(url, **kw):
        seen.append((url, kw.get("headers", {}).get("API_KEY")))
        if url.endswith("/api/psd/commodities"): return R(commodities)
        if url.endswith("/api/psd/commodityAttributes"): return R(attrs)
        if "/world/year/2026" in url: return R(world)
        if "/world/year/" in url: return R([])          # MY 2027 todavía vacío
        raise requests.ConnectionError(url)
    return get, seen

for pascal in (False, True):
    os.environ["USDA_API_KEY"] = "K123"
    get, seen = mk(pascal)
    with mock.patch("requests.get", side_effect=get):
        u = ConectorGlobal().oferta_demanda_usda("soja")
    print(("PascalCase" if pascal else "camelCase"), "->", {k: u[k] for k in ("año","campaña","produccion_global_mm_tn","stocks_finales_mm_tn","ratio_stocks_uso_pct","señal_stocks")})
    assert u["campaña"] == "2026/27" and u["produccion_global_mm_tn"] == 425.0 and u["ratio_stocks_uso_pct"] == 28.9
    assert u["señal_stocks"] == "HOLGADO" and all(h == "K123" for _, h in seen)
    assert any("/commodity/2222000/world/year/2026" in url for url, _ in seen)   # soja -> 2222000 (lookup)

os.environ.pop("USDA_API_KEY")
with mock.patch("requests.get", side_effect=requests.ConnectionError("x")) as m:
    u = ConectorGlobal().oferta_demanda_usda("soja")
    print("sin clave ->", u["fuente"], "| producción:", u.get("produccion_global_mm_tn"), "| llamadas:", m.call_count)
    assert u["referencia"] and "produccion_global_mm_tn" not in u and m.call_count == 0

os.environ["USDA_API_KEY"] = "K"
with mock.patch("requests.get", side_effect=requests.ConnectionError("x")):
    u = ConectorGlobal().oferta_demanda_usda("trigo")
    print("API caída ->", u["fuente"], u["campaña"])
    assert u["referencia"]
print("TODO OK")
