# Copyright (C) 2025 Robert Blaha, Mendel Univerzity in Brno, HULpro s.r.o.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License or
# any later version.
#  See <https://www.gnu.org/licenses/>.

"""
Modul pro modelování výškových funkcí lesních porostů.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score, mean_squared_error
import math


class ModelVysek:
	"""
	Třída pro modelování výškových funkcí stromů na základě dat z inventarizace.
	"""
	
	def __init__(self, protokoluj_fce=None, debug=False):
		"""
		Inicializace modelu výškových funkcí.
		
		Parametry:
		protokoluj_fce -- volitelná funkce pro protokolování (None = výpis pouze na terminál)
		debug -- volitelný parametr pro výpis podrobných informací
		"""
		# Definice výškových funkcí a jejich počátečních parametrů
		self.funkce = {
			'michajlov': {
				'fce': self._michajlov,
				'pocatecni_parametry': [40, 10],
				'nazev': 'Michajlovova funkce'
			},
			'korf': {
				'fce': self._korf,
				'pocatecni_parametry': [3, 0.3],
				'nazev': 'Korfova funkce'
			},
			'naslund': {
				'fce': self._naslund,
				'pocatecni_parametry': [5, 0.2],
				'nazev': 'Näslundova (Prodanova) funkce'
			},
			'petersen': {
				'fce': self._petersen,
				'pocatecni_parametry': [40, 0.05],
				'nazev': 'Petersenova funkce'
			}
		}
		
		# Výsledky modelu
		self.nejlepsi_funkce = None
		self.nejlepsi_parametry = None
		self.nejlepsi_r2 = None
		self.nejlepsi_rmse = None
		self.vysledky_srovnani = None
		
		# Nastavení funkce pro protokolování
		self.protokoluj = protokoluj_fce if protokoluj_fce else self._default_protokoluj
		self.debug = debug
	def _default_protokoluj(self, message):
		"""
		Výchozí funkce pro protokolování - pouze výpis na terminál.
		"""
		print(message)
	
	@staticmethod
	def _michajlov(dbh, a, b):
		"""
		Michajlovova výšková funkce: h = 1.3 + a * exp(-b/dbh)
		"""
		return 1.3 + a * np.exp(-b / dbh)
	
	@staticmethod
	def _korf(dbh, a, b):
		"""
		Korfova výšková funkce: h = 1.3 + a * dbh^b
		"""
		return 1.3 + a * np.power(dbh, b)
	
	@staticmethod
	def _naslund(dbh, a, b):
		"""
		Näslundova (Prodanova) výšková funkce: h = 1.3 + dbh^2 / (a + b*dbh)^2
		"""
		return 1.3 + np.power(dbh, 2) / np.power(a + b * dbh, 2)
	
	@staticmethod
	def _petersen(dbh, a, b):
		"""
		Petersenova výšková funkce: h = 1.3 + a * (1 - exp(-b*dbh))
		"""
		return 1.3 + a * (1 - np.exp(-b * dbh))
	
	def _prirad_funkci(self, nazev_funkce):
		"""
		Přiřadí výškovou funkci podle názvu.
		
		Parametry:
		nazev_funkce -- název výškové funkce (michajlov, korf, naslund, petersen)
		
		Vrací:
		funkce -- výšková funkce
		pocatecni_parametry -- počáteční odhad parametrů pro nelineární regresi
		"""
		if nazev_funkce not in self.funkce:
			dostupne = ", ".join(self.funkce.keys())
			self.protokoluj(f"......Neznámý typ výškové funkce: {nazev_funkce}. Dostupné funkce: {dostupne}")
			return None, None
		
		return self.funkce[nazev_funkce]['fce'], self.funkce[nazev_funkce]['pocatecni_parametry']
	
	def fituj_funkci(self, dbh_hodnoty, vyska_hodnoty, nazev_funkce, zobrazit_graf=False, nazev=''):
		"""
		Provede nelineární regresi výškové funkce na základě zadaných dat.
		
		Parametry:
		dbh_hodnoty -- pole tlouštěk v prsní výšce [cm]
		vyska_hodnoty -- pole výšek stromů [m]
		nazev_funkce -- typ výškové funkce (michajlov, korf, naslund, petersen)
		zobrazit_graf -- zda zobrazit graf s výsledky
		
		Vrací:
		parametry -- odhadnuté parametry funkce
		r2 -- koeficient determinace
		rmse -- střední kvadratická chyba
		"""
		funkce, pocatecni_parametry = self._prirad_funkci(nazev_funkce)
		
		try:
			# Provedení nelineární regrese
			parametry, kovariance = curve_fit(
				funkce, 
				dbh_hodnoty, 
				vyska_hodnoty, 
				p0=pocatecni_parametry, 
				maxfev=10000
			)
			
			# Vyhodnocení modelu
			predikovane_vysky = funkce(dbh_hodnoty, *parametry)
			r2 = r2_score(vyska_hodnoty, predikovane_vysky)
			rmse = math.sqrt(mean_squared_error(vyska_hodnoty, predikovane_vysky))
			
			if zobrazit_graf:
				self._vykresli_graf(
					dbh_hodnoty, 
					vyska_hodnoty, 
					funkce, 
					parametry, 
					nazev_funkce, 
					r2, 
					rmse,
					nazev
				)
			
			return parametry, r2, rmse
		
		except RuntimeError as e:
			self.protokoluj(f"......Nepovedlo se najít optimální parametry pro funkci {nazev_funkce}: {e}")
			return None, None, None
	
	def _vykresli_graf(self, dbh_hodnoty, vyska_hodnoty, funkce, parametry, nazev_funkce, r2, rmse):
		"""
		Vykreslí graf výškové funkce a změřených dat.
		
		Parametry:
		dbh_hodnoty -- pole tlouštěk v prsní výšce [cm]
		vyska_hodnoty -- pole výšek stromů [m]
		funkce -- použitá výšková funkce
		parametry -- parametry výškové funkce
		nazev_funkce -- název výškové funkce
		r2 -- koeficient determinace
		rmse -- střední kvadratická chyba
		"""
		plt.figure(figsize=(10, 8))
		plt.scatter(dbh_hodnoty, vyska_hodnoty, s=10, alpha=0.5, label='Změřená data')
		
		# Vytvoření křivky modelu
		dbh_rozsah = np.linspace(min(dbh_hodnoty), max(dbh_hodnoty), 100)
		vyskova_krivka = funkce(dbh_rozsah, *parametry)
		plt.plot(
			dbh_rozsah, 
			vyskova_krivka, 
			'r-', 
			linewidth=2, 
			label=f'{self.funkce[nazev_funkce]["nazev"]}: R² = {r2:.4f}, RMSE = {rmse:.2f}'
		)
		
		plt.xlabel('DBH [cm]')
		plt.ylabel('Výška [m]')
		plt.title(f'Výšková funkce - {self.funkce[nazev_funkce]["nazev"]}')
		plt.legend()
		plt.grid(True)
		plt.show()
	
	def srovnej_funkce(self, dbh_hodnoty, vyska_hodnoty, nazev='', zobrazit_graf=True):
		"""
		Porovná různé výškové funkce a najde nejlepší model.
		
		Parametry:
		dbh_hodnoty -- pole tlouštěk v prsní výšce [cm]
		vyska_hodnoty -- pole výšek stromů [m]
		
		Vrací:
		vysledky -- DataFrame s výsledky srovnání funkcí
		"""
		nazvy_funkci = list(self.funkce.keys())
		vysledky = []
		
		plt.figure(figsize=(12, 10))
		plt.scatter(dbh_hodnoty, vyska_hodnoty, s=10, alpha=0.5, label='Změřená data')
		
		nejlepsi_r2 = -float('inf')
		nejlepsi_parametry = None
		nejlepsi_funkce = None
		nejlepsi_rmse = None
		
		dbh_rozsah = np.linspace(min(dbh_hodnoty), max(dbh_hodnoty), 100)
		
		for nazev_funkce in nazvy_funkci:
			funkce_obj = self.funkce[nazev_funkce]
			funkce = funkce_obj['fce']
			
			parametry, r2, rmse = self.fituj_funkci(
				dbh_hodnoty, 
				vyska_hodnoty, 
				nazev_funkce, 
				zobrazit_graf=False
			)
			
			if parametry is not None and r2 is not None:
				vysledky.append({
					'funkce': nazev_funkce,
					'nazev_funkce': funkce_obj['nazev'],
					'parametry': parametry,
					'R2': r2,
					'RMSE': rmse
				})
				
				# Vykreslení křivky modelu
				vyskova_krivka = funkce(dbh_rozsah, *parametry)
				plt.plot(
					dbh_rozsah, 
					vyskova_krivka, 
					linewidth=2, 
					label=f'{funkce_obj["nazev"]}: R² = {r2:.4f}, RMSE = {rmse:.2f}'
				)
				
				# Kontrola, zda je to nejlepší model
				if r2 > nejlepsi_r2:
					nejlepsi_r2 = r2
					nejlepsi_parametry = parametry
					nejlepsi_funkce = nazev_funkce
					nejlepsi_rmse = rmse
		
		plt.xlabel('DBH [cm]')
		plt.ylabel('Výška [m]')
		if nazev:
			plt.title(f'Porovnání výškových funkcí - {nazev}')
		else:
			plt.title('Porovnání výškových funkcí')
		plt.legend()
		plt.grid(True)
		if zobrazit_graf:
			plt.show()
		
		# Uložení výsledků
		self.vysledky_srovnani = pd.DataFrame(vysledky)
		self.nejlepsi_funkce = nejlepsi_funkce
		self.nejlepsi_parametry = nejlepsi_parametry
		self.nejlepsi_r2 = nejlepsi_r2
		self.nejlepsi_rmse = nejlepsi_rmse
		
		# Výpis výsledků
		if self.debug:
			self.protokoluj("Výsledky porovnání výškových funkcí:\n")
			self.protokoluj(self.vysledky_srovnani[['funkce', 'nazev_funkce', 'R2', 'RMSE']].to_string())
			
		if nejlepsi_funkce:
			if self.debug:
				self.protokoluj(f"......Nejlepší model: {nejlepsi_funkce} ({self.funkce[nejlepsi_funkce]['nazev']})")
				self.protokoluj(f"......Parametry: {nejlepsi_parametry}")
				self.protokoluj(f"......R²: {nejlepsi_r2:.4f}")
				self.protokoluj(f"......RMSE: {nejlepsi_rmse:.2f}")
		
		return self.vysledky_srovnani
	
	def zpracuj_data(self, df, sloupec_lokalita='lokalita', sloupec_strom='kmen', 
					sloupec_dbh='tloustka_km', sloupec_vyska='mvyska', sloupec_mod_vys='mod_vys',
					nazev_funkce='', zobrazit_grafy=True, nazev=''):
		"""
		Zpracuje data lesní inventarizace a odhadne výšky stromů pomocí výškové funkce.
		Vytvoří vždy jeden model pro všechna data.
		
		Parametry:
		df -- pandas DataFrame s daty inventarizace
		sloupec_lokalita -- název sloupce s identifikátorem inventarizační lokality
		sloupec_strom -- název sloupce s identifikátorem stromu
		sloupec_dbh -- název sloupce s tloušťkou v prsní výšce [cm]
		sloupec_vyska -- název sloupce s výškou stromu [m]
		sloupec_mod_vys -- název sloupce pro uložení modelové výšky
		nazev_funkce -- explicitní volba výškové funkce (volitelné)
		zobrazit_grafy -- zda zobrazit grafy s výsledky
		
		Vrací:
		df_vysledek -- pandas DataFrame s doplněnými výškami
		info -- slovník s informacemi o použité výškové funkci a jejích parametrech
		"""
		# Kontrola vstupních dat
		if sloupec_dbh not in df.columns:
			self.protokoluj(f"......Sloupec {sloupec_dbh} nebyl nalezen v DataFrame")
			return None, None
		
		# Vytvoření kopie pro výsledky
		df_vysledek = df.copy()
		
		# Výběr dat pro modelování - stromy, které mají změřeny obě hodnoty
		mask_kompletni = ~df_vysledek[sloupec_dbh].isna() & ~df_vysledek[sloupec_vyska].isna() & (df_vysledek[sloupec_vyska] > 0)
		df_kompletni = df_vysledek[mask_kompletni].copy()
		
		if len(df_kompletni) < 10:
			self.protokoluj(f"......Varování: K dispozici je pouze {len(df_kompletni)} stromů s kompletními daty.")
			self.protokoluj("......To může být příliš málo pro spolehlivou regresi.")
		
		# Celkový model pro všechna data
		self.protokoluj(f"......Vytváření výškového modelu. Počet stromů s kompletními daty: {len(df_kompletni)}")
		
		# Extrakce hodnot pro modelování
		dbh_hodnoty = df_kompletni[sloupec_dbh].values
		vyska_hodnoty = df_kompletni[sloupec_vyska].values
		
		# Vytvoření modelu podle zadané funkce nebo výběr nejlepší funkce
		if nazev_funkce != '':
			parametry, r2, rmse = self.fituj_funkci(
				dbh_hodnoty,
				vyska_hodnoty,
				nazev_funkce,
				zobrazit_graf=zobrazit_grafy,
				nazev=nazev
			)
			funkce_obj = self.funkce[nazev_funkce]
			pouzita_funkce = nazev_funkce
			pouzite_parametry = parametry
			self.nejlepsi_r2 = r2
			self.nejlepsi_rmse = rmse
		else:
			self.srovnej_funkce(dbh_hodnoty, vyska_hodnoty, nazev=nazev, zobrazit_graf=zobrazit_grafy)
			pouzita_funkce = self.nejlepsi_funkce
			pouzite_parametry = self.nejlepsi_parametry
			funkce_obj = self.funkce[pouzita_funkce]
		
		# Vytvoření modelové výšky pro všechny stromy které mají DBH
		mask_ma_dbh = ~df_vysledek[sloupec_dbh].isna()
		
		if sum(mask_ma_dbh) > 0:
			df_vysledek.loc[mask_ma_dbh, sloupec_mod_vys] = funkce_obj['fce'](
				df_vysledek.loc[mask_ma_dbh, sloupec_dbh].values,
				*pouzite_parametry
			)
		
		# Příprava informací o modelu
		info = {
			'funkce': pouzita_funkce,
			'nazev_funkce': funkce_obj['nazev'],
			'parametry': pouzite_parametry,
			'R2': self.nejlepsi_r2,
			'RMSE': self.nejlepsi_rmse
		}
		
		# Výpis statistik
		if self.debug:
			self.protokoluj("......Statistiky modelových výšek:")
			statistiky = df_vysledek[[sloupec_dbh, sloupec_mod_vys]].describe()
			self.protokoluj(statistiky.to_string())
		
		return df_vysledek, info


# Funkce pro jednodušší použití modelu
def modeluj_vysky(df, lokalita='lokalita', strom='kmen', dbh='tloustka_km', vyska='mvyska', mod_vys='mod_vys', funkce=None, zobraz_grafy=True):
	"""
	Pomocná funkce pro modelování výšek stromů.
	
	Parametry:
	df -- pandas DataFrame s daty inventarizace
	lokalita -- název sloupce s identifikátorem inventarizační lokality (volitelné)
	strom -- název sloupce s identifikátorem stromu (volitelné)
	dbh -- název sloupce s tloušťkou v prsní výšce [cm]
	vyska -- název sloupce s výškou stromu [m]
	mod_vys -- název sloupce pro uložení modelové výšky
	funkce -- explicitní volba výškové funkce ('michajlov', 'korf', 'naslund', 'petersen')
	zobraz_grafy -- zda zobrazit grafy s výsledky
	
	Vrací:
	df_vysledek -- pandas DataFrame s doplněnými výškami
	info -- slovník s informacemi o použité výškové funkci a jejích parametrech
	"""
	model = ModelVysek()
	return model.zpracuj_data(
		df=df,
		sloupec_lokalita=lokalita,
		sloupec_strom=strom,
		sloupec_dbh=dbh,
		sloupec_vyska=vyska,
		sloupec_mod_vys=mod_vys,
		nazev_funkce=funkce,
		zobrazit_grafy=zobraz_grafy
	)


if __name__ == "__main__":
	# Příklad použití
	print("Tento modul slouží k modelování výšek stromů.")
	print("Pro použití importujte funkci modeluj_vysky nebo třídu ModelVysek")
	
	# Ukázkový kód
	print("\nUkázka použití:")
	print("""
	import pandas as pd
	from spi_model_vysek import modeluj_vysky

	# Načtení dat
	df = pd.read_csv('data_inventarizace.csv')
	
	# Modelování výšek
	df_vysledek, info = modeluj_vysky(
		df, 
		lokalita='lokalita',  # nepovinný parametr
		dbh='tloustka_cm',    # název sloupce s DBH
		vyska='vyska_m',      # název sloupce s výškou
		funkce='michajlov'    # explicitní volba funkce (nepovinné)
	)
	
	# Uložení výsledků
	df_vysledek.to_csv('vysledky_s_vyskami.csv', index=False)
	""")
