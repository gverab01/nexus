/**
 * test_ui_loader.cjs
 * Test de verificación para Tarea 4: Carga local de UI en Electron y gestión de contingencia.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('[TEST] Iniciando verificación de carga de UI local y pantalla de error...');

// 1. Verificar existencia del build de React en static/dist
const staticDistDir = path.resolve(__dirname, '..', '..', 'static', 'dist');
const indexHtmlPath = path.join(staticDistDir, 'index.html');

assert(fs.existsSync(indexHtmlPath), `index.html debe existir en ${indexHtmlPath}`);

const htmlContent = fs.readFileSync(indexHtmlPath, 'utf8');

// 2. Verificar que los assets son relativos (base: './')
assert(htmlContent.includes('src="./assets/'), 'El tag script debe referenciar un path relativo "./assets/..."');
assert(htmlContent.includes('href="./assets/'), 'El tag link CSS debe referenciar un path relativo "./assets/..."');
assert(!htmlContent.includes('src="/static/dist/'), 'No deben quedar paths absolutos a /static/dist/ en los scripts');
assert(!htmlContent.includes('href="/static/dist/'), 'No deben quedar paths absolutos a /static/dist/ en los estilos');

console.log('✓ Build de producción tiene paths de assets 100% relativos.');

// 3. Verificar estructura de pantalla de error en main.cjs
const mainCjsPath = path.resolve(__dirname, '..', 'main.cjs');
const mainContent = fs.readFileSync(mainCjsPath, 'utf8');

assert(mainContent.includes('function showConnectionErrorScreen'), 'main.cjs debe definir showConnectionErrorScreen');
assert(mainContent.includes('function loadAppUi'), 'main.cjs debe definir loadAppUi');
assert(mainContent.includes('function loadLocalUi'), 'main.cjs debe definir loadLocalUi');
assert(mainContent.includes('win.loadFile(localIndexPath)'), 'loadLocalUi debe usar win.loadFile para recursos locales');
assert(mainContent.includes('currentUrl.startsWith(\'file://\')'), 'workerRunner sessionProvider debe soportar file:// como origen seguro');

console.log('✓ Funciones de carga de UI y contingencia validadas en desktop/main.cjs.');

console.log('✅ [TEST PASSED] Carga local de UI, paths relativos y contingencia verificados exitosamente.');
