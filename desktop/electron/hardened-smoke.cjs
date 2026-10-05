'use strict';
// Post-fuse qualification cannot use a debugger. Exercise production startup,
// crash ownership and recovery on newly created disposable data only.
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
// Whole-parent acceptance includes activity checks, renderer close, the owned
// backend's separate 24-second shutdown bound, and Electron quit scheduling.
// Keep margin above their combined duration; this does not extend Backend.stop.
const PARENT_EXIT_TIMEOUT_MS = 40000;
function windowsProcess(pid, operation) {
  assert(Number.isSafeInteger(pid) && pid > 0);
  // Read/wait on a known owned PID; never signal a discovered Windows process.
  const action = operation === 'wait' ?
    'if ($p.WaitForExit(20000)) { exit 0 }; exit 1' :
    'for ($i=0; $i -lt 40; $i++) { $p.Refresh(); if ($p.CloseMainWindow()) { exit 0 }; Start-Sleep -Milliseconds 500 }; exit 1';
  execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    `try { $p = [System.Diagnostics.Process]::GetProcessById(${pid}); ${action} } catch [System.ArgumentException] { exit 0 } catch { exit 2 }`],
  { timeout: 25000, stdio: 'pipe', windowsHide: true });
}
async function backendExited(pid) {
  if (process.platform === 'win32') { windowsProcess(pid, 'wait'); return; }
  for (let i = 0; i < 40; i++) {
    try { process.kill(pid, 0); } catch (error) { if (error.code === 'ESRCH') return; throw error; }
    await delay(500);
  }
  throw new Error('Owned backend remained alive after native parent exit');
}
async function launch(executable, profile) {
  const logPath = path.join(profile, 'logs/desktop.log');
  let previousLength = 0;
  try { previousLength = (await fs.readFile(logPath)).length; } catch { /* First launch. */ }
  // This is a GUI acceptance test: Windows must expose the main window so
  // CloseMainWindow can exercise the real close event. Hide only backend processes.
  const child = spawn(executable, [], { env: { ...process.env, DATA_DIR: profile }, stdio: ['ignore', 'pipe', 'ignore'], windowsHide: false });
  let windowReady = false;
  let output = '';
  let rawOutput = '';
  const launchedAt = Date.now();
  child.stdout.on('data', chunk => {
    const text = chunk.toString('utf8');
    rawOutput = (rawOutput + text).slice(-4096);
    // Record receipt time, not the later time that a failed smoke prints output.
    output = (output + `[+${Date.now() - launchedAt}ms] ` + text).slice(-4096);
    if (rawOutput.includes('Spectra Sherpa native window ready')) windowReady = true;
  });
  let spawnError;
  child.on('error', error => { spawnError = error; });
  child.once('exit', (code, signal) => {
    output = (output + `[+${Date.now() - launchedAt}ms] Native parent exit: ${code}/${signal}\n`).slice(-4096);
  });
  const exited = new Promise(resolve => child.once('close', resolve));
  const stop = async graceful => {
    let closeError;
    try {
      if (graceful && process.platform === 'win32') windowsProcess(child.pid, 'close');
      else child.kill(graceful ? 'SIGTERM' : 'SIGKILL'); // Only our child handle; first phase deliberately crashes.
    } catch (error) {
      closeError = error;
      child.kill('SIGKILL'); // Reap only this test's child after a failed close request.
    } finally {
      let forced = false;
      const deadline = setTimeout(() => { forced = true; child.kill('SIGKILL'); }, PARENT_EXIT_TIMEOUT_MS);
      try { await exited; } finally { clearTimeout(deadline); }
      if (forced) console.error(output); // Bounded shell lifecycle receipts; no launch credential.
      if (closeError) throw new Error(`Native window close request failed (status ${closeError.status ?? 'unknown'})`);
      assert(!forced, 'Native parent did not stop within its ownership deadline');
      if (graceful) {
        const stopped = output.indexOf('Spectra Sherpa lifecycle: backend-stopped');
        const closing = output.indexOf('Spectra Sherpa lifecycle: closing-window');
        assert(stopped >= 0 && closing > stopped, 'Native window closed before owned backend exit');
      }
      if (graceful && process.platform === 'win32') assert.equal(child.exitCode, 0, 'Native window did not close cleanly');
    }
  };
  try {
    for (let attempt = 0; attempt < 360; attempt++) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null) throw new Error('Hardened app exited before scientific startup');
      try {
        const log = await fs.readFile(logPath);
        if (windowReady && log.subarray(previousLength).toString('utf8').includes('Application startup complete')) {
          const pid = Number((await fs.readFile(path.join(profile, '.spectrasherpa-desktop.lock'), 'utf8')).trim());
          assert(Number.isSafeInteger(pid) && pid > 0);
          return { pid, stop };
        }
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
      await delay(500);
    }
    throw new Error('Hardened app did not initialize its scientific backend');
  } catch (error) { await stop(false); throw error; }
}
// macOS ties the app's "Safe Storage" Keychain item to its code signature.
// Hardening and signing re-sign the app, so an item created by an earlier CI
// smoke run would raise an access prompt that nobody can answer on a runner.
// Release builds keep one Developer ID identity; only CI needs this reset, and
// it never runs on a developer's machine.
function resetCiSafeStorageItem() {
  if (process.platform !== 'darwin' || process.env.CI !== 'true') return;
  // Electron derives the service from the app name; cover display and bundle names.
  for (const service of ['Spectra Sherpa Safe Storage', 'SpectraSherpa Safe Storage']) {
    try {
      execFileSync('security', ['delete-generic-password', '-s', service], { stdio: 'ignore', timeout: 15000 });
    } catch { /* No earlier item. */ }
  }
}
async function smoke(executable, retainedProfile) {
  resetCiSafeStorageItem();
  const profile = retainedProfile ? path.resolve(retainedProfile) : await fs.mkdtemp(path.join(os.tmpdir(), 'spectra-hardened-'));
  if (retainedProfile) await fs.mkdir(profile); // Refuse existing paths, including real user profiles.
  try {
    const first = await launch(executable, profile);
    console.log('Hardened application: initial window loaded; testing owned-parent crash');
    await first.stop(false);
    await backendExited(first.pid);
    // A Windows job-object crash may terminate the backend before Python's
    // finally block removes its lock. Prove that the owner exited, then exercise
    // canonical stale-lock recovery by reopening; never delete the lock here.
    const recovered = await launch(executable, profile);
    console.log('Hardened application: recovered window loaded; testing close');
    await recovered.stop(true);
    await backendExited(recovered.pid);
    await assert.rejects(fs.access(path.join(profile, '.spectrasherpa-desktop.lock')),
      error => error.code === 'ENOENT', 'Graceful close retained the profile lock');
    if (!retainedProfile) await fs.rm(profile, { recursive: true });
    console.log('Hardened application passed startup, owned-backend exit, profile recovery and graceful close');
  } catch (error) {
    try {
      const log = await fs.readFile(path.join(profile, 'logs/desktop.log'), 'utf8');
      console.error(log.split('\n').slice(-30).map(line => line.slice(0, 512)).join('\n'));
    } catch { /* No application log was produced. */ }
    throw error;
  }
}
if (!process.argv[2]) { console.error('Usage: node hardened-smoke.cjs PACKAGED_EXECUTABLE [NEW_DISPOSABLE_PROFILE]'); process.exitCode = 1; }
else smoke(path.resolve(process.argv[2]), process.argv[3]).catch(error => { console.error(error.message); process.exitCode = 1; });
