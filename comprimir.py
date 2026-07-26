"""
Paso 6: comprime las tablas a .csv.gz para poder publicarlas en GitHub.

Sin comprimir, incendios_pif.csv pesa 176 MB y GitHub rechaza cualquier fichero de
mas de 100 MB. Comprimido baja a ~31 MB, y el conjunto entero de ~486 MB a ~89 MB,
sin necesidad de Git LFS (cuya cuota de ancho de banda se agotaria en dos descargas).

No estorba a quien los use: pandas y R leen .csv.gz directamente.

    pd.read_csv("incendios_pif.csv.gz", sep=";")

Los catalogos de datos_extraidos/ se dejan sin comprimir: son 6 MB en total y se
consultan a mano con frecuencia.

Cada fichero se verifica tras comprimirlo: se descomprime en memoria y se compara su
SHA-256 con el del original. Si no coincide, se aborta.

Uso:
  python comprimir.py
  python comprimir.py --conservar    # no borra los .csv originales
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import sys
from pathlib import Path

from egif import RAIZ, miles

BLOQUE = 8 * 1024 * 1024
NIVEL = 6  # compromiso habitual entre tamano y tiempo


def sha256(abrir) -> str:
    h = hashlib.sha256()
    with abrir() as f:
        while bloque := f.read(BLOQUE):
            h.update(bloque)
    return h.hexdigest()


def comprimir(origen: Path) -> tuple[float, float]:
    """Comprime, verifica que descomprime identico y devuelve (MB antes, MB despues)."""
    destino = origen.with_suffix(origen.suffix + ".gz")
    antes = origen.stat().st_size

    with open(origen, "rb") as f_in, gzip.open(destino, "wb", compresslevel=NIVEL) as f_out:
        shutil.copyfileobj(f_in, f_out, length=BLOQUE)

    original = sha256(lambda: open(origen, "rb"))
    recuperado = sha256(lambda: gzip.open(destino, "rb"))
    if original != recuperado:
        destino.unlink(missing_ok=True)
        sys.exit(f"FALLO en {origen.name}: al descomprimir no se recupera el original.\n"
                 f"  original  {original}\n  recuperado {recuperado}")

    return antes / 1024 / 1024, destino.stat().st_size / 1024 / 1024


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--conservar", action="store_true",
                   help="No borra los .csv sin comprimir despues de verificarlos.")
    args = p.parse_args()

    objetivos = [RAIZ / "incendios_pif.csv"]
    objetivos += sorted((RAIZ / "tablas_secundarias").rglob("nivel_*/*.csv"))
    objetivos = [p for p in objetivos if p.is_file()]
    if not objetivos:
        sys.exit("No hay tablas que comprimir. Ejecuta antes unir_pif.py y "
                 "tablas_secundarias.py")

    print(f"Ficheros a comprimir : {len(objetivos)}")
    print(f"Verificacion         : SHA-256 del original contra el descomprimido\n")
    print(f"{'FICHERO':<44}{'ANTES':>10}{'DESPUES':>10}{'RATIO':>8}")
    print("-" * 72)

    total_antes = total_despues = 0.0
    for ruta in objetivos:
        antes, despues = comprimir(ruta)
        total_antes += antes
        total_despues += despues
        print(f"{ruta.name:<44}{antes:>9.1f}M{despues:>9.1f}M"
              f"{antes / max(despues, 0.01):>7.1f}x")
        if not args.conservar:
            ruta.unlink()

    print("-" * 72)
    print(f"{'TOTAL':<44}{total_antes:>9.1f}M{total_despues:>9.1f}M"
          f"{total_antes / total_despues:>7.1f}x")
    print(f"\nTodos verificados: descomprimen byte a byte identicos al original.")
    if args.conservar:
        print("Los .csv sin comprimir se han conservado (--conservar).")
    else:
        print(f"Borrados los {len(objetivos)} .csv sin comprimir "
              f"({miles(total_antes)} MB liberados).")
    mayor = max(p.with_suffix(p.suffix + ".gz").stat().st_size for p in objetivos)
    print(f"\nFichero mayor: {mayor / 1024 / 1024:.1f} MB (limite de GitHub: 100 MB)")


if __name__ == "__main__":
    main()
