'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { claimProfile, eraseProfile } = require('../profile-erase.cjs');

async function folder() { return fs.mkdtemp(path.join(os.tmpdir(), 'spectra-erase-')); }
async function put(root, relative, content = 'x') {
  const file = path.join(root, relative);
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, content);
}

test('a profile the app created is erased completely, including the folder', async () => {
  const root = path.join(await folder(), 'profile');
  await claimProfile(fs, root);
  await put(root, 'spectra_platform.db');
  await put(root, 'spectra_platform.db-wal');
  await put(root, 'experiments/1/spectrum.csv');
  await put(root, 'models/m.pkl');
  await put(root, 'credential-key.protected');
  await put(root, 'credential-key.protected.unreadable-1');
  await put(root, '.env', 'CHAT_ENDPOINT_KEY_ENCRYPTED=abc\n');
  assert.deepEqual(await eraseProfile(fs, root), []);
  await assert.rejects(fs.access(root));
});

test('pre-existing folders with layout names are never inferred as owned', async () => {
  const root = await folder();
  await put(root, 'models/my-own-model.txt', 'mine');
  await put(root, 'thesis.docx', 'my thesis');
  await put(root, '.env', '# my project\nDATABASE_URL=postgres://mine\n');
  await claimProfile(fs, root);
  await put(root, 'experiments/1/spectrum.csv');
  await put(root, 'spectra_platform.db');

  assert.deepEqual(await eraseProfile(fs, root), ['.env', 'models', 'thesis.docx']);
  assert.equal(await fs.readFile(path.join(root, 'models/my-own-model.txt'), 'utf8'), 'mine');
  assert.equal(await fs.readFile(path.join(root, '.env'), 'utf8'), '# my project\nDATABASE_URL=postgres://mine\n');
  await assert.rejects(fs.access(path.join(root, 'experiments')));
  await assert.rejects(fs.access(path.join(root, 'spectra_platform.db')));
});

test('without an ownership record nothing but app keys in a real .env is touched', async () => {
  const root = await folder();
  await put(root, 'models/m.pkl');
  await put(root, 'spectra_platform.db');
  assert.deepEqual(await eraseProfile(fs, root), ['models', 'spectra_platform.db']);
});

test('linked entries and a linked .env are neither followed nor modified', async () => {
  const outside = await folder();
  await put(outside, 'project.env', 'CHAT_ENDPOINT_KEY=sk-other\nMASTER_ENCRYPTION_KEY=k\n');
  await put(outside, 'data/keep.txt', 'keep');
  const root = path.join(await folder(), 'profile');
  await claimProfile(fs, root);
  await fs.symlink(path.join(outside, 'project.env'), path.join(root, '.env'));
  await fs.symlink(path.join(outside, 'data'), path.join(root, 'models'), 'junction');

  assert.deepEqual(await eraseProfile(fs, root), ['.env', 'models']);
  assert.equal(await fs.readFile(path.join(outside, 'project.env'), 'utf8'), 'CHAT_ENDPOINT_KEY=sk-other\nMASTER_ENCRYPTION_KEY=k\n');
  assert.equal(await fs.readFile(path.join(outside, 'data/keep.txt'), 'utf8'), 'keep');
});

test('home and drive roots are refused outright', async () => {
  await assert.rejects(eraseProfile(fs, os.homedir()), /Refusing/);
  await assert.rejects(eraseProfile(fs, path.parse(process.cwd()).root), /Refusing/);
  await assert.rejects(claimProfile(fs, os.homedir()), /Refusing/);
});

test('a custom DATA_DIR research workspace keeps its own models, datasets and reports', async () => {
  const root = await folder(); // e.g. Documents\MyResearch
  await put(root, 'models/important-user-model.dat', 'pls');
  await put(root, 'datasets/run1.spc', 'spc');
  await put(root, 'reports/r.pdf', 'pdf');
  await put(root, 'config.json', '{}');
  await claimProfile(fs, root);
  await put(root, 'spectra_platform.db');
  await put(root, 'models/app-model.pkl'); // the app writing into a pre-existing folder

  assert.deepEqual(await eraseProfile(fs, root), ['config.json', 'datasets', 'models', 'reports']);
  assert.equal(await fs.readFile(path.join(root, 'models/important-user-model.dat'), 'utf8'), 'pls');
  await assert.rejects(fs.access(path.join(root, 'spectra_platform.db')));
});

test('an unowned .env is preserved byte-for-byte, including app-named keys', async () => {
  const root = await folder();
  const original = 'SECRET_KEY=mine\r\nCHAT_ENDPOINT_KEY=sk-mine\n# note';
  await put(root, '.env', original);
  await claimProfile(fs, root);
  assert.deepEqual(await eraseProfile(fs, root), ['.env']);
  assert.equal(await fs.readFile(path.join(root, '.env'), 'utf8'), original);
});

test('a hardlinked .env is never written, even when owned', async () => {
  const outside = await folder();
  const original = 'SECRET_KEY=other\nCHAT_ENDPOINT_KEY=sk-other\n';
  await put(outside, 'project.env', original);
  const root = path.join(await folder(), 'profile');
  await claimProfile(fs, root);
  await fs.link(path.join(outside, 'project.env'), path.join(root, '.env'));
  assert.deepEqual(await eraseProfile(fs, root), ['.env']);
  assert.equal(await fs.readFile(path.join(outside, 'project.env'), 'utf8'), original);
});

test('an owned regular .env keeps user-added settings and loses app keys', async () => {
  const root = path.join(await folder(), 'profile');
  await claimProfile(fs, root);
  await put(root, '.env', 'SECRET_KEY=app\nMY_SETTING=1\n');
  assert.deepEqual(await eraseProfile(fs, root), ['.env']);
  assert.equal(await fs.readFile(path.join(root, '.env'), 'utf8'), 'MY_SETTING=1\n');
});
