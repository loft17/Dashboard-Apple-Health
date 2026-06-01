"""
services/ecg.py
Lee los ficheros CSV de ECG del export.zip de Apple Health.
Formato: cabecera de metadatos + columna de voltaje en µV a 512 Hz.
"""

import csv
import io
import zipfile
from pathlib import Path
from datetime import datetime

UPLOAD_DIR = Path('uploads')
ZIP_PATH   = UPLOAD_DIR / 'export.zip'


def _parse_ecg_csv(text: str) -> dict | None:
    """
    Parsea un CSV de ECG de Apple Health.
    Cabecera: Nombre, Fecha de nacimiento, Fecha de registro,
              Clasificación, Síntomas, Versión del software,
              Dispositivo, Frecuencia de muestreo
    Luego: Derivación, Unidad
    Luego: valores de voltaje (uno por línea, coma decimal en es_ES).
    """
    lines = text.splitlines()
    meta  = {}
    samples: list[float] = []
    in_data = False
    unit = 'µV'
    derivation = 'I'

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('Derivaci'):
            parts = line.split(',', 1)
            if len(parts) == 2:
                derivation = parts[1].strip()
            in_data = True
            continue

        if line.startswith('Unidad'):
            parts = line.split(',', 1)
            if len(parts) == 2:
                unit = parts[1].strip()
            continue

        if not in_data:
            # Líneas de metadatos: clave,valor
            parts = line.split(',', 1)
            if len(parts) == 2:
                key = parts[0].strip().strip('"')
                val = parts[1].strip().strip('"')
                meta[key] = val
            continue

        # Valores de voltaje — formato es_ES usa coma decimal
        val_str = line.replace(',', '.')
        try:
            samples.append(float(val_str))
        except ValueError:
            pass

    if not samples:
        return None

    # Parsear fecha
    fecha_str = meta.get('Fecha de registro', '')
    fecha_dt  = None
    for fmt in ('%Y-%m-%d %H:%M:%S %z', '%Y-%m-%d %H:%M:%S'):
        try:
            fecha_dt = datetime.strptime(fecha_str, fmt)
            break
        except ValueError:
            pass

    # Frecuencia de muestreo
    freq_str = meta.get('Frecuencia de muestreo', '512 hercios')
    try:
        sample_rate = int(freq_str.split()[0])
    except (ValueError, IndexError):
        sample_rate = 512

    duration_s = round(len(samples) / sample_rate, 1)

    return {
        'meta': {
            'nombre':        meta.get('Nombre', ''),
            'fecha':         fecha_str,
            'fecha_iso':     fecha_dt.strftime('%Y-%m-%d') if fecha_dt else '',
            'hora':          fecha_dt.strftime('%H:%M') if fecha_dt else '',
            'clasificacion': meta.get('Clasificación', meta.get('Clasificacion', '')),
            'sintomas':      meta.get('Síntomas',      meta.get('Sintomas', '')) or 'Ninguno',
            'dispositivo':   meta.get('Dispositivo', ''),
            'software':      meta.get('Versión del software', ''),
            'sample_rate':   sample_rate,
            'derivacion':    derivation,
            'unit':          unit,
            'n_samples':     len(samples),
            'duration_s':    duration_s,
        },
        'samples': samples,
    }


def list_ecg_files() -> list[dict]:
    """Lista todos los ECG disponibles en el ZIP con sus metadatos."""
    if not ZIP_PATH.exists():
        return []

    results = []
    with zipfile.ZipFile(ZIP_PATH) as zf:
        ecg_names = sorted([
            n for n in zf.namelist()
            if 'electrocardiogram' in n.lower() and n.endswith('.csv')
        ])
        for name in ecg_names:
            with zf.open(name) as f:
                text = f.read(3000).decode('utf-8', errors='replace')
            parsed = _parse_ecg_csv(text)
            if parsed:
                results.append({
                    'file': name,
                    'filename': name.split('/')[-1],
                    **parsed['meta'],
                })

    return results


def get_ecg_for_date(date_str: str) -> list[dict]:
    """Devuelve la lista de ECGs de una fecha concreta con sus muestras."""
    if not ZIP_PATH.exists():
        return []

    results = []
    with zipfile.ZipFile(ZIP_PATH) as zf:
        ecg_names = sorted([
            n for n in zf.namelist()
            if 'electrocardiogram' in n.lower() and n.endswith('.csv')
        ])
        for name in ecg_names:
            with zf.open(name) as f:
                text = f.read().decode('utf-8', errors='replace')
            parsed = _parse_ecg_csv(text)
            if parsed and parsed['meta'].get('fecha_iso') == date_str:
                results.append({
                    'file': name,
                    'filename': name.split('/')[-1],
                    **parsed,
                })

    return results


def get_ecg_by_filename(filename: str) -> dict | None:
    """Devuelve un ECG completo por nombre de fichero."""
    if not ZIP_PATH.exists():
        return None

    with zipfile.ZipFile(ZIP_PATH) as zf:
        matches = [n for n in zf.namelist() if n.endswith(filename)]
        if not matches:
            return None
        with zf.open(matches[0]) as f:
            text = f.read().decode('utf-8', errors='replace')

    return _parse_ecg_csv(text)
