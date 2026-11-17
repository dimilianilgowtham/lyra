const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
test('installed runtime uses bundled executable and writable user paths', () => {
  const { runtimePaths } = require('../../electron/runtime-paths.cjs');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'lyra-desktop-'));
  try {
    const resourceDir = path.join(temp, 'app/Contents/Resources');
    fs.mkdirSync(path.join(resourceDir, 'backend'), {recursive:true});
    fs.writeFileSync(path.join(resourceDir, 'backend/lyra-backend'), '');
    const result = runtimePaths({packaged:true, appDir:path.join(resourceDir, 'app'), resourcesPath:resourceDir, userData:path.join(temp, 'user'), home:temp});
    assert.equal(result.python, path.join(resourceDir, 'backend/lyra-backend'));
    assert.deepEqual(result.args, []);
    assert.equal(result.env.DATABASE_PATH, path.join(temp, 'user/data/lyra.db'));
    assert.equal(result.env.LYRA_ENV_FILE, path.join(temp, 'user/.env'));
    assert.equal(result.env.LOCAL_STT_MODEL_DIR, path.join(resourceDir,'models/faster-whisper-tiny'));
    assert.equal(result.tokenPath, path.join(temp,'user/data/.backend-auth-token'));
    assert(!result.env.DATABASE_PATH.startsWith(resourceDir));
  } finally {fs.rmSync(temp,{recursive:true,force:true});}
});
test('missing installed backend is an explicit launch error', () => {
  const { runtimePaths } = require('../../electron/runtime-paths.cjs');
  assert.throws(() => runtimePaths({packaged:true, appDir:'/missing',resourcesPath:'/missing',userData:'/tmp/lyra-test',home:'/tmp'}), /backend.*missing/i);
});
