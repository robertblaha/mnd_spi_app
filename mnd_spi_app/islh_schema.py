import pandera as pa
from typing import Dict, Optional, Tuple

# Definice kontrolních funkcí
def check_range_or_zero(min_val, max_val):
    """
    Vytvoří funkci pro kontrolu, zda je hodnota buď 0 nebo v zadaném rozsahu.
    
    Args:
        min_val: Minimální povolená hodnota (včetně)
        max_val: Maximální povolená hodnota (včetně)
        
    Returns:
        Funkce, která vrací True, pokud je hodnota 0 nebo v povoleném rozsahu
    """
    def _check(x):
        # Vrací True, pokud je hodnota 0 nebo v povoleném rozsahu
        return (x == 0) | ((x >= min_val) & (x <= max_val))
    return _check

# Definice základních schémat
def get_base_schemas():
    # Inventarizační plochy
    ip_minimal = {
        'lokalita': pa.Column(pa.Int64, pa.Check.in_range(0, 999999999999), nullable=False, required=True),
        'plocha': pa.Column(pa.Int, pa.Check.in_range(1, 3), nullable=False, required=True),
        'azimut_stab': pa.Column(pa.Float, pa.Check.in_range(0, 360), nullable=False, default=0.0, required=True),
        'vzd_stab': pa.Column(pa.Float, pa.Check.in_range(0, 20), nullable=False, default=0.0, required=True),
        'cil_zasoba': pa.Column(pa.Int, pa.Check.in_range(0, 274), nullable=False, default=0, required=True),
        'cbp': pa.Column(pa.Float, pa.Check.in_range(0, 11.1), nullable=False, default=0.0, required=True),
        'vyr_doba': pa.Column(pa.Float, pa.Check.in_range(30, 60), nullable=False, default=0, required=True),
        'meric': pa.Column(pa.String, pa.Check.str_length(max_value=40), nullable=False, default=''),
        'pozn_plocha': pa.Column(pa.String, pa.Check.str_length(max_value=255), nullable=False, default=''),
        'status': pa.Column(pa.String, pa.Check.isin(['100', '200']), nullable=False, default='', required=True),
        'prist': pa.Column(pa.String, pa.Check.isin(['100', '200']), nullable=False, default='', required=True),
        'stab': pa.Column(pa.String, pa.Check.isin(['100', '200']), nullable=False, default='', required=True),
        'identifikace': pa.Column(str, pa.Check.isin(['', '100', '200']), nullable=False, default='', required=True),
        'duv_neob': pa.Column(str, pa.Check.isin(['', '100', '200', '300']), nullable=False, default='', required=True),
        'kat_poz': pa.Column(pa.String, pa.Check.isin(['100', '200']), nullable=False, default='', required=True),
        'poz_les': pa.Column(pa.String, pa.Check.isin(['100', '200', '300']), nullable=False, default='', required=True),
        'lt': pa.Column(pa.String, nullable=False, default=''),
        'prist_pred': pa.Column(pa.String, pa.Check.isin(['', '100', '200']), nullable=False, default='', required=True),
        'kat_poz_pred': pa.Column(pa.String, pa.Check.isin(['', '100', '200']), nullable=False, default='', required=True),
        'poz_les_pred': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300']), nullable=False, default='', required=True),
    }
    
    ip_full_extended = {
    }
    
    # Vzorníky
    vz_minimal = {
        'lokalita': pa.Column(pa.Int64, pa.Check.in_range(0, 999999999999), nullable=False, required=True),
        'plocha': pa.Column(pa.Int, pa.Check.in_range(1, 3), nullable=False, required=True),
        'kmen': pa.Column(pa.Int, pa.Check.in_range(0, 999), nullable=True, required=True, default=0),
        'kmen_pred': pa.Column(pa.Int, pa.Check.in_range(0, 999), nullable=True, required=True, default=0),
        'x_m': pa.Column(pa.Float, nullable=True, required=False),
        'y_m': pa.Column(pa.Float, nullable=True, required=False),
        'vzd_km': pa.Column(pa.Float, pa.Check.in_range(0, 50), nullable=True, required=True),
        'azimut_km': pa.Column(pa.Float, pa.Check.in_range(0, 360), nullable=True, required=True),
        'tloustka_km': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(7, 800))
            , nullable=True
            , required=True
        ),
        'tloustka_km_pred': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(7, 800))
            , nullable=True
            , required=True
        ),
        'mod_vys': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(1.3, 80))
            , nullable=True
            , required=True
        ),
        'mod_vys_pred': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(1.3, 80))
            , nullable=True
            , required=True
        ),
        'vzornik2': pa.Column(pa.String, pa.Check.isin(['A', 'N']), nullable=True, required=True),
        'vzornik2_pred': pa.Column(pa.String, pa.Check.isin(['A', 'N']), nullable=True, required=True),
        'mvyska': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(1.3, 80))
            , nullable=True
            , required=True
        ),
        'mvyska_pred': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(1.3, 80))
            , nullable=True
            , required=True
        ),
        'pno': pa.Column(pa.Int, pa.Check.in_range(0, 99), nullable=True, required=True),
        'pno_pred': pa.Column(pa.Int, pa.Check.in_range(0, 99), nullable=True, required=True),
        'd13_depl': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(7, 800))
            , nullable=True
            , required=True
        ),
        'mod_vys_depl': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(1.3, 80))
            , nullable=True
            , required=True
        ),
        'pozn_km': pa.Column(pa.String, pa.Check.str_length(max_value=255), nullable=False, default=''),
        'opak_ident_km': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300', '400', '500', '600']), nullable=False, default='', required=True),
        'parez': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300', '400', '500', '600', '700']), nullable=False, default='', required=True),
        'pol_parez': pa.Column(pa.String, pa.Check.isin(['', '100', '200']), nullable=False, default='', required=True),
        'sous': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300', '400', '500']), nullable=False, default='', required=True),
        'dr_zkr': pa.Column(pa.String, nullable=False, default='', required=True),
        'dvojak': pa.Column(pa.String, pa.Check.isin(['', '100', '200']), nullable=False, default='', required=True),
        'zlom_vyvrat': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300', '400', '500', '600', '700']), nullable=False, default='', required=True),
        'vyklizeni_km': pa.Column(pa.String, pa.Check.isin(['', '100', '200']), nullable=False, default='', required=True),
        'parez_pred': pa.Column(pa.String, pa.Check.isin(['', '100', '200']), nullable=False, default='', required=True),
        'sous_pred': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300', '400', '500']), nullable=False, default='', required=True),
        'zlom_vyvrat_pred': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300', '400', '500', '600', '700']), nullable=False, default='', required=True),
    }
    
    vz_full_extended = {
        'to_mv_sk': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_mv_bk': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_modv_bk': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_modv_sk': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_modv_bk_depl': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_modv_sk_depl': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_mv_sk_pred': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_mv_bk_pred': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_modv_bk_pred': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'to_modv_sk_pred': pa.Column(pa.Float, pa.Check.in_range(0, 4.1), nullable=True, required=True),
        'zz1': pa.Column(pa.Float, pa.Check.in_range(0, 7.5), nullable=True, required=True),
        'zz2': pa.Column(pa.Float, pa.Check.in_range(0, 7.5), nullable=True, required=True),
        'zz1_pred': pa.Column(pa.Float, pa.Check.in_range(0, 7.5), nullable=True, required=True),
        'zz2_pred': pa.Column(pa.Float, pa.Check.in_range(0, 7.5), nullable=True, required=True),
        'zz1_depl': pa.Column(pa.Float, pa.Check.in_range(0, 7.5), nullable=True, required=True),
        'zz2_depl': pa.Column(pa.Float, pa.Check.in_range(0, 7.5), nullable=True, required=True),
        'komp_zmeny': pa.Column(pa.String, pa.Check.isin(['', '100', '200', '300', '400', '500', '600', '700', '800', '900', '1000', '1100']), nullable=False, default='', required=True),
    }

    # Pomocné navigační objekty
    pno_minimal = {
        'lokalita': pa.Column(pa.Int64, pa.Check.in_range(0, 999999999999), nullable=False, required=True),
        'plocha': pa.Column(pa.Int, pa.Check.in_range(1, 3), nullable=False, required=True),
        'pomno': pa.Column(pa.Int, pa.Check.in_range(1, 2), nullable=True, required=True, default=0),
        'x_m': pa.Column(pa.Float, nullable=True, required=False),
        'y_m': pa.Column(pa.Float, nullable=True, required=False),
        'popis': pa.Column(pa.String, pa.Check.str_length(max_value=255), nullable=False, default=''),
    }

    pno_full_extended = {
    }

    # Výškový model aktuální inventarizace
    mod_vys_minimal = {
        'lokalita': pa.Column(pa.Int64, pa.Check.in_range(0, 999999999999), nullable=False, required=True),
        'plocha': pa.Column(pa.Int, pa.Check.in_range(1, 3), nullable=False, required=True),
        'kmen': pa.Column(pa.Int, pa.Check.in_range(0, 999), nullable=True, required=True, default=0),
        'mod_vys': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(1.3, 80))
            , nullable=True
            , required=True
        ),
    }
    
    mod_vys_full_extended = {
    }

    # Výškový model předchozí inventarizace
    mod_vys_pred_minimal = {
        'lokalita': pa.Column(pa.Int64, pa.Check.in_range(0, 999999999999), nullable=False, required=True),
        'plocha': pa.Column(pa.Int, pa.Check.in_range(1, 3), nullable=False, required=True),
        'kmen_pred': pa.Column(pa.Int, pa.Check.in_range(0, 999), nullable=True, required=True, default=0),
        'mod_vys_pred': pa.Column(
            pa.Float
            , checks = pa.Check(check_range_or_zero(1.3, 80))
            , nullable=True
            , required=True
        ),
    }
    
    mod_vys_pred_full_extended = {
    }

    return {
        'ip': (ip_minimal, ip_full_extended),
        'vz': (vz_minimal, vz_full_extended),
        'pno': (pno_minimal, pno_full_extended),
        'mod_vys_pred': (mod_vys_pred_minimal, mod_vys_pred_full_extended),
        'mod_vys': (mod_vys_minimal, mod_vys_full_extended)
    }

# Vytvoření schémat
def build_schemas():
    base_schemas = get_base_schemas()
    schemas = {}
    
    for key, (minimal_cols, full_extended_cols) in base_schemas.items():
        # Vytvoření minimal schématu
        minimal_schema = pa.DataFrameSchema(minimal_cols, strict=False)
        
        # Vytvoření full schématu (kombinace minimal + rozšíření)
        full_cols = minimal_cols.copy()  # Kopie základních sloupců
        full_cols.update(full_extended_cols)  # Přidání rozšířených sloupců
        full_schema = pa.DataFrameSchema(full_cols, strict=False)
        
        schemas[key] = {
            'minimal': minimal_schema,
            'full': full_schema
        }
    
    return schemas

# Vytvoření všech schémat
SCHEMA_DEFINITIONS = build_schemas()

def get_schema(soubor: str, typ: str = 'minimal') -> Optional[pa.DataFrameSchema]:
    """
    Vrátí schéma pro daný soubor a typ.
    
    Args:
        soubor: Název souboru (např. 'ip', 'vz')
        typ: Typ schématu ('minimal' nebo 'full')
        
    Returns:
        Schéma nebo None, pokud schéma neexistuje
    """
    if soubor in SCHEMA_DEFINITIONS:
        return SCHEMA_DEFINITIONS[soubor].get(typ)
    return None