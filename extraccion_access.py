"""
Extraccion de tablas de una base de datos Access (.mdb / .accdb).

Requisitos:
  - Python de 64 bits (el driver ODBC instalado es de 64 bits).
  - pip install pyodbc            (obligatorio)
  - pip install pandas pyarrow    (solo para --formato parquet)
  - pip install pandas openpyxl   (solo para --formato excel)

Uso:
  python extraccion_access.py                       # todo a CSV en ./datos_extraidos
  python extraccion_access.py --listar              # solo lista las tablas y sus filas
  python extraccion_access.py --omitir-vacias       # ignora las tablas sin registros
  python extraccion_access.py --tablas Municipio Provincia CatalogoMonte
  python extraccion_access.py --formato sqlite      # vuelca todo a un unico .sqlite
  python extraccion_access.py --formato parquet
  python extraccion_access.py --db otra_base.mdb --salida C:\\ruta\\destino
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

try:
    import pyodbc
except ImportError:
    sys.exit("Falta pyodbc. Instalalo con:  pip install pyodbc")


RAIZ = Path(__file__).resolve().parent
LOTE = 5000  # filas por lectura, para no cargar tablas grandes enteras en memoria

# --- Seleccion para publicacion (--solo-necesarios) -------------------------
# La plantilla trae 112 tablas: 41 vacias (esperan tu XML) y 71 con datos, de las
# que muchas no hacen falta para interpretar los partes. En modo publicacion se
# extraen solo:
#   (a) los catalogos que relaciones_egif.csv declara como necesarios, y
#   (b) estas seis, que no son claves foraneas y por eso no aparecen ahi, pero
#       sirven para agregar: agrupan las 87 causas y las 31 motivaciones en
#       categorias, y los 8.390 municipios en regiones geograficas.
EXTRA_PUBLICACION = [
    "CodGrupoCausa", "RelGrupoCausa",
    "CodGrupoMotivacion", "RelGrupoMotivacion",
    "Cod_Causas_USOS", "Regiones_Geograficas",
]
RELACIONES = RAIZ / "relaciones_egif.csv"


def catalogos_necesarios() -> list[str]:
    """Los catalogos que referencian las relaciones oficiales, mas los de agrupacion."""
    if not RELACIONES.is_file():
        sys.exit(f"Falta {RELACIONES.name}. Ejecuta antes:  python extraer_relaciones.py")
    necesarios = set(EXTRA_PUBLICACION)
    with open(RELACIONES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["tipo"] in ("catalogo", "entre_catalogos"):
                necesarios.add(r["referencia_tabla"])
                if r["tipo"] == "entre_catalogos":
                    necesarios.add(r["tabla"])
    return sorted(necesarios)


# --------------------------------------------------------------------------
# Conexion
# --------------------------------------------------------------------------

def localizar_bd(ruta: str | None) -> Path:
    """Devuelve la ruta de la base de datos; si no se indica, la busca junto al script."""
    if ruta:
        bd = Path(ruta)
        if not bd.is_absolute():
            bd = RAIZ / bd
        if not bd.is_file():
            sys.exit(f"No existe la base de datos: {bd}")
        return bd

    candidatas = sorted(RAIZ.glob("*.mdb")) + sorted(RAIZ.glob("*.accdb"))
    if not candidatas:
        sys.exit(f"No se ha encontrado ningun .mdb o .accdb en {RAIZ}. Usa --db para indicar la ruta.")
    if len(candidatas) > 1:
        nombres = ", ".join(c.name for c in candidatas)
        sys.exit(f"Hay varias bases de datos ({nombres}). Elige una con --db.")
    return candidatas[0]


def conectar(bd: Path) -> "pyodbc.Connection":
    """Abre la conexion ODBC en modo solo lectura."""
    driver = "{Microsoft Access Driver (*.mdb, *.accdb)}"
    disponibles = [d for d in pyodbc.drivers() if "Access" in d]
    if not any("*.accdb" in d for d in disponibles):
        if disponibles:
            driver = "{" + disponibles[0] + "}"
        else:
            sys.exit(
                "No hay ningun driver ODBC de Access instalado.\n"
                "Instala 'Microsoft Access Database Engine 2016 Redistributable' "
                "en la misma arquitectura (32/64 bits) que tu Python."
            )

    cadena = f"DRIVER={driver};DBQ={bd};ReadOnly=1;"
    try:
        return pyodbc.connect(cadena, autocommit=True)
    except pyodbc.Error as e:
        bits = 64 if sys.maxsize > 2**32 else 32
        sys.exit(
            f"No se pudo conectar a {bd.name}: {e}\n"
            f"Tu Python es de {bits} bits: el driver ODBC de Access debe ser de {bits} bits tambien."
        )


# --------------------------------------------------------------------------
# Metadatos
# --------------------------------------------------------------------------

def listar_tablas(cur) -> list[str]:
    """Nombres de las tablas de usuario, excluyendo las de sistema de Access."""
    return sorted(
        fila.table_name
        for fila in cur.tables(tableType="TABLE")
        if not fila.table_name.startswith(("MSys", "~"))
    )


def contar_filas(cur, tabla: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM [{tabla}]")
    return cur.fetchone()[0]


def describir_tabla(cur, tabla: str) -> dict:
    """Columnas, tipos y clave primaria de una tabla."""
    columnas = [
        {
            "nombre": c.column_name,
            "tipo": c.type_name,
            "tamanio": c.column_size,
            "admite_nulos": bool(c.nullable),
        }
        for c in cur.columns(table=tabla)
    ]
    try:
        clave = [c.column_name for c in cur.primaryKeys(table=tabla)]
    except pyodbc.Error:
        clave = []
    return {"tabla": tabla, "columnas": columnas, "clave_primaria": clave}


# --------------------------------------------------------------------------
# Utilidades de escritura
# --------------------------------------------------------------------------

def nombre_archivo(tabla: str) -> str:
    """Convierte el nombre de tabla en un nombre de fichero valido en Windows."""
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", tabla).rstrip(". ")
    return limpio or "tabla_sin_nombre"


def valor_csv(v):
    """Normaliza un valor para escribirlo en CSV."""
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, bool):
        return "1" if v else "0"
    return v


def valor_sqlite(v):
    """sqlite3 no acepta datetime ni Decimal de forma nativa desde Python 3.12."""
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat(sep=" ") if isinstance(v, dt.datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


TIPOS_SQLITE = {
    "COUNTER": "INTEGER", "INTEGER": "INTEGER", "SMALLINT": "INTEGER",
    "BYTE": "INTEGER", "BIT": "INTEGER", "BIGINT": "INTEGER",
    "REAL": "REAL", "DOUBLE": "REAL", "FLOAT": "REAL",
    "DECIMAL": "REAL", "NUMERIC": "REAL", "CURRENCY": "REAL",
    "LONGBINARY": "BLOB", "VARBINARY": "BLOB", "BINARY": "BLOB",
}


def leer_por_lotes(cur, tabla: str):
    """Genera (columnas, lote_de_filas) leyendo la tabla en bloques."""
    cur.execute(f"SELECT * FROM [{tabla}]")
    columnas = [d[0] for d in cur.description]
    yield columnas, None
    while True:
        filas = cur.fetchmany(LOTE)
        if not filas:
            break
        yield columnas, filas


# --------------------------------------------------------------------------
# Exportadores
# --------------------------------------------------------------------------

def exportar_csv(cur, tabla: str, destino: Path) -> tuple[int, Path]:
    ruta = destino / f"{nombre_archivo(tabla)}.csv"
    total = 0
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        for columnas, filas in leer_por_lotes(cur, tabla):
            if filas is None:
                escritor.writerow(columnas)
                continue
            escritor.writerows([valor_csv(v) for v in fila] for fila in filas)
            total += len(filas)
    return total, ruta


def exportar_sqlite(cur, tabla: str, conexion_sqlite: sqlite3.Connection) -> int:
    columnas_meta = list(cur.columns(table=tabla))
    nombres = [c.column_name for c in columnas_meta]
    definicion = ", ".join(
        f'"{c.column_name}" {TIPOS_SQLITE.get(c.type_name.upper(), "TEXT")}'
        for c in columnas_meta
    )
    conexion_sqlite.execute(f'DROP TABLE IF EXISTS "{tabla}"')
    conexion_sqlite.execute(f'CREATE TABLE "{tabla}" ({definicion})')

    marcadores = ", ".join("?" * len(nombres))
    campos = ", ".join(f'"{n}"' for n in nombres)
    insercion = f'INSERT INTO "{tabla}" ({campos}) VALUES ({marcadores})'

    total = 0
    for _, filas in leer_por_lotes(cur, tabla):
        if filas is None:
            continue
        conexion_sqlite.executemany(insercion, [[valor_sqlite(v) for v in fila] for fila in filas])
        total += len(filas)
    conexion_sqlite.commit()
    return total


def cargar_dataframe(cur, tabla: str):
    """Lee una tabla completa en un DataFrame (sin depender de SQLAlchemy)."""
    import pandas as pd

    columnas, bloques = None, []
    for cols, filas in leer_por_lotes(cur, tabla):
        columnas = cols
        if filas:
            bloques.extend(tuple(f) for f in filas)
    return pd.DataFrame.from_records(bloques, columns=columnas)


def exportar_parquet(cur, tabla: str, destino: Path) -> tuple[int, Path]:
    df = cargar_dataframe(cur, tabla)
    ruta = destino / f"{nombre_archivo(tabla)}.parquet"
    df.to_parquet(ruta, index=False)
    return len(df), ruta


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Extrae las tablas de una base de datos Access.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--db", help="Ruta del .mdb/.accdb (por defecto, el que haya junto al script).")
    p.add_argument("--salida", default="datos_extraidos", help="Carpeta o fichero de destino.")
    p.add_argument("--formato", choices=["csv", "sqlite", "parquet", "excel"], default="csv")
    p.add_argument("--tablas", nargs="+", metavar="TABLA", help="Extrae solo estas tablas.")
    p.add_argument("--solo-necesarios", action="store_true",
                   help="Extrae solo los catalogos que hacen falta para interpretar los "
                        "partes (los que referencia relaciones_egif.csv, mas los de "
                        "agrupacion). Es el modo con el que se genera la publicacion.")
    p.add_argument("--omitir-vacias", action="store_true", help="No exporta las tablas sin registros.")
    p.add_argument("--listar", action="store_true", help="Solo muestra las tablas y su numero de filas.")
    p.add_argument("--sin-esquema", action="store_true", help="No genera _esquema.json.")
    args = p.parse_args()

    bd = localizar_bd(args.db)
    print(f"Base de datos : {bd}")
    print(f"Tamanio       : {bd.stat().st_size / 1024 / 1024:.1f} MB\n")

    conexion = conectar(bd)
    cur = conexion.cursor()

    tablas = listar_tablas(cur)
    if args.solo_necesarios and not args.tablas:
        args.tablas = catalogos_necesarios()
        print(f"Modo publicacion: {len(args.tablas)} catalogos necesarios "
              f"de las {len(tablas)} tablas de la plantilla\n")
    if args.tablas:
        indice = {t.lower(): t for t in tablas}
        seleccion, desconocidas = [], []
        for t in args.tablas:
            (seleccion if t.lower() in indice else desconocidas).append(indice.get(t.lower(), t))
        if desconocidas:
            sys.exit(f"Estas tablas no existen en la base de datos: {', '.join(desconocidas)}")
        tablas = seleccion

    conteos = {t: contar_filas(cur, t) for t in tablas}

    if args.listar:
        print(f"{'TABLA':<45}{'FILAS':>10}")
        print("-" * 55)
        for t in tablas:
            print(f"{t:<45}{conteos[t]:>10,}".replace(",", "."))
        print("-" * 55)
        print(f"{'TOTAL: ' + str(len(tablas)) + ' tablas':<45}{sum(conteos.values()):>10,}".replace(",", "."))
        conexion.close()
        return

    if args.omitir_vacias:
        tablas = [t for t in tablas if conteos[t] > 0]
        if not tablas:
            sys.exit("Todas las tablas seleccionadas estan vacias.")

    salida = Path(args.salida)
    if not salida.is_absolute():
        salida = RAIZ / salida

    conexion_sqlite = None
    if args.formato == "sqlite":
        if salida.suffix.lower() not in (".sqlite", ".db", ".sqlite3"):
            salida = salida.with_suffix(".sqlite")
        salida.parent.mkdir(parents=True, exist_ok=True)
        conexion_sqlite = sqlite3.connect(salida)
    else:
        salida.mkdir(parents=True, exist_ok=True)
    print(f"Destino       : {salida}")
    print(f"Formato       : {args.formato}\n")

    escritor_excel = None
    if args.formato == "excel":
        try:
            import pandas as pd
        except ImportError:
            sys.exit("El formato excel necesita pandas y openpyxl:  pip install pandas openpyxl")
        fichero_excel = salida / f"{bd.stem}.xlsx"
        escritor_excel = pd.ExcelWriter(fichero_excel, engine="openpyxl")

    resumen, fallos, usados = [], 0, set()

    for i, tabla in enumerate(tablas, 1):
        etiqueta = f"[{i:>3}/{len(tablas)}] {tabla:<45}"
        try:
            if args.formato == "csv":
                filas, ruta = exportar_csv(cur, tabla, salida)
                destino_txt = ruta.name
            elif args.formato == "parquet":
                filas, ruta = exportar_parquet(cur, tabla, salida)
                destino_txt = ruta.name
            elif args.formato == "sqlite":
                filas = exportar_sqlite(cur, tabla, conexion_sqlite)
                destino_txt = salida.name
            else:  # excel
                df = cargar_dataframe(cur, tabla)
                if len(df) > 1_048_575:
                    raise ValueError(f"{len(df):,} filas superan el limite de una hoja de Excel")
                hoja = nombre_archivo(tabla)[:31]
                sufijo = 1
                while hoja.lower() in usados:
                    hoja = f"{nombre_archivo(tabla)[:28]}_{sufijo}"
                    sufijo += 1
                usados.add(hoja.lower())
                df.to_excel(escritor_excel, sheet_name=hoja, index=False)
                filas, destino_txt = len(df), hoja

            print(f"{etiqueta}{filas:>9,} filas  -> {destino_txt}".replace(",", "."))
            resumen.append({"tabla": tabla, "filas": filas, "destino": destino_txt, "estado": "ok"})

        except Exception as e:
            fallos += 1
            print(f"{etiqueta}    ERROR: {e}")
            resumen.append({"tabla": tabla, "filas": 0, "destino": "", "estado": f"error: {e}"})

    if escritor_excel is not None:
        escritor_excel.close()
        print(f"\nLibro de Excel: {fichero_excel}")

    carpeta_meta = salida.parent if args.formato == "sqlite" else salida

    if not args.sin_esquema:
        esquema = {
            "base_de_datos": bd.name,
            "extraido": dt.datetime.now().isoformat(timespec="seconds"),
            "tablas": [describir_tabla(cur, t) for t in tablas],
        }
        ruta_esquema = carpeta_meta / "_esquema.json"
        ruta_esquema.write_text(json.dumps(esquema, indent=2, ensure_ascii=False), encoding="utf-8")

    ruta_resumen = carpeta_meta / "_resumen.csv"
    with open(ruta_resumen, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=["tabla", "filas", "destino", "estado"], delimiter=";")
        escritor.writeheader()
        escritor.writerows(resumen)

    total_filas = sum(r["filas"] for r in resumen)
    correctas = len(resumen) - fallos
    print(f"\n{'=' * 60}")
    print(f"Tablas exportadas : {correctas}/{len(resumen)}")
    print(f"Filas totales     : {total_filas:,}".replace(",", "."))
    print(f"Resumen           : {ruta_resumen}")
    if fallos:
        print(f"Tablas con error  : {fallos} (revisa _resumen.csv)")

    if conexion_sqlite is not None:
        conexion_sqlite.close()
    conexion.close()


if __name__ == "__main__":
    main()
