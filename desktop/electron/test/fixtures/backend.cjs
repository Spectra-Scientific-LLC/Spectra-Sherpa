'use strict';
const http = require('node:http');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const mode = process.argv[2];
if (mode === 'stubborn') process.on('SIGTERM', () => {});
const lines = readline.createInterface({ input: process.stdin });
let server;
lines.once('line', line => {
  const launch = JSON.parse(line);
  if (mode === 'oversize') process.stdout.write('x'.repeat(5000));
  else if (mode === 'invalid') console.log(JSON.stringify({ protocol: 1, type: 'ready', version: '0.6.0', endpoint: 'https://elsewhere.example' }));
  else if (mode === 'failure') console.log(JSON.stringify({ protocol: 1, type: 'error', message: 'Profile recovery required' }));
  else {
    server = http.createServer((request, response) => {
      response.writeHead(request.headers['x-spectra-desktop-token'] === launch.secret ? 200 : 403);
      response.end('{}');
    });
    server.listen(0, '127.0.0.1', () => console.log(JSON.stringify({ protocol: 1, type: 'ready', version: '0.6.0', endpoint: `http://127.0.0.1:${server.address().port}` })));
  }
});
lines.once('close', () => {
  if (mode === 'stubborn') return; // Real live server that refuses cooperative shutdown.
  if (mode === 'inherited-stdout') {
    // Finite-lived writer simulates a descendant retaining our protocol pipe.
    const writer = spawn(process.execPath, ['-e', 'setTimeout(() => process.exit(0), 2000)'],
      { stdio: ['ignore', process.stdout, 'ignore'] });
    writer.unref();
  }
  if (server) server.close(() => process.exit(0));
  else process.exit(0);
});
