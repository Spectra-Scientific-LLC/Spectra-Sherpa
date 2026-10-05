'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { harden } = require('../harden.cjs');
test('release hardening refuses a missing policy and verifies every fuse after applying it', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'spectra-fuses-'));
  try {
    const file = path.join(dir, 'synthetic-fuse-wire');
    const prefix = Buffer.concat([Buffer.from('synthetic fixture:dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'), Buffer.from([1, 9])]);
    await fs.writeFile(file, Buffer.concat([prefix, Buffer.from('111111111')]));
    await assert.rejects(harden(file, true));
    await harden(file);
    await harden(file, true);
    const bytes = await fs.readFile(file);
    assert.equal(bytes.subarray(prefix.length).toString(), '000011001');
    bytes[prefix.length] = '1'.charCodeAt(0);
    await fs.writeFile(file, bytes);
    await assert.rejects(harden(file, true), /does not match/);
  } finally { await fs.rm(dir, { recursive: true }); }
});
