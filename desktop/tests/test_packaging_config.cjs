/**
 * test_packaging_config.cjs
 * Test de verificación para Tarea 5: Configuración de empaquetado y distribución con electron-builder.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('[TEST] Iniciando verificación de configuración y artefactos de empaquetado...');

// 1. Verificar package.json de desktop
const pkgPath = path.resolve(__dirname, '..', 'package.json');
const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));

assert(pkg.author, 'package.json debe definir author');
assert(pkg.scripts['prepare:ui'], 'package.json debe definir script prepare:ui');
assert(pkg.scripts['dist:win:dir'], 'package.json debe definir script dist:win:dir');
assert(pkg.scripts['dist:win'], 'package.json debe definir script dist:win');
console.log('✓ desktop/package.json scripts y metadata validados.');

// 2. Verificar script prepare_ui.cjs
const prepareScript = path.resolve(__dirname, '..', 'scripts', 'prepare_ui.cjs');
assert(fs.existsSync(prepareScript), 'desktop/scripts/prepare_ui.cjs debe existir');
console.log('✓ desktop/scripts/prepare_ui.cjs existe y está disponible.');

// 3. Verificar electron-builder.yml
const builderYmlPath = path.resolve(__dirname, '..', 'electron-builder.yml');
const ymlContent = fs.readFileSync(builderYmlPath, 'utf8');

assert(ymlContent.includes('appId: com.nexusreach.desktop'), 'appId debe ser com.nexusreach.desktop');
assert(ymlContent.includes('dist-ui/**'), 'files debe incluir explícitamente dist-ui/**');
assert(ymlContent.includes('target: nsis'), 'target de Windows debe ser nsis');
assert(ymlContent.includes('- x64'), 'arquitectura de Windows debe ser x64');
console.log('✓ desktop/electron-builder.yml contiene directivas de packaging correctas.');

// 4. Verificar artefactos generados en desktop/dist
const distDir = path.resolve(__dirname, '..', 'dist');
const installerPath = path.join(distDir, 'NexusReach Pro Setup 1.0.0.exe');
const unpackedExePath = path.join(distDir, 'win-unpacked', 'NexusReach Pro.exe');
const asarPath = path.join(distDir, 'win-unpacked', 'resources', 'app.asar');

assert(fs.existsSync(distDir), 'desktop/dist debe existir tras la compilación');
assert(fs.existsSync(unpackedExePath), 'NexusReach Pro.exe desempaquetado debe existir');
assert(fs.existsSync(asarPath), 'resources/app.asar debe existir en win-unpacked');
assert(fs.existsSync(installerPath), 'El instalador NexusReach Pro Setup 1.0.0.exe debe existir');

const installerStats = fs.statSync(installerPath);
assert(installerStats.size > 50 * 1024 * 1024, `El instalador debe ser mayor a 50MB (actual: ${(installerStats.size / (1024 * 1024)).toFixed(1)} MB)`);

console.log(`✓ Instalador NSIS verificado: ${(installerStats.size / (1024 * 1024)).toFixed(2)} MB`);
console.log('✅ [TEST PASSED] Todo el pipeline de empaquetado y distribución comercial de Windows verificado exitosamente.');

