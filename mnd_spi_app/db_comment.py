import psycopg2

# Připojení k databázi
conn = psycopg2.connect(
    host="localhost",
    database="spi_vzor", #"mnd_spi_app",
    user="postgres",
    password="MendeluRulez"
)

# Licenční text
license_text = """Copyright (C) 2025 Robert Blaha, Mendel Univerzity in Brno, HULpro s.r.o.
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License or
any later version.
 See <https://www.gnu.org/licenses/>.
 """

cursor = conn.cursor()

# Získat seznam všech procedur s rozlišením typu objektu
cursor.execute("""
    SELECT 
        n.nspname AS schema_name,
        p.proname AS procedure_name,
        pg_get_function_identity_arguments(p.oid) AS args,
        CASE 
            WHEN p.prokind = 'p' THEN 'PROCEDURE'
            WHEN p.prokind = 'f' THEN 'FUNCTION'
            WHEN p.prokind = 'a' THEN 'AGGREGATE'
            ELSE 'UNKNOWN'
        END AS object_type
    FROM 
        pg_proc p
    JOIN 
        pg_namespace n ON p.pronamespace = n.oid
    WHERE 
        n.nspname IN ('hafn')
""")

procedures = cursor.fetchall()

# Procházet procedury a přidávat licenční komentáře
for schema_name, proc_name, args, obj_type in procedures:
    try:
        comment_sql = f"COMMENT ON {obj_type} {schema_name}.{proc_name}({args}) IS %s"
        cursor.execute(comment_sql, (license_text,))
        print(f"Přidán komentář k objektu: {obj_type} {schema_name}.{proc_name}({args})")
    except Exception as e:
        print(f"Chyba při přidávání komentáře k {obj_type} {schema_name}.{proc_name}({args}): {e}")
        # Pokračovat s dalšími objekty i při chybě

conn.commit()
cursor.close()
conn.close()