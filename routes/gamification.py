"""routes/gamification.py — Rachas, logros y retos mensuales."""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required
from datetime import datetime

gami_bp = Blueprint('gami', __name__)

@gami_bp.route('/logros')
@login_required
def logros_page():
    return render_template('logros.html', today=datetime.now().strftime('%Y-%m'))

@gami_bp.route('/api/gamification/streaks')
@login_required
def api_streaks():
    from services.gamification import compute_streaks
    return jsonify(compute_streaks())

@gami_bp.route('/api/gamification/achievements')
@login_required
def api_achievements():
    from services.gamification import compute_achievements
    return jsonify(compute_achievements())

@gami_bp.route('/api/gamification/challenge')
@login_required
def api_challenge_get():
    from services.gamification import get_challenge_progress, get_monthly_challenge
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    progress = get_challenge_progress(month)
    if not progress:
        return jsonify({'month': month, 'challenges': [], 'progress': []})
    return jsonify({'month': month, 'progress': progress})

@gami_bp.route('/api/gamification/challenge', methods=['POST'])
@login_required
def api_challenge_save():
    from services.gamification import save_monthly_challenge
    data = request.get_json() or {}
    month = data.get('month', datetime.now().strftime('%Y-%m'))
    challenges = data.get('challenges', [])
    save_monthly_challenge(month, challenges)
    return jsonify({'ok': True})



@gami_bp.route('/api/gamification/stats')
@login_required
def api_stats():
    from services.gamification import get_global_stats
    return jsonify(get_global_stats())


@gami_bp.route('/api/gamification/challenge/<int:chal_id>', methods=['DELETE'])
@login_required
def api_challenge_delete(chal_id):
    from services.db import get_conn
    with get_conn() as conn:
        conn.execute("DELETE FROM challenges WHERE id=?", (chal_id,))
        conn.commit()
    return jsonify({'ok': True})


@gami_bp.route('/api/gamification/challenge/<int:chal_id>', methods=['PUT'])
@login_required
def api_challenge_update(chal_id):
    from services.db import get_conn
    d = request.get_json() or {}
    with get_conn() as conn:
        conn.execute(
            "UPDATE challenges SET label=?, target=?, unit=? WHERE id=?",
            (d.get('label',''), d.get('target',0), d.get('unit',''), chal_id)
        )
        conn.commit()
    return jsonify({'ok': True})
