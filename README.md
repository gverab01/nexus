# NexusReach Pro

Motor local de prospección y gestión multicanal B2B con arquitectura híbrida (Backend FastAPI + Frontend React/Vite + Wrapper Desktop Electron).

---

## 🚀 Arquitectura del Proyecto

- **Backend (`/`)**: API REST construida con FastAPI, SQLAlchemy y SQLite para gestión multitenant, secuencias de prospección automatizada, auditoría y control de límites de seguridad.
- **Frontend (`/frontend`)**: Interfaz web moderna desarrollada con React 19, Tailwind CSS y Lucide Icons.
- **Desktop (`/desktop`)**: Aplicación de escritorio basada en Electron para control del navegador y despacho local de tareas en segundo plano.
- **Pruebas (`/scratch`)**: Scripts de validación E2E y pruebas de aislamiento multitenant.

---

## 🛠️ Requisitos Previos

- **Python**: 3.10 o superior.
- **Node.js**: v18+ y npm.
- **Google Chrome / Chromium**: Instalado localmente para automatización de navegador.

---

## 📦 Instalación y Configuración

### 1. Backend (Python)

```bash
# Crear entorno virtual (si no existe)
python -m venv venv

# Activar entorno virtual
# En Windows:
.\venv\Scripts\activate
# En Linux/macOS:
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Frontend (React)

```bash
cd frontend
npm install
npm run build
cd ..
```

### 3. Aplicación Desktop (Electron)

```bash
cd desktop
npm install
cd ..
```

---

## ⚡ Ejecución

### Modo Todo-en-Uno (Desktop en Windows):
Doble clic en:
```bash
iniciar_nexusreach_desktop.bat
```
Este script levantará automáticamente:
1. El servidor backend FastAPI en `http://127.0.0.1:8000`.
2. La aplicación de escritorio Electron conectada a la interfaz.

### Ejecución Manual:

**Backend:**
```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

**Frontend (desarrollo Vite):**
```bash
cd frontend
npm run dev
```

**Desktop:**
```bash
cd desktop
npm start
```

---

## 🔒 Seguridad y Privacidad

- Las bases de datos SQLite locales (`leads.db`) y archivos de prospectos (`prospectos.json`) están excluidos por `.gitignore` para salvaguardar información sensible y de privacidad.
