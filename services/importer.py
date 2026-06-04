"""
services/importer.py
Parseo del export.zip de Apple Health.
Usa SQLite via services.db — nunca escribe JSON directamente.
"""

import queue
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from services.db import init_db, insert_records, rebuild_stats

progress_queue: queue.Queue = queue.Queue()
import_state: dict = {
    'running': False,
    'done':    False,
    'error':   None,
    'summary': None,
}

BATCH_SIZE = 5_000   # registros por INSERT


def _push(event: str, data: dict) -> None:
    progress_queue.put({'event': event, 'data': data})


def process_zip(zip_path: Path) -> None:
    import_state.update({'running': True, 'done': False, 'error': None, 'summary': None})

    try:
        # Fase 1 — Abrir ZIP ─────────────────────────────────────────────────
        _push('phase', {'phase': 1, 'total': 5, 'label': 'Abriendo export.zip…'})
        time.sleep(0.2)

        if not zip_path.exists():
            raise FileNotFoundError('No se encontró export.zip')

        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            # Buscar XML principal — compatible con español (exportación.xml) e inglés (export.xml)
            xml_candidates = [n for n in names if n.endswith('.xml') and
                              any(kw in n.lower() for kw in ('export', 'exportaci'))]
            if not xml_candidates:
                # Fallback: cualquier XML en la raíz
                xml_candidates = [n for n in names if n.endswith('.xml') and '/' not in n.rstrip('/').lstrip('/').replace(n.split('/')[0]+'/', '')]
            if not xml_candidates:
                xml_candidates = [n for n in names if n.endswith('.xml')]
            if not xml_candidates:
                raise ValueError('No se encontró ningún XML de Apple Health dentro del ZIP')

            xml_name = xml_candidates[0]
            zip_mb = round(zip_path.stat().st_size / 1024 / 1024, 1)
            _push('log', {'msg': f'ZIP abierto · {zip_mb} MB · {len(names)} archivos'})
            _push('log', {'msg': f'XML encontrado: {xml_name}'})

            # Fase 2 — Contar nodos ──────────────────────────────────────────
            _push('phase', {'phase': 2, 'total': 5, 'label': 'Analizando estructura del XML…'})
            total = 0
            with zf.open(xml_name) as f:
                for _, elem in ET.iterparse(f, events=('end',)):
                    if elem.tag == 'Record':
                        total += 1
                    elem.clear()
            _push('log', {'msg': f'Total de registros en el XML: {total:,}'})

            # Fase 3 — Inicializar BD ────────────────────────────────────────
            _push('phase', {'phase': 3, 'total': 5, 'label': 'Preparando base de datos…'})
            init_db()
            _push('log', {'msg': 'SQLite inicializado correctamente'})

            # Fase 4 — Parsear e insertar en lotes ───────────────────────────
            _push('phase', {'phase': 4, 'total': 5, 'label': f'Importando {total:,} registros…'})

            count = 0
            total_inserted = 0
            total_ignored  = 0
            batch: list[dict] = []
            every = max(1, total // 200)

            with zf.open(xml_name) as f:
                for _, elem in ET.iterparse(f, events=('end',)):
                    if elem.tag == 'Record':
                        batch.append({
                            'type':       elem.get('type', ''),
                            'value':      elem.get('value'),   # numérico o string de categoría
                            'unit':       elem.get('unit', ''),
                            'startDate':  elem.get('startDate', ''),
                            'endDate':    elem.get('endDate', ''),
                            'sourceName': elem.get('sourceName', ''),
                        })
                        count += 1

                        if len(batch) >= BATCH_SIZE:
                            ins, ign = insert_records(batch)
                            total_inserted += ins
                            total_ignored  += ign
                            batch = []

                        if count % every == 0:
                            pct = round(count / total * 100)
                            _push('progress', {
                                'pct': pct, 'count': count, 'total': total,
                                'msg': f'Procesados {count:,} · {total_inserted:,} nuevos · {total_ignored:,} dup.'
                            })
                    elem.clear()

            # Lote final
            if batch:
                ins, ign = insert_records(batch)
                total_inserted += ins
                total_ignored  += ign

            _push('log', {'msg': f'Insertados: {total_inserted:,} · Duplicados omitidos: {total_ignored:,}'})

            # Fase 5 — Recalcular stats ──────────────────────────────────────
            _push('phase', {'phase': 5, 'total': 5, 'label': 'Recalculando estadísticas…'})
            stats = rebuild_stats()

            _push('log', {'msg': f'BD actualizada · {stats["total_records"]:,} registros totales'})
            _push('log', {'msg': f'Métricas distintas: {stats["metrics_count"]:,}'})
            _push('log', {'msg': f'Historial: {stats["date_range_days"]} días ({stats["date_min"]} → {stats["date_max"]})'})

            summary = {
                'new':      total_inserted,
                'duplicates': total_ignored,
                'total':    stats['total_records'],
                'metrics':  stats['metrics_count'],
                'days':     stats['date_range_days'],
            }
            import_state['summary'] = summary
            _push('done', summary)
            # Invalidar caché de entrenamientos
            try:
                from services.workout import invalidate_workout_cache
                invalidate_workout_cache()
            except Exception:
                pass

    except Exception as e:
        import_state['error'] = str(e)
        _push('error', {'msg': str(e)})
    finally:
        import_state['running'] = False
        import_state['done']    = True
