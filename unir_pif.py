"""
Paso 3: une las 12 tablas pif_* de todos los anios en una sola tabla.

Una fila por incendio (numeroparte). Es seguro: medido sobre los 646.887 incendios
del historico, las 12 tablas pif_* tienen exactamente un registro por incendio, el
100% de las veces. No hay duplicacion posible.

No hace nada mas: ni traduce codigos, ni agrega, ni calcula, ni descarta campos.
Los nombres de columna y los valores son exactamente los del XML. Los codigos
numericos se quedan como codigos.

Quedan fuera de este paso, por no ser 1:1, ParteMonte y las 27 tablas Rel*: las
genera tablas_secundarias.py.

Uso:
  python unir_pif.py
  python unir_pif.py --salida incendios.csv --limite 5000
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from egif import DIR_XML, RAIZ, flujos_xml, leer_esquema, miles


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", default="incendios_pif.csv")
    p.add_argument("--limite", type=int, help="Procesa solo N incendios (prueba).")
    args = p.parse_args()

    esquema = leer_esquema(DIR_XML)
    tablas = [t for t in esquema if t.startswith("pif_")]

    # numeroparte va una sola vez, al principio; el resto en el orden del esquema
    plan = [(t, [c for c in esquema[t] if c != "numeroparte"]) for t in tablas]
    columnas = ["numeroparte"] + [c for _, campos in plan for c in campos]

    con_columnas = [t for t, campos in plan if campos]
    sin_columnas = [t for t, campos in plan if not campos]
    print(f"Tablas unidas : {len(tablas)}  ({', '.join(con_columnas)})")
    print(f"Sin columnas  : {', '.join(sin_columnas) or 'ninguna'}"
          f"{'  (solo contienen Rel*)' if sin_columnas else ''}")
    print(f"Columnas      : {len(columnas)}")

    salida = Path(args.salida)
    if not salida.is_absolute():
        salida = RAIZ / salida
    print(f"Salida        : {salida}\n")

    t0 = time.time()
    n = 0
    bloques_ausentes = {t: 0 for t in tablas}

    with open(salida, "w", newline="", encoding="utf-8-sig") as f, \
            flujos_xml(DIR_XML) as flujos:
        escritor = csv.DictWriter(f, fieldnames=columnas, delimiter=";",
                                  extrasaction="ignore", restval="")
        escritor.writeheader()
        for nombre, stream in flujos:
            print(f"  {nombre:<32} ", end="", flush=True)
            antes = n
            for _, pif in ET.iterparse(stream, events=("end",)):
                if pif.tag != "Pif":
                    continue
                fila = {"numeroparte": (pif.findtext("numeroparte") or "").strip()}
                for tabla, campos in plan:
                    bloque = pif.find(tabla)
                    if bloque is None:
                        bloques_ausentes[tabla] += 1
                        continue
                    for campo in campos:
                        hijo = bloque.find(campo)
                        if hijo is not None:
                            fila[campo] = (hijo.text or "").strip()
                escritor.writerow(fila)
                n += 1
                pif.clear()
                if args.limite and n >= args.limite:
                    break
            print(f"{miles(n - antes):>9} incendios")
            if args.limite and n >= args.limite:
                break

    ausentes = {t: v for t, v in bloques_ausentes.items() if v}
    print(f"\n{'='*58}")
    print(f"Filas escritas  : {miles(n)}   (1 por incendio)")
    print(f"Columnas        : {len(columnas)}")
    print(f"Tamanio         : {miles(salida.stat().st_size / 1024 / 1024)} MB")
    print(f"Tiempo          : {(time.time() - t0) / 60:.1f} min")
    print(f"Bloques ausentes: {ausentes or 'ninguno, las 12 tablas estan en todos los incendios'}")


if __name__ == "__main__":
    main()
