# Health Dashboard

Dashboard personal para visualizar y analizar los datos exportados de Apple Health. Diseño minimalista, modo oscuro, y herramientas para análisis con IA.

![Dashboard principal](./data/img/dashboard.png)
![Detalle de salud diaria](./data/img/salud.png)

---

## Características

- **Dashboard diario** — anillos de actividad, pasos, calorías, FC, HRV y sueño de un vistazo
- **Entrenamientos GPS** — mapa interactivo con perfil de altitud, velocidad, frecuencia cardíaca y splits por kilómetro
- **Zonas de FC y carga TRIMP** — análisis del esfuerzo por zonas con score de carga de entrenamiento
- **Histórico** — gráficas de tendencias para todas las métricas: pasos, peso, sueño, HRV, FC en reposo…
- **ECG** — visualización de registros electrocardiográficos
- **Resumen anual** — estadísticas del año al estilo Wrapped
- **Logros** — sistema de gamificación con retos y hitos desbloqueables
- **Exportar para IA** — genera un JSON estructurado para analizar tus datos con Claude o ChatGPT
- **Exportar a Obsidian** — nota Markdown diaria lista para tu vault
- **Modo oscuro** — activable desde Ajustes → Apariencia

---

## Instalación

```bash
pip install -r requirements.txt
python app.py
```

Abre `http://127.0.0.1:5050` en el navegador.

---

## Importar datos de Apple Health

1. En el iPhone: **Salud → tu perfil → Exportar datos de salud**
2. Envía el `.zip` al ordenador
3. En el dashboard: **Ajustes → Importar datos** → arrastra el ZIP

La importación es incremental: puedes subir exportaciones nuevas sin duplicar datos.

---

## Configuración

### Variables de entorno

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `HEALTH_USER` | `admin` | Usuario de acceso |
| `HEALTH_PASSWORD` | `admin` | Contraseña inicial |
| `SECRET_KEY` | Auto-generado | Clave de sesión (persiste en `data/secret_key.txt`) |
| `PORT` | `5050` | Puerto del servidor |
| `DEBUG` | `0` | Modo debug (`1` = activado) |

Al entrar por primera vez con `admin` / `admin` el sistema obliga a cambiar las credenciales.

### Modo debug

**Windows** (dos comandos separados):
```
set DEBUG=1
python app.py
```

**Linux / macOS**:
```bash
DEBUG=1 python app.py
```

> `set DEBUG=1 && python app.py` **no** funciona en Windows — el `&&` no pasa la variable al proceso hijo.

---

## Páginas

| URL | Descripción |
|-----|-------------|
| `/dashboard` | Resumen del día: anillos, métricas clave y comparativa |
| `/salud/<fecha>` | Todos los datos de salud de un día concreto |
| `/historico` | Gráficas históricas de todas las métricas |
| `/workouts` | Lista de entrenamientos con mapa de calor de rutas |
| `/workouts/<id>` | Detalle: mapa GPS, gráficas, splits, zonas de FC, TRIMP |
| `/ecg` | Registros de ECG exportados desde el Apple Watch |
| `/año` | Resumen anual estilo Wrapped |
| `/logros` | Logros, retos y estadísticas acumuladas |
| `/ajustes` | Importar datos, credenciales, objetivos, exportar |

---

## API y debug

| URL | Solo debug | Descripción |
|-----|-----------|-------------|
| `/api/types` | No | Tipos de datos en la BD con conteos y fechas |
| `/api/debug/sleep-hist2` | Sí | Diagnóstico del historial de sueño |
| `/api/debug/temp-check` | Sí | Datos de temperatura de muñeca |

---

## Seguridad

- Credenciales hasheadas (SHA-256) en `data/credentials.json`
- `SECRET_KEY` generada una vez y persistida en `data/secret_key.txt`
- Sesiones de 30 días
- Todas las rutas requieren autenticación excepto `/login` y `/sw.js`
- Endpoints de debug desactivados en producción

---

## Requisitos

- Python 3.10+
- Flask 3.0+, Flask-Login, Flask-Compress
- Ver `requirements.txt`
