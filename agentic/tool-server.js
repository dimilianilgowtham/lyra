/** Compatibility launcher: all tools now live in the authenticated Python service. */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const backend = path.join(__dirname, '..', 'lyra-backend');
const managed = path.join(backend, '.venv', 'bin', 'python');
const python = fs.existsSync(managed) ? managed : 'python3';
const child = spawn(python, ['main.py'], { cwd: backend, stdio: 'inherit', env: process.env });
child.on('error', error => { process.stderr.write(`Backend could not start: ${error.message}\n`); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
