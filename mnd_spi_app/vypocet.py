# Copyright (C) 2025 Robert Blaha, Mendel Univerzity in Brno, HULpro s.r.o.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License or
# any later version.
#  See <https://www.gnu.org/licenses/>.
"""
Hlavní soubor řídící výpočet SPI
"""
from . import spi
import argparse
import sys

def main():
    # Zpracování argumentů příkazové řádky
    parser = argparse.ArgumentParser(description='Výpočet SPI')
    parser.add_argument('--lhc', help='Kód LHC za které má být výpočet proveden')
    parser.add_argument('--debug', action='store_true', help='Povolí ladění')

    args = parser.parse_args()

    if not args.lhc:
        parser.error("Je nutné zadat kód LHC")

    # Inicializace výpočtu
    with spi.spi(args.lhc, args.debug) as vypocet_spi:
        vypocet_spi.vypocet()
    
if __name__ == "__main__":
    sys.exit(main())
    
