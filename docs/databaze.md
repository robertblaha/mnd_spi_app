# Dokumentace databázového schématu mnd_spi_app

*Verze schématu: 1.0*

## Přehled tabulek

- [dreviny](#dreviny)
- [lhc](#lhc)

## dreviny

Číselník druhů dřevin

### Sloupce

| Sloupec | Popis |
|---------|-------|
| id | Unikátní identifikátor záznamu |
| nazev | Celý název dřeviny |
| kod_dreviny | Kód dřeviny dle legislativy |
| zkratka | Zkratka dřeviny používaná v systému |
| skupina | Skupina dřevin (jehličnaté/listnaté) |

### SQL definice

```sql

        CREATE TABLE IF NOT EXISTS dreviny (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nazev TEXT NOT NULL,
            kod_dreviny TEXT NOT NULL,
            zkratka TEXT,
            skupina TEXT
        );
```

## lhc

Tabulka obsahující základní informace o LHC (obecně kód subjektu, za který je výpočet prováděn)

### Sloupce

| Sloupec | Popis |
|---------|-------|
| id | Unikátní identifikátor záznamu |
| kod | Číslo LHC (obecně kód subjektu, za který je výpočet prováděn) |
| nazev | Název LHC |
| lhp_platnost_od | Datum začátku platnosti lesního hospodářského plánu (LHP) |
| lhp_platnost_do | Datum konce platnosti lesního hospodářského plánu (LHP) |
| popis | Textový popis LHC |
| datum_vytvoreni | Datum a čas vytvoření záznamu o LHC v databázi |

### SQL definice

```sql

        CREATE TABLE IF NOT EXISTS lhc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kod TEXT NOT NULL,
            nazev TEXT NOT NULL,
            lhp_platnost_od TEXT NOT NULL,
            lhp_platnost_do TEXT NOT NULL,
            popis TEXT,
            datum_vytvoreni TEXT NOT NULL
        );
```

