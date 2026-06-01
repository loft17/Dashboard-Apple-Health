"""routes/dashboard.py"""

from flask import Blueprint, jsonify, render_template, request
from datetime import datetime

from services.workout import list_workouts as _list_workouts, _WORKOUT_CACHE
from services.db import (
    get_recovery_score, get_vo2_trend,
    load_stats, get_today_summary, get_available_dates,
    debug_type_sample, get_heart_rate_day, get_hrv_day,
    get_sleep_day, get_active_energy_series,
    get_exercise_minutes, get_stand_hours, get_steps_for_day,
    get_distance_km, get_calories, get_extra_metrics, get_all_metrics
)

dashboard_bp = Blueprint('dashboard', __name__)


def _validate_date(date_str):
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return date_str
    except ValueError:
        return datetime.now().strftime('%Y-%m-%d')


@dashboard_bp.route('/dashboard')
def dashboard():
    stats     = load_stats()
    date_str  = _validate_date(request.args.get('date') or datetime.now().strftime('%Y-%m-%d'))
    daterange = get_available_dates()
    return render_template('dashboard.html', stats=stats, date=date_str, daterange=daterange)


@dashboard_bp.route('/api/day')
def api_day():
    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Formato inválido'}), 400

    import json

    steps    = get_steps_for_day(date_str)
    distance = get_distance_km(date_str)
    calories = get_calories(date_str)
    ex_min   = get_exercise_minutes(date_str)
    stand_h  = get_stand_hours(date_str)
    hr       = get_heart_rate_day(date_str)
    hrv      = get_hrv_day(date_str)
    sleep    = get_sleep_day(date_str)
    # Entrenamientos del día desde el servicio workout (lee el ZIP directamente)
    try:
        all_wk   = _list_workouts()
        workouts = [
            {**w, '_idx': i}
            for i, w in enumerate(all_wk)
            if w['date'] == date_str
        ]
    except Exception:
        workouts = []
    cal_series = get_active_energy_series(date_str)
    extra      = get_extra_metrics(date_str)
    all_metrics    = get_all_metrics(date_str)
    recovery_score = get_recovery_score(date_str)
    vo2_trend      = get_vo2_trend(date_str)

    return jsonify({
        'date':        date_str,
        'steps':       steps,
        'distance_km': round(distance, 2),
        'calories':    calories,
        'ex_min':      ex_min,
        'stand_h':     stand_h,
        'hr':          hr,
        'hrv':         hrv,
        'sleep':       sleep,
        'workouts':    workouts,
        'cal_series':  cal_series,
        'extra':       extra,
        'all_metrics':    all_metrics,
        'recovery_score': recovery_score,
        'vo2_trend':      vo2_trend,
    })


@dashboard_bp.route('/api/date-range')
def date_range():
    return jsonify(get_available_dates())


@dashboard_bp.route('/api/debug/distance')
def debug_distance():
    return jsonify({
        'walking': debug_type_sample('HKQuantityTypeIdentifierDistanceWalkingRunning'),
        'cycling': debug_type_sample('HKQuantityTypeIdentifierDistanceCycling'),
    })
