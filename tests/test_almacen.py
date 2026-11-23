import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest import mock

import requests

from data.almacen_manual import AlmacenManual


class R:
    def __init__(self, payload=None, st=200):
        self._p, self.status_code = payload, st

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


# 1) sin configuración: no hace ninguna llamada
for var in ("SUPABASE_URL", "SUPABASE_SECRET_KEY"):
    os.environ.pop(var, None)
a = AlmacenManual()
with mock.patch("requests.get") as g, mock.patch("requests.post") as p:
    assert not a.disponible and a.leer() == {} and a.guardar({"usd_oficial_ars": 1}) is False
    assert not g.called and not p.called
print("1) sin config: ok")

# 2) leer: normaliza y descarta valores inválidos
a = AlmacenManual("https://x.supabase.co/", "SECRET")
filas = [{"clave": "usd_oficial_ars", "valor": 1600}, {"clave": "gasoil_ars_litro", "valor": -5},
         {"clave": "clave_desconocida", "valor": 3}]
with mock.patch("requests.get", return_value=R(filas)) as g:
    assert a.leer() == {"usd_oficial_ars": 1600.0}
    url = g.call_args[0][0]
    hdr = g.call_args[1]["headers"]
    assert url == "https://x.supabase.co/rest/v1/argo_valores_manuales?select=clave,valor"
    assert hdr["apikey"] == "SECRET" and hdr["Authorization"] == "Bearer SECRET"
print("2) leer: ok")

# 3) guardar: upsert de los cargados y delete de los vacíos
with mock.patch("requests.post", return_value=R()) as p, mock.patch("requests.delete", return_value=R()) as d:
    ok = a.guardar({"usd_oficial_ars": "1600", "flete_ars_tn": None, "ret_soja_pct": ""})
    assert ok
    assert p.call_args[0][0].endswith("?on_conflict=clave")
    assert p.call_args[1]["json"] == [{"clave": "usd_oficial_ars", "valor": 1600.0}]
    assert "merge-duplicates" in p.call_args[1]["headers"]["Prefer"]
    assert d.call_args[0][0].endswith("?clave=in.(flete_ars_tn,ret_soja_pct)")
print("3) guardar: ok")

# 4) error de red: no revienta
with mock.patch("requests.get", side_effect=requests.ConnectionError("x")), \
        mock.patch("requests.post", side_effect=requests.ConnectionError("x")):
    assert a.leer() == {} and a.guardar({"usd_oficial_ars": 1}) is False
print("4) errores: ok")

# 5) callbacks del dashboard con el almacén activo
with mock.patch("requests.get", side_effect=requests.ConnectionError("sin red")):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard"))
    import app
fake = mock.Mock()
fake.leer.return_value = {"usd_oficial_ars": 1600.0, "flete_ars_tn": 38000.0}
fake.guardar.return_value = True
with mock.patch.object(app, "ALMACEN_ACTIVO", True), mock.patch.object(app, "_almacen", fake):
    vals = app.cargar_valores_manuales(0)
    claves = [c for _, c in app.CAMPOS_MANUALES]
    assert vals[claves.index("usd_oficial_ars")] == 1600.0 and vals[claves.index("soja_rosario_usd_tn")] is None
    msg = app.guardar_valores_manuales(*[1600.0 if c == "usd_oficial_ars" else None for c in claves])
    assert msg.startswith("Guardado") and fake.guardar.call_args[0][0]["usd_oficial_ars"] == 1600.0
    fake.guardar.return_value = False
    assert "No se pudo" in app.guardar_valores_manuales(*[None] * len(claves))
with mock.patch.object(app, "ALMACEN_ACTIVO", False):
    for fn, args in ((app.cargar_valores_manuales, (0,)), (app.guardar_valores_manuales, [None] * len(app.CAMPOS_MANUALES))):
        try:
            fn(*args)
            raise AssertionError("debía lanzar PreventUpdate")
        except app.dash.exceptions.PreventUpdate:
            pass
print("5) callbacks: ok")
print("TODO OK")
