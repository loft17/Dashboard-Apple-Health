from flask import Blueprint, render_template, jsonify, request
from services.db import get_history, get_history_compare

history_bp = Blueprint('hist', __name__)

@history_bp.route('/historico')
def history_page():
    return render_template('history.html')

@history_bp.route('/api/history')
def api_history():
    metric = request.args.get('metric', 'pasos')
    period = request.args.get('period', 'month')
    data   = get_history_compare(metric, period)
    return jsonify(data)
