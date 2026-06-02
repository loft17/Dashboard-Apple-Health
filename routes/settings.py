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
    section = request.args.get('s', 'import')  # import | creds | obsidian
    return render_template('settings.html', stats=stats, today=today,
                           creds=creds, section=section)


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
