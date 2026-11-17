"""Smoke-test the bundled backend independently of Python, Vite, and user data."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, default=ROOT / 'build/backend/lyra-backend/lyra-backend')
    parser.add_argument('--models', type=Path, default=ROOT / 'lyra-backend/data/models/faster-whisper-tiny')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='lyra-frozen-') as folder:
        temp = Path(folder)
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        token = secrets.token_urlsafe(32)
        environment = {**os.environ, 'PATH':'/usr/bin:/bin:/usr/sbin:/sbin',
            'LYRA_DATA_DIR':str(temp/'data'), 'LYRA_ENV_FILE':str(temp/'.env'),
            'DATABASE_PATH':str(temp/'data/check.db'), 'BACKEND_AUTH_TOKEN':token,
            'BACKEND_HOST':'127.0.0.1', 'BACKEND_PORT':str(port), 'BACKEND_INSTANCE_ID':'frozen-check',
            'LOCAL_STT_MODEL_DIR':str(args.models.resolve()), 'STT_PROVIDER':'local', 'LYRA_WORKSPACE_ROOTS':folder}
        with (temp/'backend.log').open('w') as log:
            process = subprocess.Popen([str(args.executable.resolve())], cwd=folder, env=environment, stdout=log, stderr=log)
            try:
                def request(route, body=None, timeout=40):
                    req = urllib.request.Request(f'http://127.0.0.1:{port}{route}',
                        data=None if body is None else json.dumps(body).encode(),
                        headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        return json.load(response)
                health = None
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError('Frozen backend exited:\n' + (temp/'backend.log').read_text()[-4000:])
                    try:
                        health = request('/api/health', timeout=1)
                        break
                    except (urllib.error.URLError, TimeoutError): time.sleep(.25)
                if not health:
                    raise RuntimeError('Frozen backend did not become ready:\n' + (temp/'backend.log').read_text()[-5000:])
                assert health['status']=='online' and health['instance_id']=='frozen-check', health
                subprocess.run(['/usr/bin/say','-o',str(temp/'speech.aiff'),'Lyra, check the current working directory.'],check=True)
                subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16',str(temp/'speech.aiff'),str(temp/'speech.wav')],check=True)
                speech = request('/api/stt', {'audio':base64.b64encode((temp/'speech.wav').read_bytes()).decode(), 'format':'wav','language':'en'})
                assert speech.get('provider')=='local' and 'working directory' in speech.get('text','').lower(), speech
                print(json.dumps({'health':health['status'],'instance_verified':True,'speech':speech,'executable':str(args.executable)},indent=2))
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__=='__main__': main()
