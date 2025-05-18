#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Definice dokumentace databázového schématu pro mnd_spi_app.
Tento soubor obsahuje popisy tabulek a sloupců, které jsou používány
pro generování dokumentace a jsou ukládány do tabulky db_dokumentace.
"""

# Definice dokumentace pro tabulky a jejich sloupce
DB_DOKUMENTACE = {
    "lhc": {
        "__doc__": "Tabulka obsahující základní informace o LHC (obecně kód subjektu, za který je výpočet prováděn)",
        "id": "Unikátní identifikátor záznamu",
        "kod": "Číslo LHC (obecně kód subjektu, za který je výpočet prováděn)",
        "nazev": "Název LHC",
        "lhp_platnost_od": "Datum začátku platnosti lesního hospodářského plánu (LHP)",
        "lhp_platnost_do": "Datum konce platnosti lesního hospodářského plánu (LHP)",
        "popis": "Textový popis LHC",
        "datum_vytvoreni": "Datum a čas vytvoření záznamu o LHC v databázi"
    },
    "lhp": {
        "__doc__": "Informace o LHP, resp. o jeho části inventarizované pomocí SPI",
        "id": "Unikátní identifikátor záznamu",
        "platnost_od": "Datum začátku platnosti lesního hospodářského plánu (LHP)",
        "pocet_let": "Počet let platnosti LHP",
        "ft": "Koeficient nesouladu těžeb",
    },
    "dreviny": {
        "__doc__": "Číselník druhů dřevin",
        "id": "Unikátní identifikátor záznamu",
        "nazev": "Celý název dřeviny",
        "kod_dreviny": "Kód dřeviny dle legislativy",
        "zkratka": "Zkratka dřeviny používaná v systému",
        "skupina": "Skupina dřevin (jehličnaté/listnaté)"
    },
}


def ziskej_dokumentaci_tabulky(tabulka, sloupec=None):
    """
    Získá dokumentaci pro zadanou tabulku nebo sloupec.
    
    Args:
        tabulka: Název tabulky
        sloupec: Název sloupce (volitelné)
        
    Returns:
        str: Dokumentace pro tabulku nebo sloupec
    """
    if tabulka not in DB_DOKUMENTACE:
        return f"Dokumentace pro tabulku {tabulka} není k dispozici"
    
    if sloupec is None:
        # Vrátit dokumentaci pro celou tabulku
        if "__doc__" in DB_DOKUMENTACE[tabulka]:
            return DB_DOKUMENTACE[tabulka]["__doc__"]
        else:
            return f"Tabulka {tabulka} nemá dokumentaci"
    else:
        # Vrátit dokumentaci pro sloupec
        if sloupec in DB_DOKUMENTACE[tabulka]:
            return DB_DOKUMENTACE[tabulka][sloupec]
        else:
            return f"Sloupec {sloupec} v tabulce {tabulka} nemá dokumentaci"