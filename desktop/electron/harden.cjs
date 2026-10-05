'use strict';
const path = require('node:path');
async function harden(target, verifyOnly = false) {
  const { flipFuses, getCurrentFuseWire, FuseVersion, FuseV1Options: F, FuseState } = await import('@electron/fuses');
  const policy = { version: FuseVersion.V1, strictlyRequireAllFuses: true,
    resetAdHocDarwinSignature: process.platform === 'darwin',
    [F.RunAsNode]: false,
    // The workbench uses an ephemeral session and writes no cookie database.
    [F.EnableCookieEncryption]: false,
    [F.EnableNodeOptionsEnvironmentVariable]: false,
    [F.EnableNodeCliInspectArguments]: false,
    [F.EnableEmbeddedAsarIntegrityValidation]: true,
    [F.OnlyLoadAppFromAsar]: true,
    [F.LoadBrowserProcessSpecificV8Snapshot]: false,
    [F.GrantFileProtocolExtraPrivileges]: false,
    [F.WasmTrapHandlers]: true,
  };
  if (!verifyOnly) await flipFuses(target, policy);
  const wire = await getCurrentFuseWire(target);
  if (wire.version !== policy.version ||
      Object.keys(wire).filter(key => /^\d+$/.test(key)).length !==
      Object.keys(policy).filter(key => /^\d+$/.test(key)).length) {
    throw new Error('Unreviewed Electron fuse schema');
  }
  for (const [key, value] of Object.entries(policy)) {
    if (!/^\d+$/.test(key)) continue;
    if (wire[key] !== (value ? FuseState.ENABLE : FuseState.DISABLE)) {
      throw new Error(`Desktop release fuse ${key} does not match the policy`);
    }
  }
  console.log('Verified native Electron release fuses');
}
if (require.main === module) {
  const target = process.argv[2];
  if (!target) { console.error('Usage: node harden.cjs APP_OR_EXE [--verify]'); process.exitCode = 1; }
  else harden(path.resolve(target), process.argv[3] === '--verify').catch(error => {
    console.error(error.message); process.exitCode = 1;
  });
}
module.exports = { harden };
