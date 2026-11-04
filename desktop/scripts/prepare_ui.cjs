/**
 * prepare_ui.cjs
 * Sincroniza y empaqueta el build de React desde static/dist hacia desktop/dist-ui
 * para el empaquetado nativo de Electron.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const projectRoot = path.resolve(__dirname, '..', '..');
const staticDist = path.join(projectRoot, 'static', 'dist');
const targetDistUi = path.resolve(__dirname, '..', 'dist-ui');

console.log('[prepare_ui] Preparando interfaz compilada para Electron...');

// Si static/dist no existe o no tiene index.html, compilar frontend primero
const indexHtml = path.join(staticDist, 'index.html');
if (!fs.existsSync(indexHtml)) {
  console.log('[prepare_ui] static/dist/index.html no encontrado. Ejecutando build de React...');
  execSync('npm --prefix frontend run build', { cwd: projectRoot, stdio: 'inherit' });
}

if (!fs.existsSync(indexHtml)) {
  console.error('[prepare_ui] ERROR: Falló la compilación del frontend React.');
  process.exit(1);
}

// Limpiar y preparar target
if (fs.existsSync(targetDistUi)) {
  fs.rmSync(targetDistUi, { recursive: true, force: true });
}
fs.mkdirSync(targetDistUi, { recursive: true });

// Copiar archivos recursivamente
fs.cpSync(staticDist, targetDistUi, { recursive: true });

// Validar copia
const copiedIndex = path.join(targetDistUi, 'index.html');
if (!fs.existsSync(copiedIndex)) {
  console.error('[prepare_ui] ERROR: No se pudo verificar dist-ui/index.html tras la copia.');
  process.exit(1);
}

console.log(`✓ [prepare_ui] Interfaz compilada copiada exitosamente en: ${targetDistUi}`);

