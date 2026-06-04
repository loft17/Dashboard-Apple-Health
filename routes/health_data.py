"""routes/health_data.py — página de todos los datos de salud de un día."""
from flask import Blueprint, render_template, request
from flask_login import login_required
from datetime import datetime

health_data_bp = Blueprint('health_data', __name__)

def _validate_date(d):
    try: datetime.strptime(d, '%Y-%m-%d'); return d
    except: return datetime.now().strftime('%Y-%m-%d')

@health_data_bp.route('/salud')
@health_data_bp.route('/salud/<date_param>')
@login_required
def health_data_page(date_param=None):
    from services.db import get_available_dates
    from services.db import get_steps_for_day, get_calories, get_sleep_day,                            get_heart_rate_day, get_hrv_day, get_stand_hours,                            get_exercise_minutes, get_distance_km
    from services.workout import list_workouts

    date_str  = _validate_date(date_param or request.args.get('date') or datetime.now().strftime('%Y-%m-%d'))
    daterange = get_available_dates()

    # Cargar datos del día para el resumen
    try:
        steps    = get_steps_for_day(date_str)
        calories = get_calories(date_str)
        sleep    = get_sleep_day(date_str)
        hr       = get_heart_rate_day(date_str)
        hrv      = get_hrv_day(date_str)
        stand    = get_stand_hours(date_str)
        ex_min   = get_exercise_minutes(date_str)
        distance = round(get_distance_km(date_str), 2)
        all_wk   = list_workouts()
        workouts = [w for w in all_wk if w.get('date') == date_str]
    except Exception as e:
        steps=calories=stand=ex_min=distance=0; sleep=hr=hrv={}; workouts=[]

    return render_template('health_data.html',
        date=date_str, daterange=daterange,
        steps=steps, calories=calories, sleep=sleep,
        hr=hr, hrv=hrv, stand=stand, ex_min=ex_min,
        distance=distance, workouts=workouts)

@health_data_bp.route('/api/salud/sections')
@login_required
def sections_html():
    """Devuelve el HTML de las secciones para cargar en /salud."""
    from flask import send_from_directory
    return render_template('_sections_partial.html')
