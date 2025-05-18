# Copyright (C) 2025 Robert Blaha, Mendel Univerzity in Brno, HULpro s.r.o.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License or
# any later version.
#  See <https://www.gnu.org/licenses/>.

import yaml
import os
import datetime
import geopandas as gpd
import pandas as pd
from . import spi_utils
from sqlalchemy import create_engine, text, event
import traceback
import pandera as pa
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)

class spi:
	def __init__(self, lhc, debug):
		self.lhc = lhc
		self.debug = debug

		# načtení konfigurace
		self.lhc_config = yaml.safe_load(open(f"./konfigurace/{self.lhc}.yaml", encoding="utf-8"))
		self.vypocet_config = yaml.safe_load(open(f"./konfigurace/{self.lhc}_vypocet.yaml", encoding="utf-8"))
		try:
			self.uid_config = yaml.safe_load(open(f"./konfigurace/{self.lhc}_uid.yaml", encoding="utf-8"))
		except FileNotFoundError:
			# Pokud soubor neexistuje, vytvoříme prázdný slovník
			self.uid_config = {}
			# Můžeme také vytvořit prázdný soubor
			with open(f"./konfigurace/{self.lhc}_uid.yaml", "w", encoding="utf-8") as f:
				yaml.dump({}, f)
		self.kroky_config = yaml.safe_load(open("./konfigurace/vypocet_kroky.yaml", encoding="utf-8"))
		
		# nastavení zachytávání PostgreSQL zpráv
		def receive_postgres_message(context):
			if hasattr(context.original_exception, 'diag'):
				# Zachycení NOTICE, WARNING, ERROR zpráv
				self.protokoluj(context.original_exception.diag.message_primary)

		# vytvoření připojení k databázi
		self.pg_engine = create_engine(
			f"postgresql://{self.lhc_config['db_config']['postgres_user']}:{self.lhc_config['db_config']['postgres_password']}@{self.lhc_config['db_config']['postgres_host']}:{self.lhc_config['db_config']['postgres_port']}/{self.lhc_config['db_config']['postgres_db']}"
		)
		
		# připojení handleru pro zachytávání zpráv na úrovni Engine
		event.listen(self.pg_engine, "handle_error", receive_postgres_message)
		
		# vytvoření připojení
		self.pg_conn = self.pg_engine.connect()
		
		# inicializace protokolu
		self.protokol_path = os.path.join(self.get_data_dir(), 'vystup', 'protokol_vypoctu.txt')
		# otevření souboru protokolu pro zápis (přepíše existující)
		self.protokol_file = open(self.protokol_path, 'w', encoding='utf-8')
		self.protokoluj(f"Zahájení nového výpočtu pro LHC {self.lhc}")

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		# Uzavření protokolu
		if hasattr(self, 'protokol_file'):
			if exc_type is not None:
				# Pokud došlo k chybě, zaprotokolujeme ji
				self.protokoluj(f"Výpočet ukončen chybou: {exc_type.__name__}: {str(exc_value)}")
			self.protokoluj("Uzavření protokolu")
			self.protokol_file.close()
		
		# Uzavření databáze
		if hasattr(self, 'conn'):
			self.conn.close()
		if hasattr(self, 'pg_engine'):
			self.pg_engine.dispose()

	def get_data_dir(self):
		"""Vrátí cestu k adresáři s daty."""
		return self.lhc_config.get('data_dir', '')
    
	def protokoluj(self, message):
		"""
		Zapíše zprávu do protokolu a současně ji vypíše na obrazovku.
		
		Args:
			message (str): Text zprávy k zaprotokolování
		"""
		# Přidání časového razítka
		timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
		formatted_message = f"[{timestamp}] {message}"
		
		# Výpis na obrazovku
		print(formatted_message)
		
		# Zápis do souboru
		self.protokol_file.write(formatted_message + '\n')
		self.protokol_file.flush()  # Zajistí okamžitý zápis do souboru

	def inicializace_lhp(self):
		"""
		Inicializuje LHP v databázi.
		"""
		zapis_yaml = False
		vysledek = 0

		# Firma
		if self.uid_config.get('uid_firm', ''):
			self.protokoluj(f"..Firma již v databázi existuje (UID: {self.uid_config['uid_firm']})")
			with self.pg_engine.begin() as conn:
				result = conn.execute(
					text("""
						update happ.firm 
		  				set 
		  					id_number = :ico
		  					, full_name = :nazev
		  					, legal = :legal
						where uid = :uid_firm
					"""),
					{
						'ico': self.lhc_config['ico'],
						'nazev': self.lhc_config['nazev_firmy'],
						'legal': self.lhc_config['legislativni_prostredi'],
						'uid_firm': self.uid_config['uid_firm'],
					}
				)
			self.protokoluj(f"..Provedena aktualizace firmy")
		else:
			self.protokoluj(f"..Založení firmy {self.lhc_config['nazev_firmy']}, IČ: {self.lhc_config['ico']}")
			with self.pg_engine.begin() as conn:
				result = conn.execute(
					text("""
						INSERT INTO happ.firm (id_number, full_name, legal)
						VALUES (:ico, :nazev, :legal)
						RETURNING uid
					"""),
					{
						'ico': self.lhc_config['ico'],
						'nazev': self.lhc_config['nazev_firmy'],
						'legal': self.lhc_config['legislativni_prostredi']
					}
				)
				new_uid = result.scalar()
			self.protokoluj(f"..Vytvořena firma s UID: {new_uid}")
			self.uid_config['uid_firm'] = str(new_uid)
			zapis_yaml = True

		# LHC
		if self.uid_config.get('uid_lhc', ''):
			self.protokoluj(f"..LHC již v databázi existuje (UID: {self.uid_config['uid_lhc']})")
			with self.pg_engine.begin() as conn:
				result = conn.execute(
					text("""
						update happ.lhc
						set code = :kod, full_name = :nazev, legal = :legal
						where uid = :uid_lhc	
					"""),
					{
						'uid_lhc': self.uid_config['uid_lhc'],
						'kod': self.lhc_config['lhc_kod'],
						'nazev': self.lhc_config['nazev'],
						'legal': self.lhc_config['legislativni_prostredi']	
					}
				)
				self.protokoluj(f"..Provedena aktualizace LHC")
		else:
			self.protokoluj(f"..Založení LHC {self.lhc_config['lhc_kod']} {self.lhc_config['nazev']}")
			with self.pg_engine.begin() as conn:
				result = conn.execute(
					text("""
						INSERT INTO happ.lhc (uid_firm, code, full_name, legal)
						VALUES (:uid_firm, :kod, :nazev, :legal)
						RETURNING uid
					"""),
					{
						'uid_firm': self.uid_config['uid_firm'],
						'kod': self.lhc_config['lhc_kod'],
						'nazev': self.lhc_config['nazev'],
						'legal': self.lhc_config['legislativni_prostredi']
					}
				)
				new_uid = result.scalar()
			self.protokoluj(f"..Vytvořeno LHC s UID: {new_uid}")
			self.uid_config['uid_lhc'] = str(new_uid)
			zapis_yaml = True

		# LHP
		if self.uid_config.get('uid_lhp', ''):
			self.protokoluj(f"..LHP již v databázi existuje (UID: {self.uid_config['uid_lhp']})")
			with self.pg_engine.begin() as conn:
				result = conn.execute(
					text("""
						update happ.lhp
						set lhp_od = :lhp_od, pocet_let = :pocet_let, tez_lhe = :tez_lhe, legal = :legal, ktlt = :ktlt
						where uid = :uid_lhp	
					"""),
					{
						'uid_lhp': self.uid_config['uid_lhp'],
						'lhp_od': self.lhc_config['lhp_platnost_od'],
						'pocet_let': self.lhc_config['pocet_let_platnosti'],
						'legal': self.lhc_config['legislativni_prostredi'],
						'ktlt': 'TLT',
						'tez_lhe': self.lhc_config['tez_lhe']
					}
				)
				self.protokoluj(f"..Provedena aktualizace LHP")
		else:
			self.protokoluj(f"..Založení LHP od {self.lhc_config['lhp_platnost_od']}")
			with self.pg_engine.begin() as conn:
				result = conn.execute(
					text("""
						INSERT INTO happ.lhp (uid_firm, uid_lhc, lhp_od, pocet_let, tez_lhe, legal, ktlt)
						VALUES (:uid_firm, :uid_lhc, :lhp_od, :pocet_let, :tez_lhe, :legal, :ktlt)
						RETURNING uid
					"""),
					{
						'uid_firm': self.uid_config['uid_firm'],
						'uid_lhc': self.uid_config['uid_lhc'],
						'lhp_od': self.lhc_config['lhp_platnost_od'],
						'pocet_let': self.lhc_config['pocet_let_platnosti'],
						'legal': self.lhc_config['legislativni_prostredi'],
						'ktlt': 'TLT',
						'tez_lhe': self.lhc_config['tez_lhe']
					}
				)
				new_uid = result.scalar()
			self.protokoluj(f"..Vytvořen LHP s UID: {new_uid}")
			self.uid_config['uid_lhp'] = str(new_uid)
			zapis_yaml = True

		# zápis konfigurace do YAML
		if zapis_yaml:
			with open(f"./konfigurace/{self.lhc}_uid.yaml", "w", encoding="utf-8") as file:
				yaml.safe_dump(self.uid_config, file, default_flow_style=False, allow_unicode=True)

		# Hospodářské skupiny
		self.protokoluj(f"..Aktualizace hospodářských skupin")
		# Vložení typu podoblasti
		with self.pg_engine.begin() as conn:
			if self.debug:
				self.protokoluj(f"....Typ podoblasti HOS")
			result = conn.execute(
				text("""
					INSERT INTO dsuhul.pobl_typy (uid_firm, uid_lhc, uid_lhp, kod, nazev, popis, db_col)
					VALUES (:uid_firm, :uid_lhc, :uid_lhp, :kod, :nazev, :popis, :db_col)
					ON CONFLICT (kod, uid_lhp, uid_lhc, uid_firm) DO 
					UPDATE SET
						nazev = EXCLUDED.nazev,
						popis = EXCLUDED.popis,
						db_col = EXCLUDED.db_col
					RETURNING uid
				"""),
				{
					'uid_firm': self.uid_config['uid_firm'],
					'uid_lhc': self.uid_config['uid_lhc'],
					'uid_lhp': self.uid_config['uid_lhp'],
					'kod': 'HOS',
					'nazev': 'Hospodářské skupiny',
					'popis': '',
					'db_col': self.lhc_config['hos']['det_sloupec']
				}
			)
			uid_tpobl = result.scalar()
			if self.debug:
				self.protokoluj(f"......UID: {uid_tpobl}")
		
		# Samotné hospodářské skupiny
		hos_data = self.lhc_config['hos']['skupiny']
		with self.pg_engine.begin() as conn:
			for key, skupina in hos_data.items():
				if self.debug:
					self.protokoluj(f"....Hospodářská skupina {key}: {skupina['nazev']}")
				result = conn.execute(
					text("""
						INSERT INTO dsuhul.pobl (uid_firm, uid_lhc, uid_lhp, uid_tpobl, kod, nazev, popis, kod_typu, det_kod)
						VALUES (:uid_firm, :uid_lhc, :uid_lhp, :uid_tpobl, :kod, :nazev, :popis, :kod_typu, :det_kod)
						ON CONFLICT (kod, uid_tpobl) DO 
		  				UPDATE SET
		  					nazev = EXCLUDED.nazev,
		  					popis = EXCLUDED.popis,
		  					kod_typu = EXCLUDED.kod_typu,
		  					det_kod = EXCLUDED.det_kod
						RETURNING uid
					"""),
					{
						'uid_firm': self.uid_config['uid_firm'],
						'uid_lhc': self.uid_config['uid_lhc'],
						'uid_lhp': self.uid_config['uid_lhp'],
						'uid_tpobl': str(uid_tpobl),
						'kod': key,
						'nazev': skupina['nazev'],
						'popis': skupina['popis'],
						'kod_typu': 'HOS',
						'det_kod': skupina['det_kod']
					}
				)
				new_uid = result.scalar()
				if self.debug:
					self.protokoluj(f"......UID: {new_uid}")
		self.protokoluj(f"....Aktualizace hospodářských skupin dokončena")

		# Tloušťkové třídy
		self.protokoluj(f"..Aktualizace tloušťkových tříd")
		# Vložení definice tloušťkové třídy
		with self.pg_engine.begin() as conn:
			if self.debug:
				self.protokoluj(f"....Tloušťková třída TLT")
			result = conn.execute(
				text("""
					INSERT INTO dsuhul.list_ktlt_types (uid_firm, code, descr)
					VALUES (:uid_firm, :code, :descr)
					ON CONFLICT (uid_firm, code) DO 
					UPDATE SET
						descr = EXCLUDED.descr
					RETURNING uid
				"""),
				{
					'uid_firm': self.uid_config['uid_firm'],
					'code': 'TLT',
					'descr': 'Tloušťkové třídy'
				}
			)
			uid_ktlt = result.scalar()
			if self.debug:
				self.protokoluj(f"......UID: {uid_ktlt}")
		
		# Samotné tloušťkové třídy
		with self.pg_engine.begin() as conn:
			for i in range(self.lhc_config['tlt']['prvni'], self.lhc_config['tlt']['posledni'], self.lhc_config['tlt']['interval']):
				min_d13 = i - self.lhc_config['tlt']['interval']/2 + 0.1
				max_d13 = i + self.lhc_config['tlt']['interval']/2
				if self.debug:
					self.protokoluj(f"....Třída {i}: {min_d13} - {max_d13}")
				result = conn.execute(
					text("""
						INSERT INTO dsuhul.ktlt (uid_firm, uid_lktl, trida, min_d13, max_d13)
						VALUES (:uid_firm, :uid_lktl, :trida, :min_d13, :max_d13)
						ON CONFLICT (uid_firm, uid_lktl, trida) DO 
		  				UPDATE SET
		  					min_d13 = EXCLUDED.min_d13,
		  					max_d13 = EXCLUDED.max_d13
						RETURNING uid
					"""),
					{
						'uid_firm': self.uid_config['uid_firm'],
						'uid_lktl': str(uid_ktlt),
						'trida': i,
						'min_d13': min_d13,
						'max_d13': max_d13
					}
				)
				new_uid = result.scalar()
				if self.debug:
					self.protokoluj(f"......UID: {new_uid}")
		self.protokoluj(f"....Aktualizace tloušťkových tříd dokončena")

		# Konfigurace inventarizačních lokalit
		self.protokoluj(f"..Aktualizace konfigurací inventarizačních lokalit")
		kil_data = self.lhc_config['kil']
		with self.pg_engine.begin() as conn:
			for key, konfigurace in kil_data.items():
				if self.debug:
					self.protokoluj(f"....Konfigurace {key}: {konfigurace['nazev']}")
				result = conn.execute(
					text("""
						INSERT INTO dsuhul.list_kil_types (uid_firm, code, descr)
						VALUES (:uid_firm, :code, :descr)
						ON CONFLICT (uid_firm, code) DO 
		  				UPDATE SET
		  					descr = EXCLUDED.descr
					RETURNING uid
				"""),
				{
					'uid_firm': self.uid_config['uid_firm'],
					'code': key,
					'descr': konfigurace['nazev']
				}
			)
			uid_kil = result.scalar()
			if self.debug:
				self.protokoluj(f"......UID: {uid_kil}")
			# Plochy lokality
			ip_data = konfigurace['plochy']
			self.protokoluj(f"......Plochy lokality")
			for key, plocha in ip_data.items():
				if self.debug:
					self.protokoluj(f"........Plocha {key}")
				result = conn.execute(
					text("""
						INSERT INTO dsuhul.kil (uid_firm, uid_lkt, plocha, azimut_pid, vzd_pid, rf)
						VALUES (:uid_firm, :uid_lkt, :plocha, :azimut_pid, :vzd_pid, :rf)
						ON CONFLICT (uid_firm, uid_lkt, plocha) DO 
		  				UPDATE SET
		  					azimut_pid = EXCLUDED.azimut_pid,
		  					vzd_pid = EXCLUDED.vzd_pid,
		  					rf = EXCLUDED.rf
						RETURNING uid
					"""),
					{
						'uid_firm': self.uid_config['uid_firm'],
						'uid_lkt': str(uid_kil),
						'plocha': key,
						'azimut_pid': plocha['azimut_pid'],
						'vzd_pid': plocha['vzd_pid'],
						'rf': plocha['rf']
					}
				)
				uid_ip = result.scalar()
				if self.debug:
					self.protokoluj(f"..........UID: {uid_ip}")
				# Podplochy plochy
				sp_data = plocha['podplochy']
				self.protokoluj(f"............Podplochy plochy")
				for key, podplocha in sp_data.items():
					if self.debug:
						self.protokoluj(f"..............Podplocha {key}")
					result = conn.execute(
						text("""
							INSERT INTO dsuhul.kip (uid_firm, uid_lkt, uid_kil, podplocha, sp_r, min_d13)
							VALUES (:uid_firm, :uid_lkt, :uid_kil, :podplocha, :sp_r, :min_d13)	
							ON CONFLICT (uid_firm, uid_lkt, uid_kil, podplocha) DO 
		  					UPDATE SET
		  						sp_r = EXCLUDED.sp_r,
		  						min_d13 = EXCLUDED.min_d13
							RETURNING uid
						"""),
						{
							'uid_firm': self.uid_config['uid_firm'],
							'uid_lkt': str(uid_kil),
							'uid_kil': str(uid_ip),
							'podplocha': key,
							'sp_r': podplocha['sp_r'],
							'min_d13': podplocha['min_d13']
						}
					)
					uid_sp = result.scalar()
					if self.debug:
						self.protokoluj(f"................UID: {uid_sp}")
		self.protokoluj(f"..Aktualizace konfigurací inventarizačních lokalit dokončena")

		# Výběrová strata
		self.protokoluj(f"..Aktualizace výběrových strat")
		with self.pg_engine.begin() as conn:
			for key, stratum in self.lhc_config['vs'].items():
				if self.debug:
					self.protokoluj(f"....Stratum {key}: {stratum['stratum_popis']}")
				result = conn.execute(
					text("""
						INSERT INTO dsuhul.vs (uid_firm, uid_lhc, stratum, stratum_popis, lkt_code)
						VALUES (:uid_firm, :uid_lhc, :stratum, :stratum_popis, :lkt_code)
						ON CONFLICT (uid_firm, uid_lhc, stratum) DO 
		  				UPDATE SET
		  						stratum_popis = EXCLUDED.stratum_popis,
		  					lkt_code = EXCLUDED.lkt_code
						RETURNING uid
					"""),
					{
						'uid_firm': self.uid_config['uid_firm'],
						'uid_lhc': self.uid_config['uid_lhc'],
						'stratum': key,
						'stratum_popis': stratum['stratum_popis'],
						'lkt_code': stratum['kil']
					}
				)
				uid_vs = result.scalar()
				if self.debug:
					self.protokoluj(f"......UID: {uid_vs}")
		self.protokoluj(f"..Aktualizace výběrových strat dokončena")

		# Inventarizační kampaně
		self.protokoluj(f"..Aktualizace inventarizačních kampaní")
		with self.pg_engine.begin() as conn:
			for key, kampan in self.lhc_config['ik'].items():
				if self.debug:
					self.protokoluj(f"....Kampaň {key}")
				result = conn.execute(
					text("""
						INSERT INTO dsuhul.ik (uid_firm, uid_lhc, uid_lhp, kampan, kampan_od, kampan_do, legal)
						VALUES (:uid_firm, :uid_lhc, :uid_lhp, :kampan, :kampan_od, :kampan_do, :legal)
						ON CONFLICT (uid_firm, uid_lhc, uid_lhp, kampan) DO 
		  				UPDATE SET
		  						kampan_od = EXCLUDED.kampan_od,
		  						kampan_do = EXCLUDED.kampan_do,
		  						legal = EXCLUDED.legal
						RETURNING uid
					"""),
					{
						'uid_firm': self.uid_config['uid_firm'],
						'uid_lhc': self.uid_config['uid_lhc'],
						'uid_lhp': self.uid_config['uid_lhp'],
						'kampan': key,
						'kampan_od': kampan['kampan_od'],
						'kampan_do': kampan['kampan_do'],
						'legal': kampan['legal']
					}
				)
				uid_ik = result.scalar()
				if self.debug:
					self.protokoluj(f"......UID: {uid_ik}")

		# vložení vazeb na výběrová strata
		# pokud je pro všechny, rovnou se vloží ke všem
		if kampan.get('vs_all', 0):
			self.protokoluj(f"......Vložení vazeb na všechna výběrová strata")
			with self.pg_engine.begin() as conn:
				conn.execute(text("""
					insert into dsuhul.vs_spi (uid_firm, uid_lhc, uid_lhp, uid_ik, uid_vs)
					select :uid_firm, :uid_lhc, :uid_lhp, :uid_ik, uid
					from dsuhul.vs vs
					where vs.uid_firm = :uid_firm
					ON CONFLICT (uid_firm, uid_lhc, uid_lhp, uid_ik, uid_vs) DO NOTHING
				""")
				, {
					'uid_firm': self.uid_config['uid_firm'],
					'uid_lhc': self.uid_config['uid_lhc'],
					'uid_lhp': self.uid_config['uid_lhp'],
					'uid_ik': uid_ik
				})
				self.protokoluj(f"......Vložení vazeb na všechna výběrová strata dokončeno")
		else:
			for vs in kampan.get('vs', []):
				self.protokoluj(f"......Vložení vazby na výběrové stratum {vs}")
				with self.pg_engine.begin() as conn:
					conn.execute(text("""
						insert into dsuhul.vs_spi (uid_firm, uid_lhc, uid_lhp, uid_ik, uid_vs)
						values (:uid_firm, :uid_lhc, :uid_lhp, :uid_ik, :uid_vs)
						ON CONFLICT (uid_firm, uid_lhc, uid_lhp, uid_ik, uid_vs) DO NOTHING
						RETURNING uid
					"""), {
						'uid_firm': self.uid_config['uid_firm'],
						'uid_lhc': self.uid_config['uid_lhc'],
						'uid_lhp': self.uid_config['uid_lhp'],
						'uid_ik': uid_ik,
						'uid_vs': vs
					})
					uid_vs_spi = result.scalar()
					if self.debug:
						self.protokoluj(f"..........UID: {uid_vs_spi}")
		self.protokoluj(f"..Aktualizace inventarizačních kampaní dokončena")

		return(vysledek)

	def inicializace_podoblasti(self):
		"""
		Inicializuje podoblasti v databázi.
		"""
		vysledek = 0
		# Podoblasti
		if self.vypocet_config['inicializace'].get('podoblasti', 0):
			self.protokoluj(f"..Aktualizace podoblastí")
			for pobl_typ, typ_data in self.lhc_config['podoblasti'].items():
				self.protokoluj(f"....Typ podoblasti {pobl_typ}: {typ_data['nazev']}")

				# Vložení typu podoblasti
				with self.pg_engine.begin() as conn:
					result = conn.execute(
						text("""
							INSERT INTO dsuhul.pobl_typy (uid_firm, uid_lhc, uid_lhp, kod, nazev, popis, db_col)
							VALUES (:uid_firm, :uid_lhc, :uid_lhp, :kod, :nazev, :popis, :db_col)
							ON CONFLICT (kod, uid_lhp, uid_lhc, uid_firm) DO 
							UPDATE SET
								nazev = EXCLUDED.nazev,
								popis = EXCLUDED.popis,
								db_col = EXCLUDED.db_col
							RETURNING uid
						"""),
						{
							'uid_firm': self.uid_config['uid_firm'],
							'uid_lhc': self.uid_config['uid_lhc'],
							'uid_lhp': self.uid_config['uid_lhp'],
							'kod': pobl_typ,
							'nazev': typ_data['nazev'],
							'popis': typ_data['popis'],
							'db_col': pobl_typ
						}
					)
					uid_tpobl = result.scalar()
					if self.debug:
						self.protokoluj(f"......UID: {uid_tpobl}")
		
				# Samotné podoblasti
				for pobl, pobl_data in typ_data['oblasti'].items():
					self.protokoluj(f"......Podoblast {pobl}: {pobl_data['nazev']}")
					with self.pg_engine.begin() as conn:
						self.protokoluj(f"......{pobl}: {pobl_data['nazev']}")
						result = conn.execute(
							text("""
								INSERT INTO dsuhul.pobl (uid_firm, uid_lhc, uid_lhp, uid_tpobl, kod, nazev, popis, kod_typu, det_kod)
								VALUES (:uid_firm, :uid_lhc, :uid_lhp, :uid_tpobl, :kod, :nazev, :popis, :kod_typu, :det_kod)
								ON CONFLICT (kod, uid_tpobl) DO 
								UPDATE SET
									nazev = EXCLUDED.nazev,
									popis = EXCLUDED.popis,
									kod_typu = EXCLUDED.kod_typu,
									det_kod = EXCLUDED.det_kod
								RETURNING uid
							"""),
							{
								'uid_firm': self.uid_config['uid_firm'],
								'uid_lhc': self.uid_config['uid_lhc'],
								'uid_lhp': self.uid_config['uid_lhp'],
								'uid_tpobl': str(uid_tpobl),
								'kod': pobl,
								'nazev': pobl_data['nazev'],
								'popis': pobl_data['popis'],
								'kod_typu': pobl_typ,
								'det_kod': pobl
							}
						)
						new_uid = result.scalar()
						if self.debug:
							self.protokoluj(f"......UID: {new_uid}")
			self.protokoluj(f"....Aktualizace podoblastí dokončena")
		else:
			self.protokoluj(f"..Podoblasti nebyly aktualizovány")
		
		return(vysledek)

	def import_gis(self):
		"""
		Importuje mapové vrstvy do databáze.
		"""
		# protože jsem v této metodě tak vím, že se má importovat. 
		# takže můžu rovnou řešit import jednotlivých vrstev
		vysledek = 0

		importovane_vrstvy = []
		importovane_vrstvy = list(self.vypocet_config['import_gis']['vrstvy'].keys())
		if not importovane_vrstvy:
			self.protokoluj("Nejsou definovány žádné mapové vrstvy k importu")
			return(vysledek)
		for vrstva in importovane_vrstvy:
			if self.vypocet_config['import_gis']['vrstvy'][vrstva]:
				self.protokoluj(f"..Vrstva {vrstva}")
				import_file = os.path.join(self.get_data_dir(), 'vstup', 'mapove_vrstvy', self.lhc_config['mapove_vrstvy'][vrstva].get('soubor', vrstva + '.shp'))
				if not os.path.exists(import_file):
					self.protokoluj(f"Soubor {import_file} neexistuje")
					return(20)
				
				# samotné načtení vrstvy a uložení do databáze
				self.protokoluj(f"....Soubor: {import_file}")
				
				gdf = gpd.read_file(import_file)
				gdf.set_crs(self.lhc_config.get('CRS', 'EPSG:5514'), inplace=True)
				# Převod názvů sloupců na malá písmena
				gdf.columns = [col.lower() for col in gdf.columns]
				self.protokoluj(f"......Načteno {len(gdf)} záznamů")

				gdf = gdf.rename(columns={"geometry": "ggeom"})
				gdf = gdf.set_geometry("ggeom")
				gdf.to_postgis('f_' + self.lhc_config['ico'].lower() + '_input_' + vrstva, self.pg_conn, schema='maps_layers', if_exists='replace', index=False)
				self.protokoluj(f"......Uloženo do PostgreSQL")
			else:
				self.protokoluj(f"..Vrstva {vrstva} ignorována")
		return(vysledek)

	def vypocet_ploch(self):
		"""
		Vypočítá celkové plochy a plochy PSPP.
		"""
		try:
			with self.pg_engine.begin() as conn:
				conn.execute(text("""call hafn.gen_geom_lhp_all(:uid_lhp, null)"""), {'uid_lhp': self.uid_config['uid_lhp']})
		except Exception as e:
			self.protokoluj(f"Chyba při výpočtu ploch: {e}")
			return(20)
		
		return(0)

	def generovani_vazeb(self):
		"""
		Generuje vazby mezi VS, IL, IP a podoblastmi.
		"""
		vysledek = 0
		
		# Generování IP
		if self.vypocet_config['generovani_vazeb'].get('ip', 0):
			self.protokoluj("..Generování IP")
			vysledek = self.generovani_ip()
			if vysledek == 20:
				self.protokoluj("..Generování IP ukončeno s chybou")
				return(20)
		else:
			self.protokoluj("..Generování IP nebylo prováděno")

		# Generování il_vs_spi
		if self.vypocet_config['generovani_vazeb'].get('il', 0):
			self.protokoluj("..Generování vazeb IL a VS")
			self.protokoluj("....Smazání stávajících vazeb")
			with self.pg_engine.begin() as conn:
				conn.execute(text("""delete from dsuhul.il_vs_spi where uid_firm = :uid_firm"""), {'uid_firm': self.uid_config['uid_firm']})
			self.protokoluj("...... provedeno")
			self.protokoluj("....Vygenerování nových vazeb")
			with self.pg_engine.begin() as conn:
				conn.execute(text("""
								insert into dsuhul.il_vs_spi (uid_firm, uid_vs_spi, uid_il)
								select il.uid_firm, vs_spi.uid, il.uid
								from
									dsuhul.il
									, dsuhul.vs vs
									, dsuhul.vs_spi vs_spi
								where 
									il.uid_firm = :uid_firm
									and st_within(il.ggeom, vs.ggeom)
									and  vs_spi.uid_firm = il.uid_firm and vs_spi.uid_vs = vs.uid
				"""), {'uid_firm': self.uid_config['uid_firm']})
			self.protokoluj("...... provedeno")
		else:
			self.protokoluj("..Generování vazeb IL a VS nebylo prováděno")

		# Generování vazeb podoblastí
		if self.vypocet_config['generovani_vazeb'].get('podoblasti', 0):
			self.protokoluj("..Generování vazeb podoblastí")
			vysledek = self.generovani_vazeb_podoblasti()
			if vysledek == 20:
				self.protokoluj("..Generování vazeb podoblastí ukončeno s chybou")
				return(20)
		else:
			self.protokoluj("..Generování vazeb podoblastí nebylo prováděno")
		return(vysledek)
	
	def generovani_ip(self):
		"""
		Generuje inventarizační plochy.
		"""
		vysledek = 0

		self.protokoluj("..Smazání stávajících IP")
		with self.pg_engine.begin() as conn:
			conn.execute(text("""delete from dsuhul.ip where uid_firm = :uid_firm"""), {'uid_firm': self.uid_config['uid_firm']})
		self.protokoluj(".... provedeno")
		self.protokoluj("..Smazání stávajících IL")
		with self.pg_engine.begin() as conn:
			conn.execute(text("""delete from dsuhul.il where uid_firm = :uid_firm"""), {'uid_firm': self.uid_config['uid_firm']})
		self.protokoluj(".... provedeno")

		self.protokoluj("..Generování IL z importované mapové vrstvy")
		with self.pg_engine.begin() as conn:
			conn.execute(text(f"""
					 insert into dsuhul.il (uid_firm, uid_lhc, lokalita, ggeom, geom_gnss_sjtsk)
					 select :uid_firm, :uid_lhc, input.lokalita, input.ggeom, input.ggeom
					 from 
					 	maps_layers.f_{self.lhc_config['ico'].lower()}_input_il input
					 where
					 	input.lokalita is not null
					 """), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc']})
		self.protokoluj(".... provedeno")

		if self.vypocet_config['generovani_vazeb'].get('ip_zdroj', 'gen'):
			self.protokoluj("..Generování IP z konfigurace inventarizačních lokalit")
			with self.pg_engine.begin() as conn:
				conn.execute(text("""call hafn.generuj_ip(:uid_lhp)"""), {'uid_lhp': self.uid_config['uid_lhp']})
				self.protokoluj(".... provedeno")
		else:
			self.protokoluj("..Generování IP z importované mapové vrstvy")
		return(vysledek)

	def generovani_vazeb_podoblasti(self):
		"""
		Generuje všechny vazby podoblastí (VS včetně případného sloučení, IL, IP)
		"""
		vysledek = 0
		df_tpobl = pd.read_sql(f"select kod, uid from dsuhul.pobl_typy where uid_firm = '{self.uid_config['uid_firm']}' and uid_lhc = '{self.uid_config['uid_lhc']}' and uid_lhp = '{self.uid_config['uid_lhp']}'", self.pg_conn)
		for index, row in df_tpobl.iterrows():
			self.protokoluj(f"....Typ podoblasti {row['kod']}")
			df_pobl = pd.read_sql(f"select kod, uid from dsuhul.pobl where uid_firm = '{self.uid_config['uid_firm']}' and uid_lhc = '{self.uid_config['uid_lhc']}' and uid_lhp = '{self.uid_config['uid_lhp']}' and uid_tpobl = '{row['uid']}'", self.pg_conn)
			for index, row in df_pobl.iterrows():
				self.protokoluj(f"......Podoblast {row['kod']}")
				with self.pg_engine.begin() as conn:
					conn.execute(text("""call hafn.pobl_generuj_vazby(:uid_pobl,'')"""), {'uid_pobl': row['uid']})
				if self.debug:
					self.protokoluj(f"call hafn.pobl_generuj_vazby(:uid_pobl,'') {row['uid']}")
				self.protokoluj("........ provedeno")
		return(vysledek)

	def import_csv_dat(self):
		"""
		Importuje inventarizační data data z CSV souborů do databáze.
		"""
		# Import schémat
		from mnd_spi_app.islh_schema import get_schema

		vysledek = 0

		importovane_soubory = []
		importovane_soubory = list(self.vypocet_config['import_csv']['data'].keys())
		if not importovane_soubory:
			self.protokoluj("Nejsou definovány žádné soubory k importu")
			return(vysledek)
		for soubor in importovane_soubory:
			if self.vypocet_config['import_csv']['data'][soubor]:
				self.protokoluj(f"..Soubor {soubor}")
				import_file = os.path.join(self.get_data_dir(), 'vstup', 'csv', self.lhc_config['datove_soubory'][soubor].get('soubor', soubor + '.csv'))
				if not os.path.exists(import_file):
					self.protokoluj(f"Soubor {import_file} neexistuje")
					return(20)
				
				# samotné načtení vrstvy a uložení do databáze
				self.protokoluj(f"....Soubor: {import_file}")

				# Načtení pandera schematu
				schema = get_schema(soubor, 'minimal')

				# zjištění datových typů sloupců, pro správné vytvoření pandas dataframe
				dtype_dict = {}
				if schema:
					for column_name, column in schema.columns.items():
						# Kontrola, zda sloupec používá isin validaci nebo je definován jako string
						if isinstance(column.dtype, pa.String):
							dtype_dict[column_name] = str

				# načtení csv souboru
				df = pd.read_csv(import_file, decimal=',', sep=';', dtype=dtype_dict)

				# Převod názvů sloupců na malá písmena
				df.columns = [col.lower() for col in df.columns]
				self.protokoluj(f"......Načteno {len(df)} záznamů")

				# Validace a doplnění výchozích hodnot
				if schema:
					# Doplnění výchozích hodnot pro NULL hodnoty
					for column_name, column_schema in schema.columns.items():
						if column_name in df.columns and column_schema.default is not None:
							df[column_name] = df[column_name].fillna(column_schema.default)
							if self.debug:
								self.protokoluj(f"......Doplnění výchozí hodnoty {column_schema.default} pro sloupec {column_name}")

					# Převod datových typů na základě schématu
					for column_name, column_schema in schema.columns.items():
						if column_name in df.columns:
							# Převod datového typu podle schématu
							try:
								if self.debug:
									self.protokoluj(f"......Převod datového typu {column_name}: {column_schema.dtype}")
								# Kontrola skutečného typu dat před převodem
								actual_type = df[column_name].dtype
								if self.debug:
									self.protokoluj(f"......Aktuální typ dat: {actual_type}")
								
								if isinstance(column_schema.dtype, pa.dtypes.String):
									df[column_name] = df[column_name].astype(str)
								elif isinstance(column_schema.dtype, pa.dtypes.Int):
									df[column_name] = pd.to_numeric(df[column_name], errors='coerce').fillna(0).astype(int)
								elif isinstance(column_schema.dtype, pa.dtypes.Float):
									df[column_name] = pd.to_numeric(df[column_name], errors='coerce').fillna(0.0)
								elif isinstance(column_schema.dtype, pa.dtypes.Bool):
									df[column_name] = df[column_name].astype(bool)
								else:
									self.protokoluj(f"......Varování: Nelze převést sloupec {column_name}: {column_schema.dtype}")
							except Exception as e:
								self.protokoluj(f"......Chyba: Nelze převést sloupec {column_name}: {str(e)}")
					try:
						# Validace podle schématu
						self.protokoluj(f"......Validace dat")
						schema.validate(df, lazy=True)
						self.protokoluj(f"......Validováno {len(df)} záznamů")
					except pa.errors.SchemaErrors as e:
						# Log chyb
						self.protokoluj(f"......Kontrolováno {len(df)} záznamů")
						self.protokoluj(f"......Chyby ve validaci: {len(e.failure_cases)} problémů")
						self.protokoluj("\n" + str(e.failure_cases))
						vysledek = 10
				else:
					self.protokoluj(f"......Pro soubor {soubor} není definováno schéma - pouze základní zpracování")

				df.to_sql(name = 'f_' + self.lhc_config['ico'].lower() + '_input_' + soubor, con = self.pg_engine, schema='vstup', if_exists='replace', index=False)
				self.protokoluj(f"......Uloženo do PostgreSQL {len(df)} záznamů ({'f_' + self.lhc_config['ico'].lower() + '_input_' + soubor})")
			else:
				self.protokoluj(f"..Soubor {soubor} ignorován")
		return(vysledek)

	def import_dat(self):
		"""
		Kontrola importovaných dat a jejich přesun z dočasných tabulek do výsledných struktur.
		"""
		vysledek = 0

		# nejprve vymazání případných předchozích dat
		if self.vypocet_config['import_dat']['vz'].get('provadet', 0) or self.vypocet_config['import_dat']['pno'].get('provadet', 0):
			self.protokoluj("..Vymazání stávajících dat")

		if self.vypocet_config['import_dat']['vz'].get('provadet', 0):
			self.protokoluj("....Vymazání VZ")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text("""
							delete from dsuhul.vz vz
							using dsuhul.ip ip
							where 
								ip.uid_firm = :uid_firm and ip.uid_lhc = :uid_lhc and ip.uid_lhp = :uid_lhp
								and vz.uid_ip = ip.uid
								"""
							),
							{'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc'], 'uid_lhp': self.uid_config['uid_lhp']}
							)
				self.protokoluj("......provedeno")
			except Exception as e:
				self.protokoluj(f"....Chyba při vymazání VZ: {e}\n {traceback.format_exc()}")
				return(20)

		if self.vypocet_config['import_dat']['pno'].get('provadet', 0):
			self.protokoluj("....Vymazání PNO")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text("""
							delete from dsuhul.pno pno
							using dsuhul.ip ip
							where 
								ip.uid_firm = :uid_firm and ip.uid_lhc = :uid_lhc and ip.uid_lhp = :uid_lhp
								and pno.uid_ip = ip.uid
								"""
							),
							{'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc'], 'uid_lhp': self.uid_config['uid_lhp']}
							)
					self.protokoluj("......provedeno")
			except Exception as e:
				self.protokoluj(f"....Chyba při vymazání PNO: {e}\n {traceback.format_exc()}")
				return(20)
		
		# Zpracování IP
		if self.vypocet_config['import_dat']['ip'].get('provadet', 0):
			self.protokoluj("..Import IP")
			self.protokoluj("....Kontrola dat")
			prikaz = f"""
				SELECT input.*
				FROM vstup.f_{self.lhc_config['ico'].lower()}_input_ip input
				WHERE
					not exists(
						select 1
						from 
							dsuhul.ip ip
							, dsuhul.il il
						where 
							ip.uid_firm = '{self.uid_config['uid_firm']}' and ip.uid_lhc = '{self.uid_config['uid_lhc']}' and ip.uid_lhp = '{self.uid_config['uid_lhp']}'
							and il.uid = ip.uid_il
							and il.lokalita = input.lokalita and ip.plocha = input.plocha
					)
			"""
			df = pd.read_sql(prikaz, self.pg_conn)
			if len(df) > 0:
				self.protokoluj(f"......Chyba: Nalezeno {len(df)} záznamů odkazujících na neexistující IP")
				self.protokoluj(f"\n{df}")
				return(20)
			self.protokoluj("......dokončena")

			self.protokoluj("....Import dat (update)")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text(f"""
						update dsuhul.ip ip
						set
							datum_m = input.datum_m::date
							, datum_m_pred = input.datum_m_pred::date
							, mdcel = input.mdcel
							, azimut_stab = input.azimut_stab
							, vzd_stab = input.vzd_stab
					   		, nadm_vyska = input.nadm_vyska
							, cil_zasoba = input.cil_zasoba
							, cbp = input.cbp
							, vyr_doba = input.vyr_doba
							, meric = input.meric
							, pozn_plocha = input.pozn_plocha
							, status = input.status
							, prist = input.prist
							, stab = input.stab
							, identifikace = input.identifikace
							, duv_neob = input.duv_neob
							, kat_poz = input.kat_poz
							, poz_les = input.poz_les
							, prist_pred = input.prist_pred
							, kat_poz_pred = input.kat_poz_pred
							, poz_les_pred = input.poz_les_pred
							{', lt = input.lt' if self.vypocet_config['import_dat']['ip']['lt_zdroj'] == 'import' else ''}
						from
							dsuhul.il il
							, vstup.f_{self.lhc_config['ico'].lower()}_input_ip input
						where
							il.uid_firm = :uid_firm and il.uid_lhc = :uid_lhc
							and il.uid = ip.uid_il
							and il.lokalita = input.lokalita and ip.plocha = input.plocha
					"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc']})
			except Exception as e:
				self.protokoluj(f"....Chyba při importu IP: {e}\n {traceback.format_exc()}")
				return(20)
			
			# Natčení LT IP z typologické mapy
			if self.vypocet_config['import_dat']['ip'].get('lt_zdroj') == 'mapa':
				self.protokoluj("......Přiřazení LT dle typologické mapy LT")
				self.protokoluj("........Kontrola dat")
				prikaz = f"""
							SELECT
								il.lokalita, ip.status, ip.prist, ip.kat_poz, ip.poz_les, ip.uid
							FROM
								dsuhul.ip ip
								, dsuhul.il il
							WHERE
								ip.uid_firm ='{self.uid_config['uid_firm']}'
								and il.uid = ip.uid_il
								and coalesce(ip.prist, '') = '100' and coalesce(ip.kat_poz, '') = '100' and coalesce(ip.poz_les, '') = '100' and coalesce(ip.lt, '') = ''
								and not exists(select 1 from  maps_layers.f_{self.lhc_config['ico'].lower()}_input_typologie typ where st_within(ip.geom_gnss_sjtsk , typ.ggeom))
				"""
				df = pd.read_sql(prikaz, self.pg_conn)
				if len(df) > 0:
					self.protokoluj(f"......Chyba: Nalezeno {len(df)} záznamů bez vazby na typologickou mapu")
					self.protokoluj(f"\n{df}")
					return(20)
				self.protokoluj("..........dokončena")

				self.protokoluj("........Dohledání LT z typologické mapy")
				try:
					with self.pg_engine.begin() as conn:
						conn.execute(text(f"""
							update dsuhul.ip ip
							set
								lt = typ.lt
							from
								dsuhul.il il
								, maps_layers.f_{self.lhc_config['ico'].lower()}_input_typologie typ
							where
								ip.uid_firm = :uid_firm and ip.uid_lhc = :uid_lhc
								and st_within(ip.geom_gnss_sjtsk , typ.ggeom)
						"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc']})
				except Exception as e:
					self.protokoluj(f"....Chyba při dohledání LT IP: {e}\n {traceback.format_exc()}")
					return(20)
				self.protokoluj("..........dokončeno")

			# Natčení JPRL z DETu
			self.protokoluj("......Přiřazení JPRL dle DETu")
			self.protokoluj("........Kontrola dat")
			prikaz = f"""
						SELECT
							il.lokalita, ip.uid
						FROM
							dsuhul.ip ip
							, dsuhul.il il
						WHERE
							ip.uid_firm ='{self.uid_config['uid_firm']}'
							and il.uid = ip.uid_il
							and not exists(select 1 from  maps_layers.f_{self.lhc_config['ico'].lower()}_input_det det where st_within(ip.geom_gnss_sjtsk , det.ggeom))
			"""
			df = pd.read_sql(prikaz, self.pg_conn)
			if len(df) > 0:
				self.protokoluj(f"......Varování: Nalezeno {len(df)} záznamů bez vazby na DET")
				self.protokoluj(f"\n{df}")
				vysledek = 10
			self.protokoluj("..........dokončena")

			self.protokoluj("........Dohledání JPRL z DETu")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text(f"""
						update dsuhul.ip ip
						set
							odd = coalesce(det.oddeleni, 0)
							, dil = coalesce(det.dilec, '')
							, por = coalesce(det.porost, '')
							, hos = coalesce(det.hos, 0)::character varying
						from
							dsuhul.il il
					   		, dsuhul.ip ipd
								 left outer join maps_layers.f_{self.lhc_config['ico'].lower()}_input_det det on (st_within(ipd.geom_gnss_sjtsk , det.ggeom))
						where
							ip.uid_firm = :uid_firm and ip.uid_lhc = :uid_lhc
							and il.uid = ip.uid_il
							and ipd.uid = ip.uid
					"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc']})
			except Exception as e:
				self.protokoluj(f"....Chyba při dohledání JPRL IP: {e}\n {traceback.format_exc()}")
				return(20)
			self.protokoluj("..........dokončeno")

			self.protokoluj("....Import IP dokončen")

			self.protokoluj("........Dohledání maximálních CBP a minimálních cílových zásob")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text(f"""
						update dsuhul.ip ip
						set
							ek = substring(ip.lt from '[0-9]+([A-Z])')
					   		, cbp_max = cbp.cbp
							, cil_zasoba_min = mcz.mcz
						from
							dsuhul.l_er_cz01 er
							, dsuhul.l_ip_cbp_cz01 cbp
							, dsuhul.l_ip_mcz_cz01 mcz
						where
							ip.uid_firm = :uid_firm
							and er.ek = substring(ip.lt from '[0-9]+([A-Z])')
							and cbp.er = er.er and cbp.vyska_min <= ip.nadm_vyska and cbp.vyska_max >= ip.nadm_vyska and coalesce(ip.nadm_vyska, 0) > 0
							and mcz.er = er.er and mcz.vyska_min <= ip.nadm_vyska and mcz.vyska_max >= ip.nadm_vyska and coalesce(ip.nadm_vyska, 0) > 0
						"""), {'uid_firm': self.uid_config['uid_firm']})
			except Exception as e:
				self.protokoluj(f"....Chyba při dohledání cbp/cil.zás.): {e}\n {traceback.format_exc()}")
				return(20)
			self.protokoluj("..........dokončeno")

			self.protokoluj("....Import IP dokončen")

		# Zpracování VZ
		if self.vypocet_config['import_dat']['vz'].get('provadet', 0):
			self.protokoluj("..Import VZ")
			self.protokoluj("....Kontrola dat")
			prikaz = f"""
				SELECT input.*
				FROM vstup.f_{self.lhc_config['ico'].lower()}_input_vz input
				WHERE
					not exists(
						select 1
						from 
							dsuhul.ip ip
							, dsuhul.il il
						where 
							ip.uid_firm = '{self.uid_config['uid_firm']}' and ip.uid_lhc = '{self.uid_config['uid_lhc']}' and ip.uid_lhp = '{self.uid_config['uid_lhp']}'
							and il.uid = ip.uid_il
							and il.lokalita = input.lokalita and ip.plocha = input.plocha
					)
			"""
			df = pd.read_sql(prikaz, self.pg_conn)
			if len(df) > 0:
				self.protokoluj(f"......Chyba: Nalezeno {len(df)} záznamů odkazujících na neexistující IP")
				self.protokoluj(f"\n{df}")
				return(20)
			self.protokoluj("......dokončena")

			self.protokoluj("....Import dat (insert)")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text(f"""
						insert into dsuhul.vz(
					   		uid_ip
					   		, kmen, kmen_pred
					   		, x_m, y_m, vzd_km, azimut_km, tloustka_km, tloustka_km_pred, mod_vys, mod_vys_pred, vzornik2, vzornik2_pred
					   		, vyska, vyska_pred, pno, pno_pred, d13_depl, mod_vys_depl, pozn_km
					   		, opak_ident_km, parez, pol_parez, sous, dr_zkr, dvojak, zlom_vyvrat, vyklizeni_km, parez_pred, sous_pred, zlom_vyvrat_pred
					   	)
						select
					   		ip.uid
					   		, input.kmen
					   		, input.kmen_pred
					   		, input.x_m
					   		, input.y_m
					   		, input.vzd_km
					   		, input.azimut_km
					   		, input.tloustka_km
					   		, input.tloustka_km_pred
					   		, input.mod_vys
					   		, input.mod_vys_pred
					   		, upper(input.vzornik2) = 'A'
					   		, upper(input.vzornik2_pred) = 'A'
					   		, input.mvyska
					   		, input.mvyska_pred
					   		, input.pno
					   		, input.pno_pred
					   		, input.d13_depl
					   		, input.mod_vys_depl
					   		, input.pozn_km
					   		, input.opak_ident_km
					   		, input.parez
					   		, input.pol_parez
					   		, input.sous
					   		, input.dr_zkr
					   		, input.dvojak
					   		, input.zlom_vyvrat
					   		, input.vyklizeni_km
					   		, input.parez_pred
					   		, input.sous_pred
					   		, input.zlom_vyvrat_pred
					   		from
					   			vstup.f_{self.lhc_config['ico'].lower()}_input_vz input
								, dsuhul.il il
								, dsuhul.ip ip
							where
								il.uid_firm = :uid_firm and il.uid_lhc = :uid_lhc and il.lokalita = input.lokalita
								and ip.uid_il = il.uid
					"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc']})
			except Exception as e:
				self.protokoluj(f"....Chyba při importu VZ: {e}\n {traceback.format_exc()}")
				return(20)

			self.protokoluj("....Výpočet ZZ")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text(f"""
						update dsuhul.vz
					    set xcmd = '#PROPOCET_ZZ;'
					   		from
								dsuhul.ip ip
							where
								ip.uid_firm = :uid_firm and ip.uid_lhc = :uid_lhc and ip.uid_lhp = :uid_lhp
								and vz.uid_ip = ip.uid
					"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc'], 'uid_lhp': self.uid_config['uid_lhp']})
			except Exception as e:
				self.protokoluj(f"....Chyba při výpočtu ZZ: {e}\n {traceback.format_exc()}")
				return(20)

			self.protokoluj("....Import VZ dokončen")


		# Zpracování PNO
		if self.vypocet_config['import_dat']['pno'].get('provadet', 0):
			self.protokoluj("..Import PNO")
			self.protokoluj("....Kontrola dat")
			prikaz = f"""
				SELECT input.*
				FROM vstup.f_{self.lhc_config['ico'].lower()}_input_pno input
				WHERE
					not exists(
						select 1
						from 
							dsuhul.ip ip
							, dsuhul.il il
						where 
							ip.uid_firm = '{self.uid_config['uid_firm']}' and ip.uid_lhc = '{self.uid_config['uid_lhc']}' and ip.uid_lhp = '{self.uid_config['uid_lhp']}'
							and il.uid = ip.uid_il
							and il.lokalita = input.lokalita and ip.plocha = input.plocha
					)
			"""
			df = pd.read_sql(prikaz, self.pg_conn)
			if len(df) > 0:
				self.protokoluj(f"......Chyba: Nalezeno {len(df)} záznamů odkazujících na neexistující IP")
				self.protokoluj(f"\n{df}")
				return(20)
			self.protokoluj("......dokončena")

			self.protokoluj("....Import dat (insert)")
			try:
				with self.pg_engine.begin() as conn:
					conn.execute(text(f"""
						insert into dsuhul.pno(
					   		uid_ip
					   		, pomno, popis
					   		, x_m, y_m
					   	)
						select
					   		ip.uid
					   		, input.pomno
					   		, input.popis
					   		, input.x_m
					   		, input.y_m
					   		from
					   			vstup.f_{self.lhc_config['ico'].lower()}_input_pno input
								, dsuhul.il il
								, dsuhul.ip ip
							where
								il.uid_firm = :uid_firm and il.uid_lhc = :uid_lhc and il.lokalita = input.lokalita
								and ip.uid_il = il.uid
					"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc']})
			except Exception as e:
				self.protokoluj(f"....Chyba při importu VZ: {e}\n {traceback.format_exc()}")
				return(20)

			self.protokoluj("....Import PNO dokončen")

		return(vysledek)

	def vyskovy_model(self):
		"""
		Výpočet výškového modelu.
		"""
		vysledek = 0
		vysky_vypocteny = 0

		if self.vypocet_config['vyskovy_model'].get('zdroj_vysek', '') == 'import_vz':
			self.protokoluj("....Výškový model byl součástí importu vzorníků a nebude generován.")
			vysky_vypocteny = 1
		
		if self.vypocet_config['vyskovy_model'].get('zdroj_vysek', '') == 'import_modelu':
			self.protokoluj("....Modelové výšky byly importovány z CSV dat")
			# vymazání dat výškového modelu
			with self.pg_engine.begin() as conn:
				conn.execute(text(f"""
					delete from dsuhul.mod_vys where uid_lhp = :uid_lhp
				"""), {'uid_lhp': self.uid_config['uid_lhp']})
				conn.execute(text(f"""
					delete from dsuhul.mod_vys_pred where uid_lhp = :uid_lhp
				"""), {'uid_lhp': self.uid_config['uid_lhp']})
			self.protokoluj("....Předchozí výškový model byl vymazán")

			with self.pg_engine.begin() as conn:
				self.protokoluj("......Uložení modelových výšek aktuální inventarizace do databáze")
				conn.execute(text(f"""
					insert into dsuhul.mod_vys(
						uid_lhp, lokalita, plocha, kmen, mod_vys
					)
					select :uid_lhp, mod.lokalita, mod.plocha, mod.kmen, mod.mod_vys from vstup.f_{self.lhc_config['ico'].lower()}_input_mod_vys mod
				"""), {'uid_lhp': self.uid_config['uid_lhp']})
				self.protokoluj("......dokončeno")
				self.protokoluj("......Uložení modelových výšek předchozí inventarizace do databáze")
				conn.execute(text(f"""
					insert into dsuhul.mod_vys_pred(
						uid_lhp, lokalita, plocha, kmen_pred, mod_vys_pred
					)
					select :uid_lhp, mod.lokalita, mod.plocha, mod.kmen_pred, mod.mod_vys_pred from vstup.f_{self.lhc_config['ico'].lower()}_input_mod_vys_pred mod
				"""), {'uid_lhp': self.uid_config['uid_lhp']})
				self.protokoluj("......dokončeno")
			vysky_vypocteny = 1
		
		if self.vypocet_config['vyskovy_model'].get('zdroj_vysek', '') == 'vypocet':
			self.protokoluj("....Výpočet výškových funkcí a modelových výšek")

			import mnd_spi_app.spi_model_vysek as smv
			model = smv.ModelVysek(protokoluj_fce=self.protokoluj, debug=self.debug)
			# pro všechny skupiny dřevin zjistím modely výšek v aktuální a předchozí inventarizaci
			inventarizace = [
				{
					'nazev': 'aktuální',
					'suffix': '',
				}
			]
			if self.lhc_config['opakovana_inventarizace']:
				inventarizace.append({
					'nazev': 'předchozí',
					'suffix': '_pred',
				})
			for inv in inventarizace:
				prikaz = f"""select distinct dr.rt from dsuhul.l_dr_zkr_cz01 dr where coalesce(dr.rt, '') <> ''"""
				df_dr = pd.read_sql(prikaz, self.pg_conn)
				for rt in df_dr['rt']:
					self.protokoluj(f"....Výpočet výškové funkce pro skupinu {rt} - {inv['nazev']} inventarizace")
					prikaz = f"""
						select ip.uid_lhp as uid_lhp,il.lokalita as lokalita, ip.plocha as plocha, vz.kmen as kmen{inv['suffix']}, vz.tloustka_km as tloustka_km{inv['suffix']}, vz.vyska as mvyska{inv['suffix']}
						from 
							dsuhul.ip ip
							, dsuhul.vz vz
							, dsuhul.l_dr_zkr_cz01 dr
							, dsuhul.il il
						where
							ip.uid_firm = '{self.uid_config['uid_firm']}'
							and vz.uid_ip = ip.uid
							and dr.code = vz.dr_zkr
							and il.uid = ip.uid_il
							and vz.tloustka_km{inv['suffix']} > 0 and vz.kmen{inv['suffix']} > 0
							and dr.rt = '{rt}'
					"""
					df_vys = pd.read_sql(prikaz, self.pg_conn)
					if len(df_vys) > 0:
						model_df, model_info = model.zpracuj_data(
							df_vys
							, nazev = f"skupina dřevin {rt}, {inv['nazev']} inventarizace"
							, sloupec_strom = f"kmen{inv['suffix']}"
							, sloupec_dbh = f"tloustka_km{inv['suffix']}"
							, sloupec_vyska = f"mvyska{inv['suffix']}"
							, sloupec_mod_vys = f"mod_vys{inv['suffix']}"
							, zobrazit_grafy=self.vypocet_config['vyskovy_model'].get('nahledy_modelu', 0)
							, nazev_funkce=self.vypocet_config['vyskovy_model'].get('vyskova_funkce', '')
						)
						if model_info is None:
							self.protokoluj("......Chyba: Nebyla nalezena žádná vhodná výšková funkce")
							return(20)
						self.protokoluj("......Parametry výpočtu:")
						self.protokoluj(f"........Výšková funkce: {model_info['nazev_funkce']} ({model_info['funkce']})")
						self.protokoluj(f"........R2: {model_info['R2']}")
						self.protokoluj(f"........RMSE: {model_info['RMSE']}")
						self.protokoluj(f"........parametry: {model_info['parametry']}")
						# uložím model do databaze
						model_df.to_sql(name = f"mod_vys{inv['suffix']}", con = self.pg_engine, schema = 'dsuhul', if_exists='append', index=False)
						self.protokoluj("......uloženo do databáze")
						self.protokoluj(f"......Výškový model pro skupinu {rt} - {inv['nazev']} inventarizace dokončen")
			vysky_vypocteny = 1

		if vysky_vypocteny == 0:
			self.protokoluj("....Chyba: Chybný zdroj výšek.")
			return(20)

		# pokud se mají výšky použít, update do VZ a kontrola, jestli všechny mají
		if self.vypocet_config['vyskovy_model'].get('pouzit_vysky', 0) and self.vypocet_config['vyskovy_model'].get('zdroj_vysek', '') != 'import_vz': # pokud byly modelové výšky již v datech VZ, znovu se nepřepisují
			self.protokoluj("....Aktualizace modelových výšek vzorníků")

			with self.pg_engine.begin() as conn:
				conn.execute(text(f"""
						update dsuhul.vz vz
						set
							mod_vys = coalesce(
											(select m.mod_vys from dsuhul.mod_vys m where m.uid_lhp = ip.uid_lhp and m.lokalita = il.lokalita and m.plocha = ip.plocha and m.kmen = vz.kmen)
											, 0
										)
						from
							dsuhul.ip ip
							, dsuhul.il il
						where
					  		ip.uid_firm = :uid_firm and ip.uid_lhc = :uid_lhc and ip.uid_lhp = :uid_lhp
							and vz.uid_ip = ip.uid
							and il.uid = ip.uid_il
					"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc'], 'uid_lhp': self.uid_config['uid_lhp']})
				self.protokoluj("......modelové výšky aktuální inventarizace uloženy")
				conn.execute(text(f"""
						update dsuhul.vz vz
						set
							mod_vys_pred = coalesce(
											(select m.mod_vys_pred from dsuhul.mod_vys_pred m where m.uid_lhp = ip.uid_lhp and m.lokalita = il.lokalita and m.plocha = ip.plocha and m.kmen_pred = vz.kmen_pred)
											, 0
										)
						from
							dsuhul.ip ip
							, dsuhul.il il
						where
					  		ip.uid_firm = :uid_firm and ip.uid_lhc = :uid_lhc and ip.uid_lhp = :uid_lhp
							and vz.uid_ip = ip.uid
							and il.uid = ip.uid_il
					"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhc': self.uid_config['uid_lhc'], 'uid_lhp': self.uid_config['uid_lhp']})
				self.protokoluj("......modelové výšky předchozí inventarizace uloženy")

		# Kontrola naplnění modelových výšek
		self.protokoluj("....Kontrola naplnění modelových výšek")
		prikaz = f"""
					SELECT
						il.lokalita, ip.plocha, vz.kmen
					FROM
						dsuhul.ip ip
						, dsuhul.il il
						, dsuhul.vz vz
					WHERE
						ip.uid_firm = '{self.uid_config['uid_firm']}' and ip.uid_lhc = '{self.uid_config['uid_lhc']}' and ip.uid_lhp = '{self.uid_config['uid_lhp']}'
						and il.uid = ip.uid_il
						and vz.uid_ip = ip.uid
						and coalesce(vz.parez, '') = '100' and coalesce(vz.mod_vys, 0) = 0
				"""
		df_kontrola = pd.read_sql(prikaz, self.pg_conn)
		if len(df_kontrola) > 0:
			self.protokoluj(f"......Počet vzorníků s chybějící modelovou výškou v aktuální inventarizaci: {len(df_kontrola)}")
			self.protokoluj(f"\n{df_kontrola.to_string()}")
			vysledek = 10
		prikaz = f"""
					SELECT
						il.lokalita, ip.plocha,vz.kmen_pred
					FROM
						dsuhul.ip ip
						, dsuhul.il il
						, dsuhul.vz vz
					WHERE
						ip.uid_firm = '{self.uid_config['uid_firm']}' and ip.uid_lhc = '{self.uid_config['uid_lhc']}' and ip.uid_lhp = '{self.uid_config['uid_lhp']}'
						and il.uid = ip.uid_il
						and vz.uid_ip = ip.uid
						and coalesce(vz.parez_pred, '') = '100' and coalesce(vz.kmen_pred, 0) > 0 and coalesce(vz.mod_vys_pred, 0) = 0
				"""
		df_kontrola = pd.read_sql(prikaz, self.pg_conn)
		if len(df_kontrola) > 0:
			self.protokoluj(f"......Počet vzorníků s chybějící modelovou výškou v předchozí inventarizaci: {len(df_kontrola)}")
			self.protokoluj(f"\n{df_kontrola.to_string()}")
			vysledek = 10

		return(vysledek)

	def vypocet_lhp(self):
		"""
		Samotný výpočet všech hodnot a ukazatelů LHP.
		"""
		vysledek = 0
		
		if self.vypocet_config['vypocet_lhp'].get('provadet', 0) == 0:
			self.protokoluj("Výpočet LHP nebyl prováděn")
			return(vysledek)

		self.protokoluj("..Výpočet LHP")

		# sestavední parametru pro výpočet
		parametr = ''
		parametr += '#PREPOCET_UMISTENI;' if self.vypocet_config['vypocet_lhp']['parametry'].get('propocet_poloh_kmenu', 0) else ''
		parametr += '#PROPOCET_ZZ;' if self.vypocet_config['vypocet_lhp']['parametry'].get('propocet_zz', 0) else ''
		parametr += '#VYPOCET_MINULE;' if self.vypocet_config['vypocet_lhp']['parametry'].get('pocitat_i_minulou_inventarizaci', 0) else ''
		parametr += '#NEPOCITAT_PLOCHY;' if self.vypocet_config['vypocet_lhp']['parametry'].get('nepocitat_plochy_pspp', 0) else ''
		parametr += '#PROPOCET_HODNOT;' if self.vypocet_config['vypocet_lhp']['parametry'].get('vypocet_hodnot_kmenu', 0) else ''
		parametr += '#FT_MODEL;' if self.vypocet_config['vypocet_lhp']['parametry'].get('pouzit_modelovy_ft', 0) else ''

		# pokud se má použít modelový FT, uložím ho
		if self.vypocet_config['vypocet_lhp']['parametry'].get('pouzit_modelovy_ft', 0):
			if self.vypocet_config['vypocet_lhp']['parametry'].get('modelovy_ft', 0) == 0:
				self.protokoluj("....Chyba: Modelový FT není nastaven")
				return(20)
			else:
				with self.pg_engine.begin() as conn:
					conn.execute(text(f"""
						update happ.lhp set ft_model = :ft_model where uid = :uid_lhp
					"""), {'ft_model': self.vypocet_config['vypocet_lhp']['parametry']['modelovy_ft'], 'uid_lhp': self.uid_config['uid_lhp']})
				self.protokoluj(f"....Uložen modelový FT {self.vypocet_config['vypocet_lhp']['parametry']['modelovy_ft']}")

		if self.debug:
			self.protokoluj(f"....parametr výpočtu: {parametr}")
		try:
			with self.pg_engine.begin() as conn:
				conn.execute(text("SET client_min_messages TO notice"))
				conn.execute(text(f"""
					call hafn.vypocet_lhp_cz01(:uid_firm, :uid_lhp, :parametr)
				"""), {'uid_firm': self.uid_config['uid_firm'], 'uid_lhp': self.uid_config['uid_lhp'], 'parametr': parametr})
		except Exception as e:
			self.protokoluj(f"..Chyba při výpočtu hodnot LHP: {e} \n {traceback.format_exc()}")
			return(20)
		self.protokoluj("....dokončen")

		# přehled výsledku
		sql_query = f"""
		SELECT lhp.lhp_od,
			COALESCE(lhpcz.t_z_akt, 0::numeric) AS t_z_akt,
			COALESCE(lhpcz.y_z_akt, 0::numeric) AS y_z_akt,
			COALESCE(lhpcz.t_z_pred, 0::numeric) AS t_z_pred,
			COALESCE(lhpcz.y_z_pred, 0::numeric) AS y_z_pred,
			COALESCE(lhpcz.t_tez, 0::numeric) AS t_tez,
			COALESCE(lhpcz.y_tez, 0::numeric) AS y_tez,
			COALESCE(lhp.ft, 0::numeric) AS ft,
			COALESCE(lhpcz.t_cbp, 0::numeric) AS t_cbp,
			COALESCE(lhpcz.y_cbp, 0::numeric) AS y_cbp,
			COALESCE(lhpcz.t_cvt, 0::numeric) AS t_cvt,
			COALESCE(lhpcz.y_cvt, 0::numeric) AS y_cvt,
			COALESCE(lhpcz.t_n, 0::numeric) AS t_n,
			COALESCE(lhpcz.se_y_z_akt, 0::numeric) AS se_zas_25,
			COALESCE(lhpcz.se_y_cvt/lhp.pocet_let, 0::numeric) AS se_cvt_1,
			COALESCE(lhp.pocet_let, 0::numeric) AS pocet_let,
			lhpcz.ts_vypocet::character varying(19) AS cas_vypoctu
		FROM happ.lhp lhp,
			happ.lhp_cz01 lhpcz
			WHERE lhp.uid = '{self.uid_config['uid_lhp']}'::uuid AND lhpcz.uid = lhp.uid AND lhpcz.dr_zkr::text = ''::text;
		"""
		df_vysl = pd.read_sql(sql_query, self.pg_engine)
		self.protokoluj(f"Výsledek výpočtu:")
		self.protokoluj(f"Aktuální zásoba - {spi_utils.ceske_cislo(df_vysl['t_z_akt'].values[0])} m3, {spi_utils.ceske_cislo(df_vysl['y_z_akt'].values[0])} m3/ha")
		if self.lhc_config['opakovana_inventarizace']:
			self.protokoluj(f"Předchozí zásoba - {spi_utils.ceske_cislo(df_vysl['t_z_pred'].values[0])} m3, {spi_utils.ceske_cislo(df_vysl['y_z_pred'].values[0])} m3/ha")
			self.protokoluj(f"Těžba - {spi_utils.ceske_cislo(df_vysl['t_tez'].values[0])} m3, {spi_utils.ceske_cislo(df_vysl['y_tez'].values[0])} m3/ha")
		self.protokoluj(f"CBP - {spi_utils.ceske_cislo(df_vysl['t_cbp'].values[0])} m3, {spi_utils.ceske_cislo(df_vysl['y_cbp'].values[0])} m3/ha")
		self.protokoluj(f"Zjištěný FT - {spi_utils.ceske_cislo(df_vysl['ft'].values[0], 3)}")
		self.protokoluj(
			f"CVT - {spi_utils.ceske_cislo(df_vysl['t_cvt'].values[0])} m3"
			f", {spi_utils.ceske_cislo(round(df_vysl['t_cvt'].values[0]/df_vysl['pocet_let'].values[0], 1))} m3/rok"
			f", {spi_utils.ceske_cislo(round(df_vysl['y_cvt'].values[0]/df_vysl['pocet_let'].values[0], 1))} m3/ha/rok"
		)
		# kontroly standardních chyb
		self.protokoluj(f"SE akt. zásoby {spi_utils.ceske_cislo(df_vysl['se_zas_25'].values[0], 3)} m3 {('splňuje' if df_vysl['se_zas_25'].values[0] < 25 or df_vysl['se_zas_25'].values[0] < 0.1 * df_vysl['y_z_akt'].values[0] else 'nesplňuje')} podmínky §7c odst. 1.")
		self.protokoluj(f"SE CVT {spi_utils.ceske_cislo(df_vysl['se_cvt_1'].values[0], 3)} m3 {('splňuje' if df_vysl['se_cvt_1'].values[0] < 1 or df_vysl['se_cvt_1'].values[0] < 0.1 * (df_vysl['y_cvt'].values[0]/df_vysl['pocet_let'].values[0]) else 'nesplňuje')} podmínky §7c odst. 2.")
		# kontroly minimálního počtu IL
		prikaz = f"""
			SELECT
				count(*)
			FROM
				dsuhul.vs_spi vs
				, dsuhul.il_vs_spi il

			WHERE vs.uid_firm = '{self.uid_config['uid_firm']}' and vs.uid_lhc = '{self.uid_config['uid_lhc']}' and vs.uid_lhp = '{self.uid_config['uid_lhp']}'
				and il.uid_vs_spi = vs.uid
		"""
		df_il = pd.read_sql(prikaz, self.pg_conn)
		self.protokoluj(f"Celkový počet IL {spi_utils.ceske_cislo(df_il['count'].values[0], 0)} {('splňuje' if df_il['count'].values[0] > 50 else 'nesplňuje')} podmínky §7b odst. 2.")
		del df_il

		prikaz = f"""
			select
			round(
			(select 
				count(*)
			from
				dsuhul.ip ip
				, dsuhul.vz vz
			where
				ip.uid_firm = '{self.uid_config['uid_firm']}' and ip.uid_lhc = '{self.uid_config['uid_lhc']}' and ip.uid_lhp = '{self.uid_config['uid_lhp']}'
				and vz.uid_ip = ip.uid
				and vz.zapocitat
				and vz.vzornik2 and coalesce(vz.vyska, 0) > 0
				and coalesce(vz.zlom_vyvrat, '') not in ('200', '300', '400', '500', '700') and coalesce(vz.sous, '') in ('', '100') and coalesce(vz.parez, '') = '100'
			)::decimal(10,2)/
			(select 
				count(*)
			from
				dsuhul.ip ip
			where
				ip.uid_firm = '{self.uid_config['uid_firm']}' and ip.uid_lhc = '{self.uid_config['uid_lhc']}' and ip.uid_lhp = '{self.uid_config['uid_lhp']}'
				and ip.poz_les = '100' and ip.kat_poz = '100')
			, 1) as pomer
		"""
		df_vz2 = pd.read_sql(prikaz, self.pg_conn)
		self.protokoluj(f"Průměrný počet vzorníků 2. stupně na jednu IP {spi_utils.ceske_cislo(df_vz2['pomer'].values[0], 1)} {('splňuje' if df_vz2['pomer'].values[0] > 2 else 'nesplňuje')} podmínky hlavy III. odst. 9 přílohy č. 6")
		del df_vz2
		return(vysledek)

	def export_dat(self):
		"""
		Export dat s výsledky výpočtu
		"""
		self.protokoluj("..Export dat")
		if self.vypocet_config['export_dat'].get('csv', 0) or self.vypocet_config['export_dat'].get('excel', 0) or self.vypocet_config['export_dat'].get('gis', 0):
			self.export_dat_vypoctu()
		if self.vypocet_config['export_dat'].get('xml_islh', 0):
			self.export_dat_islh()
		self.protokoluj("....proveden")
		return(0)

	def export_dat_vypoctu(self):
		"""
		Export dat s výsledky výpočtu
		"""
		self.protokoluj("....Export dat s výsledky výpočtu")
		vystup_excel = self.vypocet_config['export_dat'].get('excel', 0) == 1
		vystup_csv = self.vypocet_config['export_dat'].get('csv', 0) == 1
		vystup_gis = self.vypocet_config['export_dat'].get('gis', 0) == 1
		vystup_dir_gis = os.path.join(self.get_data_dir(), 'vystup', 'gis')
		vystup_dir_spi = os.path.join(self.get_data_dir(), 'vystup', 'spi')

		schema_updates_ps = {
			'lhp_od': 'str:10',
			'y_z_akt': 'float:6.1',
			'y_z_akt_1': 'float:6.1',
			'y_z_akt_2': 'float:6.1',
			't_z_akt': 'float:10.1',
			'y_z_pred': 'float:6.1',
			'y_z_pred_1': 'float:6.1',
			'y_z_pred_2': 'float:6.1',
			't_z_pred': 'float:10.1',
			'y_tez': 'float:6.1',
			't_tez': 'float:10.1',
			'y_cil_zas': 'float:6.1',
			't_cil_zas': 'float:10.1',
			'ft': 'float:5.3',
			'se_zas_25': 'float:6.1',
			'se_cvt_1': 'float:6.1',
			'plocha_ps': 'float:10.1',
			't_cbp': 'float:10.1',
			'y_cbp': 'float:6.1',
			't_cvt': 'float:10.1',
			'y_cvt': 'float:6.1',
			't_n': 'int:12',
			'y_n': 'float:6.1',
			'se_y_z_akt': 'float:6.1',
			'se_y_cvt': 'float:6.1',
			'se_t_z_akt': 'float:6.1',
			'se_t_cvt': 'float:6.1',
			'y_cbp_vyhl': 'float:6.1',
			't_cbp_vyhl': 'float:10.1',
			'lokalita': 'str:12',
			'plocha': 'int:3',
			'odd': 'int:3',
			'nadm_vyska': 'float:6.1',
			'cil_zasoba': 'float:6.1',
			'min_cil_z': 'float:6.1',
			'perioda': 'float:3.1',
			'vyr_doba': 'int:3',
			'cbp_vyhl': 'float:6.1',
			'azimut_km': 'float:6.1',
			'vzd_km': 'float:6.1',
			'd13': 'float:6.1',
			'd13_p': 'float:6.1',
			'mvys_p': 'float:6.1',
			'mvyska': 'float:6.1',
			'pno': 'int:3',
			'pno_pred': 'int:3',
			'mod_vys': 'float:6.1',
			'mod_vys_p': 'float:6.1',
			'mod_vys_d': 'float:6.1',
			'to_md_bk_d': 'float:6.1',
			'to_mv_bk': 'float:6.1',
			'to_modv_bk': 'float:6.1',
			'to_mv_bk_p': 'float:6.1',
			'to_md_bk_p': 'float:6.1',
			'prirust': 'float:6.1',
		}

		self.protokoluj(f"......výstupy za LHP")
		sql_query = f"""
		SELECT lhp.lhp_od::character varying(10) AS lhp_od,
			round(COALESCE(lhpcz.y_z_akt, 0::numeric), 1) AS y_z_akt,
			COALESCE(lhpcz.t_z_akt, 0::numeric) AS t_z_akt,
			COALESCE(lhpcz.y_z_pred, 0::numeric) AS y_z_pred,
			COALESCE(lhpcz.t_z_pred, 0::numeric) AS t_z_pred,
			COALESCE(lhpcz.y_tez, 0::numeric) AS y_tez,
			COALESCE(lhpcz.t_tez, 0::numeric) AS t_tez,
			COALESCE(lhpcz.y_cil_zasoba, 0::numeric) AS y_cil_zas,
			COALESCE(lhpcz.t_cil_zasoba, 0::numeric) AS t_cil_zas,
			COALESCE(lhpcz.ft, 0::numeric) AS ft,
			COALESCE(lhpcz.y_cbp, 0::numeric) AS y_cbp,
			COALESCE(lhpcz.t_cbp, 0::numeric) AS t_cbp,
			COALESCE(lhpcz.y_cvt, 0::numeric) AS y_cvt,
			COALESCE(lhpcz.t_cvt, 0::numeric) AS t_cvt,
			COALESCE(lhpcz.y_n, 0::numeric) AS y_n,
			COALESCE(lhpcz.t_n, 0::numeric) AS t_n,
			COALESCE(lhpcz.se_y_z_akt, 0::numeric) AS se_zas_25,
			COALESCE(lhpcz.se_y_cvt/10, 0::numeric) AS se_cvt_1,
			COALESCE(round((COALESCE(st_area(lhp.ggeom_ps), 0::double precision) / 10000::double precision)::numeric, 5), 0::numeric) AS plocha_ps,
			/*COALESCE(lhpcz.par_vypocet, ''::character varying) AS parametry_vypoctu,*/
			lhpcz.ts_vypocet::character varying(19) AS ts_vypoctu,
			lhp.ggeom_all AS geometry
		FROM happ.lhp lhp,
			happ.lhp_cz01 lhpcz
		WHERE lhp.uid = '{self.uid_config['uid_lhp']}'::uuid AND lhpcz.uid = lhp.uid AND lhpcz.dr_zkr::text = ''::text;
		"""
		
		# Načtení dat včetně geometrie pomocí GeoDataFrame
		gdf_vysl_010 = gpd.GeoDataFrame.from_postgis(sql_query, self.pg_conn, geom_col='geometry')
		gdf_vysl_010_ps = gpd.GeoDataFrame.from_postgis(sql_query.replace('lhp.ggeom_all AS geometry', 'lhp.ggeom_ps AS geometry'), self.pg_conn, geom_col='geometry')

		schema = spi_utils.uprav_schema_pro_export(gdf_vysl_010_ps, schema_updates_ps)

		# Export do SHP souboru, pokud je požadován
		if vystup_gis:
			# Export celkové plochy
			self.protokoluj(f"........export SHP celkové plochy")
			gdf_vysl_010.to_file(os.path.join(vystup_dir_gis, '10_lhp.shp'), driver='ESRI Shapefile', encoding='utf-8', engine='fiona', schema=schema)
			
			# Export porostní plochy
			self.protokoluj(f"........export SHP PSPP")
			# Přesun obsahu sloupce geom_ps do sloupce geometry
			gdf_vysl_010_ps.to_file(os.path.join(vystup_dir_gis, '10_lhp_ps.shp'), driver='ESRI Shapefile', encoding='utf-8', engine='fiona', schema=schema)
		
		# Vytvoření DataFrame bez geometrie pro export do CSV a Excel
		df_vysl_010 = pd.DataFrame(gdf_vysl_010.drop(columns=['geometry']))
		
		# Export do CSV, pokud je požadován
		if vystup_csv:
			df_vysl_010.to_csv(os.path.join(vystup_dir_spi, '10_lhp.csv'), decimal=',', sep=';', index=False)
			self.protokoluj(f"........export CSV")
		
		# Export do Excel, pokud je požadován
		if vystup_excel:
			self.protokoluj(f"........export XLSX")
			df_vysl_010.to_excel(os.path.join(vystup_dir_spi, '10_lhp.xlsx'), index=False)

		# Založení kontrolního DF
		df_check = pd.DataFrame({
			'Úroveň': ['LHP'],
			'T Z AKT LHP': df_vysl_010['t_z_akt'].iloc[0],
			'T Z AKT CHK': df_vysl_010['t_z_akt'].iloc[0],
			'Rozdíl Z AKT': df_vysl_010['t_z_akt'].iloc[0] - df_vysl_010['t_z_akt'].iloc[0],
			'% Z AKT': round(100 * (df_vysl_010['t_z_akt'].iloc[0] - df_vysl_010['t_z_akt'].iloc[0])/df_vysl_010['t_z_akt'].iloc[0], 1),
			'T CVT LHP': df_vysl_010['t_cvt'].iloc[0],
			'T CVT CHK': df_vysl_010['t_cvt'].iloc[0],
			'Rozdíl CVT': df_vysl_010['t_cvt'].iloc[0] - df_vysl_010['t_cvt'].iloc[0],
			'% CVT': round(100 * (df_vysl_010['t_cvt'].iloc[0] - df_vysl_010['t_cvt'].iloc[0])/df_vysl_010['t_cvt'].iloc[0], 1),
			'T N LHP': df_vysl_010['t_n'].iloc[0],
			'T N CHK': df_vysl_010['t_n'].iloc[0],
			'Rozdíl N': df_vysl_010['t_n'].iloc[0] - df_vysl_010['t_n'].iloc[0],
			'% N': round(100 * (df_vysl_010['t_n'].iloc[0] - df_vysl_010['t_n'].iloc[0])/df_vysl_010['t_n'].iloc[0], 1)
		})
		
		del gdf_vysl_010
		del gdf_vysl_010_ps

		self.protokoluj(f"......výstupy za VS")
		sql_query = f"""
		SELECT vs.stratum,
			COALESCE(vscz.y_z_akt, 0::numeric) AS y_z_akt,
			COALESCE(vscz.t_z_akt, 0::numeric) AS t_z_akt,
			COALESCE(vscz.y_z_pred, 0::numeric) AS y_z_pred,
			COALESCE(vscz.t_z_pred, 0::numeric) AS t_z_pred,
			COALESCE(vscz.y_tez, 0::numeric) AS y_tez,
			COALESCE(vscz.t_tez, 0::numeric) AS t_tez,
			COALESCE(vscz.y_cil_zasoba, 0::numeric) AS y_cil_zas,
			COALESCE(vscz.t_cil_zasoba, 0::numeric) AS t_cil_zas,
			COALESCE(lhp.ft, 0::numeric) AS ft,
			COALESCE(vscz.y_cbp, 0::numeric) AS y_cbp,
			COALESCE(vscz.t_cbp, 0::numeric) AS t_cbp,
			COALESCE(vscz.y_cvt, 0::numeric) AS y_cvt,
			COALESCE(vscz.t_cvt, 0::numeric) AS t_cvt,
			COALESCE(vscz.y_n, 0::numeric) AS y_n,
			COALESCE(vscz.t_n, 0::numeric) AS t_n,
			COALESCE(vscz.se_y_z_akt, 0::numeric) AS se_y_z_akt,
			COALESCE(vscz.se_y_cvt, 0::numeric) AS se_y_cvt,
			COALESCE(vscz.se_t_z_akt, 0::numeric) AS se_t_z_akt,
			COALESCE(vscz.se_t_cvt, 0::numeric) AS se_t_cvt,
			round(COALESCE(vsspi.plocha_ps, 0::numeric), 2) AS plocha_ps,
			COALESCE(vscz.y_cbp_vyhl, 0::numeric) AS y_cbp_vyhl,
			COALESCE(vscz.t_cbp_vyhl, 0::numeric) AS t_cbp_vyhl,
			vsspi.ggeom_ps AS geometry
		FROM dsuhul.vs_spi vsspi,
			dsuhul.vs_spi_dr_cz01 vscz,
			dsuhul.vs vs,
			happ.lhp lhp
		WHERE vsspi.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND vsspi.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND vsspi.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
			AND vscz.uid = vsspi.uid AND vs.uid = vsspi.uid_vs AND vscz.dr_zkr::text = ''::text
			AND lhp.uid = '{self.uid_config['uid_lhp']}'::uuid
		ORDER BY vs.stratum;
		"""

		# Načtení dat včetně geometrie pomocí GeoDataFrame
		gdf_vysl_020 = gpd.GeoDataFrame.from_postgis(sql_query, self.pg_conn, geom_col='geometry')

		schema = spi_utils.uprav_schema_pro_export(gdf_vysl_020, schema_updates_ps)

		# Export do SHP souboru, pokud je požadován
		if vystup_gis:
			# Export porostní plochy
			self.protokoluj(f"........export SHP PSPP")
			# Přesun obsahu sloupce geom_ps do sloupce geometry
			gdf_vysl_020.to_file(os.path.join(vystup_dir_gis, '20_vs.shp'), driver='ESRI Shapefile', encoding='utf-8', engine='fiona', schema=schema)
		
		# Vytvoření DataFrame bez geometrie pro export do CSV a Excel
		df_vysl_020 = pd.DataFrame(gdf_vysl_020.drop(columns=['geometry']))
		
		# Export do CSV, pokud je požadován
		if vystup_csv:
			df_vysl_020.to_csv(os.path.join(vystup_dir_spi, '20_vs.csv'), decimal=',', sep=';', index=False)
			self.protokoluj(f"........export CSV")
		
		# Export do Excel, pokud je požadován
		if vystup_excel:
			self.protokoluj(f"........export XLSX")
			df_vysl_020.to_excel(os.path.join(vystup_dir_spi, '20_vs.xlsx'), index=False)

		sums_vs = df_vysl_020[['t_z_akt', 't_cvt', 't_n']].sum()

		# Vytvoření nového řádku pro df_check
		new_row = pd.DataFrame([{
			'Úroveň': 'VS',
			'T Z AKT LHP': df_vysl_010['t_z_akt'].iloc[0],
			'T Z AKT CHK': sums_vs['t_z_akt'],
			'Rozdíl Z AKT': sums_vs['t_z_akt'] - df_vysl_010['t_z_akt'].iloc[0],
			'% Z AKT': round(100 * (sums_vs['t_z_akt'] - df_vysl_010['t_z_akt'].iloc[0]) / df_vysl_010['t_z_akt'].iloc[0], 1) if df_vysl_010['t_z_akt'].iloc[0] != 0 else 0,
			'T CVT LHP': df_vysl_010['t_cvt'].iloc[0],
			'T CVT CHK': sums_vs['t_cvt'],
			'Rozdíl CVT': sums_vs['t_cvt'] - df_vysl_010['t_cvt'].iloc[0],
			'% CVT': round(100 * (sums_vs['t_cvt'] - df_vysl_010['t_cvt'].iloc[0]) / df_vysl_010['t_cvt'].iloc[0], 1) if df_vysl_010['t_cvt'].iloc[0] != 0 else 0,
			'T N LHP': df_vysl_010['t_n'].iloc[0],
			'T N CHK': sums_vs['t_n'],
			'Rozdíl N': sums_vs['t_n'] - df_vysl_010['t_n'].iloc[0],
			'% N': round(100 * (sums_vs['t_n'] - df_vysl_010['t_n'].iloc[0]) / df_vysl_010['t_n'].iloc[0], 1) if df_vysl_010['t_n'].iloc[0] != 0 else 0
		}])

		# Přidání nového řádku do df_check
		df_check = pd.concat([df_check, new_row], ignore_index=True)
		del df_vysl_020

		self.protokoluj(f"......výstupy za IP")

		sql_query = f"""
			select kod 
			from dsuhul.pobl_typy pt 
			where pt.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND pt.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND pt.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
			order by pt.kod
		"""

		df_pobl_typy = pd.read_sql_query(sql_query, self.pg_conn)

		sql_query = f"""
		SELECT strat.stratum,
			il.lokalita,
			ip.plocha,
			ip.odd,
			ip.dil,
			ip.por,
		"""
		# načtení identifikací podoblastí
		for index, row in df_pobl_typy.iterrows():
			sql_query = sql_query +f"""
			(SELECT pobl.kod
				from
					dsuhul.il_vs_pobl ilp
					, dsuhul.pobl_typy pt
					, dsuhul.pobl pobl
				where
					ilp.uid_il = il.uid
					and ilp.uid_vs = strat.uid
					and pobl.uid = ilp.uid_pobl
					and pt.uid = pobl.uid_tpobl
					and pt.kod = '{row['kod']}'
			) AS {row['kod'].lower().replace(' ', '_')},
			"""
		sql_query = sql_query +f"""
		ip.nadm_vyska,
			ip.ek,
			COALESCE(er.er, ''::bpchar) AS er,
			ip.poz_les,
				CASE
					WHEN ip.poz_les::text = '100'::text THEN ip.status
					ELSE ''::character varying
				END AS status,
			COALESCE(ipcz.y_z_akt, 0::numeric) AS y_z_akt,
			COALESCE(ipcz.y_z_pred, 0::numeric) AS y_z_pred,
			COALESCE(ipcz.y_tez, 0::numeric) AS y_tez,
			COALESCE(ip.cil_zasoba, 0::numeric) AS cil_zasoba,
			COALESCE(ipcz.perioda, 0::numeric) AS perioda,
			COALESCE(ip.vyr_doba, 0::numeric) AS vyr_doba,
			COALESCE(ipcz.y_cbp, 0::numeric) AS y_cbp,
			COALESCE(ipcz.y_cvt, 0::numeric) AS y_cvt,
			COALESCE(ipcz.y_n, 0::numeric) AS y_n,
			/*COALESCE(ipcz.vyr_doba_vypocet, 0::numeric) AS vyr_doba_vypocet,
			COALESCE(ipcz.perioda, 0::numeric) AS perioda_vypocet,
			COALESCE(ipcz.ft_vypocet, 0::numeric) AS ft_vypocet,
			COALESCE(ipcz.cbp_vypocet, 0::numeric) AS cbp_vypocet,
			COALESCE(ipcz.cil_zasoba_vypocet, 0::numeric) AS cil_zasoba_vypocet,*/
			ip.cbp_max AS cbp_vyhl,
			ip.cil_zasoba_min AS min_cil_z,
			COALESCE(ip.pozn_plocha, ''::character varying) AS poznamka,
			ip.geom_gnss_sjtsk AS geometry
		FROM dsuhul.ip ip
			LEFT JOIN dsuhul.ip_cz01 ipcz ON ipcz.uid = ip.uid AND ipcz.dr_zkr::text = ''::text
			LEFT JOIN dsuhul.l_er_cz01 er ON er.ek = ip.ek,
			dsuhul.il il,
			dsuhul.vs_spi vs,
			dsuhul.vs_spi_dr_cz01 vscz,
			dsuhul.vs strat
		WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
			AND vs.uid_firm = ip.uid_firm AND vs.uid_lhc = ip.uid_lhc AND vs.uid_lhp = ip.uid_lhp AND vs.uid_ik = ip.uid_ik AND vs.uid_vs = ip.uid_vs AND vscz.uid = vs.uid AND vscz.dr_zkr::text = ''::text 
			AND il.uid = ip.uid_il AND strat.uid = vs.uid_vs
		ORDER BY (il.lokalita::integer)
		"""
		# Načtení dat včetně geometrie pomocí GeoDataFrame
		gdf_vysl_030 = gpd.GeoDataFrame.from_postgis(sql_query, self.pg_conn, geom_col='geometry')

		schema = spi_utils.uprav_schema_pro_export(gdf_vysl_030, schema_updates_ps)

		# Export do SHP souboru, pokud je požadován
		if vystup_gis:
			# Export porostní plochy
			self.protokoluj(f"........export SHP")
			# Přesun obsahu sloupce geom_ps do sloupce geometry
			gdf_vysl_030.to_file(os.path.join(vystup_dir_gis, '30_ip.shp'), driver='ESRI Shapefile', encoding='utf-8', engine='fiona', schema=schema)
		
		# Vytvoření DataFrame bez geometrie pro export do CSV a Excel
		df_vysl_030 = pd.DataFrame(gdf_vysl_030.drop(columns=['geometry']))
		
		# Export do CSV, pokud je požadován
		if vystup_csv:
			df_vysl_030.to_csv(os.path.join(vystup_dir_spi, '30_ip.csv'), decimal=',', sep=';', index=False)
			self.protokoluj(f"........export CSV")
		
		# Export do Excel, pokud je požadován
		if vystup_excel:
			self.protokoluj(f"........export XLSX")
			df_vysl_030.to_excel(os.path.join(vystup_dir_spi, '30_ip.xlsx'), index=False)

		del df_vysl_030

		self.protokoluj(f"......výstupy za VZ")

		sql_query = f"""
		SELECT 
			il.lokalita,
			ip.plocha,
			ip.odd,
			ip.dil,
			ip.por,
			vs.stratum,
		"""
		# načtení identifikací podoblastí
		for index, row in df_pobl_typy.iterrows():
			sql_query = sql_query +f"""
			(SELECT pobl.kod
				from
					dsuhul.il_vs_pobl ilp
					, dsuhul.pobl_typy pt
					, dsuhul.pobl pobl
				where
					ilp.uid_il = il.uid
					and ilp.uid_vs = vs.uid
					and pobl.uid = ilp.uid_pobl
					and pt.uid = pobl.uid_tpobl
					and pt.kod = '{row['kod']}'
			) AS {row['kod'].lower().replace(' ', '_')},
			"""
		sql_query = sql_query +f"""
		COALESCE(vz.podplocha, 0::numeric)::integer AS podplocha,
		vz.kmen::integer,
		COALESCE(vz.dr_zkr, ''::character varying) AS dr_zkr,
			CASE
				WHEN COALESCE(vz.parez, ''::character varying)::text = ANY (ARRAY['200'::character varying::text, '300'::character varying::text]) THEN 'Starý pařez'::text
				WHEN COALESCE(vz.parez, ''::character varying)::text = '400'::text THEN 'Pařez z těžby'::text
				WHEN COALESCE(vz.parez, ''::character varying)::text = '500'::text THEN 'Pařez zlomu'::text
				WHEN COALESCE(vz.parez, ''::character varying)::text = '400'::text THEN 'Pařez z těžby souše'::text
				WHEN COALESCE(vz.parez, ''::character varying)::text = '500'::text THEN 'Pařez zlomu souše'::text
				WHEN COALESCE(vz.zlom_vyvrat, ''::character varying)::text = '200'::text THEN 'Ohyb'::text
				WHEN COALESCE(vz.zlom_vyvrat, ''::character varying)::text = '300'::text THEN 'Vrškový zlom'::text
				WHEN COALESCE(vz.zlom_vyvrat, ''::character varying)::text = '400'::text THEN 'Korunový zlom'::text
				WHEN COALESCE(vz.zlom_vyvrat, ''::character varying)::text = '500'::text THEN 'Kmenový zlom'::text
				WHEN COALESCE(vz.zlom_vyvrat, ''::character varying)::text = '600'::text THEN 'Náhradní vrchol'::text
				WHEN COALESCE(vz.zlom_vyvrat, ''::character varying)::text = '700'::text THEN 'Živý vývrat'::text
				WHEN COALESCE(vz.dvojak, ''::character varying)::text = '200'::text THEN 'Dvoják'::text
				ELSE 'Živý kmen'::text
			END AS typ_vzorniku,
			vz.azimut_km,
			vz.vzd_km,
			COALESCE(vz.opak_ident_km, ''::character varying) AS opak_ident_km,
			COALESCE(vz.parez, ''::character varying) AS parez,
			COALESCE(vz.pol_parez, ''::character varying) AS pol_parez,
			COALESCE(vz.vyklizeni_km, ''::character varying) AS vyklizeni_km,
			COALESCE(vz.sous, ''::character varying) AS sous,
			COALESCE(vz.zlom_vyvrat, ''::character varying) AS zlom_vyvrat,
			COALESCE(vz.dvojak, ''::character varying) AS dvojak,
			COALESCE(vz.kmen_pred, 0::numeric)::integer AS kmen_pred,
			COALESCE(vz.parez_pred, ''::character varying) AS parez_pred,
			COALESCE(vz.sous_pred, ''::character varying) AS sous_pred,
			COALESCE(vz.zlom_vyvrat_pred, ''::character varying) AS zlom_vyvrat_pred,
			COALESCE(vz.komp_zmeny, ''::character varying) AS komp_zmeny,
			COALESCE(vz.tloustka_km, 0::numeric) AS tloustka_km,
			COALESCE(vz.vyska, 0::numeric) AS mvyska,
			COALESCE(vz.mod_vys, 0::numeric) AS mod_vys,
			COALESCE(vz.tloustka_km_pred, 0::numeric) AS tloustka_km_pred,
			COALESCE(vz.vyska_pred, 0::numeric) AS mvyska_pred,
			COALESCE(vz.mod_vys_pred, 0::numeric) AS mod_vys_pred,
			COALESCE(vz.pno, 0::numeric) AS pno,
			COALESCE(vz.to_mv_bk, 0::numeric) AS to_mv_bk,
			COALESCE(vz.to_modv_bk, 0::numeric) AS to_modv_bk,
			COALESCE(vz.pno_pred, 0::numeric) AS pno_pred,
			COALESCE(vz.to_mv_bk_pred, 0::numeric) AS to_mv_bk_pred,
			COALESCE(vz.to_modv_bk_pred, 0::numeric) AS to_modv_bk_pred,
				CASE
					WHEN COALESCE(vz.vzornik2, false) THEN 'A'::text
					ELSE 'N'::text
				END AS vzornik2,
				CASE
					WHEN COALESCE(vz.vzornik2_pred, false) THEN 'A'::text
					ELSE 'N'::text
				END AS vzornik2_pred,
			COALESCE(vz.zz1, 0::numeric) AS zz1,
			COALESCE(vz.zz2, 0::numeric) AS zz2,
			COALESCE(vz.d13_depl, 0::numeric) AS d13_depl,
			COALESCE(vz.mod_vys_depl, 0::numeric) AS mod_vys_depl,
			COALESCE(vz.to_modv_bk_depl, 0::numeric) AS to_modv_bk_depl,
			COALESCE(vz.zz1_depl, 0::numeric) AS zz1_depl,
			COALESCE(vz.zz2_depl, 0::numeric) AS zz2_depl,
			coalesce(vzc.y_z_akt_1, 0::numeric) AS y_z_akt_1,
			coalesce(vzc.y_z_akt_2, 0::numeric) AS y_z_akt_2,
			coalesce(vzc.y_z_akt, 0::numeric) AS y_z_akt,
			coalesce(vzc.y_z_pred_1, 0::numeric) AS y_z_pred_1,
			coalesce(vzc.y_z_pred_2, 0::numeric) AS y_z_pred_2,
			coalesce(vzc.y_z_pred, 0::numeric) AS y_z_pred,
			coalesce(vzc.y_tez, 0::numeric) AS y_tez,
			coalesce(vzc.y_z_akt_1, 0::numeric) - coalesce(vzc.y_z_pred_1, 0::numeric)
			+ coalesce(vzc.y_z_akt_2, 0::numeric) - coalesce(vzc.y_z_pred_2, 0::numeric)
			+ coalesce(vzc.y_tez, 0::numeric) as prirust,
			COALESCE(vz.pozn_km, ''::character varying) AS pozn_km,
			vz.geom_gnss_sjtsk AS geometry
		FROM dsuhul.ip ip,
			dsuhul.il il,
			dsuhul.vz vz
				left outer join dsuhul.vz_cz01 vzc on vz.uid = vzc.uid,
			dsuhul.vs vs
		WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
			AND il.uid = ip.uid_il AND vz.uid_ip = ip.uid AND vs.uid = ip.uid_vs
			AND vz.zapocitat
		ORDER BY il.lokalita;
		"""
		# Načtení dat včetně geometrie pomocí GeoDataFrame
		gdf_vysl_040 = gpd.GeoDataFrame.from_postgis(sql_query, self.pg_conn, geom_col='geometry')

		schema = spi_utils.uprav_schema_pro_export(gdf_vysl_040, schema_updates_ps)

		# Export do SHP souboru, pokud je požadován
		if vystup_gis:
			# Export porostní plochy
			self.protokoluj(f"........export SHP")
			# Přejmenování dlouhých sloupců pro SHP export
			rename_dict = {
				'typ_vzorniku': 'typ_vz',
				'opak_ident_km': 'opak_ident',
				'vyklizeni_km': 'vyklizeni',
				'zlom_vyvrat': 'zlom_vyv',
				'zlom_vyvrat_pred': 'zlom_vyv_p',
				'tloustka_km': 'd13',
				'tloustka_km_pred': 'd13_p',
				'mvyska_pred': 'mvys_p',
				'mod_vys_pred': 'mod_vys_p',
				'mod_vys_depl': 'mod_vys_d',
				'to_modv_bk_depl': 'to_md_bk_d',
				'to_mv_bk_pred': 'to_mv_bk_p',
				'to_modv_bk_pred': 'to_md_bk_p',
				'vzornik2_pred': 'vzornik2_p',
			}
			gdf_vysl_040_shp = gdf_vysl_040.copy()
			gdf_vysl_040_shp.rename(columns=rename_dict, inplace=True)
			shp_schema = spi_utils.uprav_schema_pro_export(gdf_vysl_040_shp, schema_updates_ps)
			# Přesun obsahu sloupce geom_ps do sloupce geometry
			gdf_vysl_040_shp.to_file(os.path.join(vystup_dir_gis, '40_vz.shp'), driver='ESRI Shapefile', encoding='utf-8', engine='fiona', schema=shp_schema)
			del gdf_vysl_040_shp

		# Vytvoření DataFrame bez geometrie pro export do CSV a Excel
		df_vysl_040 = pd.DataFrame(gdf_vysl_040.drop(columns=['geometry']))
		
		# Export do CSV, pokud je požadován
		if vystup_csv:
			df_vysl_040.to_csv(os.path.join(vystup_dir_spi, '40_vz.csv'), decimal=',', sep=';', index=False)
			self.protokoluj(f"........export CSV")
		
		# Export do Excel, pokud je požadován
		if vystup_excel:
			self.protokoluj(f"........export XLSX")
			df_vysl_040.to_excel(os.path.join(vystup_dir_spi, '40_vz.xlsx'), index=False)

		del df_vysl_040

		self.protokoluj(f"......výstupy za podoblasti")
		# načtení identifikací podoblastí
		for index, row in df_pobl_typy.iterrows():
			self.protokoluj(f"........{row['kod']}")
			sql_query = f"""
				SELECT p.kod, p.nazev,
					round(pc.y_n, 1) AS y_n,
					round(pc.t_n, 0) AS t_n,
					pc.y_z_akt AS y_z_akt,
					pc.t_z_akt AS t_z_akt,
					pc.y_cbp,
					pc.t_cbp,
					pc.y_cvt,
					pc.t_cvt,
					round(p.plocha_ps, 2) plocha_ps,
					p.ggeom_ps AS geometry
				FROM dsuhul.pobl_typy pt,
					dsuhul.pobl p,
					dsuhul.pobl_cz01 pc
				WHERE pt.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid AND pt.kod::text = '{row['kod']}'::text AND p.uid_tpobl = pt.uid AND pc.uid_pobl = p.uid AND pc.dr_zkr::text = ''::text
				ORDER BY p.kod
			"""

			# Načtení dat včetně geometrie pomocí GeoDataFrame
			gdf_vysl_050 = gpd.GeoDataFrame.from_postgis(sql_query, self.pg_conn, geom_col='geometry')

			schema = spi_utils.uprav_schema_pro_export(gdf_vysl_050, schema_updates_ps)

			# Export do SHP souboru, pokud je požadován
			if vystup_gis:
				# Export porostní plochy
				self.protokoluj(f"..........export SHP")
				# Přesun obsahu sloupce geom_ps do sloupce geometry
				gdf_vysl_050.to_file(os.path.join(vystup_dir_gis, f"50_{row['kod'].lower().replace(' ', '_')}.shp"), driver='ESRI Shapefile', encoding='utf-8', engine='fiona', schema=schema)
			
			# Vytvoření DataFrame bez geometrie pro export do CSV a Excel
			df_vysl_050 = pd.DataFrame(gdf_vysl_050.drop(columns=['geometry']))
			
			# Export do CSV, pokud je požadován
			if vystup_csv:
				df_vysl_050.to_csv(os.path.join(vystup_dir_spi, f"50_{row['kod'].lower().replace(' ', '_')}_sumar.csv"), decimal=',', sep=';', index=False)
				self.protokoluj(f"..........export CSV")
			
			# Export do Excel, pokud je požadován
			if vystup_excel:
				self.protokoluj(f"..........export XLSX")
				df_vysl_050.to_excel(os.path.join(vystup_dir_spi, f"50_{row['kod'].lower().replace(' ', '_')}_sumar.xlsx"), index=False)

			sums_vs = df_vysl_050[['t_z_akt', 't_cvt', 't_n']].sum()

			# Vytvoření nového řádku pro df_check
			new_row = pd.DataFrame([{
				'Úroveň': row['kod'],
				'T Z AKT LHP': df_vysl_010['t_z_akt'].iloc[0],
				'T Z AKT CHK': sums_vs['t_z_akt'],
				'Rozdíl Z AKT': sums_vs['t_z_akt'] - df_vysl_010['t_z_akt'].iloc[0],
				'% Z AKT': round(100 * (sums_vs['t_z_akt'] - df_vysl_010['t_z_akt'].iloc[0]) / df_vysl_010['t_z_akt'].iloc[0], 1) if df_vysl_010['t_z_akt'].iloc[0] != 0 else 0,
				'T CVT LHP': df_vysl_010['t_cvt'].iloc[0],
				'T CVT CHK': sums_vs['t_cvt'],
				'Rozdíl CVT': sums_vs['t_cvt'] - df_vysl_010['t_cvt'].iloc[0],
				'% CVT': round(100 * (sums_vs['t_cvt'] - df_vysl_010['t_cvt'].iloc[0]) / df_vysl_010['t_cvt'].iloc[0], 1) if df_vysl_010['t_cvt'].iloc[0] != 0 else 0,
				'T N LHP': df_vysl_010['t_n'].iloc[0],
				'T N CHK': sums_vs['t_n'],
				'Rozdíl N': sums_vs['t_n'] - df_vysl_010['t_n'].iloc[0],
				'% N': 100 * (sums_vs['t_n'] - df_vysl_010['t_n'].iloc[0]) / df_vysl_010['t_n'].iloc[0] if df_vysl_010['t_n'].iloc[0] != 0 else 0
			}])

			# Přidání nového řádku do df_check
			df_check = pd.concat([df_check, new_row], ignore_index=True)
			
			del df_vysl_050

		self.protokoluj(f"......dřevinná skladba za podoblasti")
		# načtení identifikací podoblastí
		for index, row in df_pobl_typy.iterrows():
			self.protokoluj(f"........{row['kod']}")
			sql_query = f"""
				SELECT p.kod,
					pc.dr_zkr,
					sum(pc.t_n) AS pocet_kh,
					sum(pc.t_z_akt) AS zasoba,
					round(100::numeric * sum(pc.t_z_akt) / max(pcsum.t_z_akt), 1) AS podil_zasoby
				FROM dsuhul.pobl_typy pt,
					dsuhul.pobl p,
					dsuhul.pobl_cz01 pc,
					dsuhul.pobl_cz01 pcsum
				WHERE pt.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid AND pt.kod::text = '{row['kod']}'::text AND p.uid_tpobl = pt.uid AND pc.uid_pobl = p.uid AND pc.dr_zkr::text <> ''::text 
					AND pcsum.uid_pobl = pc.uid_pobl AND pcsum.dr_zkr::text = ''::text AND pcsum.tlt = 0::numeric
				GROUP BY p.kod, pc.dr_zkr
				ORDER BY p.kod, pc.dr_zkr
			"""

			df_vysl_052 = pd.read_sql_query(sql_query, self.pg_conn)
			
			# Export do CSV, pokud je požadován
			if vystup_csv:
				df_vysl_052.to_csv(os.path.join(vystup_dir_spi, f"52_{row['kod'].lower().replace(' ', '_')}_dr{'_3d' if row['kod'] == 'HOS' else ''}.csv"), decimal=',', sep=';', index=False)
				self.protokoluj(f"..........export CSV")
			
			# Export do Excel, pokud je požadován
			if vystup_excel:
				self.protokoluj(f"..........export XLSX")
				df_vysl_052.to_excel(os.path.join(vystup_dir_spi, f"52_{row['kod'].lower().replace(' ', '_')}_dr{'_3d' if row['kod'] == 'HOS' else ''}.xlsx"), index=False)

			del df_vysl_052

		self.protokoluj(f"......tloušťkové třídy za podoblasti")
		# načtení identifikací podoblastí
		for index, row in df_pobl_typy.iterrows():
			self.protokoluj(f"........{row['kod']}")
			sql_query = f"""
				SELECT p.kod,
					pc.tlt,
					concat(min(ktlt.min_d13)::character varying(10), ' - ', max(ktlt.max_d13)::character varying(10)) AS interval_tlt,
					sum(pc.t_n) AS pocet_kh,
					sum(pc.t_z_akt) AS zasoba,
					round(100::numeric * sum(pc.t_z_akt) / max(pcsum.t_z_akt), 1) AS podil_zasoby
				FROM dsuhul.pobl_typy pt,
					dsuhul.pobl p,
					dsuhul.pobl_cz01 pc,
					dsuhul.pobl_cz01 pcsum,
					happ.lhp lhp,
					dsuhul.list_ktlt_types lktt,
					dsuhul.ktlt ktlt
				WHERE pt.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid AND pt.kod::text = '{row['kod']}'::text AND p.uid_tpobl = pt.uid AND pc.uid_pobl = p.uid AND pc.dr_zkr::text <> ''::text AND pc.tlt > 0::numeric 
					AND pcsum.uid_pobl = pc.uid_pobl AND pcsum.dr_zkr::text = ''::text AND lhp.uid = pt.uid_lhp AND lktt.code::text = lhp.ktlt::text AND ktlt.uid_firm = lhp.uid_firm AND ktlt.uid_lktl = lktt.uid AND ktlt.trida = pc.tlt
				GROUP BY p.kod, pc.tlt
				ORDER BY p.kod, pc.tlt
			"""

			df_vysl_053	 = pd.read_sql_query(sql_query, self.pg_conn)
			
			# Export do CSV, pokud je požadován
			if vystup_csv:
				df_vysl_053.to_csv(os.path.join(vystup_dir_spi, f"53_{row['kod'].lower().replace(' ', '_')}_tlt{'_3e' if row['kod'] == 'HOS' else ''}.csv"), decimal=',', sep=';', index=False)
				self.protokoluj(f"..........export CSV")
			
			# Export do Excel, pokud je požadován
			if vystup_excel:
				self.protokoluj(f"..........export XLSX")
				df_vysl_053.to_excel(os.path.join(vystup_dir_spi, f"53_{row['kod'].lower().replace(' ', '_')}_tlt{'_3e' if row['kod'] == 'HOS' else ''}.xlsx"), index=False)

			del df_vysl_053

		self.protokoluj(f"......Kontrolní soubor porovnání")
		# Export do CSV, pokud je požadován
		if vystup_csv:
			df_check.to_csv(os.path.join(vystup_dir_spi, '90_kontrola.csv'), decimal=',', sep=';', index=False)
			self.protokoluj(f"........export CSV")
		
		# Export do Excel, pokud je požadován
		if vystup_excel:
			self.protokoluj(f"........export XLSX")
			df_check.to_excel(os.path.join(vystup_dir_spi, '90_kontrola.xlsx'), index=False)


		del df_vysl_010
		del df_check

		# Pomocné SHP soubory
		definice_shp = {
			'pom_vz_zz1_nom': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred, vz.zz1_nom_ggeom as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il,
						dsuhul.vz vz
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il AND vz.uid_ip = ip.uid
						AND vz.zapocitat
					ORDER BY il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred;
				"""
			},
			'pom_vz_zz1': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred, vz.zz1_ggeom as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il,
						dsuhul.vz vz
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il AND vz.uid_ip = ip.uid
						AND vz.zapocitat
					ORDER BY il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred;
				""",
			},
			'pom_vz_zz2_nom': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred, vz.zz2_nom_ggeom as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il,
						dsuhul.vz vz
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il AND vz.uid_ip = ip.uid
						AND vz.zapocitat
					ORDER BY il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred;
				"""
			},
			'pom_vz_zz2': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred, vz.zz2_ggeom as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il,
						dsuhul.vz vz
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il AND vz.uid_ip = ip.uid
						AND vz.zapocitat
					ORDER BY il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred;
				"""
			},
			'pom_vz_prumet': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred, vz.ggeom_prumet as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il,
						dsuhul.vz vz
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il AND vz.uid_ip = ip.uid
					ORDER BY il.lokalita, ip.plocha, vz.kmen, vz.kmen_pred;
				""",
			},
			'pno': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, pno.pomno, pno.geom_pno_sjtsk as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il,
						dsuhul.pno pno
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il AND pno.uid_ip = ip.uid
					ORDER BY il.lokalita, ip.plocha, pno.pomno;
				""",
			},
			'pom_ip_pp_1': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, ip.geom_pp_1 as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il
					ORDER BY il.lokalita, ip.plocha;
				""",
			},
			'pom_ip_pp_2': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, ip.geom_pp_2 as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il
					ORDER BY il.lokalita, ip.plocha;
				""",
			},
			'pom_ip_pp_3': {
				'query': f"""
					SELECT il.lokalita, ip.plocha, ip.geom_pp_3 as geometry
					FROM dsuhul.ip ip,
						dsuhul.il il
					WHERE ip.uid_firm = '{self.uid_config['uid_firm']}'::uuid AND ip.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid AND ip.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
						AND il.uid = ip.uid_il
					ORDER BY il.lokalita, ip.plocha;
				""",
			},
		}

		self.protokoluj(f"......export podpůrných SHP")
		if vystup_gis:
			for klic, radek in definice_shp.items():
				gdf_pom = gpd.GeoDataFrame.from_postgis(radek['query'], self.pg_conn, geom_col='geometry')
				schema = spi_utils.uprav_schema_pro_export(gdf_pom, schema_updates_ps)

				gdf_pom.to_file(os.path.join(vystup_dir_gis, f"{klic}.shp"), driver='ESRI Shapefile', encoding='utf-8', engine='fiona', schema=schema)
				self.protokoluj(f"........{klic}")

		self.protokoluj("......export dat LHP dokončen")

		return(0)

	def export_dat_islh(self):
		"""
		Export dat s výsledky výpočtu
		"""
		self.protokoluj("....Export dat s výsledky výpočtu")

		self.protokoluj("......vytvoření XML")
		# Vytvoření XML root elementu
		root = ET.Element("DATAISLH")
		#root.set("version", "1.0")
		#root.set("encoding", "utf-8")
		
		#islh_element = ET.SubElement(root, "DATAISLH")
		# Vrcholový element LHC
		lhc_element = ET.SubElement(root, "LHC")
		lhc_element.set("LHP_Z_LIC", 'Určeno pro vložení do výsledného XML TAXu')
		lhc_element.set("LHP_Z_TAX", 'Robert Blaha')

		# Hospodářské skupiny
		sql_query = f"""
			select
				p.kod HOS
				, round(p.vymera_ps, 4) HOS_V
				, round(pc.t_z_pred, 0) INV_ZAS_PRED_CEL
				, round(pc.y_z_pred, 0) INV_ZAS_PRED_HA
				, round(pc.t_z_akt, 0) INV_ZAS_SOUC_CEL
				, round(pc.y_z_akt, 0) INV_ZAS_SOUC_HA
				, coalesce(round(pc.t_tez_lhe, 0), 0) C_TEZBA_INVOBD_LHE_CEL
				, coalesce(round(pc.t_tez/p.plocha_ps, 0), 0) C_TEZBA_INVOBD_LHE_HA
				, coalesce(round(pc.t_cbp, 0), 0) PPR_INVOBD_CEL
				, coalesce(round(pc.y_cbp, 0), 0) PPR_INVOBD_HA
				, '' HOS_TEXT
				, p.uid UID_HOS
			from 
				dsuhul.pobl_typy pt,
				dsuhul.pobl p,
				dsuhul.pobl_cz01 pc
			where
				pt.uid_firm = '{self.uid_config['uid_firm']}'::uuid and pt.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid and pt.kod = 'HOS'
				and p.uid_tpobl = pt.uid
				and pc.uid_pobl = p.uid and pc.dr_zkr = ''
			order by p.kod
		"""
		with self.pg_conn.connection.cursor() as cursor:
			cursor.execute(sql_query)
			rows_hos = cursor.fetchall()
			columns_hos = [desc[0] for desc in cursor.description]
			
		for row_data_hos in rows_hos:
			row_dict_hos = spi_utils.oprav_format_cisel(
				dict(zip(columns_hos, row_data_hos)),
				{
					'HOS_V': 4,
					'INV_ZAS_PRED_CEL': 0,
					'INV_ZAS_PRED_HA': 0,
					'INV_ZAS_SOUC_CEL': 0,
				}
			)
			hos_element = ET.SubElement(lhc_element, "HOS")
			hos_element = spi_utils.element_vloz_atributy(hos_element, row_dict_hos, ['uid_hos'])

			# Mapová data
			sql_query = f"""
                select
                    ST_asgeoJSON(p.ggeom) MP
                from 
                    dsuhul.pobl p
                where
                    p.uid = '{row_dict_hos['uid_hos']}'::uuid
			"""
			with self.pg_conn.connection.cursor() as cursor:
				cursor.execute(sql_query)
				row_mp = cursor.fetchone()
				if row_mp:
					spi_utils.generuj_mapovy_element(hos_element, "HOS_OBRAZ", row_mp[0])
				
			# Tloušťkové třídy
			sql_query = f"""
				select
					pc.tlt TLT
					, round(min(tlt.min_d13), 0) TLT_SPOD_HRA
					, round(sum(pc.t_z_akt), 0) TLT_ZAS
					, round(sum(pc.t_n), 0) TLT_KM_POC
					, min(tlt.min_d13)::character varying(10) || ' - ' || min(tlt.max_d13)::character varying(10)|| ' cm' TLT_TEXT
				from 
					dsuhul.pobl_cz01 pc
					, happ.lhp
					, dsuhul.list_ktlt_types ktlt
					, dsuhul.ktlt tlt
				where
					pc.uid_pobl = '{row_dict_hos['uid_hos']}'::uuid and pc.tlt > 0 /* jen stojící kmeny */
					and lhp.uid = '{self.uid_config['uid_lhp']}'::uuid
					and ktlt.uid_firm = lhp.uid_firm and ktlt.code = lhp.ktlt
					and tlt.uid_firm = lhp.uid_firm and tlt.uid_lktl = ktlt.uid and tlt.trida = pc.tlt
				group by pc.tlt
				order by pc.tlt
			"""
			with self.pg_conn.connection.cursor() as cursor:
				cursor.execute(sql_query)
				rows_tlt = cursor.fetchall()
				columns_tlt = [desc[0] for desc in cursor.description]
			
			for row_data_tlt in rows_tlt:
				row_dict_tlt = spi_utils.oprav_format_cisel(
					dict(zip(columns_tlt, row_data_tlt)),
					{
						'TLT_ZAS': 0,
					}
				)
				tlt_element = ET.SubElement(hos_element, "TLT")
				tlt_element = spi_utils.element_vloz_atributy(tlt_element, row_dict_tlt)

			# Dřeviny
			sql_query = f"""
                    select
                        dr.code_uhul DRH_ZKR
                        , min(coalesce(dr.full_name, '')) DRH_NAZ
                        , round(sum(pc.t_n), 0) DRH_KM_POC
                        --, case when round(sum(pc.t_z_akt), 0) < 0 then 0 else round(sum(pc.t_z_akt), 0) end DRH_ZAS
                        , round(sum(pc.t_z_akt), 0) DRH_ZAS
                        , Round((100 * sum(pc.t_z_akt)/max(ps.t_z_akt)), 0) DRH_ZAST
                    from 
                        dsuhul.pobl_cz01 pc
                            left outer join dsuhul.l_dr_zkr_cz01 dr on (dr.sort_val = pc.dr_zkr)
                        , dsuhul.pobl_cz01 ps
                    where
                        pc.uid_pobl = '{row_dict_hos['uid_hos']}'::uuid and pc.dr_zkr <> '' and pc.tlt > 0 /* jen stojící kmeny */
                        and ps.uid_pobl = pc.uid_pobl and ps.dr_zkr = ''
                    group by dr.code_uhul
                    order by dr.code_uhul
			"""
			with self.pg_conn.connection.cursor() as cursor:
				cursor.execute(sql_query)
				rows_drh = cursor.fetchall()
				columns_drh = [desc[0] for desc in cursor.description]
			
			for row_data_drh in rows_drh:
				row_dict_drh = spi_utils.oprav_format_cisel(
					dict(zip(columns_drh, row_data_drh)),
					{
						'DRH_KM_POC': 0,
					}
				)
				drh_element = ET.SubElement(hos_element, "DRH")
				drh_element = spi_utils.element_vloz_atributy(drh_element, row_dict_drh)

		# Inventarizační kampaně
		sql_query = f"""
            select
                ik.kampan KAMPAN
                , to_char(ik.kampan_od, 'DD.MM.YYYY') KAMPAN_OD
                , to_char(ik.kampan_do, 'DD.MM.YYYY') KAMPAN_DO
                , ik.uid uid_ik
            from 
                dsuhul.ik ik
            where
				ik.uid_firm = '{self.uid_config['uid_firm']}'::uuid and ik.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid and ik.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid
		"""
		with self.pg_conn.connection.cursor() as cursor:
			cursor.execute(sql_query)
			rows_ik = cursor.fetchall()
			columns_ik = [desc[0] for desc in cursor.description]
			
			for row_data_ik in rows_ik:
				row_dict_ik = spi_utils.oprav_format_cisel(
					dict(zip(columns_ik, row_data_ik)),
					{
					}
				)
				ik_element = ET.SubElement(lhc_element, "IK")
				ik_element = spi_utils.element_vloz_atributy(ik_element, row_dict_ik, ['uid_ik'])

				# VS - výběrová strata
				sql_query = f"""
                    select
                        vs.stratum stratum
                        , vs.stratum_popis stratum_popis
                        , vs_spi.plocha_ps PRIST_POR_PUDA
                        , vs.lkt_code lkt_code
                        , vs.uid uid_vs
                    from 
                        dsuhul.vs_spi vs_spi
                        , dsuhul.vs vs
                        ,  dsuhul.ik ik
                    where
                        vs_spi.uid_firm = '{self.uid_config['uid_firm']}'::uuid and vs_spi.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid and vs_spi.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid and vs_spi.uid_ik = '{row_dict_ik['uid_ik']}'::uuid
                        and vs.uid = vs_spi.uid_vs
                        and ik.uid = vs_spi.uid_ik
                        and exists(select 1 from dsuhul.ip ip, dsuhul.vz vz 
                                            where ip.uid_firm = vs_spi.uid_firm and ip.uid_lhc = vs_spi.uid_lhc and ip.uid_lhp = vs_spi.uid_lhp
                                                    and ip.uid_ik = vs_spi.uid_ik and ip.uid_vs = vs_spi.uid_vs
                                                    and vz.uid_ip = ip.uid
                                    )
                    order by vs.stratum
				"""
				with self.pg_conn.connection.cursor() as cursor:
					cursor.execute(sql_query)
					rows_vs = cursor.fetchall()
					columns_vs = [desc[0] for desc in cursor.description]
				
				for row_data_vs in rows_vs:
					row_dict_vs = spi_utils.oprav_format_cisel(
						dict(zip(columns_vs, row_data_vs)),
						{
							'prist_por_puda': 2
						}
					)
					vs_element = ET.SubElement(ik_element, "VS")
					vs_element = spi_utils.element_vloz_atributy(vs_element, row_dict_vs, ['uid_vs', 'lkt_code'])

					# Mapová data
					sql_query = f"""
						select
							ST_asgeoJSON(vs.ggeom) MP
						from 
							dsuhul.vs vs
						where
							vs.uid = '{row_dict_vs['uid_vs']}'::uuid
					"""
					with self.pg_conn.connection.cursor() as cursor:
						cursor.execute(sql_query)
						row_mp = cursor.fetchone()
						if row_mp:
							spi_utils.generuj_mapovy_element(vs_element, "STRATUM_OBRAZ", row_mp[0])


					# KIL - konfigurace inventarizačních lokalit
					sql_query = f"""
						select
							kil.plocha plocha
							, kil.azimut_pid azimut_pid
							, kil.vzd_pid vzd_pid
							, kil.rf rf
							, kil.uid_lkt uid_lkt
							, kil.uid uid_kil
						from 
							dsuhul.list_kil_types lkt
							, dsuhul.kil kil
						where
							lkt.uid_firm = '{self.uid_config['uid_firm']}'::uuid and lkt.code = '{row_dict_vs['lkt_code']}'
							and kil.uid_firm = lkt.uid_firm and kil.uid_lkt = lkt.uid
					"""
					with self.pg_conn.connection.cursor() as cursor:
						cursor.execute(sql_query)
						rows_kil = cursor.fetchall()
						columns_kil = [desc[0] for desc in cursor.description]
						
						for row_data_kil in rows_kil:
							row_dict_kil = spi_utils.oprav_format_cisel(
								dict(zip(columns_kil, row_data_kil)),
								{
									'azimut_pid': 1,
									'vzd_pid': 1,
								}
							)
							kil_element = ET.SubElement(vs_element, "KIL")
							kil_element = spi_utils.element_vloz_atributy(kil_element, row_dict_kil, ['uid_kil', 'uid_lkt'])

							# KIP - konfigurace inventarizačních ploch
							sql_query = f"""
								select
									kip.podplocha podplocha
									, kip.sp_r sp_r
									, kip.min_d13
								from 
									dsuhul.kip kip
								where
									kip.uid_firm = '{self.uid_config['uid_firm']}'::uuid and kip.uid_lkt = '{row_dict_kil['uid_lkt']}'::uuid and kip.uid_kil = '{row_dict_kil['uid_kil']}'::uuid
								order by kip.podplocha
							"""
							with self.pg_conn.connection.cursor() as cursor:
								cursor.execute(sql_query)
								rows_kip = cursor.fetchall()
								columns_kip = [desc[0] for desc in cursor.description]
								
								for row_data_kip in rows_kip:
									row_dict_kip = spi_utils.oprav_format_cisel(
										dict(zip(columns_kip, row_data_kip)),
										{
											'sp_r': 2,
											'min_d13': 0,
										}
									)
									kip_element = ET.SubElement(kil_element, "KIP")
									kip_element = spi_utils.element_vloz_atributy(kip_element, row_dict_kip, [])

					# IP - inventarizační plochy
					sql_query = f"""
						select
							il.lokalita lokalita
							, ip.plocha plocha
							, ip.odd odd
							, ip.dil dil
							, ip.por por
							, pobl.kod hos
							, to_char(ip.datum_m, 'DD.MM.YYYY') datum_m
							, to_char(ip.datum_m_pred, 'DD.MM.YYYY') datum_m_pred
							, ip.mdcel
							, ip.azimut_stab azimut_stab
							, ip.vzd_stab vzd_stab
							, hafn.tr_geom_sjtsk_text_uhul(ip.ggeom) ggeom
							, hafn.tr_geom_sjtsk_text_uhul(ip.geom_gnss_sjtsk) geom_gnss
							, coalesce(ipcz.cil_zasoba_vypocet, 0) /*coalesce(ip.cil_zasoba, 0)*/ cil_zasoba
							, case when ip.status = '100' then coalesce(ipcz.cbp_vypocet, 0) else coalesce(ip.cbp_max, 0) end cbp
							, coalesce(ip.vyr_doba, 0) vyr_doba
							, ip.status status
							, ip.prist prist
							, ip.stab stab
							, ip.identifikace identifikace
							, ip.duv_neob duv_neob
							, ip.kat_poz kat_poz
							, ip.poz_les poz_les
							, ip.lt lt 
							, ip.prist_pred prist_pred
							, ip.kat_poz_pred kat_poz_pred
							, ip.poz_les_pred poz_les_pred
							, ip.meric meric
							, coalesce(ip.pozn_plocha, '') pozn_plocha
							, ip.uid uid_ip
						from 
							dsuhul.vs_spi vs_spi
							, dsuhul.ip ip
								left outer join dsuhul.ip_cz01 ipcz on (ipcz.uid = ip.uid and ipcz.dr_zkr = '')
							, dsuhul.il il
							, dsuhul.il_vs_pobl pil
							, dsuhul.pobl pobl
							, dsuhul.pobl_typy tpobl
						where
							vs_spi.uid_firm = '{self.uid_config['uid_firm']}'::uuid and vs_spi.uid_lhc = '{self.uid_config['uid_lhc']}'::uuid and vs_spi.uid_lhp = '{self.uid_config['uid_lhp']}'::uuid 
							and vs_spi.uid_ik = '{row_dict_ik['uid_ik']}'::uuid and vs_spi.uid_vs = '{row_dict_vs['uid_vs']}'::uuid
							and ip.uid_firm = vs_spi.uid_firm and ip.uid_lhc = vs_spi.uid_lhc and ip.uid_lhp = vs_spi.uid_lhp and ip.uid_ik = vs_spi.uid_ik and ip.uid_vs = vs_spi.uid_vs
							and il.uid = ip.uid_il
							and pil.uid_il = il.uid and pil.uid_vs = vs_spi.uid_vs
							and pobl.uid = pil.uid_pobl
							and tpobl.uid = pobl.uid_tpobl and tpobl.kod = 'HOS'
						order by il.lokalita
					"""
					with self.pg_conn.connection.cursor() as cursor:
						cursor.execute(sql_query)
						rows_ip = cursor.fetchall()
						columns_ip = [desc[0] for desc in cursor.description]
						
					for row_data_ip in rows_ip:
						row_dict_ip = spi_utils.oprav_format_cisel(
							dict(zip(columns_ip, row_data_ip)),
							{
								'mdcel': 1,
								'azimut_stab': 1,
								'vzd_stab': 1,
								'cbp': 1,
							}
						)

						# Vypouštěné klíče
						vyp_klice = ['uid_ip']

						if row_dict_ip.get('status') != '100':
							vyp_klice.append('identifikace')
							# Vypuštění klíčů končících "_pred"
							for klic in list(row_dict_ip.keys()):
								if klic.endswith('_pred'):
									vyp_klice.append(klic)

						if row_dict_ip.get('stab') == '100':
							vyp_klice.append('azimut_stab')
							vyp_klice.append('vzd_stab')

						if row_dict_ip.get('identifikace') != '200' or row_dict_ip.get('status') != '100':
							vyp_klice.append('duv_neob')

						if row_dict_ip.get('identifikace') == '100' and row_dict_ip.get('status') == '100':
							vyp_klice.append('cbp')

						ip_element = ET.SubElement(kil_element, "IP")
						ip_element = spi_utils.element_vloz_atributy(ip_element, row_dict_ip, vyp_klice)

						# VZ - vzorníky
						sql_query = f"""
							select
								vz.kmen kmen
								, vz.KMEN_PRED KMEN_PRED
								, coalesce(dr.code_uhul, vz.DR_ZKR) DR_ZKR
								, vz.VZD_KM VZD_KM
								, vz.AZIMUT_KM AZIMUT_KM
								, coalesce(vz.TLOUSTKA_KM, 0) TLOUSTKA_KM
								, case when coalesce(vz.OPAK_IDENT_KM, '') = '' then '100' else vz.OPAK_IDENT_KM end OPAK_IDENT_KM
								, coalesce(vz.PAREZ, '100') PAREZ
								, case when case when coalesce(vz.PAREZ, '') = '' then '0' else vz.parez end::integer > 100 and coalesce(vz.POL_PAREZ, '') = '' then '100' else POL_PAREZ end
								, vz.SOUS SOUS
								, vz.DVOJAK DVOJAK
								, case when coalesce(vz.PAREZ, '100') = '100' then case when coalesce(vz.ZLOM_VYVRAT, '') = '' then '100' else vz.zlom_vyvrat end else '' end ZLOM_VYVRAT
								, /*case when*/ coalesce(vz.KOMP_ZMENY, '') /*= '' then '100' else vz.KOMP_ZMENY end*/ KOMP_ZMENY
								, case when case when coalesce(vz.PAREZ, '') = '' then '0' else vz.parez end::integer > 300 and coalesce(vz.VYKLIZENI_KM, '') = '' then '100' else vz.VYKLIZENI_KM end VYKLIZ_KM
								, vz.PAREZ_PRED PAREZ_PRED
								, vz.SOUS_PRED SOUS_PRED
								, vz.ZLOM_VYVRAT_PRED ZLOM_VYVRAT_PRED
								, coalesce(vz.TLOUSTKA_KM_PRED, 0) TLOUSTKA_KM_PRED
								, coalesce(vz.MOD_VYS, 0) MOD_VYSKA
								, coalesce(vz.MOD_VYS_PRED, 0) MOD_VYSKA_PRED
								, case when vz.VZORNIK2 then 'A' else 'N' end VZORNIK2
								, case when vz.VZORNIK2_PRED then 'A' else 'N' end VZORNIK2_PRED
								, coalesce(vz.VYSKA, 0) MVYSKA
								, coalesce(vz.VYSKA_PRED, 0) MVYSKA_PRED
								, vz.TO_MV_SK TO_MV_SK
								, vz.TO_MV_BK TO_MV_BK
								, vz.TO_MODV_SK TO_MODV_SK
								, vz.TO_MODV_BK TO_MODV_BK
								, vz.ZZ1 ZZ1
								, vz.ZZ2 ZZ2
								, coalesce(vz.PNO, 0) PNO
								, vz.TO_MV_SK_PRED TO_MV_SK_PRED
								, vz.TO_MV_BK_PRED TO_MV_BK_PRED
								, vz.TO_MODV_SK_PRED TO_MODV_SK_PRED
								, vz.TO_MODV_BK_PRED TO_MODV_BK_PRED
								, vz.ZZ1_PRED ZZ1_PRED
								, vz.ZZ2_PRED ZZ2_PRED
								, vz.PNO_PRED PNO_PRED
								, coalesce(vz.D13_DEPL, 0) D13_DEPL
								, coalesce(vz.MOD_VYS_DEPL, 0) MOD_VYSKA_DEPL
								, coalesce(vz.TO_MODV_SK_DEPL, 0) TO_MODV_SK_DEPL
								, coalesce(vz.TO_MODV_BK_DEPL, 0) TO_MODV_BK_DEPL
								, coalesce(vz.ZZ1_DEPL, 0) ZZ1_DEPL
								, coalesce(vz.ZZ2_DEPL, 0) ZZ2_DEPL
								, case when strpos(coalesce(vz.POZN_KM, ''), '#KLEPACOV') > 0 then '' else  coalesce(vz.POZN_KM, '') end POZN_KM /* #KLEPACOV je specialita SLP 2023 */
							from 
								dsuhul.vz vz
									left outer join dsuhul.l_dr_zkr_cz01 dr on (dr.sort_val = vz.dr_zkr)
								, dsuhul.ip ip
							where
								vz.uid_ip = '{row_dict_ip['uid_ip']}'::uuid
								and vz.zapocitat
								and ip.uid = vz.uid_ip and ip.poz_les = '100' and ip.prist = '100'
							order by vz.kmen
						"""
						with self.pg_conn.connection.cursor() as cursor:
							cursor.execute(sql_query)
							rows_vz = cursor.fetchall()
							columns_vz = [desc[0] for desc in cursor.description]
							
							for row_data_vz in rows_vz:
								row_dict_vz = spi_utils.oprav_format_cisel(
									dict(zip(columns_vz, row_data_vz)),
									{
                                        'vzd_km' : 2,
                                        'azimut_km' : 1,
                                        'tloustka_km' : 1,
                                        'tloustka_km_pred' : 1,
                                        'mod_vyska' : 1,
                                        'mod_vyska_pred' : 1,
                                        'mod_vyska_depl' : 1,
                                        'mvyska' : 1,
                                        'mvyska_pred' : 1,
                                        'to_mv_sk' : 1,
                                        'to_mv_bk' : 1,
                                        'to_modv_sk' : 1,
                                        'to_modv_bk' : 1,
                                        'to_mv_sk_pred' : 1,
                                        'to_mv_bk_pred' : 1,
                                        'to_modv_sk_pred' : 1,
                                        'to_modv_bk_pred' : 1,
                                        'to_modv_sk_depl' : 1,
                                        'to_modv_bk_depl' : 1,
                                        'zz1' : 5,
                                        'zz2' : 5,
                                        'zz1_pred' : 5,
										'zz2_pred' : 5,
                                        'zz1_depl' : 5,
                                        'zz2_depl' : 5,
                                        'd13_depl' : 1,
									}
								)
								
								# Vypouštěné klíče
								vyp_klice = []
								
								# Vypuštění předchozího kmene
								if row_dict_vz.get('kmen_pred') == '0':
									vyp_klice.append('kmen_pred')
									if row_dict_vz.get('opak_ident_km') not in ['200']:
										vyp_klice.append('opak_ident_km')
								
								# Vypuštění předchozího kmene
								if (row_dict_vz.get('komp_zmeny') in ['', '300', '900', '1000', '1100'] 
									and row_dict_vz.get('kmen') > 0
									and row_dict_vz.get('parez') not in ['200', '300']
									and 'opak_ident_km' in row_dict_vz and row_dict_vz.get('opak_ident_km') != '300'):
									vyp_klice.extend(['kmen_pred', 'opak_ident_km'])
								
								# Odstranění informací o předchozí inventarizaci, pokud jde o první
								if 'kmen_pred' not in row_dict_vz or row_dict_vz.get('status') != '100':
									for klic in list(row_dict_vz.keys()):
										if klic.endswith('_pred') and klic != 'kmen_pred':
											vyp_klice.append(klic)
								
								# Vypuštění polí ve vztahu k pařezu
								if row_dict_vz.get('parez') == '100':
									vyp_klice.append('pol_parez')
								else:
									vyp_klice.extend(['sous', 'dvojak', 'zlom_vyvrat', 'mod_vyska', 'to_modv_sk', 'to_modv_bk'])
								
								# Pařez nemůže mít ZZ2 (nemůže být vzorník2 protože nemá výčetní výšku)
								if row_dict_vz.get('parez') > '100':
									vyp_klice.append('zz2')
								
								# Vypuštění polí ve vztahu k předchozímu pařezu
								if 'parez_pred' in row_dict_vz and row_dict_vz.get('parez_pred') == '200':
									vyp_klice.extend(['sous_pred', 'zlom_vyvrat_pred', 'mod_vyska_pred', 
													'to_modv_sk_pred', 'to_modv_bk_pred', 'vykliz_km'])
								
								# Vypuštění polí ve vztahu k předchozímu pařezu
								if ('parez_pred' in row_dict_vz and row_dict_vz.get('parez_pred') == '200' 
									and (row_dict_vz.get('parez') == '200' or row_dict_vz.get('parez') == '300')):
									vyp_klice.append('dr_zkr')
								
								# Vypuštění DEPL hodnot mimo pařezy (z těžby nebo mortality)
								if row_dict_vz.get('parez') not in ['400', '500', '600', '700']:
									vyp_klice.extend(['d13_depl', 'mod_vyska_depl', 'to_modv_sk_depl', 
													'to_modv_bk_depl', 'zz1_depl', 'zz2_depl'])
								
								# Kmeny co už minule neměly být
								if 'opak_ident_km' in row_dict_vz and row_dict_vz.get('opak_ident_km') == '300':
									vyp_klice.extend(['mod_vyska_pred', 'to_modv_sk_pred', 'to_modv_bk_pred'])
								
								# Souše nejsou zlomy a vývraty
								if row_dict_vz.get('parez') == '100' and row_dict_vz.get('sous', '0') > '100':
									vyp_klice.append('zlom_vyvrat')
								
								# Vypuštění vyklizení kmene, pokud nemá smysl
								if row_dict_vz.get('parez') == '100':
									vyp_klice.append('vykliz_km')
								
								# VI.VZ měřené výšky a objemy
								if (row_dict_vz.get('vzornik2') != 'A'
									or ('opak_ident_km' in row_dict_vz and row_dict_vz.get('opak_ident_km') in ['400', '500', '600'])
									or ('sous' in row_dict_vz and row_dict_vz.get('sous') in ['200', '300', '400', '500'])
									or row_dict_vz.get('parez') > '100'
									or ('zlom_vyvrat' in row_dict_vz and row_dict_vz.get('zlom_vyvrat') in ['200', '300', '400', '500', '700'])):
									vyp_klice.extend(['mvyska', 'to_mv_sk', 'to_mv_bk'])
								
								# VI.VZ měřené výšky předchozí
								if (('vzornik2_pred' in row_dict_vz and row_dict_vz.get('vzornik2_pred') != 'A')
									or ('opak_ident_km' in row_dict_vz and row_dict_vz.get('opak_ident_km') in ['300', '600'])
									or ('sous_pred' in row_dict_vz and row_dict_vz.get('sous_pred') in ['400', '500'])
									or row_dict_vz.get('parez') in ['200', '300']
									or ('parez_pred' in row_dict_vz and row_dict_vz.get('parez_pred') in ['200'])
									or ('zlom_vyvrat_pred' in row_dict_vz and row_dict_vz.get('zlom_vyvrat_pred') in ['200', '300', '400', '500', '700'])):
									vyp_klice.append('mvyska_pred')
								
								# VI.VZ měřené objemy v minulé inventarizaci
								if ('kmen_pred' not in row_dict_vz
									or ('opak_ident_km' in row_dict_vz and (row_dict_vz.get('opak_ident_km') == '300' or row_dict_vz.get('opak_ident_km') == '600'))
									or ('vzornik2_pred' in row_dict_vz and row_dict_vz.get('vzornik2_pred') != 'A')
									or ('parez_pred' in row_dict_vz and row_dict_vz.get('parez_pred') == '200')
									or row_dict_vz.get('parez') == '200' or row_dict_vz.get('parez') == '300'
									or ('sous_pred' in row_dict_vz and (row_dict_vz.get('sous_pred') == '400' or row_dict_vz.get('sous_pred') == '500'))
									or ('zlom_vyvrat_pred' in row_dict_vz and row_dict_vz.get('zlom_vyvrat_pred') in ['200', '300', '400', '500', '700'])):
									vyp_klice.extend(['to_mv_bk_pred', 'to_mv_sk_pred'])
								
								# VI.VZ PNO
								if (('opak_ident_km' in row_dict_vz and row_dict_vz.get('opak_ident_km') in ['400', '500', '600'])
									or ('sous' in row_dict_vz and row_dict_vz.get('sous') in ['100', '200', '300']
										and (('zlom_vyvrat' in row_dict_vz and row_dict_vz.get('zlom_vyvrat') in ['', '100', '200', '600', '700']) 
											or 'zlom_vyvrat' not in row_dict_vz))
									or row_dict_vz.get('parez') in ['200', '300', '400', '500', '600', '700']):
									vyp_klice.append('pno')
								
								# VI.VZ modelové objemy v minulé inventarizaci
								if ('kmen_pred' not in row_dict_vz
									or row_dict_vz.get('opak_ident_km') == '300' or row_dict_vz.get('opak_ident_km') == '600'
									or ('parez_pred' in row_dict_vz and row_dict_vz.get('parez_pred') == '200')
									or row_dict_vz.get('parez') == '200' or row_dict_vz.get('parez') == '300'):
									vyp_klice.extend(['to_modv_sk_pred', 'zz2_pred', 'vzornik2_pred'])
								
								# VI.VZ plocha ZZ1 před
								if 'kmen_pred' not in row_dict_vz or row_dict_vz.get('opak_ident_km') == '300':
									vyp_klice.append('zz1_pred')
								
								# VI.VZ PNO před
								if ('parez_pred' not in row_dict_vz
									or row_dict_vz.get('opak_ident_km') == '300' or row_dict_vz.get('opak_ident_km') == '600'
									or ('parez_pred' in row_dict_vz and row_dict_vz.get('parez_pred') == '200')
									or row_dict_vz.get('parez') == '200' or row_dict_vz.get('parez') == '300'
									or ('sous_pred' in row_dict_vz and row_dict_vz.get('sous_pred') in ['100', '200', '300']
										and (('zlom_vyvrat_pred' in row_dict_vz and row_dict_vz.get('zlom_vyvrat_pred') in ['', '100', '200', '600', '700'])
											or 'zlom_vyvrat_pred' not in row_dict_vz))):
									vyp_klice.append('pno_pred')
								
								# VI.VZ vzorníky 2 stupně
								if (row_dict_vz.get('kmen') == '0'
									or ('opak_ident_km' in row_dict_vz and row_dict_vz.get('opak_ident_km') in ['400', '500', '600'])
									or row_dict_vz.get('parez') > '100'):
									vyp_klice.extend(['vzornik2', 'mvyska', 'to_mv_sk', 'to_mv_bk'])
								
								# Pro opakovaný pařez se nezjišťuje komponenta změny
								if (row_dict_vz.get('parez') != '100'
									and ('parez_pred' not in row_dict_vz or row_dict_vz.get('parez_pred') != '100')
									and row_dict_vz.get('komp_zmeny') != '900'):
									vyp_klice.append('komp_zmeny')
								
								# Vypuštění informací o současné inventarizaci, pokud není kmenem v současné inventarizaci
								if row_dict_vz.get('kmen') == '0':
									vyp_klice.extend(['zz1', 'zz2', 'parez', 'dvojak', 'zlom_vyvrat', 'opak_ident_km',
													'tloustka_km', 'mod_vyska', 'to_modv_sk', 'to_modv_bk', 'mvyska', 'pno'])
									
								# Vypuštění klíčů objemu s kůrou
								vyp_klice.extend(['to_mv_sk', 'to_modv_sk', 'to_mv_sk_pred', 'to_modv_sk_pred', 'to_modv_sk_depl'])

								# Pokud nejde o opakovanou inventarizaci, vypuštění komponenty změny
								if row_dict_ip.get('status') != '100':
									vyp_klice.append('komp_zmeny')

								# Vypuštění informací o vzornících 2. stupně, pokud jimi nejsou - diskuse PDS/Kopla/Černík
								if row_dict_vz.get('vzornik2') != 'A':
									vyp_klice.extend(['vzornik2', 'zz2'])
								if row_dict_vz.get('vzornik2_pred') != 'A':
									vyp_klice.extend(['vzornik2_pred', 'zz2_pred'])

								vz_element = ET.SubElement(ip_element, "VZ")
								vz_element = spi_utils.element_vloz_atributy(vz_element, row_dict_vz, vyp_klice)
					
		self.protokoluj("......formátování XML")
		# Převod na řetězec (bez XML deklarace)
		xml_content = ET.tostring(root, encoding='Windows-1250')
		# Úprava pro lepší čitelnost (odsazení)
		xml_str = minidom.parseString(xml_content).toprettyxml(indent='  ')

		# Odstranění XML deklarace, kterou přidá minidom.toprettyxml()
		lines = xml_str.split('\n')
		xml_str_bez_deklarace = '\n'.join(lines[1:])

		# Vytvoření vlastní hlavičky
		custom_header = '<?xml version="1.0" encoding="Windows-1250" ?>\n<?ISLH 2024 LHP $ ?>\n<!-- LED xml ver.4.2.113.80 -->\n'

		# Kompletní XML s vlastní hlavičkou
		final_xml = custom_header + xml_str_bez_deklarace

		self.protokoluj("......uložení do souboru")
		with open(os.path.join(self.get_data_dir(), 'vystup', 'islh', 'islh.xml'), 'w', encoding='Windows-1250') as f:
			f.write(final_xml)

		return(0)
	
	def vypocet(self):
		self.protokoluj(f"Zahájení výpočtu SPI pro LHC {self.lhc} {self.lhc_config['nazev_firmy']}")

		# Procházení kroků výpočtu
		for krok in self.kroky_config['kroky']:
			# Kontrola, zda se má krok provádět
			konfig_hodnota = self.vypocet_config
			for klic in krok['konfig_klic'].split('.'):
				konfig_hodnota = konfig_hodnota.get(klic, {})
			
			if konfig_hodnota:
				# Zápis zahájení kroku do protokolu
				self.protokoluj(f">>> {krok['zprava']} >>>")
				
				# Volání metody
				try:
					vysledek = getattr(self, krok['metoda'])()
				except Exception as e:
					self.protokoluj(f"Chyba při volání metody {krok['metoda']}: {e} \n {traceback.format_exc()}")
					return(20)
				
				# Zpracování výsledku
				if vysledek == 0:
					self.protokoluj(krok['zprava'] + " dokončena")
				elif vysledek == 10:
					self.protokoluj(krok['zprava'] + " dokončena s varováním")
					if self.vypocet_config['nastaveni_vypoctu'].get('ignorovat_varovani', 0):
						self.protokoluj("..varování ignorováno")
					else:
						self.protokoluj("Zpracování ukončeno")
						return(1)
				else:
					self.protokoluj(krok['zprava'] + " ukončeno s chybou")
					self.protokoluj("Zpracování ukončeno")
					return(1)
			else:
				self.protokoluj(krok['zprava'] + " nebylo prováděno")

		self.protokoluj("Ukončení výpočtu")

