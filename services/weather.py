"""services/weather.py — Integración con Open-Meteo (gratuito, sin API key)."""
import json
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import URLError
from services.db import get_conn, DB_FILE, get_city

WMO_CODES = {
    0:  ('Despejado',        '☀️'),
    1:  ('Mayormente despejado','🌤️'),
    2:  ('Parcialmente nublado','⛅'),
    3:  ('Nublado',          '☁️'),
    45: ('Niebla',           '🌫️'),
    48: ('Niebla con escarcha','🌫️'),
    51: ('Llovizna ligera',  '🌦️'),
    53: ('Llovizna',         '🌦️'),
    55: ('Llovizna intensa', '🌧️'),
    61: ('Lluvia ligera',    '🌧️'),
    63: ('Lluvia',           '🌧️'),
    65: ('Lluvia intensa',   '🌧️'),
    71: ('Nevada ligera',    '🌨️'),
    73: ('Nevada',           '🌨️'),
    75: ('Nevada intensa',   '❄️'),
    80: ('Chubascos',        '🌦️'),
    81: ('Chubascos moderados','🌧️'),
    82: ('Chubascos fuertes','⛈️'),
    95: ('Tormenta',         '⛈️'),
    99: ('Tormenta con granizo','⛈️'),
}


def _fetch_url(url: str) -> dict:
    req = Request(url, headers={'User-Agent': 'HealthDashboard/1.0'})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def geocode_city(name: str) -> list[dict]:
    """Busca ciudades por nombre usando la API de geocodificación de Open-Meteo."""
    url = 'https://geocoding-api.open-meteo.com/v1/search?' + urlencode({
        'name': name, 'count': 5, 'language': 'es', 'format': 'json'
    })
    try:
        data = _fetch_url(url)
        results = []
        for r in data.get('results', []):
            results.append({
                'name':    r.get('name', ''),
                'country': r.get('country', ''),
                'region':  r.get('admin1', ''),
                'lat':     r.get('latitude'),
                'lon':     r.get('longitude'),
                'display': f"{r.get('name','')} — {r.get('admin1','')} ({r.get('country','')})",
            })
        return results
    except Exception as e:
        return [{'error': str(e)}]


def fetch_weather_range(date_from: str, date_to: str) -> int:
    """Descarga datos meteorológicos para un rango de fechas y los guarda en la BD."""
    city = get_city()
    url = 'https://archive-api.open-meteo.com/v1/archive?' + urlencode({
        'latitude':        city['lat'],
        'longitude':       city['lon'],
        'start_date':      date_from,
        'end_date':        date_to,
        'daily':           'temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,windspeed_10m_max,weathercode',
        'timezone':        'Europe/Madrid',
        'format':          'json',
    })
    data = _fetch_url(url)
    daily = data.get('daily', {})
    dates = daily.get('time', [])
    if not dates:
        return 0

    rows = []
    for i, d in enumerate(dates):
        rows.append((
            d,
            city['name'],
            _safe(daily.get('temperature_2m_max', []), i),
            _safe(daily.get('temperature_2m_min', []), i),
            _safe(daily.get('temperature_2m_mean', []), i),
            _safe(daily.get('precipitation_sum', []), i),
            _safe(daily.get('windspeed_10m_max', []), i),
            int(_safe(daily.get('weathercode', []), i) or 0),
        ))

    with get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO daily_weather
            (date_day, city, temp_max, temp_min, temp_mean, precipitation, windspeed_max, weathercode)
            VALUES (?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
    return len(rows)


def fetch_weather_today() -> dict | None:
    """Descarga el tiempo de hoy y los últimos 7 días si faltan."""
    today = datetime.now().strftime('%Y-%m-%d')
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    try:
        n = fetch_weather_range(week_ago, today)
        return get_weather_for_day(today)
    except Exception as e:
        return {'error': str(e)}


def get_weather_for_day(date_str: str) -> dict | None:
    """Lee el tiempo de un día desde la BD."""
    if not DB_FILE.exists():
        return None
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM daily_weather WHERE date_day=?", (date_str,)
        ).fetchone()
    if not r:
        return None
    code = int(r['weathercode'] or 0)
    desc, icon = WMO_CODES.get(code, ('', '🌡️'))
    return {
        'date':          r['date_day'],
        'city':          r['city'],
        'temp_max':      r['temp_max'],
        'temp_min':      r['temp_min'],
        'temp_mean':     r['temp_mean'],
        'precipitation': r['precipitation'],
        'windspeed_max': r['windspeed_max'],
        'weathercode':   code,
        'description':   desc,
        'icon':          icon,
    }


def get_weather_history(date_from: str, date_to: str) -> list[dict]:
    """Devuelve el histórico de tiempo para un rango."""
    if not DB_FILE.exists():
        return []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_weather WHERE date_day>=? AND date_day<=? ORDER BY date_day",
            (date_from, date_to)
        ).fetchall()
    result = []
    for r in rows:
        code = int(r['weathercode'] or 0)
        desc, icon = WMO_CODES.get(code, ('', '🌡️'))
        result.append({**dict(r), 'description': desc, 'icon': icon})
    return result


def _safe(lst, i):
    try: return lst[i]
    except: return None


def sync_missing_weather():
    """Sincroniza días con datos de salud pero sin datos meteorológicos."""
    if not DB_FILE.exists():
        return 0
    with get_conn() as conn:
        # Días con datos de salud sin datos de tiempo
        rows = conn.execute("""
            SELECT DISTINCT r.date_day FROM records r
            LEFT JOIN daily_weather w ON r.date_day = w.date_day
            WHERE w.date_day IS NULL AND r.date_day >= '2016-01-01'
            ORDER BY r.date_day
        """).fetchall()
    if not rows:
        return 0
    dates = [r['date_day'] for r in rows]
    # Descargar en chunks de 90 días (límite de la API de archivo)
    total = 0
    chunk = 90
    for i in range(0, len(dates), chunk):
        batch = dates[i:i+chunk]
        try:
            total += fetch_weather_range(batch[0], batch[-1])
        except Exception:
            pass
    return total
