# Incendios forestales en España, 1968–2023

Los partes de incendio de la Estadística General de Incendios Forestales (EGIF) del
MITECO, con todos los años ya unificados. Todo en CSV comprimido (`.csv.gz`), UTF-8,
separador `;`.

La tabla principal cubre la mayoría de usos por sí sola. Las secundarias contienen el
detalle para quien lo necesite.

| | Qué es | Filas | Columnas |
|---|---|---|---|
| **`incendios_pif.csv.gz`** | **La tabla principal. Una fila por parte de incendio.** | 646.887 | 72 |
| [`tablas_secundarias/`](tablas_secundarias/) | 28 tablas de detalle, una por fichero | 9.965.794 | — |

Van comprimidos porque sin comprimir suman 480 MB y GitHub rechaza los ficheros de más
de 100 MB. No hace falta descomprimirlos: pandas y R los leen tal cual.

Las secundarias están organizadas según la jerarquía que define la propia base de datos
oficial del MITECO, en dos niveles:

```
incendios_pif.csv.gz                 1 fila por parte de incendio
   │
   ├── nivel_incendio/   (19)        se unen por  numeroparte
   │      RelMedioPersonalPif.csv.gz, RelTipoFuegoPif.csv.gz, …
   │
   └── nivel_monte/      (9)
          ParteMonte.csv.gz          se une por   numeroparte
             └── las otras 8         se unen por  numeroparte + idpartemonte
```

[`tablas_secundarias/_indice.csv`](tablas_secundarias/_indice.csv) lista las 28 con su
nivel, su clave de unión, sus filas y sus columnas.

```python
import pandas as pd
inc = pd.read_csv("incendios_pif.csv.gz", sep=";", dtype=str)
med = pd.read_csv("tablas_secundarias/nivel_incendio/RelMedioPersonalPif.csv.gz",
                  sep=";", dtype=str)
inc.merge(med, on="numeroparte", how="left")   # atención: duplica filas del incendio
```

Los datos son los oficiales, sin modificar: no se ha imputado, corregido ni calculado
nada. Los nombres de columna y los valores son exactamente los del origen, y los
códigos siguen siendo códigos.

---

## Lo que hay que saber antes de usarla

- **Una fila = un parte de incendio**, no un incendio físico. `numeroparte` es la clave
  y no se repite.
  La diferencia viene de que **un fuego que cruza de provincia genera dos partes**, uno
  por provincia, cada uno con la superficie que le corresponde. En la práctica afecta a
  **155 casos de 646.887 (0,024%)**: los 646.887 partes equivalen a unos 646.732
  incendios. Sumar superficies da bien de todos modos; contar incendios sobreestima en
  ese 0,024%.
  Los partes enlazados se identifican con
  [`RelAsociadoPif`](tablas_secundarias/nivel_incendio/), pero **esa tabla mezcla dos
  cosas**: de sus 6.874 enlaces, solo 155 son cruces de provincia; 6.619 son incendios
  reproducidos, que son fuegos **distintos** y no deben fusionarse. Se distinguen porque
  el reproducido lleva `idcausa = 600`.
- **Los códigos no están traducidos.** `idcausa`, `idcomunidad`, etc. son números.
  Los 61 diccionarios están en [`datos_extraidos/`](datos_extraidos/) (`CodCausa.csv`,
  `Comunidad.csv`…), y la correspondencia entre cada campo y su diccionario está en
  [`relaciones_egif.csv`](relaciones_egif.csv) (ver abajo).
  Al cruzarlos hay que **filtrar por `IdIdioma = 0`** (castellano): cada concepto está
  repetido en 6 idiomas, y sin ese filtro las filas se multiplican por seis.
- Tres diccionarios sirven para agregar: `CodGrupoCausa` + `RelGrupoCausa` reducen las
  87 causas a ~15 grupos, `CodGrupoMotivacion` + `RelGrupoMotivacion` hacen lo propio
  con las motivaciones, y `Regiones_Geograficas` agrupa los municipios en macrorregiones.
- **`numeroparte` es `AAAAPPNNNN`**: año (4) + provincia INE (2) + correlativo (4).
- **Faltan comunidades enteras en los últimos años.** No es un fallo de la descarga:
  el MITECO aún no las ha publicado. Los datos que hay son definitivos, pero la
  cobertura territorial está incompleta.
  - 2021: falta Illes Balears
  - 2022: faltan Cantabria y Navarra
  - 2023: faltan Cataluña, Canarias, Navarra, Extremadura y Ceuta
- **No compares cifras absolutas entre décadas.** El número de partes pasa de 2.038
  en 1968 a 25.557 en 1995. Las condiciones de registro no son homogéneas a lo largo
  de la serie, y este conjunto no permite separar cuánto del cambio es del registro y
  cuánto de la siniestralidad.
- **Superficies en hectáreas**, tiempos como `YYYY-MM-DDTHH:MM:SS`.

## Columnas vacías o de cobertura parcial

- **Siempre vacías**: `notas` y `numparteevento`. El exportador oficial no saca los
  campos de texto libre.
- **Existen solo desde 2016** (0% antes, 100% en 2020–2023): `puntosinicioincendio`,
  `iddatum`, `idgradoresponsabilidad`, `idinvestigacioncausa`,
  `idautorizacionactividad`, `idnivelgravedadmaximo`.
  Un vacío ahí significa "el campo no existía", no "dato perdido".
- **Coordenadas** (`x`, `y`, `latitud`, `longitud`, `huso`): 0% hasta 1997, 6% en los
  90, 75% en los 2000, 98% desde 2010. Para los años antiguos hay `hoja` y
  `cuadricula` (cuadrícula del mapa militar 1:250.000), al 100% desde 1974.
- **Otras de arranque tardío**: `controlado` (desde 1989), `idcomarcaisla` (desde
  1983), `superficienoarboladaagricola` y `superficienoarboladaotras` (útiles desde
  2016), `paraje` e `identidadmenor` (nunca superan el 83%).
- **Meteorología** (`tempmaxima`, `humrelativa`, `velocidadviento`,
  `diasultimalluvia`): cobertura irregular y **no creciente** — 27% en los 70, 64% en
  los 80, baja al 37% en los 90 y sube al 91% en los 2020.
- **Columnas que se abandonan**, relevante para cualquier serie reciente:
  - `idpeligro`: 100% hasta 2009 → 71% en los 2010 → **8% en 2020–2023**
  - `probabilidadignicion`: 100% hasta 1999 → 74% → 34% → **5%**
  - `idestacionmeteorologica`: 100% hasta 2009 → 92% → 69%

## Por qué hay tablas secundarias y no una sola tabla

La principal contiene las 12 tablas `pif_*` del parte, las únicas con exactamente un
registro por incendio. **Las otras 28 se han dejado aparte a propósito**: son
relaciones 1-a-muchos, y meterlas en la misma tabla plana obligaría a duplicar filas o
a inventar representaciones. Medido sobre los 646.887 incendios:

| Qué se une | Filas | Factor |
|---|---|---|
| Solo `pif_*` (este fichero) | 646.887 | ×1 |
| `+ ParteMonte` y sus 8 hijas | 1.475.298 | ×2,3 |
| `+` las 19 `Rel*` de nivel incendio | 6.319.858.011 | ×9.770 |
| Las 28 a la vez | 1.109.835.983.260 | ×1.715.657 |

El árbol del monte sale barato (×2,3) porque sus tablas se unen por
`numeroparte + idpartemonte`: las filas de detalle se **reparten** entre los partes de
monte en lugar de multiplicarse. Lo que dispara el total son las `Rel*` de nivel
incendio, que sí se multiplican entre sí: un incendio con 13 filas de personal, 14 de
medios aéreos y 8 de medios pesados genera 13 × 14 × 8 = 1.456 filas solo con esas
tres, y son 19 tablas.

### Cómo unir sin que se disparen las filas

Si al hacer un `merge` salen muchas más filas de las esperadas, la causa es una de dos,
y **tienen soluciones distintas**.

**1. La clave está incompleta.** Le pasa a las 8 tablas de `nivel_monte/`: su clave es
`numeroparte + idpartemonte`, y uniendo solo por `numeroparte` cada parte de monte se
cruza con el detalle de todos los demás. Se arregla añadiendo la columna que falta:

```python
pm  = pd.read_csv("tablas_secundarias/nivel_monte/ParteMonte.csv.gz", sep=";", dtype=str)
arb = pd.read_csv("tablas_secundarias/nivel_monte/RelArboladoAfectadoParteMonte.csv.gz",
                  sep=";", dtype=str)
pm.merge(arb, on=["numeroparte", "idpartemonte"])   # bien
pm.merge(arb, on="numeroparte")                     # MAL: cruza montes entre si
```

Encadenar `merge(on="numeroparte")` con las 28 tablas lleva el total de 1,1 billones de
filas a **2×10²⁰**. Solo el parte `2022120052` aportaría 1,99×10²⁰: tiene 78 partes de
monte, 320 factores de pérdida y 200 registros de arbolado.

**2. Son tablas hermanas, y no hay clave que las una.** Dos `Rel*` de `nivel_incendio/`
son listas independientes del mismo incendio. Cruzarlas produce combinaciones que no
existen, y **aquí añadir columnas no lo arregla: lo empeora**.

Ejemplo real, incendio `2022120052`: 13 filas de personal y 14 de medios aéreos.

| | Filas | |
|---|---|---|
| `merge(on="numeroparte")` | 182 | explota |
| `merge(on=["numeroparte", "idtitularidadmedio"])` | 63 | **peor**: parece arreglado |

Las dos tablas comparten `idtitularidadmedio`, así que unir por ella reduce las filas y
da resultado plausible — pero empareja *"personal de la comunidad autónoma"* con
*"avión de la comunidad autónoma"*, y **no hay ningún dato que ligue una fila con la
otra**. Es una relación inventada.

Lo correcto es **agregar cada tabla por su cuenta y unir después los resultados**:

```python
per = (pd.read_csv("tablas_secundarias/nivel_incendio/RelMedioPersonalPif.csv.gz", sep=";")
         .groupby("numeroparte")["numero"].sum().rename("personal_total"))
inc.merge(per, on="numeroparte", how="left")    # una fila por parte, sin duplicar
```

### Las 28 tablas secundarias

Una por fichero en [`tablas_secundarias/`](tablas_secundarias/), repartidas en
`nivel_incendio/` y `nivel_monte/` según la jerarquía oficial, con todos los años ya
concatenados. `cols` = columnas; `%` = incendios que tienen al menos una fila;
`máx` = mayor número de filas visto en un solo incendio.

**El monte** (hojas 4–6 del parte)

| Tabla | Contenido | cols | % | máx |
|---|---|---|---|---|
| `ParteMonte` | Una hoja por municipio × tipo de propiedad: monte afectado, titularidad, protector/consorciado, totales económicos | 23 | 100 | 78 |
| `RelArboladoAfectadoParteMonte` | Especies arbóreas afectadas, FCC y estado de la masa | 7 | 40 | 200 |
| `RelNoArboladoLeniosoParteMonte` | Monte abierto (FCC<20%) y matorral, con superficie | 2 | 62 | 125 |
| `RelNoArboladoHerbaceoParteMonte` | Dehesas, pastizales y zonas húmedas | 2 | 17 | 72 |
| `RelNoForestalAfectadoParteMonte` | Superficie agrícola, militar y urbana quemada | 2 | 5 | 53 |

**Medios y técnicas de extinción** (apartados 7 y 8)

| Tabla | Contenido | cols | % | máx |
|---|---|---|---|---|
| `RelMedioPersonalPif` | Nº de personas por categoría (técnicos, agentes, brigadas…) y administración | 3 | 93 | 15 |
| `RelMedioPesadoPif` | Autobombas, bulldozer, tractores, nodrizas… por administración | 3 | 64 | 24 |
| `RelMedioAereoPif` | Aeronaves por tipo, con descargas y brigadas transportadas | 5 | 16 | 14 |
| `RelTransportePersonalPif` | Cómo llegó el personal: vehículos, helicópteros o sin personal | 1 | 100 | 2 |
| `RelGrupoMedioRetardantePif` | Qué medios usaron retardante (terrestres, aéreos, ninguno) | 1 | 100 | 2 |
| `RelRetardantePif` | Tipo de retardante: amónicos, espumantes, viscosantes | 1 | 13 | 3 |
| `RelAtaquePif` | Ataque directo, indirecto o sin actuación | 1 | 100 | 2 |
| `RelTipoAtaqueIndirectoPif` | Cortafuegos, contrafuego, quemas de ensanche | 1 | 4 | 3 |

**Inicio, condiciones y propagación** (apartados 3, 5 y 6)

| Tabla | Contenido | cols | % | máx |
|---|---|---|---|---|
| `RelModeloCombustionPif` | Combustible de la zona: pastizales, matorrales, bosques, restos | 1 | 100 | 4 |
| `RelModeloCombustionCampoPif` | Modelo de combustible detallado. **Códigos 1–13, catálogo distinto del anterior** | 1 | 1 | 13 |
| `RelTipoFuegoPif` | De superficie, de copas, de subsuelo, focos secundarios | 1 | 100 | 4 |
| `RelIniciadoJuntoAPif` | Junto a qué se inició: carretera, vía férrea, línea eléctrica, vertedero… | 1 | 100 | 6 |
| `RelTipoAreaIniciadoPif` | Tipo de área de inicio: agrícola, ganadera, militar, urbana, forestal | 1 | 15 | 5 |

**Pérdidas e incidencias** (apartados 9, 10 y 12)

| Tabla | Contenido | cols | % | máx |
|---|---|---|---|---|
| `RelPerdidaMontePif` | Superficie arbolada y no arbolada por tipo de propiedad. **Suma exactamente el total del incendio** | 3 | 96 | 4 |
| `RelVictimaPif` | Fallecidos y heridos, dentro y fuera del dispositivo de extinción | 3 | 1 | 4 |
| `RelIncidenciasProtecCivilPif` | Cortes de carretera, línea férrea, luz, teléfono; evacuaciones; daños | 1 | 1 | 6 |
| `RelEspacioProtegidoPif` | Espacios protegidos afectados y superficie quemada dentro de cada uno | 6 | 5 | 6 |
| `RelAsociadoPif` | Nº de parte asociado: enlaza incendios reproducidos y los que cruzan de provincia | 1 | 1 | 3 |

**Valoración económica y cartografía** (anexos)

| Tabla | Contenido | cols | % | máx |
|---|---|---|---|---|
| `RelFactorCalculoPerdidaParteMonte` | Peritaje de madera: especie, edad, volúmenes, precios | 15 | 38 | 320 |
| `RelOtraPerdidaParteMonte` | Pérdidas por aprovechamiento: corcho, resinas, setas, leñas, pastos, caza | 2 | 13 | 108 |
| `RelFactorProductoOtrosParteMonte` | Superficie afectada de corcho, resinas, frutos y setas | 2 | 1 | 20 |
| `RelFactorRentaParteMonte` | Superficie afectada de leña, pastos y caza | 2 | 2 | 61 |
| `RelTeselaAfectadaPif` | Teselas del Mapa Forestal Español. **La fuente oficial la declara orientativa**: prevalece el Parte de Monte | 15 | 2 | 610 |

## Cómo unirlo todo: `relaciones_egif.csv`

La correspondencia entre campos no está inferida: la plantilla Access oficial del MITECO
lleva **155 relaciones definidas dentro**, y están extraídas en
[`relaciones_egif.csv`](relaciones_egif.csv) — 172 filas, una por par de campos:

| columna | qué es |
|---|---|
| `tipo` | `union_parte`, `catalogo` o `entre_catalogos` |
| `tabla`, `campo` | dónde está el código |
| `referencia_tabla`, `referencia_campo` | con qué se une |
| `etiqueta` | columna del catálogo que lleva el texto legible |
| `campos_en_la_clave`, `id_relacion` | si es >1, la clave es **compuesta**: hay que unir por todos los campos que compartan `id_relacion`, no por uno suelto |
| `nota` | anomalías de la propia plantilla |

Lo que dicen esas relaciones, resumido:

- **`Pif` es el eje.** Las 12 `pif_*`, las 19 `Rel*Pif` y `ParteMonte` se unen todas por
  `numeroparte`.
- **Las 8 `Rel*ParteMonte` cuelgan de `ParteMonte`, no de `Pif`**, y con clave
  compuesta `numeroparte + idpartemonte`.
- **Las búsquedas geográficas son compuestas.** `idmunicipio` no basta: hace falta
  `idcomunidad + idprovincia + idmunicipio`. Igual `idcomarcaisla` (necesita
  `idcomunidad`) e `identidadmenor` (necesita los tres anteriores).
- **Todos los catálogos `Cod*` se unen a `CodIdioma`**, que es la razón estructural de
  que haya que filtrar por idioma.

Dos erratas de la plantilla, ya marcadas en la columna `nota`:

- `RelTeselaAfectadaPif.IdEstado3` está mapeado a la vez a `CodEstadoMasa` y a
  `CodEspecieArbol`. Lo coherente con `IdEstado1` e `IdEstado2` es `CodEstadoMasa`.
- La relación de `RelTipoAtaqueIndirectoPif` está invertida: aparece como tabla
  principal y `Pif` como dependiente, al revés que las otras 18.

Y una ausencia: **`RelModeloCombustionCampoPif` no tiene ninguna relación definida**,
coherente con el aviso de más abajo sobre su codificación.

Dos avisos sobre estas tablas:

- `RelModeloCombustionCampoPif` y `RelModeloCombustionPif` comparten el nombre de campo
  `idmodelocombustion` pero **no la codificación**: la primera usa 13 modelos y la
  segunda los 4 grupos del catálogo `CodModeloCombustion`. No deben cruzarse con el mismo
  diccionario.
- Los códigos de `idespacioprotegido` cambiaron por completo al adoptarse el código
  europeo `SITE_CODE_NAT`, así que **no son comparables a lo largo de toda la serie**.

## Origen y reproducción

No hay API. Los dos insumos se descargan a mano, y de sitios distintos.

**1. Los datos** — del **buscador de partes de incendio**, en
[servicio.mapa.gob.es/incendios/Search/Publico](https://servicio.mapa.gob.es/incendios/Search/Publico).
Se consulta acotando por años y territorio, y se exporta en **XML (Pif/Monte)**, no en
el resumen de Excel, con **todos los capítulos marcados**. Conviene pedir rangos de años
disjuntos de unos 100.000 incendios por consulta: por encima de ~120.000 la herramienta
falla. Los ZIP resultantes van a `datos_egif/`.

**2. La base de datos Access** (`PlantillaEgifWebDetalle.mdb`) — de ella salen los
diccionarios de códigos y las relaciones entre tablas. Se descarga desde el propio
buscador, y es la parte menos evidente del proceso porque **no está enlazada en la
página principal**:

> En el buscador, el **botón de ayuda — el icono de información, una "ℹ"** — abre el
> panel *Documentación Egif Web*. Ahí está el enlace **"Plantilla Access de importación
> XML"**.

Enlace directo, sin login:
`https://servicio.mapa.gob.es/incendios/Content/templates/PlantillaEgifWebDetalle.zip`

La versión usada aquí está fechada el **21-03-2025**. El `.mdb` no se incluye en este
repositorio: es un fichero del ministerio y pesa 19,7 MB. Lo que sí se publica es el
resultado de procesarlo — los 61 catálogos de [`datos_extraidos/`](datos_extraidos/) y
las relaciones de [`relaciones_egif.csv`](relaciones_egif.csv) —, que es lo que evita
tener que abrir Access. La descarga solo hace falta para regenerarlos.

### Documentación oficial

Aquí no se redistribuye ningún documento del ministerio. Están publicados en
**[MITECO · Incendios forestales: estadísticas y datos](https://www.miteco.gob.es/es/biodiversidad/temas/incendios-forestales/estadisticas-datos.html)**,
que es la página general de incendios forestales, distinta del buscador de partes del
que salen los datos y la plantilla Access.

Los dos primeros son los más útiles para interpretar las columnas:

| Documento | Para qué sirve |
|---|---|
| **Modelo de Parte de Incendio Forestal** | El formulario **anotado con el nombre de tabla y columna de cada casilla**. Es el diccionario de campos hecho por la propia fuente, y la referencia para saber qué significa una columna. |
| **Instrucciones de relleno del parte** | Define campo a campo qué se anota y cómo, con los casos particulares. Explica cosas que cambian un análisis: qué cuenta como incendio forestal, el umbral de FCC ≥ 20% para "arbolado", que el personal se cuenta en personas y no en jornales… |
| **Interpretación de la base de datos EGIF** | Cómo se organizan las familias de tablas (`pif_*`, `Rel*`, `Cod*`) y cómo relacionarlas. |
| **Ayuda del buscador EGIF** | Manual de la herramienta de descarga y sus límites de exportación. |

Tres erratas conocidas del *Modelo de Parte*, ya verificadas contra el esquema real:
donde pone `RelTipoTransportePersonalPif` es `RelTransportePersonalPif`; donde pone
`RelTipoAtaqueIndirecto` es `RelTipoAtaqueIndirectoPif`; y donde repite
`superficielenosa` para dos casillas distintas son en realidad `superficielenosa` y
`superficieherbacea`.

### Cómo regenerarlo todo

**El orden importa**: cada paso usa la salida del anterior.

```bash
python scripts/extraer_relaciones.py                   # .mdb -> relaciones_egif.csv
python scripts/extraccion_access.py --solo-necesarios  # .mdb -> datos_extraidos/
python scripts/unir_pif.py                             # XML  -> incendios_pif.csv
python scripts/tablas_secundarias.py                   # XML  -> tablas_secundarias/
python scripts/verificar.py --exhaustivo               # comprueba todo contra el XML
python scripts/comprimir.py                            # .csv -> .csv.gz
```

Se ejecutan desde la raíz del proyecto; los scripts localizan los datos por sí solos.

`relaciones_egif.csv` va primero porque los dos pasos siguientes lo leen: uno para
saber qué catálogos hacen falta y otro para saber en qué nivel va cada tabla. Si falta,
avisan y paran en vez de adivinar.

`comprimir.py` va el último porque `verificar.py` trabaja sobre los CSV sin comprimir.
Verifica cada fichero por SHA-256 antes de borrar el original, y aborta si al
descomprimir no se recupera exactamente el mismo contenido.

Los pasos que recorren los XML tardan 1–2 minutos cada uno; `verificar.py --exhaustivo`,
unos 6. El resto, segundos.

### Requisitos

- **Python 3 de 64 bits** y el driver ODBC de Access **también de 64 bits**. La
  arquitectura de ambos tiene que coincidir: es el fallo típico con ficheros `.mdb`.
- `pip install -r requirements.txt` → solo `pyodbc` y `pywin32`, y **solo para leer el
  `.mdb`**. `pywin32` hace falta porque las relaciones no se pueden leer por ODBC: el
  driver no implementa `SQLForeignKeys` y Access protege sus tablas de sistema, así que
  se leen vía DAO.
- Los scripts que construyen las tablas desde los XML (`unir_pif.py`,
  `tablas_secundarias.py`, `verificar.py`) **no tienen ninguna dependencia externa**:
  solo biblioteca estándar.

### Verificación

`verificar.py` comprueba contra los XML de origen que no se ha perdido ni alterado nada.
Con `--exhaustivo` compara **todos los valores publicados**, no una muestra:

| Comprobación | Resultado |
|---|---|
| Campos del esquema presentes en alguna tabla | 257 / 257 |
| Filas de la principal vs incendios en el XML | 646.887 = 646.887 |
| Filas de las 28 secundarias vs XML | 9.965.794 = 9.965.794 |
| `numeroparte` único; `(numeroparte, idpartemonte)` único en `ParteMonte` | sin duplicados |
| Filas huérfanas al unir por las claves documentadas | ninguna |
| Textos con mojibake | ninguno |
| **Valores idénticos al XML** | **108.832.989 / 108.832.989** |

Valida además la regla del formulario oficial —las superficies por titularidad deben
sumar el total del incendio—, que se cumple en el 99,9997%. Los 23 incendios que fallan
son errores del dato publicado por el MITECO, y el script los marca como aviso, no como
fallo del proceso.

Licencia de los datos: los del MITECO. Cita la fuente original.
