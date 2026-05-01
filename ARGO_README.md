# ARGO — Adaptive Risk & Global Operations

> **Plataforma de Inteligencia Operacional** · Metodología táctica aplicada a negocios · Multi-industria · Open source

---

```
Score operacional global   57/100  ████████████░░░░░░░░  ALTO

  Sequía crítica           71/100  ██████████████░░░░░░  ALTO
  Helada fuera temporada   54/100  ██████████░░░░░░░░░░  MEDIO
  Caída precio commodity   49/100  █████████░░░░░░░░░░░  MEDIO
  Demora logística cosecha 47/100  █████████░░░░░░░░░░░  MEDIO

⚠  ALERTA: Sequía crítica — precipitación acumulada 12mm [umbral: 20mm].
   Monitoreo reforzado. Preparar respuesta de contingencia.
```

---

## ¿Qué es ARGO?

ARGO es una plataforma parametrizada de análisis de riesgo operacional que **se adapta a cualquier empresa cambiando un archivo de configuración**.

El motor evalúa cada riesgo con cuatro variables:

| Variable | Descripción | Peso |
|---|---|---|
| **P** Probabilidad | Ajustada por indicadores en tiempo real | 35% |
| **I** Impacto | Sobre la operación en caso de materializarse | 40% |
| **V** Velocidad | Tiempo de materialización — cuánto hay para reaccionar | 15% |
| **M** Mitigación | Capacidad de respuesta disponible | 10% |

El resultado es un **SITREP** (Situation Report) ejecutivo: un número, un nivel, y qué hacer.

---

## Demo en vivo

| Industria | Score actual | Link |
|---|---|---|
| 🚛 Logística / Transporte | Ver demo | [argo-logistica.onrender.com](https://argo-logistica.onrender.com) |
| 🌾 Agro / Cooperativas | Ver demo | [argo-agro.onrender.com](https://argo-agro.onrender.com) |
| ⛽ Energía / Oil & Gas | Ver demo | [argo-energia.onrender.com](https://argo-energia.onrender.com) |
| 🏥 Salud / Hospitales | Ver demo | [argo-salud.onrender.com](https://argo-salud.onrender.com) |

---

## Instalación en 3 pasos

```bash
# 1. Clonar
git clone https://github.com/tu-usuario/argo.git && cd argo

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Correr con tu empresa
python main.py --config config/tu_empresa.json
```

Dashboard disponible en `http://localhost:8050`

---

## Agregar una empresa nueva

```bash
python wizard.py
```

El asistente hace 10 preguntas y genera el config automáticamente:

```
  1. Nombre de la empresa:     Cooperativa Agropecuaria Pampa Sur
  2. Sector:                   agro
  3. País:                     Argentina
  4. Email para alertas:       gerencia@cooperativa.com.ar
  5. Capacidad (hectáreas):    8500
  6. Umbral operación normal:  85%
  7. Frecuencia de análisis:   diaria
  8. Riesgos a monitorear:     4
  9. Score de alerta:          45
  10. Score crítico:           70

  ✓ Config generado: config/cooperativa_agropecuaria_pampa_sur.json
  ✓ Empresa lista para analizar en ARGO.
```

---

## Análisis de escenarios (Monte Carlo)

ARGO puede simular **10.000 escenarios** para responder:
*"¿Qué pasa si el clima y el combustible fallan al mismo tiempo?"*

```python
from core.simulador import SimuladorMonteCarlo
from core.risk_scorer import LecturaIndicador

sim = SimuladorMonteCarlo("config/transportadora_ejemplo.json")
resultado = sim.simular(lecturas, n_simulaciones=10_000)

print(f"Escenario esperado  (P50): {int(resultado.p50*100)}/100")
print(f"Escenario adverso   (P90): {int(resultado.p90*100)}/100")
print(f"Probabilidad CRÍTICO:      {int(resultado.prob_critico*100)}%")
```

```
  Escenario esperado  (P50):  48/100
  Escenario adverso   (P90):  51/100
  Probabilidad CRÍTICO:        0%

  RECOMENDACIÓN: Situación controlada. Monitoreo rutinario suficiente.
```

---

## Datos en tiempo real (APIs públicas, sin costo)

```python
from data.connectors import ConectorDatos

datos = ConectorDatos()
clima      = datos.clima_actual(lat=-34.6, lon=-58.4)   # Open-Meteo
precios    = datos.precios_commodities()                 # Yahoo Finance
tipo_cambio = datos.tipo_cambio_bcra()                  # API BCRA oficial
```

| Fuente | Datos | Costo |
|---|---|---|
| Open-Meteo | Temperatura, lluvia, viento — cualquier coordenada | Gratis |
| Yahoo Finance | Soja, maíz, trigo, petróleo | Gratis |
| BCRA API | Tipo de cambio oficial Argentina | Gratis |

---

## Estructura del proyecto

```
argo/
├── core/
│   ├── engine.py          # Motor central — orquesta el análisis
│   ├── risk_scorer.py     # Scoring de riesgo individual (fórmula táctica P·I·V·M)
│   └── simulador.py       # Monte Carlo — análisis de escenarios
├── data/
│   └── connectors.py      # APIs públicas: clima, precios, tipo de cambio
├── dashboard/
│   └── app.py             # Interfaz visual (Plotly Dash)
├── config/
│   ├── transportadora_ejemplo.json
│   ├── agro_ejemplo.json
│   └── ypf_vaca_muerta.json
├── wizard.py              # Generador de config en 10 preguntas
└── main.py                # Punto de entrada
```

---

## Sectores soportados

| Sector | Riesgos incluidos | KPI principal |
|---|---|---|
| `logistica` | Clima, combustible, flota, personas | OTIF |
| `agro` | Sequía, helada, precio commodity, logística | Rendimiento tn/ha |
| `mineria` | Equipos, seguridad, clima extremo, rotación | Disponibilidad mecánica |
| `retail` | Stock, proveedores, demanda, sistemas | Fill rate |
| `salud` | Insumos, capacidad, guardias, sistemas | Tiempo de respuesta |
| `energia` | Producción, precios, clima, conflicto laboral | Producción diaria |

---

## Personalización del config

```json
{
  "empresa": {
    "nombre": "Mi Empresa S.A.",
    "sector": "logistica"
  },
  "riesgos": [
    {
      "id": "LOG-001",
      "nombre": "Corte de ruta por clima",
      "probabilidad_base": 0.30,
      "impacto_base": 0.80,
      "umbrales": {
        "precipitacion_mm": { "alerta": 30, "critico": 60 }
      }
    }
  ],
  "alertas": {
    "email_destino": "operaciones@miempresa.com",
    "score_umbral_critico": 0.75
  }
}
```

---

## ¿Por qué ARGO?

La mayoría de los sistemas de análisis de riesgo son caros, rígidos o requieren implementación larga. ARGO es diferente:

- **Parametrizado** — un archivo JSON por empresa, mismo motor para todas
- **Tiempo real** — conectado a datos públicos sin costo
- **Accionable** — no solo muestra números, recomienda qué hacer
- **Rápido de implementar** — empresa nueva lista en menos de 48 horas
- **Open source** — auditeable, extendible, sin vendor lock-in

---

## Licencia

MIT — libre para usar, modificar y distribuir.

---

## Contacto

¿Querés implementar ARGO en tu empresa o tenés preguntas?

**LinkedIn:** [linkedin.com/in/tu-perfil](https://linkedin.com/in/tu-perfil)

---

*ARGO — Del griego Ἀργώ, el navío que navegó aguas peligrosas. Nosotros también.*
