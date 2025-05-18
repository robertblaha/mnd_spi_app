# Copyright (C) 2025 Robert Blaha, Mendel Univerzity in Brno, HULpro s.r.o.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License or
# any later version.
#  See <https://www.gnu.org/licenses/>.

"""
Pomocné funkce pro výpočet SPI
"""
import geopandas as gpd
import xml.etree.ElementTree as ET
import json
def is_numeric_string(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

def ceske_cislo(cislo, des_mista=1):
    return f"{cislo:,.{des_mista}f}".replace(",", " ").replace(".", ",")

def uprav_schema_pro_export(df, schema_updates):
    schema = gpd.io.file.infer_schema(df)
    # Aktualizace schématu podle našich specifikací
    for col, dtype_spec in schema_updates.items():
        if col in schema['properties']:
            schema['properties'][col] = dtype_spec
    return schema

def oprav_format_cisel(zdroj, format):
    """
    Funkce pro úpravu formátu čísel v zadaném slovníku podle definovaného formátu.
    
    Args:
        zdroj (dict): Slovník s hodnotami, které se mají upravit
        format (dict): Slovník definující počet desetinných míst pro jednotlivé klíče
        
    Returns:
        dict: Slovník s upravenými hodnotami
    """
    vystup = zdroj.copy()  # Vytvoříme kopii vstupního slovníku, abychom nemodifikovali originál
    
    for pole, pocet in format.items():
        if pole in zdroj:
            vystup[pole] = dopln_des_mista(zdroj[pole], pocet)
    
    return vystup


def dopln_des_mista(zdroj, pocet):
    """
    Funkce pro doplnění desetinných míst v čísle.
    
    Args:
        zdroj (str): Vstupní číslo jako řetězec
        pocet (int): Počet desetinných míst
        
    Returns:
        str: Řetězec s upraveným počtem desetinných míst
    """
    rozpad = str(zdroj).split('.')
    
    if pocet == 0:
        return rozpad[0]
    else:
        if len(rozpad) == 1:
            return rozpad[0] + '.' + '0' * pocet
        else:
            return rozpad[0] + '.' + rozpad[1].ljust(pocet, '0')

def element_vloz_atributy(element, atributy, vyloucene = []):
    for key, value in atributy.items():
        if key not in vyloucene:
            element.set(key.upper(), str(value))
    return element

def generuj_mapovy_element(parent, element_name, data_json):
    element = ET.SubElement(parent, element_name)
    data = json.loads(data_json)
    for plocha in data['coordinates']:
        p_element = ET.SubElement(element, "P")
        for linie in plocha:
            l_element = ET.SubElement(p_element, "L")
            for bod in linie:
                rozpad = str(bod[1]).split('.')
                x_sour = str(rozpad[0])[1:16] + '.'
                
                if len(rozpad) == 1:
                    x_sour += '000'
                else:
                    if len(rozpad[1]) < 3:
                        x_sour += (rozpad[1] + '000')[:3]
                    else:
                        x_sour += rozpad[1]
                
                # Zpracování Y souřadnice
                rozpad = str(bod[0]).split('.')
                y_sour = str(rozpad[0])[1:16] + '.'
                
                if len(rozpad) == 1:
                    y_sour += '000'
                else:
                    if len(rozpad[1]) < 3:
                        y_sour += (rozpad[1] + '000')[:3]
                    else:
                        y_sour += rozpad[1]                
                b_element = ET.SubElement(l_element, "B")
                b_element.set("S", f"{x_sour}${y_sour}")
    return element
