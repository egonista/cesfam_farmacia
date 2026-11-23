"""
Script de verificación e inicialización automática de la base de datos PostgreSQL.
Verifica si la base de datos 'cesfam_farmacia_db' existe; si no, la crea conectándose
a 'postgres' con las credenciales configuradas.
"""
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def ensure_database():
    db_name = 'cesfam_farmacia_db'
    user = 'postgres'
    password = 'Valorant-1'
    host = 'localhost'
    port = '5432'

    try:
        conn = psycopg2.connect(
            dbname='postgres',
            user=user,
            password=password,
            host=host,
            port=port
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (db_name,))
        exists = cur.fetchone()

        if not exists:
            cur.execute(f'CREATE DATABASE "{db_name}";')
            print(f"[OK] Base de datos '{db_name}' creada exitosamente en PostgreSQL.")
        else:
            print(f"[OK] Base de datos '{db_name}' ya existe en PostgreSQL.")

        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[ERROR] No se pudo verificar o crear la base de datos: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    ensure_database()
