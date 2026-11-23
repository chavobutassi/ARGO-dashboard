"""Regresión: factores CBOT centavos/bushel → USD/tn (bug previo: 10x de menos)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.unidades import (
    FACTOR_CENTAVOS_BU_A_USD_TN,
    centavos_bu_a_usd_tn,
    es_plausible,
)


def test_soja_1225_centavos_son_450_usd_tn():
    assert abs(centavos_bu_a_usd_tn("soja", 1224.75) - 450.0) < 0.1


def test_maiz_y_trigo_en_orden_de_magnitud_correcto():
    assert 150 < centavos_bu_a_usd_tn("maiz", 447.75) < 200
    assert 200 < centavos_bu_a_usd_tn("trigo", 593.5) < 250


def test_factores_no_regresan_al_valor_viejo():
    assert FACTOR_CENTAVOS_BU_A_USD_TN["soja"] > 0.3
    assert FACTOR_CENTAVOS_BU_A_USD_TN["maiz"] > 0.3


def test_guarda_de_plausibilidad_rechaza_errores_de_unidad():
    assert es_plausible("soja", 450.0)
    assert not es_plausible("soja", 44.95)    # lo que mostraba el dashboard
    assert not es_plausible("maiz", 17.64)
    assert not es_plausible("trigo", 21.81)


if __name__ == "__main__":
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("ok", nombre)
