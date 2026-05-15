# ⚽ Bot de Telegram - Partidos de Fútbol Diarios

Bot que scrapea **Promiedos.com.ar** y envía automáticamente todos los partidos
del día a grupos o chats de Telegram.

## 📋 Características

- Envío automático diario a la hora que configures
- Comando `/partidos` para pedir los partidos en cualquier momento
- Sistema de suscriptores: cualquier usuario que haga `/start` se suscribe
- Agrupa partidos por liga/competición
- Muestra resultados en vivo y finalizados
- Soporte para múltiples grupos y chats

---

## 🚀 Instalación rápida

### 1. Clonar / descargar los archivos

```bash
mkdir futbol_bot && cd futbol_bot
# (copiá aquí los archivos del bot)
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python3 -m venv venv
source venv/bin/activate          # Linux/Mac
# venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 3. Crear tu bot en Telegram

1. Abrí Telegram y buscá **@BotFather**
2. Enviá `/newbot`
3. Elegí un nombre y username para tu bot
4. Copiá el **token** que te da BotFather

### 4. Configurar variables de entorno

```bash
cp .env.example .env
nano .env   # (o editá con cualquier editor)
```

Completá tu token:
```
TELEGRAM_BOT_TOKEN=TU_TOKEN_AQUI
HORA_ENVIO=8
ZONA_HORARIA=America/Argentina/Buenos_Aires
```

### 5. Ejecutar el bot

```bash
# Cargar variables de entorno
export $(cat .env | xargs)

# Iniciar el bot
python bot.py
```

---

## 🤖 Comandos del bot

| Comando | Descripción |
|---------|-------------|
| `/start` | Suscribirse a partidos diarios |
| `/partidos` | Ver partidos de hoy ahora mismo |
| `/stop` | Cancelar suscripción |
| `/ayuda` | Ayuda |

---

## 🖥️ Mantenerlo corriendo 24/7

### Opción A — systemd (Linux, recomendado)

Creá el archivo `/etc/systemd/system/futbol-bot.service`:

```ini
[Unit]
Description=Bot Telegram Fútbol
After=network.target

[Service]
Type=simple
User=tu_usuario
WorkingDirectory=/ruta/a/futbol_bot
EnvironmentFile=/ruta/a/futbol_bot/.env
ExecStart=/ruta/a/futbol_bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable futbol-bot
sudo systemctl start futbol-bot
sudo systemctl status futbol-bot
```

### Opción B — screen (más simple)

```bash
screen -S futbol-bot
export $(cat .env | xargs)
python bot.py
# Ctrl+A, D para desconectarte (el bot sigue corriendo)
```

### Opción C — Railway / Render (cloud gratuito)

1. Subí los archivos a GitHub
2. Creá un nuevo proyecto en [railway.app](https://railway.app) o [render.com](https://render.com)
3. Conectá tu repositorio
4. Configurá las variables de entorno en el panel
5. El comando de inicio es: `python bot.py`

---

## 📁 Estructura del proyecto

```
futbol_bot/
├── bot.py           # Bot principal y comandos
├── scraper.py       # Scraping de Promiedos.com.ar
├── formatter.py     # Formatea los mensajes para Telegram
├── requirements.txt # Dependencias Python
├── .env.example     # Plantilla de configuración
├── .env             # Tu configuración (NO subir a git)
└── subscribers.txt  # Suscriptores (se crea automáticamente)
```

---

## ⚙️ Configuración avanzada

### Cambiar la hora de envío

En `.env`:
```
HORA_ENVIO=7   # Enviará a las 7:00 AM
```

### Agregar un grupo de Telegram

1. Agregá el bot al grupo
2. Enviá `/start` en el grupo
3. El grupo quedará suscrito automáticamente

### Pre-cargar chat IDs

Si ya sabés los IDs de tus grupos, podés cargarlos en `.env`:
```
TELEGRAM_CHAT_IDS=-1001234567890,-1009876543210
```

Para obtener el ID de un grupo, usá [@userinfobot](https://t.me/userinfobot).

---

## 🐛 Solución de problemas

**El bot no responde**
- Verificá que el token esté correcto
- Asegurate de que el bot esté corriendo (`python bot.py`)

**No llegan los partidos automáticos**
- Verificá que alguien haya usado `/start` o que hayas puesto chat IDs en `.env`
- Revisá los logs del bot para ver errores

**No encuentra partidos**
- Promiedos puede cambiar su estructura HTML; revisá los logs
- Podés abrir un issue para actualizar el scraper
