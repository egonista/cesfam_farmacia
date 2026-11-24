"""
Script de verificación e inicialización automática de la base de datos PostgreSQL.
Solo actúa cuando DB_ENGINE=postgresql está configurado en las variables de entorno / .env.
"""
import os
import sys
from pathlib import Path


def _cargar_env():
    env_file = Path(__file__).resolve().parent / '.env'
    if env_file.exists():
        for raw in env_file.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def ensure_database():
    _cargar_env()
    if os.environ.get('DB_ENGINE', 'sqlite').strip().lower() != 'postgresql':
        return True

    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    db_name = os.environ.get('DB_NAME', 'cesfam_farmacia_db')
    user = os.environ.get('DB_USER', 'postgres')
    password = os.environ.get('DB_PASSWORD', '')
    host = os.environ.get('DB_HOST', 'localhost')
    port = os.environ.get('DB_PORT', '5432')

    try:
        conn = psycopg2.connect(
            dbname='postgres',
            user=user,
            password=password,
            host=host,
            port=port,
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
        print(f"[ERROR] No se pudo verificar o crear la base de datos PostgreSQL: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    ensure_database()
