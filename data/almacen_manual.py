"""
ARGO — Almacén de valores manuales en Supabase (tabla argo_valores_manuales).

Configuración por variables de entorno (solo servidor, nunca en el navegador):
  SUPABASE_URL         https://<ref>.supabase.co
  SUPABASE_SECRET_KEY  secret key / service role (la tabla tiene RLS sin policies)

Sin configuración, `disponible` es False y el dashboard usa el almacenamiento
local del navegador como antes. El esquema está en db/argo_valores_manuales.sql.
"""

import logging
import os
from typing import Optional

import requests

from data.connectors_agro import limpiar_manuales

log = logging.getLogger("argo.almacen")

TABLA = "argo_valores_manuales"
TIMEOUT = 8


class AlmacenManual:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SECRET_KEY", "")

    @property
    def disponible(self) -> bool:
        return bool(self.url and self.key)

    def _headers(self, extra: Optional[dict] = None) -> dict:
        return {"apikey": self.key, "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json", **(extra or {})}

    def leer(self) -> dict:
        """Valores guardados {clave: valor}. Vacío si no hay configuración o falla."""
        if not self.disponible:
            return {}
        try:
            resp = requests.get(f"{self.url}/rest/v1/{TABLA}?select=clave,valor",
                                headers=self._headers(), timeout=TIMEOUT)
            resp.raise_for_status()
            return limpiar_manuales({f["clave"]: f["valor"] for f in resp.json()})
        except Exception as e:
            log.warning(f"Almacén manual no disponible al leer ({e})")
            return {}

    def guardar(self, valores: dict) -> bool:
        """
        Sincroniza el estado: upsert de los valores informados y borrado de los
        vacíos. `valores` es {clave: valor | None | ""}. True si se guardó.
        """
        if not self.disponible:
            return False
        try:
            limpios = limpiar_manuales(valores)
            if limpios:
                resp = requests.post(
                    f"{self.url}/rest/v1/{TABLA}?on_conflict=clave",
                    json=[{"clave": k, "valor": v} for k, v in limpios.items()],
                    headers=self._headers(
                        {"Prefer": "resolution=merge-duplicates,return=minimal"}),
                    timeout=TIMEOUT)
                resp.raise_for_status()
            vacias = [k for k in valores if k not in limpios]
            if vacias:
                lista = ",".join(vacias)
                resp = requests.delete(
                    f"{self.url}/rest/v1/{TABLA}?clave=in.({lista})",
                    headers=self._headers({"Prefer": "return=minimal"}),
                    timeout=TIMEOUT)
                resp.raise_for_status()
            return True
        except Exception as e:
            log.warning(f"Almacén manual no disponible al guardar ({e})")
            return False
