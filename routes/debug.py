"""routes/debug.py — endpoints de diagnóstico temporales"""
from flask import Blueprint, jsonify, request
from services.db import get_conn, DB_FILE

debug_bp = Blueprint('debug', __name__)

@debug_bp.route('/api/debug/types')
def all_types():
    """Lista todos los tipos distintos con su conteo."""
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT type, COUNT(*) as n, MAX(unit) as unit '
            'FROM records GROUP BY type ORDER BY n DESC'
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@debug_bp.route('/api/debug/sample')
def sample():
    """Muestra 5 registros de un tipo concreto."""
    t = request.args.get('type', '')
    date = request.args.get('date', '')
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    with get_conn() as conn:
        if date:
            rows = conn.execute(
                'SELECT * FROM records WHERE type=? AND date_day=? LIMIT 10',
                (t, date)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM records WHERE type=? ORDER BY start_date DESC LIMIT 5',
                (t,)
            ).fetchall()
    return jsonify([dict(r) for r in rows])

@debug_bp.route('/api/debug/stand-raw')
def stand_raw():
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT value, unit, start_date, end_date FROM records "
            "WHERE type='HKCategoryTypeIdentifierAppleStandHour' "
            "ORDER BY start_date DESC LIMIT 10"
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@debug_bp.route('/api/debug/xml-sleep')
def xml_sleep():
    """Lee directamente el export.xml para ver cómo viene el sueño."""
    import zipfile, xml.etree.ElementTree as ET
    from pathlib import Path
    zip_path = Path('uploads/export.zip')
    if not zip_path.exists():
        return jsonify({'error': 'No hay export.zip en uploads/'})
    results = []
    with zipfile.ZipFile(zip_path) as zf:
        xml_name = next((n for n in zf.namelist() if n.endswith('export.xml')), None)
        if not xml_name:
            return jsonify({'error': 'No export.xml'})
        with zf.open(xml_name) as f:
            count = 0
            for _, elem in ET.iterparse(f, events=('end',)):
                if elem.tag == 'Record' and elem.get('type') == 'HKCategoryTypeIdentifierSleepAnalysis':
                    results.append({k: elem.get(k) for k in elem.keys()})
                    count += 1
                    if count >= 5:
                        break
                elem.clear()
    return jsonify(results)

@debug_bp.route('/api/debug/ecg-raw')
def ecg_raw():
    """Explora la estructura del ECG en el export.zip."""
    import zipfile
    import xml.etree.ElementTree as ET
    from pathlib import Path

    zip_path = Path('uploads/export.zip')
    if not zip_path.exists():
        return jsonify({'error': 'No hay export.zip en uploads/'})

    result = {'ecg_files': [], 'ecg_xml_sample': None, 'zip_ecg_names': []}

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # Buscar ficheros relacionados con ECG
        ecg_names = [n for n in names if 'ecg' in n.lower() or 'electrocardiogram' in n.lower()]
        result['zip_ecg_names'] = ecg_names[:20]

        # Buscar en el export.xml registros de tipo ECG
        xml_name = next((n for n in names if n.endswith('export.xml')), None)
        if xml_name:
            samples = []
            with zf.open(xml_name) as f:
                for _, elem in ET.iterparse(f, events=('end',)):
                    if elem.tag in ('Electrocardiogram', 'ECG') or \
                       (elem.tag == 'Record' and 'ECG' in elem.get('type','').upper()):
                        attribs = dict(elem.attrib)
                        # Buscar hijos
                        children = [{'tag': c.tag, 'attrib': dict(c.attrib),
                                     'text_preview': (c.text or '')[:100]}
                                    for c in elem]
                        samples.append({'attrib': attribs, 'children': children[:5]})
                        if len(samples) >= 3:
                            break
                    elem.clear()
            result['ecg_xml_sample'] = samples

        # Si hay ficheros CSV de ECG, leer primeras líneas
        for ecg_file in ecg_names[:3]:
            try:
                with zf.open(ecg_file) as f:
                    content = f.read(2000).decode('utf-8', errors='replace')
                result['ecg_files'].append({
                    'name': ecg_file,
                    'preview': content
                })
            except Exception as ex:
                result['ecg_files'].append({'name': ecg_file, 'error': str(ex)})

    return jsonify(result)

@debug_bp.route('/api/debug/workouts-raw')
def workouts_raw():
    """Explora la estructura de los entrenamientos en el export.zip."""
    import zipfile, xml.etree.ElementTree as ET
    from pathlib import Path

    zip_path = Path('uploads/export.zip')
    if not zip_path.exists():
        return jsonify({'error': 'No hay export.zip'})

    result = {'workout_samples': [], 'route_files': [], 'workout_route_sample': None}

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # Buscar ficheros de ruta GPX/workout-routes
        route_files = [n for n in names if 'route' in n.lower() or 'gpx' in n.lower()]
        result['route_files'] = route_files[:10]

        # Muestra de fichero de ruta si existe
        if route_files:
            with zf.open(route_files[0]) as f:
                result['workout_route_sample'] = f.read(3000).decode('utf-8', errors='replace')

        # Buscar Workout en el XML principal
        xml_name = next((n for n in names if n.endswith('export.xml')), None)
        if xml_name:
            samples = []
            with zf.open(xml_name) as f:
                for _, elem in ET.iterparse(f, events=('end',)):
                    if elem.tag == 'Workout' and len(samples) < 3:
                        attribs = dict(elem.attrib)
                        children = []
                        for c in elem:
                            children.append({
                                'tag': c.tag,
                                'attrib': dict(c.attrib),
                                'children': [{'tag':cc.tag,'attrib':dict(cc.attrib)} for cc in c][:3]
                            })
                        samples.append({'attrib': attribs, 'children': children[:10]})
                    elem.clear()
            result['workout_samples'] = samples

    return jsonify(result)

@debug_bp.route('/api/debug/gpx-sample')
def gpx_sample():
    """Lee el contenido completo del primer fichero GPX."""
    import zipfile
    from pathlib import Path
    zip_path = Path('uploads/export.zip')
    if not zip_path.exists():
        return jsonify({'error': 'No hay export.zip'})
    with zipfile.ZipFile(zip_path) as zf:
        gpx_files = sorted([n for n in zf.namelist() if n.endswith('.gpx')])
        if not gpx_files:
            return jsonify({'error': 'No hay ficheros GPX'})
        results = []
        for gpx in gpx_files[:2]:
            with zf.open(gpx) as f:
                content = f.read(4000).decode('utf-8', errors='replace')
            results.append({'file': gpx, 'content': content})
    return jsonify(results)

@debug_bp.route('/api/debug/workout-list-sample')
def workout_list_sample():
    """Muestra los primeros 3 entrenamientos parseados."""
    from services.workout import list_workouts
    ws = list_workouts()
    return jsonify({'total': len(ws), 'sample': ws[:3]})

@debug_bp.route('/api/debug/workout-stats-raw')
def workout_stats_raw():
    """Muestra las estadísticas completas del primer Workout."""
    import zipfile, xml.etree.ElementTree as ET
    from pathlib import Path
    zip_path = Path('uploads/export.zip')
    if not zip_path.exists():
        return jsonify({'error': 'No hay export.zip'})
    with zipfile.ZipFile(zip_path) as zf:
        xml_name = next((n for n in zf.namelist() if n.endswith('export.xml')), None)
        samples = []
        with zf.open(xml_name) as f:
            for _, elem in ET.iterparse(f, events=('end',)):
                if elem.tag == 'Workout' and len(samples) < 2:
                    children = []
                    for c in elem:
                        children.append({'tag': c.tag, 'attrib': dict(c.attrib)})
                    samples.append({'attrib': dict(elem.attrib), 'children': children})
                    elem.clear()
                else:
                    elem.clear()
    return jsonify(samples)

@debug_bp.route('/api/debug/workout-stats-raw2')
def workout_stats_raw2():
    """Lee el XML sin limpiar elementos para ver atributos reales."""
    import zipfile, xml.etree.ElementTree as ET
    from pathlib import Path
    zip_path = Path('uploads/export.zip')
    if not zip_path.exists():
        return jsonify({'error': 'No hay export.zip'})
    
    with zipfile.ZipFile(zip_path) as zf:
        xml_name = next((n for n in zf.namelist() if n.endswith('export.xml')), None)
        # Leer trozo del XML para encontrar un Workout completo
        with zf.open(xml_name) as f:
            content = b''
            in_workout = False
            workouts_found = 0
            for line in f:
                if b'<Workout ' in line:
                    in_workout = True
                    content = line
                elif in_workout:
                    content += line
                    if b'</Workout>' in line:
                        workouts_found += 1
                        if workouts_found >= 3:
                            break
                        in_workout = False
                        content = b''
            
            # Parsear el último workout completo encontrado
            if content and b'</Workout>' in content:
                try:
                    # Envolver en root para parsear
                    xml_str = b'<root>' + content + b'</root>'
                    root = ET.fromstring(xml_str)
                    result = []
                    for w in root.findall('Workout'):
                        children = [{'tag': c.tag, 'attrib': dict(c.attrib)} for c in w]
                        result.append({'attrib': dict(w.attrib), 'children': children})
                    return jsonify(result)
                except Exception as e:
                    return jsonify({'error': str(e), 'content_preview': content[:500].decode('utf-8','replace')})
    
    return jsonify({'error': 'no workout found'})

@debug_bp.route('/api/debug/sleep-segments')
def sleep_segments():
    from services.db import get_sleep_day
    from flask import request as req
    from datetime import datetime, timedelta
    date = req.args.get('date') or (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    data = get_sleep_day(date)
    # Mostrar primeros y últimos 3 segmentos
    segs = data.get('segments', [])
    sample = segs[:3] + (segs[-3:] if len(segs) > 3 else [])
    return jsonify({'date': date, 'total_str': data.get('total_str'), 
                    'n_segments': len(segs), 'sample': sample})

@debug_bp.route('/api/debug/sleep-raw')
def sleep_raw():
    """Muestra segmentos crudos de sueño de los últimos días con datos."""
    from services.db import get_conn, DB_FILE
    from flask import request as req
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    date = req.args.get('date', '')
    with get_conn() as conn:
        if date:
            rows = conn.execute(
                'SELECT value_str, value, start_date, end_date, source_name FROM records '
                'WHERE type=? AND date_day=? ORDER BY start_date LIMIT 20',
                ('HKCategoryTypeIdentifierSleepAnalysis', date)
            ).fetchall()
        else:
            # Fechas con sueño
            dates = conn.execute(
                'SELECT DISTINCT date_day FROM records '
                'WHERE type=? ORDER BY date_day DESC LIMIT 10',
                ('HKCategoryTypeIdentifierSleepAnalysis',)
            ).fetchall()
            return jsonify([r['date_day'] for r in dates])
    return jsonify([dict(r) for r in rows])

@debug_bp.route('/api/debug/history-coverage')
def history_coverage():
    """Muestra cobertura de datos históricos por tipo de métrica."""
    from services.db import get_conn, DB_FILE
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    
    METRICS = {
        'Pasos':        'HKQuantityTypeIdentifierStepCount',
        'Calorías act': 'HKQuantityTypeIdentifierActiveEnergyBurned',
        'Distancia':    'HKQuantityTypeIdentifierDistanceWalkingRunning',
        'FC':           'HKQuantityTypeIdentifierHeartRate',
        'FC reposo':    'HKQuantityTypeIdentifierRestingHeartRate',
        'HRV':          'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
        'SpO2':         'HKQuantityTypeIdentifierOxygenSaturation',
        'VO2':          'HKQuantityTypeIdentifierVO2Max',
        'Sueño':        'HKCategoryTypeIdentifierSleepAnalysis',
        'Peso':         'HKQuantityTypeIdentifierBodyMass',
        'Resp':         'HKQuantityTypeIdentifierRespiratoryRate',
        'Pasos cadencia':'HKQuantityTypeIdentifierStepCount',
        'Pisos':        'HKQuantityTypeIdentifierFlightsClimbed',
        'Esfuerzo':     'HKQuantityTypeIdentifierPhysicalEffort',
        'Luz diurna':   'HKQuantityTypeIdentifierTimeInDaylight',
    }
    
    result = {}
    with get_conn() as conn:
        for name, hk_type in METRICS.items():
            row = conn.execute(
                'SELECT MIN(date_day) as first, MAX(date_day) as last, COUNT(DISTINCT date_day) as days '
                'FROM records WHERE type=?', (hk_type,)
            ).fetchone()
            result[name] = {
                'first': row['first'], 'last': row['last'], 'days': row['days']
            }
    return jsonify(result)

@debug_bp.route('/api/debug/hist-test')
def hist_test():
    from services.db import get_history
    return jsonify({
        'distancia_month': get_history('distancia','month')[:5],
        'sueno_month':     get_history('sueno','month')[:5],
        'peso_month':      get_history('peso','month')[:5],
        'peso_all':        get_history('peso','all')[:5],
    })

@debug_bp.route('/api/debug/sleep-hist')
def sleep_hist():
    from services.db import get_conn, DB_FILE
    from flask import request as req
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    with get_conn() as conn:
        # Ver qué agrupa la nueva query de sueño
        rows = conn.execute("""
            SELECT strftime('%Y-%m-%d', end_date) as g,
                   SUM(CAST((julianday(end_date) - julianday(start_date)) * 1440 AS INTEGER)) as v
            FROM records
            WHERE type = 'HKCategoryTypeIdentifierSleepAnalysis'
              AND date_day >= '2026-05-01'
              AND value_str NOT LIKE '%InBed%'
              AND value_str NOT LIKE '%Awake%'
            GROUP BY g ORDER BY g DESC LIMIT 10
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@debug_bp.route('/api/debug/sleep-hist2')
def sleep_hist2():
    """Debug sueño — ahora usa get_history para mostrar lo mismo que ve el usuario."""
    from services.db import get_history, get_conn, DB_FILE
    from datetime import datetime, timedelta
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    
    result_month = get_history('sueno', 'month')
    result_week  = get_history('sueno', 'week')
    
    # También muestra raw para diagnóstico
    now = datetime.now()
    date_from = (now - timedelta(days=31)).strftime('%Y-%m-%d')
    with get_conn() as conn:
        sample = conn.execute(
            'SELECT value_str, substr(start_date,1,19) as s, substr(end_date,1,19) as e, date_day '
            "FROM records WHERE type='HKCategoryTypeIdentifierSleepAnalysis' "
            'ORDER BY start_date DESC LIMIT 5'
        ).fetchall()
    
    # Calcular un ejemplo manualmente
    from datetime import datetime as _dt
    examples = []
    for r in sample:
        try:
            s = _dt.strptime(r['s'], '%Y-%m-%d %H:%M:%S')
            e = _dt.strptime(r['e'], '%Y-%m-%d %H:%M:%S')
            mins = (e-s).total_seconds()/60
            examples.append({'date': r['date_day'], 'phase': r['value_str'][-20:], 'mins': round(mins,1)})
        except Exception as ex:
            examples.append({'error': str(ex)})
    
    return jsonify({
        'history_week':  result_week,
        'history_month': result_month,
        'calculation_examples': examples
    })
