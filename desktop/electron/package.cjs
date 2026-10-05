'use strict';
const path = require('node:path');
const fs = require('node:fs');
async function build() {
  const { packager } = await import('@electron/packager');
  if (!((process.platform === 'darwin' && process.arch === 'arm64') ||
        (['win32', 'linux'].includes(process.platform) && process.arch === 'x64'))) {
    throw new Error('Native candidates support Windows x64, Ubuntu x64 and Apple Silicon macOS');
  }
  const source = path.join(__dirname, '..', 'dist', 'SpectraSherpa');
  const binary = process.platform === 'win32' ? 'SpectraSherpa.exe' : 'SpectraSherpa';
  if (!fs.existsSync(path.join(source, binary))) throw new Error('Build the pipe-enabled frozen backend first');
  const staged = path.join(__dirname, 'staged');
  fs.mkdirSync(staged, { recursive: true });
  const backend = path.join(staged, 'backend');
  fs.cpSync(source, backend, { recursive: true, force: false, errorOnExist: true });
  try {
    const outputs = await packager({ dir: __dirname, name: 'SpectraSherpa',
      out: path.join(__dirname, 'out'), overwrite: true, asar: true,
      platform: process.platform, arch: process.arch,
      appBundleId: 'ai.spectrascientific.sherpa', appVersion: require('./package.json').version,
      electronVersion: require('./package.json').devDependencies.electron,
      ...(process.platform === 'win32' ? { icon: path.join(__dirname, 'assets/logo.ico') } : {}),
      appCopyright: 'Copyright © 2026 Spectra Scientific LLC. All rights reserved.',
      win32metadata: { CompanyName: 'Spectra Scientific LLC', FileDescription: 'Spectra Sherpa', ProductName: 'Spectra Sherpa' },
      extraResource: [backend],
      ignore: [/^\/test($|\/)/, /^\/staged($|\/)/, /^\/out($|\/)/, /^\/package.cjs$/, /^\/smoke.cjs$/, /^\/lifecycle-smoke.cjs$/, /^\/harden.cjs$/, /^\/hardened-smoke.cjs$/, /^\/internal-native.tar.gz$/],
      executableName: 'SpectraSherpa', prune: true,
    });
    console.log(outputs.join('\n'));
  } finally { fs.rmSync(staged, { recursive: true, force: true }); }
}
build().catch(error => { console.error(error.message); process.exitCode = 1; });
