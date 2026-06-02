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


# ── Logros personalizados ─────────────────────────────────────────────────────
@gami_bp.route('/api/gamification/custom-achievements', methods=['GET'])
@login_required
def api_custom_ach_get():
    from services.db import get_conn, DB_FILE
    if not DB_FILE.exists():
        return jsonify([])
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM custom_achievements ORDER BY unlocked DESC, created_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@gami_bp.route('/api/gamification/custom-achievements', methods=['POST'])
@login_required
def api_custom_ach_create():
    from services.db import get_conn
    d = request.get_json() or {}
    emoji       = d.get('emoji', '🎯').strip() or '🎯'
    label       = d.get('label', '').strip()
    desc        = d.get('desc', '').strip()
    target_type = d.get('target_type', 'manual')
    target_val  = d.get('target_val')
    if not label:
        return jsonify({'ok': False, 'error': 'Nombre obligatorio'}), 400
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO custom_achievements (emoji,label,desc,target_type,target_val) VALUES (?,?,?,?,?)",
            (emoji, label, desc, target_type, target_val)
        )
        conn.commit()
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({'ok': True, 'id': row_id})


@gami_bp.route('/api/gamification/custom-achievements/<int:ach_id>/unlock', methods=['POST'])
@login_required
def api_custom_ach_unlock(ach_id):
    from services.db import get_conn
    today = datetime.now().strftime('%Y-%m-%d')
    with get_conn() as conn:
        conn.execute(
            "UPDATE custom_achievements SET unlocked=1, unlock_date=? WHERE id=?",
            (today, ach_id)
        )
        conn.commit()
    return jsonify({'ok': True})


@gami_bp.route('/api/gamification/custom-achievements/<int:ach_id>', methods=['DELETE'])
@login_required
def api_custom_ach_delete(ach_id):
    from services.db import get_conn
    with get_conn() as conn:
        conn.execute("DELETE FROM custom_achievements WHERE id=?", (ach_id,))
        conn.commit()
    return jsonify({'ok': True})
