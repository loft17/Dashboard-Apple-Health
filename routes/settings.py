"""routes/settings.py — página de ajustes."""
from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required
from services.db import load_stats

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/ajustes')
@login_required
def settings_page():
    from datetime import datetime
    from routes.auth import load_creds
    stats  = load_stats()
    today  = datetime.now().strftime('%Y-%m-%d')
    creds  = load_creds()
    section = request.args.get('s', 'import')  # import | creds | obsidian | goals
    from services.db import get_user_goals
    goals = get_user_goals()
    return render_template('settings.html', stats=stats, today=today,
                           creds=creds, section=section, goals=goals)


@settings_bp.route('/api/settings/goals', methods=['POST'])
@login_required
def api_save_goals():
    from services.db import save_user_goals
    from routes.dashboard import invalidate_cache
    from routes.history import invalidate_hist_cache
    data = request.get_json() or {}
    goals = {}
    for key in ('steps_daily', 'calories_daily', 'exercise_min', 'stand_hours'):
        try:
            goals[key] = float(data[key])
        except (KeyError, ValueError):
            pass
    if goals:
        save_user_goals(goals)
        invalidate_cache()
        invalidate_hist_cache()
    return jsonify({'ok': True})


@settings_bp.route('/api/settings/obsidian-export')
@login_required
def obsidian_export():
    """Exporta el resumen de un día como nota Markdown para Obsidian."""
    from flask import request, Response
    from datetime import datetime
    from services.db import (get_steps_for_day, get_calories, get_sleep_day,
                              get_heart_rate_day, get_hrv_day, get_stand_hours,
                              get_exercise_minutes, get_distance_km,
                              get_available_dates)
    from services.workout import list_workouts

    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Fecha inválida'}), 400

    steps    = get_steps_for_day(date_str)
    calories = get_calories(date_str)
    distance = round(get_distance_km(date_str), 2)
    sleep    = get_sleep_day(date_str)
    hr       = get_heart_rate_day(date_str)
    hrv      = get_hrv_day(date_str)
    stand    = get_stand_hours(date_str)
    ex_min   = get_exercise_minutes(date_str)
    wks      = [w for w in list_workouts() if w.get('date') == date_str]

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    DIAS = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo']
    MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto',
             'septiembre','octubre','noviembre','diciembre']

    lines = [
        f'---',
        f'fecha: {date_str}',
        f'tipo: salud',
        f'tags: [salud, diario]',
        f'---',
        f'',
        f'# 🏥 Salud — {DIAS[dt.weekday()]} {dt.day} de {MESES[dt.month-1]} de {dt.year}',
        f'',
        f'## 🏃 Actividad',
        f'',
        f'| Métrica | Valor |',
        f'|---------|-------|',
        f'| Pasos | {steps:,} |'.replace(',', '.'),
        f'| Distancia | {distance} km |',
        f'| Calorías activas | {calories} kcal |',
        f'| Minutos ejercicio | {ex_min} min |',
        f'| Horas de pie | {stand} h |',
        f'',
        f'## ❤️ Corazón',
        f'',
        f'| Métrica | Valor |',
        f'|---------|-------|',
        f'| FC media | {hr.get("avg", "—") if hr else "—"} PPM |',
        f'| FC mín / máx | {hr.get("min", "—") if hr else "—"} / {hr.get("max", "—") if hr else "—"} PPM |',
        f'| HRV | {round(hrv.get("avg", 0), 1) if hrv else "—"} ms |',
        f'',
        f'## 🌙 Sueño',
        f'',
        f'| Métrica | Valor |',
        f'|---------|-------|',
        f'| Total | {sleep.get("total_str", "—") if sleep else "—"} |',
        f'| Profundo | {round(sleep.get("deep_min", 0) or 0)} min |' if sleep else '| Profundo | — |',
        f'| REM | {round(sleep.get("rem_min", 0) or 0)} min |' if sleep else '| REM | — |',
        f'',
    ]

    if wks:
        lines += ['## 🏋️ Entrenamientos', '']
        for w in wks:
            lines.append(f'- **{w.get("type","Entrenamiento")}** — {w.get("distance_km","—")} km · {w.get("duration_str","—")} · {w.get("kcal","—")} kcal')
        lines.append('')

    lines += [
        f'## 📝 Notas',
        f'',
        f'<!-- Escribe aquí tus notas del día -->',
        f'',
        f'---',
        f'*Generado por Health Dashboard*',
    ]

    md = '\n'.join(lines)
    filename = f'salud_{date_str}.md'
    return Response(
        md,
        mimetype='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@settings_bp.route('/api/settings/export-ai')
@login_required
def export_ai():
    """Exporta datos de los últimos N días en JSON estructurado para análisis con IA."""
    from services.db import get_conn, DB_FILE, get_history
    from services.workout import list_workouts
    from datetime import datetime, timedelta
    import json as _json

    days = int(request.args.get('days', 7))
    if days not in (7, 14, 30):
        days = 7

    today     = datetime.now()
    date_from = (today - timedelta(days=days)).strftime('%Y-%m-%d')
    date_to   = today.strftime('%Y-%m-%d')

    metrics = ['pasos','distancia','calorias','fc','fc_reposo','hrv','sueno','peso','pisos','resp','spo2']
    data_export = {
        'periodo': {'dias': days, 'desde': date_from, 'hasta': date_to},
        'metricas_diarias': {},
        'entrenamientos': [],
        'resumen': {},
    }

    # Métricas diarias
    for m in metrics:
        try:
            rows = get_history(m, 'all' if days >= 30 else 'month')
            # Filtrar solo el rango
            filtered = [r for r in rows if r.get('date','') >= date_from]
            data_export['metricas_diarias'][m] = filtered
        except Exception:
            pass

    # Entrenamientos del período
    wks = [w for w in list_workouts() if date_from <= (w.get('date') or '') <= date_to]
    from services.workout import WORKOUT_NAMES
    for w in wks:
        data_export['entrenamientos'].append({
            'fecha':    w.get('date'),
            'tipo':     WORKOUT_NAMES.get(w.get('type',''), (w.get('type',''),))[0],
            'km':       w.get('distance_km'),
            'minutos':  w.get('duration_min'),
            'kcal':     w.get('kcal'),
        })

    # Calcular resumen estadístico
    steps_vals = [r['v'] for r in data_export['metricas_diarias'].get('pasos',[]) if r.get('v')]
    sleep_vals = [r['v'] for r in data_export['metricas_diarias'].get('sueno',[]) if r.get('v')]
    fc_vals    = [r['v'] for r in data_export['metricas_diarias'].get('fc',[]) if r.get('v')]
    hrv_vals   = [r['v'] for r in data_export['metricas_diarias'].get('hrv',[]) if r.get('v')]

    def _stats(vals):
        if not vals: return {}
        return {
            'media': round(sum(vals)/len(vals), 1),
            'min':   round(min(vals), 1),
            'max':   round(max(vals), 1),
            'n':     len(vals),
        }

    data_export['resumen'] = {
        'pasos':   _stats(steps_vals),
        'sueno_h': _stats(sleep_vals),
        'fc':      _stats(fc_vals),
        'hrv':     _stats(hrv_vals),
        'entrenamientos': len(wks),
    }

    # Añadir instrucciones para la IA
    data_export['_instrucciones'] = (
        f"Estos son mis datos de salud de Apple Health de los últimos {days} días "
        f"(del {date_from} al {date_to}). Por favor analiza mis tendencias, "
        f"identifica patrones, y dame recomendaciones personalizadas basadas en estos datos."
    )

    output = _json.dumps(data_export, ensure_ascii=False, indent=2)
    filename = f'health_export_{days}d_{date_to}.json'
    from flask import Response
    return Response(
        output,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
