"""
Conector MongoDB con patrón singleton y fallback a archivo local.
Implementa resiliencia: si MongoDB no responde, usa archivo JSON local.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_mongo_client = None
_mongo_db = None
_fallback_mode = False

def get_fallback_dir():
    """Retorna el directorio para persistencia de fallback."""
    try:
        from django.conf import settings
        base = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
    except Exception:
        base = Path(__file__).resolve().parent.parent
    d = Path(base) / 'mongo_fallback'
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_mongo_db():
    """Obtiene la conexión a MongoDB o None si no está disponible."""
    global _mongo_client, _mongo_db, _fallback_mode

    if _mongo_db is not None:
        return _mongo_db

    try:
        from pymongo import MongoClient
        from pymongo.errors import ServerSelectionTimeoutError

        _mongo_client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
        )
        # Verificar conectividad
        _mongo_client.admin.command('ping')
        _mongo_db = _mongo_client[settings.MONGODB_NAME]
        _fallback_mode = False
        logger.info('Conexión exitosa a MongoDB: %s', settings.MONGODB_NAME)
        return _mongo_db

    except Exception as e:
        logger.warning('MongoDB no disponible, activando fallback local: %s', e)
        _fallback_mode = True
        _mongo_db = FallbackDocStore()
        return _mongo_db


def is_fallback_mode():
    """Retorna True si se está usando el fallback local en vez de MongoDB real."""
    return _fallback_mode


class FallbackCollection:
    """Colección de fallback que escribe a archivos JSON locales."""

    def __init__(self, name):
        self.name = name
        self.dir = get_fallback_dir()
        self.filepath = self.dir / f'{name}.json'

    def _load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save(self, data):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def insert_one(self, document):
        docs = self._load()
        document['_fallback_id'] = len(docs) + 1
        document['_inserted_at'] = datetime.now(timezone.utc).isoformat()
        docs.append(document)
        self._save(docs)
        return type('Result', (), {'inserted_id': document['_fallback_id']})()

    def insert_many(self, documents):
        docs = self._load()
        ids = []
        for doc in documents:
            doc['_fallback_id'] = len(docs) + 1
            doc['_inserted_at'] = datetime.now(timezone.utc).isoformat()
            docs.append(doc)
            ids.append(doc['_fallback_id'])
        self._save(docs)
        return type('Result', (), {'inserted_ids': ids})()

    def find(self, filter_dict=None, *args, **kwargs):
        docs = self._load()
        if not filter_dict:
            return docs
        result = []
        for doc in docs:
            match = True
            for key, value in filter_dict.items():
                if doc.get(key) != value:
                    match = False
                    break
            if match:
                result.append(doc)
        return result

    def find_one(self, filter_dict=None):
        results = self.find(filter_dict)
        return results[0] if results else None

    def count_documents(self, filter_dict=None):
        return len(self.find(filter_dict or {}))

    def drop(self):
        if self.filepath.exists():
            self.filepath.unlink()

    def create_index(self, *args, **kwargs):
        pass  # No-op en fallback


class FallbackDocStore:
    """Store documental de fallback que simula la interfaz de pymongo database."""

    def __init__(self):
        self._collections = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = FallbackCollection(name)
        return self._collections[name]

    def list_collection_names(self):
        return list(self._collections.keys())
