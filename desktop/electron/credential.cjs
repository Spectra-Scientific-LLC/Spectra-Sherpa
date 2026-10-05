'use strict';
// The key that encrypts saved API keys, protected by the operating system
// (Windows DPAPI / macOS Keychain / Linux secret store via Electron safeStorage). It is stored only
// as a protected blob in the profile and reaches the backend over the private
// launch pipe, never through argv, environment variables, URLs or logs.
const path = require('node:path');
const { randomBytes } = require('node:crypto');

const PROTECTED_FILE = 'credential-key.protected';
// A Fernet key, or a legacy MASTER_ENCRYPTION_KEY secret the backend normalizes.
const KEY_SHAPE = /^[\x21-\x7e]{16,256}$/;
const LEGACY_LINE = /^MASTER_ENCRYPTION_KEY=(.*)$/;

function newKey() {
  return randomBytes(32).toString('base64url') + '=';
}

async function readLegacyKey(fs, envPath) {
  let text;
  try { text = await fs.readFile(envPath, 'utf8'); } catch { return null; }
  for (const line of text.split(/\r?\n/)) {
    const match = LEGACY_LINE.exec(line.trim());
    if (match && KEY_SHAPE.test(match[1].trim())) return match[1].trim();
  }
  return null;
}

async function writeProtected(fs, file, blob) {
  const temporary = `${file}.${process.pid}.tmp`;
  await fs.writeFile(temporary, blob, { mode: 0o600 });
  await fs.rename(temporary, file);
}

/**
 * Return the profile's credential key, creating or migrating it as needed.
 * Returns ``{ key: null }`` when the OS keystore is unavailable and touches
 * nothing; the backend then refuses to store or use saved credentials.
 */
async function loadCredentialKey({ safeStorage, fs, dataDir, platform = process.platform }) {
  if (!safeStorage.isEncryptionAvailable()) return { key: null, status: 'unavailable' };
  if (platform === 'linux' && (!safeStorage.getSelectedStorageBackend ||
      !['gnome_libsecret', 'kwallet', 'kwallet5', 'kwallet6'].includes(safeStorage.getSelectedStorageBackend()))) {
    return { key: null, status: 'unavailable' };
  }
  await fs.mkdir(dataDir, { recursive: true });
  const file = path.join(dataDir, PROTECTED_FILE);
  const envPath = path.join(dataDir, '.env');
  let blob = null;
  try { blob = await fs.readFile(file); } catch { /* first launch or migration */ }
  if (blob) {
    try {
      const key = safeStorage.decryptString(blob);
      if (KEY_SHAPE.test(key)) return { key, status: 'protected' };
    } catch { /* e.g. a profile copied from another computer or account */ }
    // Keep the unreadable blob for inspection; saved API keys must be re-entered.
    await fs.rename(file, `${file}.unreadable-${Date.now()}`);
    const key = newKey();
    await writeProtected(fs, file, safeStorage.encryptString(key));
    return { key, status: 'replaced' };
  }
  const legacy = await readLegacyKey(fs, envPath);
  const key = legacy || newKey();
  await writeProtected(fs, file, safeStorage.encryptString(key));
  if (safeStorage.decryptString(await fs.readFile(file)) !== key) throw new Error('Credential key protection could not be verified');
  // The shell never edits .env: it may not own the profile yet. The backend
  // retires the matching plaintext line only after acquiring the profile lock.
  return { key, status: legacy ? 'migrated' : 'created' };
}

module.exports = { loadCredentialKey, PROTECTED_FILE };
