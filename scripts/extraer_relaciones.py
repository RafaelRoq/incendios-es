"""
Extrae las 155 relaciones que el MITECO dejo definidas dentro de la plantilla Access.

Son la documentacion oficial de como se unen las tablas y de que catalogo decodifica
cada campo. No estan en ningun PDF: viven dentro del .mdb y no se pueden leer por ODBC
(el driver no implementa SQLForeignKeys y Access protege MSysRelationships), asi que se
leen por DAO via COM.

Genera relaciones_egif.csv con una fila por par de campos y una columna `tipo`:

  union_parte       como se unen entre si las tablas del parte
  catalogo          que catalogo traduce cada campo codificado  <- lo mas util
  entre_catalogos   jerarquia geografica y multi-idioma de los propios catalogos

Requisitos: pywin32, y el motor de Access (ACE/DAO) instalado.

Uso:
  python extraer_relaciones.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# Los scripts viven en scripts/, los datos cuelgan de la raiz del proyecto
RAIZ = Path(__file__).resolve().parent.parent
MDB = RAIZ / "PlantillaEgifWebDetalle.mdb"
SALIDA = RAIZ / "relaciones_egif.csv"

# Este script solo depende del .mdb, de nada mas: es el primero del pipeline y el
# resto de pasos leen su salida para saber que hace falta.

# Tablas del parte de incendio (las que el XML rellena). El resto son catalogos.
def es_parte(t: str) -> bool:
    return t == "Pif" or t == "ParteMonte" or t.startswith(("pif_", "Rel"))


def columnas_por_tabla(db) -> dict[str, list[str]]:
    """Nombre de las columnas de cada tabla, leido del propio .mdb."""
    return {td.Name: [f.Name for f in td.Fields]
            for td in db.TableDefs if not td.Name.startswith("MSys")}


def columna_etiqueta(catalogo: str, columnas: dict[str, list[str]]) -> str:
    """Que columna del catalogo lleva el texto legible."""
    cols = columnas.get(catalogo, [])
    for candidata in ("Descripcion", "Nombre", "DescripcionCorta", "PrimeraDefinicion"):
        if candidata in cols:
            return candidata
    return ""


def main() -> None:
    try:
        import win32com.client
    except ImportError:
        sys.exit("Falta pywin32:  pip install pywin32")
    if not MDB.is_file():
        sys.exit(f"No existe {MDB}")

    motor = None
    for prog in ("DAO.DBEngine.120", "DAO.DBEngine.36"):
        try:
            motor = win32com.client.Dispatch(prog)
            break
        except Exception:
            continue
    if motor is None:
        sys.exit("No hay motor DAO disponible (instala Microsoft Access Database Engine)")

    db = motor.OpenDatabase(str(MDB))
    crudas = [(r.Table, r.ForeignTable, [(f.Name, f.ForeignName) for f in r.Fields])
              for r in db.Relations]
    columnas = columnas_por_tabla(db)
    db.Close()

    # DAO: Table = tabla referenciada (el "padre"), ForeignTable = la que lleva la clave
    filas = []
    for i, (referida, tabla, campos) in enumerate(crudas, 1):
        if tabla.startswith("MSys") or referida.startswith("MSys"):
            continue
        if es_parte(tabla) and es_parte(referida):
            tipo = "union_parte"
        elif es_parte(tabla):
            tipo = "catalogo"
        else:
            tipo = "entre_catalogos"

        for campo, campo_ref in campos:
            # DAO da (campo de la tabla referida, campo de la tabla que apunta)
            filas.append({
                "tipo": tipo,
                "tabla": tabla,
                "campo": campo_ref,
                "referencia_tabla": referida,
                "referencia_campo": campo,
                "etiqueta": (columna_etiqueta(referida, columnas)
                             if tipo != "union_parte" else ""),
                # varios campos con el mismo id_relacion = clave compuesta: hay que
                # unir por todos a la vez, no por uno suelto
                "id_relacion": i,
                "campos_en_la_clave": len(campos),
                "nota": "",
            })

    # Anomalias reales de la plantilla. Un campo que aparece en varias relaciones
    # NO es ambiguo si son claves compuestas (idcomunidad participa en la busqueda
    # de Municipio, de ComarcaIsla y de EntidadMenor, y en las tres es correcto).
    # Solo es contradictorio si el campo es, el solo, la clave de dos relaciones
    # que apuntan a catalogos distintos.
    solitarios = {}
    for f in filas:
        if f["tipo"] == "catalogo" and f["campos_en_la_clave"] == 1:
            solitarios.setdefault((f["tabla"], f["campo"]), set()).add(f["referencia_tabla"])
    for f in filas:
        destinos = solitarios.get((f["tabla"], f["campo"]), set())
        if f["campos_en_la_clave"] == 1 and len(destinos) > 1:
            f["nota"] = f"CONTRADICTORIO en la plantilla: mapeado a {', '.join(sorted(destinos))}"
        elif f["tipo"] == "union_parte" and f["tabla"] == "Pif":
            f["nota"] = "relacion invertida en la plantilla: el padre deberia ser Pif"

    campos = ["tipo", "tabla", "campo", "referencia_tabla", "referencia_campo",
              "etiqueta", "campos_en_la_clave", "id_relacion", "nota"]
    filas.sort(key=lambda f: (f["tipo"], f["tabla"], f["campo"]))
    with open(SALIDA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(filas)

    print(f"Relaciones en la plantilla : {len(crudas)}")
    print(f"Filas escritas             : {len(filas)}")
    print(f"Salida                     : {SALIDA}\n")
    for t in ("union_parte", "catalogo", "entre_catalogos"):
        n = sum(1 for f in filas if f["tipo"] == t)
        print(f"  {t:<20}{n:>5}")
    sin_cat = [f for f in filas if f["tipo"] == "catalogo" and not f["etiqueta"]]
    if sin_cat:
        print(f"\n  Catalogos sin columna de texto reconocible: "
              f"{sorted({f['referencia_tabla'] for f in sin_cat})}")
    notas = [f for f in filas if f["nota"]]
    if notas:
        print(f"\n  Anomalias marcadas ({len(notas)}):")
        for f in notas:
            print(f"    {f['tabla']}.{f['campo']:<28} {f['nota']}")


if __name__ == "__main__":
    main()
