'use strict';
// "Delete all local data" removes only what Spectra Sherpa demonstrably created
// in its profile folder. The folder may be one the user chose (DATA_DIR), so a
// name alone never proves ownership: before the backend starts, the shell
// records which layout names did not exist yet. Only those are erased; anything
// that already existed, and anything linked, is kept and reported.
const path = require('node:path');
const os = require('node:os');
const layout = require('./profile-layout.json');

const RECORD = '.spectra-sherpa-owned.json';
const OWNED = new Set([...layout.entries, '.env']);
const ENV_KEYS = new Set(layout.env_keys);

async function lstat(fs, file) {
  try { return await fs.lstat(file); } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

async function readRecord(fs, directory) {
  const file = path.join(directory, RECORD);
  const info = await lstat(fs, file);
  if (!info || !info.isFile()) return new Set();
  try {
    const names = JSON.parse(await fs.readFile(file, 'utf8')).owned;
    return new Set(Array.isArray(names) ? names.filter(name => OWNED.has(name)) : []);
  } catch { return new Set(); }
}

async function checkedDirectory(fs, directory) {
  const resolved = path.resolve(directory);
  if (resolved === path.parse(resolved).root || resolved === path.resolve(os.homedir())) {
    throw new Error('Refusing to use a home or drive root directory as the profile');
  }
  const info = await lstat(fs, resolved);
  if (info && !info.isDirectory()) throw new Error('The profile path is not a directory');
  return { resolved, exists: Boolean(info) };
}

/** Before launch: claim the layout names that do not exist yet. */
async function claimProfile(fs, directory) {
  const { resolved, exists } = await checkedDirectory(fs, directory);
  if (!exists) await fs.mkdir(resolved, { recursive: true });
  const owned = await readRecord(fs, resolved);
  for (const name of OWNED) {
    if (!owned.has(name) && !(await lstat(fs, path.join(resolved, name)))) owned.add(name);
  }
  const file = path.join(resolved, RECORD);
  if ((await lstat(fs, file))?.isSymbolicLink()) throw new Error('The profile ownership record is a link');
  const temporary = `${file}.${process.pid}.tmp`;
  await fs.writeFile(temporary, JSON.stringify({ owned: [...owned].sort() }, null, 2), { mode: 0o600 });
  await fs.rename(temporary, file);
  return owned;
}

function ownerOf(name, owned) {
  if (owned.has(name)) return true;
  return layout.prefixes.some(prefix => name.startsWith(prefix) && owned.has(prefix.replace(/[.-]$/, '')));
}

// In a .env the app created, keep any settings the user added; drop app keys.
async function eraseEnv(fs, file) {
  let text;
  try { text = await fs.readFile(file, 'utf8'); } catch { return true; }
  const kept = text.split(/\r?\n/).filter(line => {
    const key = line.split('=', 1)[0].replace(/^\s*export\s+/, '').trim();
    return !(line.includes('=') && ENV_KEYS.has(key));
  });
  if (kept.every(line => !line.trim())) { await fs.rm(file, { force: true }); return true; }
  await fs.writeFile(file, kept.join('\n'), { mode: 0o600 });
  return false;
}

/** Erase application-owned profile entries; return the names that were kept. */
async function eraseProfile(fs, directory) {
  const { resolved, exists } = await checkedDirectory(fs, directory);
  if (!exists) return [];
  const owned = await readRecord(fs, resolved);
  const kept = [];
  for (const name of await fs.readdir(resolved)) {
    if (name === RECORD) continue;
    const file = path.join(resolved, name);
    const info = await lstat(fs, file);
    if (!info) continue;
    if (info.isSymbolicLink()) {
      kept.push(name); // never follow or remove a link
    } else if (name === '.env') {
      // An unowned .env is never touched; a multiply linked one would write elsewhere.
      if (!owned.has(name) || !info.isFile() || info.nlink !== 1 || !(await eraseEnv(fs, file))) kept.push(name);
    } else if (ownerOf(name, owned)) {
      await fs.rm(file, { recursive: true, force: true });
    } else {
      kept.push(name);
    }
  }
  if (kept.length === 0) {
    await fs.rm(path.join(resolved, RECORD), { force: true });
    await fs.rmdir(resolved).catch(() => {});
  }
  return kept.sort();
}

module.exports = { claimProfile, eraseProfile, RECORD };
