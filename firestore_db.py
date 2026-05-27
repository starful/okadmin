"""Firestore client for work-hub data."""
from __future__ import annotations

import os

import firebase_admin
from firebase_admin import credentials, firestore

_db = None
_init_error: str | None = None


def get_db():
    global _db, _init_error
    if _db is not None:
        return _db
    if _init_error:
        return None
    try:
        if not firebase_admin._apps:
            cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path and os.path.isfile(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
        _db = firestore.client()
        return _db
    except Exception as e:
        _init_error = str(e)
        print(f"Firestore init error: {e}")
        return None


def firestore_unavailable_message() -> str:
    if _init_error:
        return _init_error
    return "Firestore not configured (set GOOGLE_APPLICATION_CREDENTIALS)"


def doc_to_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    for key, val in list(data.items()):
        if val is None:
            continue
        if hasattr(val, "isoformat"):
            data[key] = val.isoformat()
        elif hasattr(val, "timestamp"):
            try:
                data[key] = val.timestamp()
            except Exception:
                data[key] = str(val)
    return data
