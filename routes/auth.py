"""routes/auth.py — autenticación con credenciales persistentes."""

import os, hashlib, json
from pathlib import Path
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

auth_bp      = Blueprint('auth', __name__)
login_manager = LoginManager()

CREDS_FILE = Path('data/credentials.json')

# ── Credenciales ──────────────────────────────────────────────────────────────

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def load_creds() -> dict:
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text())
        except Exception:
            pass
    # Primera vez: admin/admin, fuerza cambio
    return {'username': 'admin', 'password_hash': _hash('admin'), 'must_change': True}

def save_creds(username: str, password: str, must_change: bool = False,
               display_name: str = '', email: str = '', birth_year: str = ''):
    CREDS_FILE.parent.mkdir(exist_ok=True)
    # Preservar campos extra existentes
    existing = {}
    if CREDS_FILE.exists():
        try: existing = json.loads(CREDS_FILE.read_text())
        except: pass
    CREDS_FILE.write_text(json.dumps({
        'username':      username,
        'password_hash': _hash(password),
        'must_change':   must_change,
        'display_name':  display_name or existing.get('display_name', ''),
        'email':         email or existing.get('email', ''),
        'birth_year':    birth_year or existing.get('birth_year', ''),
    }))

def save_profile(display_name: str = '', email: str = '', birth_year: str = ''):
    """Actualizar datos de perfil sin tocar la contraseña."""
    CREDS_FILE.parent.mkdir(exist_ok=True)
    existing = {}
    if CREDS_FILE.exists():
        try: existing = json.loads(CREDS_FILE.read_text())
        except: pass
    existing['display_name'] = display_name
    existing['email']        = email
    existing['birth_year']   = birth_year
    CREDS_FILE.write_text(json.dumps(existing))

def check_creds(username: str, password: str) -> bool:
    c = load_creds()
    return username == c['username'] and _hash(password) == c['password_hash']

def must_change_password() -> bool:
    return load_creds().get('must_change', False)


# ── User model ────────────────────────────────────────────────────────────────
class User(UserMixin):
    id = 'admin'

_USER_OBJ = User()

@login_manager.user_loader
def load_user(user_id):
    return _USER_OBJ if user_id == 'admin' else None

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for('auth.login', next=request.path))


# ── Rutas ─────────────────────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        if check_creds(u, p):
            login_user(_USER_OBJ, remember=True)
            if must_change_password():
                return redirect(url_for('auth.force_change'))
            return redirect(request.args.get('next') or '/')
        flash('Usuario o contraseña incorrectos')
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def force_change():
    """Pantalla de cambio obligatorio (primera vez o si must_change=True)."""
    if request.method == 'POST':
        new_user = request.form.get('username', '').strip()
        new_pass = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if len(new_user) < 3:
            flash('El usuario debe tener al menos 3 caracteres')
        elif len(new_pass) < 6:
            flash('La contraseña debe tener al menos 6 caracteres')
        elif new_pass != confirm:
            flash('Las contraseñas no coinciden')
        else:
            save_creds(new_user, new_pass, must_change=False)
            flash('Credenciales actualizadas correctamente', 'ok')
            return redirect('/')
    return render_template('change_password.html', forced=True)


@auth_bp.route('/api/auth/change-password', methods=['POST'])
@login_required
def api_change_password():
    """Cambio de credenciales desde ajustes (AJAX)."""
    data        = request.get_json() or {}
    current_pw  = data.get('current', '')
    new_user    = data.get('username', '').strip()
    new_pass    = data.get('password', '')
    confirm     = data.get('confirm', '')

    creds = load_creds()
    if _hash(current_pw) != creds['password_hash']:
        return jsonify({'ok': False, 'error': 'Contraseña actual incorrecta'})
    if len(new_user) < 3:
        return jsonify({'ok': False, 'error': 'Usuario demasiado corto (mín. 3 caracteres)'})
    if len(new_pass) < 6:
        return jsonify({'ok': False, 'error': 'Contraseña demasiado corta (mín. 6 caracteres)'})
    if new_pass != confirm:
        return jsonify({'ok': False, 'error': 'Las contraseñas no coinciden'})

    save_creds(new_user, new_pass, must_change=False)
    return jsonify({'ok': True})


@auth_bp.route('/api/auth/save-profile', methods=['POST'])
@login_required
def api_save_profile():
    from routes.auth import save_profile
    data = request.get_json() or {}
    save_profile(
        display_name = data.get('display_name', '').strip(),
        email        = data.get('email', '').strip(),
        birth_year   = data.get('birth_year', '').strip(),
    )
    return jsonify({'ok': True})
