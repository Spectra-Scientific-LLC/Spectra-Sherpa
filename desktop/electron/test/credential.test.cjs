'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { loadCredentialKey, PROTECTED_FILE } = require('../credential.cjs');

// Reversible stand-in for the OS keystore; the real one is DPAPI/Keychain.
function keystore({ available = true, broken = false } = {}) {
  return {
    isEncryptionAvailable: () => available,
    getSelectedStorageBackend: () => 'gnome_libsecret',
    encryptString: value => Buffer.from(`sealed:${value}`),
    decryptString: blob => {
      const text = blob.toString();
      if (broken || !text.startsWith('sealed:')) throw new Error('cannot unseal');
      return text.slice('sealed:'.length);
    },
  };
}
async function profile() { return fs.mkdtemp(path.join(os.tmpdir(), 'spectra-credential-')); }

test('creates a protected key and never writes it in plaintext', async () => {
  const dataDir = await profile();
  const first = await loadCredentialKey({ safeStorage: keystore(), fs, dataDir });
  assert.equal(first.status, 'created');
  assert.match(first.key, /^[A-Za-z0-9_-]{43}=$/);
  const stored = await fs.readFile(path.join(dataDir, PROTECTED_FILE), 'utf8');
  assert.equal(stored, `sealed:${first.key}`);
  await assert.rejects(fs.readFile(path.join(dataDir, '.env')));
  const again = await loadCredentialKey({ safeStorage: keystore(), fs, dataDir });
  assert.deepEqual(again, { key: first.key, status: 'protected' });
});

test('adopts the legacy plaintext key without editing .env before admission', async () => {
  const dataDir = await profile();
  const legacy = 'Zm9vYmFyYmF6cXV4cXV1eGNvcmdlZ3JhdWx0Z2FycGx5d2FsZG9=';
  await fs.writeFile(path.join(dataDir, '.env'), `CHAT_ENDPOINT_URL=https://api.example.com\nMASTER_ENCRYPTION_KEY=${legacy}\n`);
  const result = await loadCredentialKey({ safeStorage: keystore(), fs, dataDir });
  assert.deepEqual(result, { key: legacy, status: 'migrated' });
  const env = await fs.readFile(path.join(dataDir, '.env'), 'utf8');
  assert.equal(env, `CHAT_ENDPOINT_URL=https://api.example.com\nMASTER_ENCRYPTION_KEY=${legacy}\n`);
});

test('an unreadable protected key is set aside and replaced, not reused', async () => {
  const dataDir = await profile();
  await fs.writeFile(path.join(dataDir, PROTECTED_FILE), 'sealed-by-another-account');
  const result = await loadCredentialKey({ safeStorage: keystore(), fs, dataDir });
  assert.equal(result.status, 'replaced');
  const names = await fs.readdir(dataDir);
  assert.ok(names.some(name => name.startsWith(`${PROTECTED_FILE}.unreadable-`)));
});

test('without an OS keystore the backend keeps its previous behavior', async () => {
  const dataDir = await profile();
  const result = await loadCredentialKey({ safeStorage: keystore({ available: false }), fs, dataDir });
  assert.deepEqual(result, { key: null, status: 'unavailable' });
  assert.deepEqual(await fs.readdir(dataDir), []);
});


test('Linux basic_text never stores or migrates a credential key', async () => {
  for (const backend of ['basic_text', 'unknown']) {
    const dataDir = await profile();
    const storage = { ...keystore(), getSelectedStorageBackend: () => backend };
    assert.deepEqual(await loadCredentialKey({ safeStorage: storage, fs, dataDir, platform: 'linux' }),
      { key: null, status: 'unavailable' });
    assert.deepEqual(await fs.readdir(dataDir), []);
  }
});
