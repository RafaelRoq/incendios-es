"""
Utilidades compartidas por los scripts del proyecto.

Aqui vive lo unico que todos necesitan: como recorrer los XML del MITECO (que vienen
en ZIP, a veces con otro ZIP dentro) y como leer el esquema XSD que llevan embebido.

No se ejecuta directamente.
"""

from __future__ import annotations

import io
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

RAIZ = Path(__file__).resolve().parent
DIR_XML = RAIZ / "datos_egif"

# Espacio de nombres del XSD que el MITECO embebe al principio de cada XML
XS = "{http://www.w3.org/2001/XMLSchema}"


def comprobar_origen(carpeta: Path = DIR_XML) -> list[Path]:
    """Falla con un mensaje util si no estan los ZIP descargados del buscador."""
    if not carpeta.is_dir():
        sys.exit(f"No existe {carpeta}.\n"
                 f"Descarga los XML del buscador del MITECO y dejalos ahi "
                 f"(ver README, seccion 'Origen y reproduccion').")
    zips = sorted(carpeta.glob("*.zip"))
    if not zips:
        sys.exit(f"{carpeta} no contiene ningun .zip.\n"
                 f"Se esperan los ficheros exportados del buscador del MITECO.")
    return zips


@contextmanager
def flujos_xml(carpeta: Path = DIR_XML) -> Iterator[Iterator[tuple[str, io.BufferedIOBase]]]:
    """
    Recorre todos los XML, atravesando los ZIP anidados, y cierra lo que abre.

    El buscador entrega un ZIP por consulta; si la consulta se troceo en varios
    bloques, cada bloque viene dentro de otro ZIP. El interno pesa poco (<=18 MB) y
    se lee entero en memoria, pero el XML de dentro se sirve como flujo: son hasta
    340 MB por fichero y no caben comodamente.

        with flujos_xml() as flujos:
            for nombre, stream in flujos:
                ...
    """
    abiertos: list[zipfile.ZipFile] = []

    def recorrer():
        for ruta in comprobar_origen(carpeta):
            zf = zipfile.ZipFile(ruta)
            abiertos.append(zf)
            for nombre in sorted(n for n in zf.namelist() if not n.endswith("/")):
                if nombre.lower().endswith(".zip"):
                    interno = zipfile.ZipFile(io.BytesIO(zf.open(nombre).read()))
                    abiertos.append(interno)
                    for n2 in sorted(x for x in interno.namelist() if not x.endswith("/")):
                        yield n2, interno.open(n2)
                else:
                    yield nombre, zf.open(nombre)

    try:
        yield recorrer()
    finally:
        for zf in abiertos:
            zf.close()


def leer_esquema(carpeta: Path = DIR_XML) -> dict[str, list[str]]:
    """
    tabla -> campos escalares, en el orden en que los declara el XSD embebido.

    Se parsea como XML y no con expresiones regulares a proposito: hay campos
    declarados con <xsd:simpleType> anidado en vez de con atributo type=, y una
    regex ingenua se deja fuera 44 de ellos, entre ellos las superficies totales
    y todos los meteorologicos.
    """
    with flujos_xml(carpeta) as flujos:
        _, stream = next(flujos)
        cabecera = stream.read(400_000).decode("utf-8", "replace")

    ini = cabecera.find("<xsd:schema")
    fin = cabecera.find("</xsd:schema>")
    if ini == -1 or fin == -1:
        sys.exit("El primer XML no lleva el esquema XSD embebido al principio.\n"
                 "Se esperaba un export 'XML (Pif/Monte)' del buscador del MITECO; "
                 "revisa que la descarga sea de ese tipo y no del resumen en Excel.")

    raiz = ET.fromstring(cabecera[ini:fin + len("</xsd:schema>")])
    esquema: dict[str, list[str]] = {}
    for tabla in raiz.findall(f"{XS}element"):
        nombre = tabla.get("name")
        secuencia = tabla.find(f"{XS}complexType/{XS}sequence")
        if nombre is None or secuencia is None:
            continue
        esquema[nombre] = [el.get("name").lower()
                           for el in secuencia.findall(f"{XS}element") if el.get("name")]
    return esquema


def miles(n: float, decimales: int = 0) -> str:
    """Formatea con punto como separador de miles, al uso espanol."""
    return f"{n:,.{decimales}f}".replace(",", ".")
