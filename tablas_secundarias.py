"""
Paso 4: genera las 28 tablas secundarias, cada una en su propio CSV.

No se unen a la tabla principal: son relaciones 1-a-muchos y meterlas en la misma
tabla plana obligaria a duplicar filas. Se dejan aparte, con todos los anios ya
concatenados, y **ordenadas segun la jerarquia que define la propia plantilla Access**
del MITECO (se lee de relaciones_egif.csv, no se deduce de los nombres):

    tablas_secundarias/
        nivel_incendio/   cuelgan de Pif        -> se unen por numeroparte
        nivel_monte/      cuelgan de ParteMonte -> por numeroparte + idpartemonte

    incendios_pif.csv --[numeroparte]--> nivel_incendio/*.csv
    incendios_pif.csv --[numeroparte]--> nivel_monte/ParteMonte.csv
                                             --[+ idpartemonte]--> el resto

Las 12 tablas pif_* no se generan aqui: ya estan unidas en incendios_pif.csv
(usa --todas si las quieres tambien sueltas).

No traduce codigos, ni agrega, ni calcula. Nombres de columna y valores son los
del XML.

Uso:
  python tablas_secundarias.py
  python tablas_secundarias.py --salida tablas --limite 5000 --todas
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from egif import DIR_XML, RAIZ, flujos_xml, leer_esquema, miles

RELACIONES = RAIZ / "relaciones_egif.csv"


def jerarquia_oficial() -> dict[str, str]:
    """
    tabla -> 'nivel_monte' | 'nivel_incendio', segun las relaciones de la plantilla.

    Regla: cuelga de ParteMonte -> nivel_monte. Todo lo demas cuelga de Pif.
    ParteMonte encabeza su rama, asi que va con los suyos.
    """
    if not RELACIONES.is_file():
        sys.exit(f"Falta {RELACIONES.name}. Ejecuta antes:  python extraer_relaciones.py")
    padre = {}
    with open(RELACIONES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["tipo"] == "union_parte":
                padre[r["tabla"]] = r["referencia_tabla"]

    def nivel(t: str) -> str:
        if t == "ParteMonte" or padre.get(t) == "ParteMonte":
            return "nivel_monte"
        return "nivel_incendio"

    return {t: nivel(t) for t in padre} | {"ParteMonte": "nivel_monte"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", default="tablas_secundarias")
    p.add_argument("--limite", type=int, help="Procesa solo N incendios (prueba).")
    p.add_argument("--todas", action="store_true",
                   help="Genera tambien las 12 pif_*, ya incluidas en incendios_pif.csv.")
    args = p.parse_args()

    esquema = leer_esquema(DIR_XML)
    # 'pifs' es el envoltorio raiz y 'Pif' solo lleva claves: ninguno aporta datos
    tablas = [t for t in esquema
              if t not in ("pifs", "Pif")
              and (args.todas or not t.startswith("pif_"))]

    destino = Path(args.salida)
    if not destino.is_absolute():
        destino = RAIZ / destino
    destino.mkdir(parents=True, exist_ok=True)

    # la jerarquia la dicta la plantilla Access; las pif_* (con --todas) van aparte
    niveles = jerarquia_oficial()
    nivel = {t: niveles.get(t, "nivel_incendio" if not t.startswith("pif_") else "pif")
             for t in tablas}
    sin_relacion = [t for t in tablas if t not in niveles and not t.startswith("pif_")]

    print(f"Tablas a generar : {len(tablas)}")
    for n in sorted(set(nivel.values())):
        print(f"  {n:<16}{sum(1 for v in nivel.values() if v == n):>3}")
    if sin_relacion:
        print(f"  (sin relacion definida en la plantilla, se asumen de nivel incendio: "
              f"{', '.join(sin_relacion)})")
    print(f"Destino          : {destino}\n")

    ficheros, escritores, filas = {}, {}, {}
    for t in tablas:
        carpeta = destino / nivel[t]
        carpeta.mkdir(parents=True, exist_ok=True)
        f = open(carpeta / f"{t}.csv", "w", newline="", encoding="utf-8-sig")
        w = csv.DictWriter(f, fieldnames=esquema[t], delimiter=";",
                           extrasaction="ignore", restval="")
        w.writeheader()
        ficheros[t], escritores[t], filas[t] = f, w, 0

    t0, n_inc = time.time(), 0
    try:
        with flujos_xml(DIR_XML) as flujos:
            for nombre, stream in flujos:
                print(f"  {nombre:<32} ", end="", flush=True)
                antes = sum(filas.values())
                for _, pif in ET.iterparse(stream, events=("end",)):
                    if pif.tag != "Pif":
                        continue
                    # recorrido recursivo: las Rel* van anidadas dentro de su pif_*
                    # o dentro de ParteMonte, no colgando de la raiz
                    for elem in pif.iter():
                        escritor = escritores.get(elem.tag)
                        if escritor is None:
                            continue
                        fila = {}
                        for campo in esquema[elem.tag]:
                            hijo = elem.find(campo)
                            if hijo is not None:
                                fila[campo] = (hijo.text or "").strip()
                        escritor.writerow(fila)
                        filas[elem.tag] += 1
                    n_inc += 1
                    pif.clear()
                    if args.limite and n_inc >= args.limite:
                        break
                print(f"{miles(sum(filas.values()) - antes):>10} filas")
                if args.limite and n_inc >= args.limite:
                    break
    finally:
        for fichero in ficheros.values():
            fichero.close()

    # indice: que es cada tabla y por que clave se une
    CLAVE = {"nivel_incendio": "numeroparte", "nivel_monte": "numeroparte + idpartemonte",
             "pif": "numeroparte"}
    with open(destino / "_indice.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["nivel", "tabla", "clave_union", "filas",
                                          "columnas", "fichero"], delimiter=";")
        w.writeheader()
        for t in sorted(tablas, key=lambda x: (nivel[x], x)):
            w.writerow({
                "nivel": nivel[t], "tabla": t,
                "clave_union": "numeroparte" if t == "ParteMonte" else CLAVE[nivel[t]],
                "filas": filas[t], "columnas": len(esquema[t]),
                "fichero": f"{nivel[t]}/{t}.csv",
            })

    print(f"\n{'='*80}")
    print(f"{'NIVEL':<16}{'TABLA':<38}{'FILAS':>13}{'MB':>8}{'cols':>5}")
    print("-" * 80)
    total_mb = 0.0
    for t in sorted(tablas, key=lambda x: (nivel[x], -filas[x])):
        mb = (destino / nivel[t] / f"{t}.csv").stat().st_size / 1024 / 1024
        total_mb += mb
        print(f"{nivel[t]:<16}{t:<38}{miles(filas[t]):>13}{mb:>8.1f}"
              f"{len(esquema[t]):>5}")
    print("-" * 80)
    print(f"{'TOTAL':<54}{miles(sum(filas.values())):>13}{total_mb:>8.1f}")
    print(f"\nIndice: {destino / '_indice.csv'}")
    print(f"Incendios recorridos: {miles(n_inc)}   "
          f"Tiempo: {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
