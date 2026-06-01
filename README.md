# Apple Health Dashboard

Dashboard personal para visualizar datos de Apple Health.
Los datos se almacenan localmente en tu servidor Debian.

## Estructura del proyecto

```
health_dashboard/
├── app.py              # Servidor Flask principal
├── requirements.txt    # Dependencias Python
├── templates/
│   └── index.html      # Página de inicio
├── data/               # Base de datos local (JSON/SQLite)
├── uploads/            # ZIPs temporales durante importación
└── static/             # CSS/JS adicional si se necesita
```

## Instalación en Debian

```bash
# 1. Clonar / copiar el proyecto
cd /opt
sudo mkdir health_dashboard
sudo chown $USER: health_dashboard

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Arrancar el servidor
python app.py
```

El servidor escucha en `http://0.0.0.0:5050`

## Ejecutar como servicio systemd

Crea `/etc/systemd/system/health-dashboard.service`:

```ini
[Unit]
Description=Apple Health Dashboard
After=network.target

[Service]
User=TU_USUARIO
WorkingDirectory=/opt/health_dashboard
ExecStart=/opt/health_dashboard/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable health-dashboard
sudo systemctl start health-dashboard
```

## Cómo exportar desde Apple Health

1. Abrir Apple Health en iPhone
2. Foto de perfil (arriba a la derecha)
3. "Exportar todos los datos de salud"
4. Compartir el `export.zip` resultante
5. Subirlo desde la web del dashboard

## Próximos pasos (pendientes)

- [ ] Parser del export.zip de Apple Health
- [ ] Base de datos SQLite con deduplicación
- [ ] Dashboard con métricas y gráficas
