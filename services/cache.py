"""
Caché persistente en disco para datos del dashboard.
- Días históricos: JSON gzip en disco (permanente)
- Hoy: memoria con TTL 5 min
- Warm-up: solo cachea días sin caché existente desde el último import
"""
import gzip
import json
import os
import threading
import logging
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def _cache_path(date_str: str) -> Path:
    return CACHE_DIR / f"{date_str}.json.gz"


def get_cached_day(date_str: str) -> dict | None:
    p = _cache_path(date_str)
    try:
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Cache read error {date_str}: {e}")
        try: p.unlink()  # borrar si está corrupto
        except: pass
    return None


def set_cached_day(date_str: str, data: dict) -> None:
    p = _cache_path(date_str)
    try:
        with _lock:
            with gzip.open(p, "wt", encoding="utf-8", compresslevel=6) as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        logger.warning(f"Cache write error {date_str}: {e}")


def invalidate_day(date_str: str) -> None:
    p = _cache_path(date_str)
    if p.exists():
        p.unlink()


def invalidate_from(date_str: str) -> int:
    """Invalida solo el día dado y posteriores. Para cuando se importan datos recientes."""
    count = 0
    for p in CACHE_DIR.glob("*.json.gz"):
        if p.stem.replace(".json", "") >= date_str:
            p.unlink()
            count += 1
    logger.info(f"Cache invalidated from {date_str}: {count} files")
    return count


def invalidate_all() -> int:
    count = 0
    for p in CACHE_DIR.glob("*.json.gz"):
        p.unlink()
        count += 1
    # También limpiar archivos .json sin comprimir si quedan
    for p in CACHE_DIR.glob("*.json"):
        p.unlink()
        count += 1
    logger.info(f"Cache cleared: {count} files")
    return count


def is_today(date_str: str) -> bool:
    return date_str == date.today().strftime("%Y-%m-%d")


def get_last_import_date() -> str | None:
    """Devuelve la fecha del último registro importado en la BD."""
    try:
        from services.db import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(date_day) as d FROM records WHERE date_day IS NOT NULL"
            ).fetchone()
            return row["d"] if row else None
    except Exception:
        return None


def warm_cache_async() -> None:
    """
    Pre-calienta el caché en background al arrancar.
    Solo procesa días que NO tienen caché todavía — nunca reprocesa.
    """
    t = threading.Thread(target=_warm_worker, daemon=True)
    t.start()


def _warm_worker() -> None:
    try:
        from services.db import get_conn

        with get_conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT date_day FROM records
                WHERE date_day IS NOT NULL
                  AND date_day < date('now')
                ORDER BY date_day DESC
            """).fetchall()

        all_days = [r["date_day"] for r in rows]
        # Solo los que faltan en caché
        missing = [d for d in all_days if get_cached_day(d) is None]

        if not missing:
            logger.info("Cache warm-up: already complete")
            return

        logger.info(f"Cache warm-up: {len(missing)} days missing (of {len(all_days)} total)")

        from routes.dashboard import _build_day_data
        for date_str in missing:
            try:
                data = _build_day_data(date_str)
                set_cached_day(date_str, data)
            except Exception as e:
                logger.warning(f"Cache warm-up error {date_str}: {e}")

        logger.info("Cache warm-up complete")

    except Exception as e:
        logger.error(f"Cache warm-up failed: {e}")
