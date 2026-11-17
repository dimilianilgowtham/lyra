'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

function runtimePaths({packaged, appDir, resourcesPath, userData, home = os.homedir(), env = process.env}) {
  const dataDir = packaged ? path.join(userData, 'data') : path.join(appDir, 'lyra-backend/data');
  const backendDir = packaged ? path.join(resourcesPath, 'backend') : path.join(appDir, 'lyra-backend');
  const python = packaged ? path.join(backendDir, 'lyra-backend') : path.join(backendDir, '.venv/bin/python');
  if (!fs.existsSync(python)) throw new Error('Lyra backend runtime is missing. Rebuild the application before launching.');
  let settings = {};
  try { settings = JSON.parse(fs.readFileSync(path.join(userData, 'workspace-settings.json'), 'utf8')); } catch {}
  const candidates = Array.isArray(settings.workspaceRoots) ? settings.workspaceRoots : [path.join(home,'Documents'), path.join(home,'Desktop'), path.join(home,'Downloads')];
  const roots = candidates.filter(root => typeof root === 'string' && path.isAbsolute(root) && fs.existsSync(root));
  if (!roots.length) roots.push(home);
  const additions = [path.join(home,'.local/bin'),'/opt/homebrew/bin','/usr/local/bin','/usr/bin','/bin','/usr/sbin','/sbin'];
  const runtimeEnv = {...env, PYTHONUNBUFFERED:'1', PYTHONDONTWRITEBYTECODE:'1',
    PATH: [...new Set([...(env.PATH || '').split(path.delimiter),...additions])].filter(Boolean).join(path.delimiter)};
  if (packaged) Object.assign(runtimeEnv, {
    LYRA_DATA_DIR:dataDir, LYRA_CONFIG_DIR:userData, LYRA_ENV_FILE:path.join(userData,'.env'),
    DATABASE_PATH:path.join(dataDir,'lyra.db'), LYRA_LEGACY_SESSION_FILE:path.join(dataDir,'session_memory.json'),
    LOCAL_STT_MODEL_DIR:path.join(resourcesPath,'models/faster-whisper-tiny'),
    LYRA_WORKSPACE_ROOTS: env.LYRA_WORKSPACE_ROOTS || roots.join(path.delimiter),
  });
  return {python, args:packaged ? [] : ['main.py'], backendDir, dataDir,
    tokenPath:path.join(dataDir,'.backend-auth-token'), logPath:path.join(userData,'logs/backend.log'), env:runtimeEnv};
}
module.exports = {runtimePaths};
