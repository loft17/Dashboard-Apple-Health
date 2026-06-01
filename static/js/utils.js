/* utils.js — compartido en todas las páginas */

function showToast(msg, type = '') {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = msg;
  toast.className = 'show ' + type;
  setTimeout(() => { toast.className = ''; }, 3500);
}

function startNavClock() {
  const el = document.getElementById('nav-date');
  if (!el) return;
  const tick = () => {
    const now = new Date();
    const date = now.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' });
    const time = now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    el.textContent = date + ' · ' + time;
  };
  tick();
  setInterval(tick, 1000);
}

document.addEventListener('DOMContentLoaded', () => {
  startNavClock();
});
