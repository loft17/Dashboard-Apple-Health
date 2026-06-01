/* static/js/upload.js — lógica de subida de ZIP y progreso SSE */

/* ── Upload ──────────────────────────────────────────────────────────────────*/

const uploadZone  = document.getElementById('upload-zone');
const fileInput   = document.getElementById('file-input');
const progressWrap = document.getElementById('progress-wrap');

function toggleUpload() {
  uploadZone.classList.toggle('visible');
  if (uploadZone.classList.contains('visible'))
    uploadZone.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

uploadZone.addEventListener('dragover', e => {
  e.preventDefault(); uploadZone.classList.add('drag-over');
});
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault(); uploadZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

function handleFile(file) {
  if (!file.name.endsWith('.zip')) { showToast('Solo se aceptan archivos .zip', 'error'); return; }

  uploadZone.classList.remove('visible');
  progressWrap.classList.add('visible');
  progressWrap.scrollIntoView({ behavior: 'smooth', block: 'center' });

  const formData = new FormData();
  formData.append('file', file);
  const xhr = new XMLHttpRequest();

  xhr.upload.addEventListener('progress', e => {
    if (e.lengthComputable) {
      const pct = Math.round(e.loaded / e.total * 100);
      setBar(pct, `Subiendo… ${pct}%`, `${(e.loaded/1024/1024).toFixed(1)} / ${(e.total/1024/1024).toFixed(1)} MB`);
    }
  });

  xhr.addEventListener('load', () => {
    if (xhr.status === 200) {
      addLog('Archivo recibido · iniciando procesado', 'highlight');
      setBar(100, 'Procesando…', '');
      startSSE();
    } else {
      addLog('Error: ' + JSON.parse(xhr.responseText).error, 'error-txt');
      stopDot('error');
      showToast('Error al subir el archivo', 'error');
    }
  });

  xhr.addEventListener('error', () => { addLog('Error de red', 'error-txt'); stopDot('error'); });
  xhr.open('POST', '/upload');
  xhr.send(formData);
}

/* ── SSE ─────────────────────────────────────────────────────────────────────*/

let es = null;

function startSSE() {
  if (es) es.close();
  es = new EventSource('/progress-stream');

  es.onmessage = e => {
    const d = JSON.parse(e.data);
    switch (d.event) {
      case 'connected': addLog('Conectado al stream de progreso'); break;
      case 'phase':
        setPhase(d.phase, d.total, d.label);
        setBar(0, d.label, '');
        addLog(`── Fase ${d.phase}/${d.total}: ${d.label}`, 'highlight');
        break;
      case 'progress':
        setBar(d.pct, document.getElementById('progress-label').textContent, d.msg);
        document.getElementById('progress-pct').textContent = d.pct + '%';
        document.getElementById('progress-msg').textContent = d.msg;
        break;
      case 'log': addLog(d.msg); break;
      case 'done':
        setBar(100, 'Importación completada ✓', '');
        document.getElementById('progress-pct').textContent = '100%';
        addLog(`Completado · ${d.new.toLocaleString()} registros nuevos`, 'success');
        showSummary(d); stopDot('success');
        showToast('Importación completada', 'success');
        es.close();
        setTimeout(() => location.reload(), 2000);
        break;
      case 'error':
        addLog('ERROR: ' + d.msg, 'error-txt');
        stopDot('error');
        showToast('Error durante la importación', 'error');
        es.close();
        break;
    }
  };
}

/* ── Helpers UI ──────────────────────────────────────────────────────────────*/

function setBar(pct, label, msg) {
  document.getElementById('progress-fill').style.width = pct + '%';
  if (label) document.getElementById('progress-label').textContent = label;
  if (msg !== undefined) document.getElementById('progress-msg').textContent = msg;
}

function setPhase(phase, total, label) {
  for (let i = 1; i < phase; i++) {
    document.getElementById('ph-' + i)?.classList.replace('active', 'done') ||
    document.getElementById('ph-' + i)?.classList.add('done');
    if (i < total) document.getElementById('pl-' + i)?.classList.add('done');
  }
  const dot = document.getElementById('ph-' + phase);
  if (dot) { dot.classList.add('active'); dot.classList.remove('done'); }
  document.getElementById('progress-label').textContent = label;
}

function addLog(msg, cls = '') {
  const container = document.getElementById('log-entries');
  const ts = new Date().toTimeString().slice(0, 8);
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span class="log-time">${ts}</span><span class="log-text ${cls}">${msg}</span>`;
  container.appendChild(entry);
  container.scrollTop = container.scrollHeight;
}

function stopDot(state) {
  const dot = document.getElementById('log-dot');
  dot.className = state;
  const title = dot.nextElementSibling;
  if (state === 'success') title.textContent = 'log · importación completada';
  if (state === 'error')   title.textContent = 'log · error en la importación';
}

function showSummary(d) {
  document.getElementById('s-new').textContent     = (d.new     || 0).toLocaleString();
  document.getElementById('s-total').textContent   = (d.total   || 0).toLocaleString();
  document.getElementById('s-metrics').textContent = (d.metrics || 0).toLocaleString();
  document.getElementById('s-days').textContent    = (d.days    || 0).toLocaleString();
  document.getElementById('summary-grid').classList.add('visible');
  for (let i = 1; i <= 5; i++) {
    document.getElementById('ph-' + i)?.classList.add('done');
    document.getElementById('ph-' + i)?.classList.remove('active');
    document.getElementById('pl-' + i)?.classList.add('done');
  }
}
