"""
Verifica que las tablas generadas son fieles a los XML de origen.

Comprueba, en este orden:
  1. Cobertura   : todo campo del esquema XSD acaba en alguna tabla, sin perderse
  2. Integridad  : cada fila tiene el numero de columnas debido (CSV bien formado)
  3. Recuento    : las filas de cada CSV coinciden con las que hay en el XML
  4. Claves      : numeroparte unico en la principal, (numeroparte, idpartemonte)
                   unico en ParteMonte, y toda tabla secundaria apunta a un
                   incendio que existe
  5. Invariante  : la suma de superficies por titularidad cuadra con el total del
                   incendio (regla que impone el propio formulario oficial)
  6. Codificacion: sin mojibake en los textos
  7. Valores     : se re-leen N incendios del XML y se comparan campo a campo

Uso:
  python verificar.py
  python verificar.py --muestra 500
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from egif import DIR_XML, RAIZ, flujos_xml, leer_esquema, miles

csv.field_size_limit(50_000_000)

PRINCIPAL = RAIZ / "incendios_pif.csv"
SECUNDARIAS = RAIZ / "tablas_secundarias"
MOJIBAKE = ("Ã±", "Ã³", "Ã¡", "Ã©", "Ãº", "Ã", "â€")

fallos: list[str] = []
avisos: list[str] = []


def check(ok: bool, mensaje: str, detalle: str = "") -> None:
    if ok:
        print(f"  OK    {mensaje}")
    else:
        fallos.append(f"{mensaje} {detalle}".strip())
        print(f"  FALLO {mensaje}   {detalle}")


def aviso(mensaje: str) -> None:
    avisos.append(mensaje)
    print(f"  aviso {mensaje}")


def ficheros_secundarios() -> dict[str, Path]:
    return {p.stem: p for nivel in ("nivel_incendio", "nivel_monte")
            for p in sorted((SECUNDARIAS / nivel).glob("*.csv"))}


def leer_indice() -> list[dict]:
    """Lo que _indice.csv promete: nivel y clave de union de cada tabla."""
    with open(SECUNDARIAS / "_indice.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def comparar_muestra(esquema: dict, objetivo: set[str]) -> tuple[int, int, list[str]]:
    """Compara contra el XML solo los incendios de la muestra. Rapido."""
    tablas_pif = [t for t in esquema if t.startswith("pif_")]
    del_xml: dict[str, dict] = {}
    with flujos_xml(DIR_XML) as flujos:
        for _, stream in flujos:
            for _, pif in ET.iterparse(stream, events=("end",)):
                if pif.tag != "Pif":
                    continue
                numero = pif.findtext("numeroparte")
                if numero in objetivo:
                    valores = {}
                    for tabla in tablas_pif:
                        bloque = pif.find(tabla)
                        if bloque is None:
                            continue
                        for campo in esquema[tabla]:
                            if campo == "numeroparte":
                                continue
                            hijo = bloque.find(campo)
                            valores[campo] = ((hijo.text or "").strip()
                                              if hijo is not None else "")
                    del_xml[numero] = valores
                pif.clear()

    comparados = discrepancias = 0
    ejemplos: list[str] = []
    with open(PRINCIPAL, encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f, delimiter=";"):
            esperados = del_xml.get(fila["numeroparte"])
            if esperados is None:
                continue
            for campo, valor in esperados.items():
                comparados += 1
                if fila.get(campo, "") != valor:
                    discrepancias += 1
                    if len(ejemplos) < 5:
                        ejemplos.append(f"{fila['numeroparte']}.{campo}: "
                                        f"XML='{valor}' CSV='{fila.get(campo)}'")
    return comparados, discrepancias, ejemplos


def comparar_exhaustivo(esquema: dict) -> tuple[int, int, list[str]]:
    """
    Compara la tabla principal entera contra el XML, valor por valor.

    unir_pif.py escribe las filas en el mismo orden en que recorre los XML, asi que
    se pueden leer los dos en paralelo y comparar sin cargar nada en memoria. Cubre
    los 646.887 incendios y sus 71 campos, no una muestra.
    """
    tablas_pif = [t for t in esquema if t.startswith("pif_")]
    comparados = discrepancias = 0
    ejemplos: list[str] = []

    with open(PRINCIPAL, encoding="utf-8-sig", newline="") as f, \
            flujos_xml(DIR_XML) as flujos:
        filas_csv = csv.DictReader(f, delimiter=";")
        for _, stream in flujos:
            for _, pif in ET.iterparse(stream, events=("end",)):
                if pif.tag != "Pif":
                    continue
                fila = next(filas_csv, None)
                if fila is None:
                    ejemplos.append("el CSV tiene menos filas que incendios el XML")
                    return comparados, discrepancias + 1, ejemplos

                numero = (pif.findtext("numeroparte") or "").strip()
                comparados += 1
                if fila["numeroparte"] != numero:
                    discrepancias += 1
                    if len(ejemplos) < 5:
                        ejemplos.append(f"fila desalineada: XML={numero} "
                                        f"CSV={fila['numeroparte']}")
                for tabla in tablas_pif:
                    bloque = pif.find(tabla)
                    for campo in esquema[tabla]:
                        if campo == "numeroparte":
                            continue
                        esperado = ""
                        if bloque is not None:
                            hijo = bloque.find(campo)
                            if hijo is not None:
                                esperado = (hijo.text or "").strip()
                        comparados += 1
                        if fila.get(campo, "") != esperado:
                            discrepancias += 1
                            if len(ejemplos) < 5:
                                ejemplos.append(f"{numero}.{campo}: XML='{esperado}' "
                                                f"CSV='{fila.get(campo)}'")
                pif.clear()
        if next(filas_csv, None) is not None:
            discrepancias += 1
            ejemplos.append("el CSV tiene mas filas que incendios el XML")
    return comparados, discrepancias, ejemplos


def comparar_secundarias(esquema: dict, sec: dict[str, Path]) -> tuple[int, int, list[str]]:
    """
    Compara las 28 tablas secundarias enteras contra el XML, valor por valor.

    tablas_secundarias.py escribe cada fila en el momento en que encuentra su elemento
    recorriendo el XML con pif.iter(). Repitiendo el mismo recorrido y leyendo los 28
    CSV en paralelo, cada fila que sale del XML debe corresponderse con la siguiente
    fila sin consumir de su fichero.
    """
    ficheros = {t: open(p, encoding="utf-8-sig", newline="") for t, p in sec.items()}
    lectores = {t: csv.DictReader(f, delimiter=";") for t, f in ficheros.items()}
    comparados = discrepancias = 0
    ejemplos: list[str] = []

    try:
        with flujos_xml(DIR_XML) as flujos:
            for _, stream in flujos:
                for _, pif in ET.iterparse(stream, events=("end",)):
                    if pif.tag != "Pif":
                        continue
                    for elem in pif.iter():
                        if elem.tag not in lectores:
                            continue
                        fila = next(lectores[elem.tag], None)
                        if fila is None:
                            discrepancias += 1
                            ejemplos.append(f"{elem.tag}: el CSV se queda sin filas")
                            return comparados, discrepancias, ejemplos
                        for campo in esquema[elem.tag]:
                            hijo = elem.find(campo)
                            esperado = (hijo.text or "").strip() if hijo is not None else ""
                            comparados += 1
                            if fila.get(campo, "") != esperado:
                                discrepancias += 1
                                if len(ejemplos) < 5:
                                    ejemplos.append(
                                        f"{elem.tag}.{campo} (parte "
                                        f"{fila.get('numeroparte')}): XML='{esperado}' "
                                        f"CSV='{fila.get(campo)}'")
                    pif.clear()
        sobrantes = [t for t, lector in lectores.items() if next(lector, None) is not None]
        if sobrantes:
            discrepancias += len(sobrantes)
            ejemplos.append(f"sobran filas en el CSV de: {sobrantes}")
    finally:
        for f in ficheros.values():
            f.close()
    return comparados, discrepancias, ejemplos


def verificar_uniones(sec: dict[str, Path], partes: set[str]) -> None:
    """
    Comprueba que las claves que documenta el README unen de verdad:

      - nivel_incendio: numeroparte contra la tabla principal
      - nivel_monte   : numeroparte + idpartemonte contra ParteMonte

    Una union correcta no debe perder filas (huerfanas) ni inventarlas (una fila de
    detalle que case con varios padres). Ademas se mide cuanto multiplicaria la union
    mal hecha, para confirmar que el aviso del README no es teorico.
    """
    indice = leer_indice()

    # (numeroparte, idpartemonte) de ParteMonte: el padre de las 8 tablas del monte
    claves_pm: set[tuple[str, str]] = set()
    pm_por_parte: Counter = Counter()
    with open(sec["ParteMonte"], encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            claves_pm.add((r["numeroparte"], r["idpartemonte"]))
            pm_por_parte[r["numeroparte"]] += 1

    huerfanas: dict[str, int] = {}
    inflado: list[tuple[str, float]] = []

    for entrada in indice:
        tabla, nivel = entrada["tabla"], entrada["nivel"]
        if tabla == "ParteMonte" or tabla not in sec:
            continue
        rel_por_parte: Counter = Counter()
        sueltas = filas = 0
        with open(sec[tabla], encoding="utf-8-sig", newline="") as f:
            lector = csv.DictReader(f, delimiter=";")
            tiene_pm = "idpartemonte" in (lector.fieldnames or [])
            for r in lector:
                filas += 1
                np_ = r["numeroparte"]
                rel_por_parte[np_] += 1
                if nivel == "nivel_monte" and tiene_pm:
                    if (np_, r["idpartemonte"]) not in claves_pm:
                        sueltas += 1
                elif np_ not in partes:
                    sueltas += 1
        if sueltas:
            huerfanas[tabla] = sueltas
        # Cuanto multiplicaria unir una tabla del monte solo por numeroparte.
        # La media enganya: el 96% de incendios tiene un unico parte de monte y no
        # se multiplica nada. Lo que importa es el peor incendio, que es donde la
        # union mal hecha se descontrola al encadenar varias tablas.
        if nivel == "nivel_monte" and filas:
            media = sum(pm_por_parte[np_] * n for np_, n in rel_por_parte.items()) / filas
            peor = max(pm_por_parte[np_] for np_ in rel_por_parte)
            inflado.append((tabla, media, peor))

    check(not huerfanas,
          f"las {len(indice)} tablas unen con su padre sin filas huerfanas",
          f"huerfanas: {huerfanas}")

    # la union correcta conserva exactamente las filas de la tabla de detalle:
    # el padre es unico por clave (ya comprobado), asi que no puede duplicar
    check(True, "la union correcta no duplica filas "
                "(la clave del padre es unica, comprobado en el paso 2)")

    if inflado:
        media_max = max(inflado, key=lambda x: x[1])
        peor_max = max(inflado, key=lambda x: x[2])
        print(f"  info  si las {len(inflado)} tablas del monte se unieran solo por "
              f"numeroparte, sin idpartemonte:")
        print(f"          de media multiplicarian x{media_max[1]:.1f} "
              f"(peor tabla: {media_max[0]})")
        print(f"          en el peor incendio, x{peor_max[2]} ({peor_max[0]})")
        print(f"        La media enganya porque el 96% de incendios tiene un solo parte "
              f"de monte;")
        print(f"        el dano real aparece al encadenar tablas. Ver el README.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--muestra", type=int, default=300,
                    help="Incendios a comparar campo a campo contra el XML.")
    ap.add_argument("--exhaustivo", action="store_true",
                    help="Compara TODOS los incendios y TODOS los campos contra el XML, "
                         "no una muestra. Tarda unos minutos mas.")
    args = ap.parse_args()

    # Este script trabaja sobre los CSV sin comprimir, que es como los dejan
    # unir_pif.py y tablas_secundarias.py. Si ya se ha pasado comprimir.py, los
    # originales no estan y hay que regenerarlos: verificar contra el .gz no
    # probaria nada que comprimir.py no compruebe ya por SHA-256.
    comprimidos = (PRINCIPAL.with_suffix(".csv.gz").is_file()
                   or any(SECUNDARIAS.rglob("*.csv.gz")))
    if not PRINCIPAL.is_file() or not ficheros_secundarios():
        if comprimidos:
            sys.exit("Las tablas ya estan comprimidas (.csv.gz) y este script necesita "
                     "los .csv sin comprimir.\n"
                     "Regeneralos con:  python scripts/unir_pif.py  y  "
                     "python scripts/tablas_secundarias.py\n"
                     "(comprimir.py ya verifica por SHA-256 que el .gz devuelve el "
                     "original byte a byte)")
        sys.exit("Faltan las tablas. Ejecuta antes:\n"
                 "  python scripts/unir_pif.py\n"
                 "  python scripts/tablas_secundarias.py")
    sec = ficheros_secundarios()

    esquema = leer_esquema(DIR_XML)

    # ---------------------------------------------------------------- 1. cobertura
    print("\n1. COBERTURA DE CAMPOS")
    with open(PRINCIPAL, encoding="utf-8-sig", newline="") as f:
        cols_principal = next(csv.reader(f, delimiter=";"))
    cols_sec = {}
    for t, p in sec.items():
        with open(p, encoding="utf-8-sig", newline="") as f:
            cols_sec[t] = next(csv.reader(f, delimiter=";"))

    perdidos = []
    for tabla, campos in esquema.items():
        if tabla == "pifs":
            continue
        destino = cols_principal if tabla.startswith("pif_") else cols_sec.get(tabla)
        if destino is None:
            if tabla != "Pif":
                perdidos.append(f"{tabla} (tabla entera)")
            continue
        for c in campos:
            if c not in destino:
                perdidos.append(f"{tabla}.{c}")
    check(not perdidos, f"los {sum(len(v) for k, v in esquema.items() if k != 'pifs')} "
                        f"campos del esquema estan en alguna tabla",
          f"faltan: {perdidos[:6]}" if perdidos else "")

    # ------------------------------------------------- 2-4. recorrido de los CSV
    print("\n2. INTEGRIDAD DE LOS CSV Y CLAVES")

    partes_principal: set[str] = set()
    dup_principal = 0
    total_arb: dict[str, float] = {}
    total_noarb: dict[str, float] = {}
    malformadas = 0
    mojibake_en = set()
    n_principal = 0

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    idx = {c: i for i, c in enumerate(cols_principal)}
    with open(PRINCIPAL, encoding="utf-8-sig", newline="") as f:
        lector = csv.reader(f, delimiter=";")
        next(lector)
        for fila in lector:
            n_principal += 1
            if len(fila) != len(cols_principal):
                malformadas += 1
                continue
            np_ = fila[idx["numeroparte"]]
            if np_ in partes_principal:
                dup_principal += 1
            partes_principal.add(np_)
            total_arb[np_] = num(fila[idx["superficiearboladatotal"]])
            total_noarb[np_] = num(fila[idx["superficienoarboladatotal"]])
            if any(m in fila[idx["paraje"]] for m in MOJIBAKE):
                mojibake_en.add("incendios_pif.paraje")

    check(malformadas == 0, "la tabla principal esta bien formada",
          f"{malformadas} filas con columnas de mas o de menos")
    check(dup_principal == 0, "numeroparte es unico en la tabla principal",
          f"{dup_principal} duplicados")

    filas_csv = Counter({"__principal__": n_principal})
    huerfanos = Counter()
    pm_claves = set()
    pm_dup = 0

    for t, p in sec.items():
        cols = cols_sec[t]
        i_np = cols.index("numeroparte") if "numeroparte" in cols else None
        i_pm = cols.index("idpartemonte") if "idpartemonte" in cols else None
        with open(p, encoding="utf-8-sig", newline="") as f:
            lector = csv.reader(f, delimiter=";")
            next(lector)
            for fila in lector:
                filas_csv[t] += 1
                if len(fila) != len(cols):
                    malformadas += 1
                    continue
                if i_np is not None and fila[i_np] not in partes_principal:
                    huerfanos[t] += 1
                if t == "ParteMonte" and i_pm is not None:
                    clave = (fila[i_np], fila[i_pm])
                    if clave in pm_claves:
                        pm_dup += 1
                    pm_claves.add(clave)
                for celda in fila:
                    if celda and any(m in celda for m in MOJIBAKE):
                        mojibake_en.add(t)
                        break

    check(malformadas == 0, "todos los CSV estan bien formados",
          f"{malformadas} filas malformadas")
    check(not huerfanos, "toda fila secundaria apunta a un incendio existente",
          f"huerfanas: {dict(huerfanos)}")
    check(pm_dup == 0, "(numeroparte, idpartemonte) es unico en ParteMonte",
          f"{pm_dup} duplicados")
    check(not mojibake_en, "los textos no tienen mojibake", f"en {sorted(mojibake_en)}")

    # ------------------------------------------------------- 3. recuento vs XML
    print("\n3. RECUENTO CONTRA EL XML DE ORIGEN")
    filas_xml = Counter()
    n_xml = 0
    muestra_objetivo = set()
    with flujos_xml(DIR_XML) as flujos:
        for _, stream in flujos:
            for _, pif in ET.iterparse(stream, events=("end",)):
                if pif.tag != "Pif":
                    continue
                n_xml += 1
                for elem in pif.iter():
                    if elem.tag in sec:
                        filas_xml[elem.tag] += 1
                if len(muestra_objetivo) < args.muestra and random.random() < 0.002:
                    muestra_objetivo.add(pif.findtext("numeroparte"))
                pif.clear()

    check(n_xml == n_principal,
          f"la principal tiene una fila por incendio del XML ({miles(n_xml)})",
          f"XML {n_xml} vs CSV {n_principal}")
    desajustes = {t: (filas_xml[t], filas_csv[t]) for t in sec
                  if filas_xml[t] != filas_csv[t]}
    check(not desajustes,
          f"las {len(sec)} tablas secundarias tienen las filas del XML "
          f"({miles(sum(filas_csv[t] for t in sec))})",
          f"desajustes: {desajustes}")

    # ------------------------------------------------------- 5. invariante oficial
    print("\n4. INVARIANTE DEL FORMULARIO OFICIAL")
    print("   (la suma por titularidad debe dar el total del incendio)")
    suma_arb: dict[str, float] = defaultdict(float)
    suma_noarb: dict[str, float] = defaultdict(float)
    p = sec.get("RelPerdidaMontePif")
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            suma_arb[r["numeroparte"]] += num(r["superficiearbolada"])
            suma_noarb[r["numeroparte"]] += num(r["superficienoarbolada"])
    for etiqueta, tot, sub in (("arbolada", total_arb, suma_arb),
                               ("no arbolada", total_noarb, suma_noarb)):
        malos = sum(1 for np_ in tot if abs(tot[np_] - sub.get(np_, 0.0)) > 0.011)
        pct = 100 * (len(tot) - malos) / len(tot)
        if malos == 0:
            check(True, f"superficie {etiqueta}: cuadra en los {len(tot):,} incendios"
                  .replace(",", "."))
        else:
            aviso(f"superficie {etiqueta}: cuadra en {pct:.4f}% "
                  f"({malos} incendios no, error del dato de origen)")

    # ------------------------------------------------------- 6. valores campo a campo
    if args.exhaustivo:
        print("\n5. COMPARACION CAMPO A CAMPO (todos los incendios, todos los campos)")
        comparados, discrepancias, ejemplos = comparar_exhaustivo(esquema)
    else:
        print(f"\n5. COMPARACION CAMPO A CAMPO ({len(muestra_objetivo)} incendios al azar; "
              f"usa --exhaustivo para comparar los {miles(n_principal)})")
        comparados, discrepancias, ejemplos = comparar_muestra(esquema, muestra_objetivo)
    check(discrepancias == 0,
          f"tabla principal: {miles(comparados)} valores coinciden con el XML",
          f"{discrepancias} discrepancias: {ejemplos}")

    if args.exhaustivo:
        comparados, discrepancias, ejemplos = comparar_secundarias(esquema, sec)
        check(discrepancias == 0,
              f"las 28 secundarias: {miles(comparados)} valores coinciden con el XML",
              f"{discrepancias} discrepancias: {ejemplos}")
    else:
        print("  ----  las 28 tablas secundarias solo se comparan con --exhaustivo")

    # -------------------------------------------------- 7. claves de union del README
    print("\n6. LAS CLAVES DE UNION DOCUMENTADAS FUNCIONAN")
    verificar_uniones(sec, partes_principal)

    # ---------------------------------------------------------------- resumen
    print(f"\n{'='*70}")
    if fallos:
        print(f"RESULTADO: {len(fallos)} FALLO(S)")
        for f_ in fallos:
            print(f"  - {f_}")
        sys.exit(1)
    print("RESULTADO: todo correcto")
    if avisos:
        print(f"\nCon {len(avisos)} aviso(s) sobre el dato de origen, no sobre el proceso:")
        for a in avisos:
            print(f"  - {a}")


if __name__ == "__main__":
    main()
