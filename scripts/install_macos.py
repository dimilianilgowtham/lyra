"""Install a built Lyra app and migrate the local profile without overwriting it."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import uuid

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def migrate_data(root, support):
    root, support = Path(root), Path(support)
    support.mkdir(parents=True, exist_ok=True)
    data = support/'data'; data.mkdir(exist_ok=True)
    support.chmod(0o700); data.chmod(0o700)
    values = {}
    for source in (root/'.env', root/'lyra-backend/.env'):
        if source.is_file(): values.update({key:value for key,value in dotenv_values(source).items() if value is not None})
    profile = support/'.env'
    if not profile.exists():
        installed_values = {**values, 'DATABASE_PATH':str(data/'lyra.db'), 'BACKEND_HOST':'127.0.0.1'}
        profile.write_text(''.join(f'{key}={json.dumps(value)}\n' for key,value in installed_values.items()))
        profile.chmod(0o600)
    raw_database = Path(values.get('DATABASE_PATH') or 'lyra-backend/data/lyra.db').expanduser()
    source_database = raw_database if raw_database.is_absolute() else root/raw_database
    target = data/'lyra.db'
    if source_database.is_file() and not target.exists():
        # SQLite's online backup includes committed WAL changes; raw file copying does not.
        temporary = data/'.lyra-migration.db'
        original = sqlite3.connect(source_database.resolve().as_uri()+'?mode=ro', uri=True)
        copied = sqlite3.connect(temporary)
        try: original.backup(copied)
        finally: copied.close(); original.close()
        temporary.chmod(0o600); temporary.replace(target)
    for name in ('session_memory.json', '.backend-auth-token'):
        source = root/'lyra-backend/data'/name
        destination = data/name
        if source.is_file() and not source.is_symlink() and not destination.exists():
            shutil.copyfile(source,destination); destination.chmod(0o600)
    preferences = support/'workspace-settings.json'
    if not preferences.exists():
        paths = [root,Path.home()/'Desktop',Path.home()/'Documents',Path.home()/'Downloads']
        preferences.write_text(json.dumps({'workspaceRoots':[str(item) for item in paths if item.is_dir()]},indent=2))
        preferences.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,default=Path('/Applications/Lyra.app'))
    parser.add_argument('--support',type=Path,default=Path.home()/'Library/Application Support/Lyra')
    args = parser.parse_args()
    metadata = json.loads((ROOT/'build/mac-artifact.json').read_text())
    source = Path(metadata['appPath'])
    if args.destination.name != 'Lyra.app': parser.error('Destination must be named Lyra.app')
    for app in (source,args.destination):
        if app.exists():
            with (app/'Contents/Info.plist').open('rb') as stream: info=plistlib.load(stream)
            if info.get('CFBundleIdentifier') != 'com.lyra.desktop':
                raise RuntimeError(f'Refusing to replace an unrelated application: {app}')
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(source)],check=True)
    migrate_data(ROOT,args.support)
    args.destination.parent.mkdir(parents=True,exist_ok=True)
    staging = args.destination.parent/f'.Lyra-install-{uuid.uuid4().hex}.app'
    subprocess.run(['/usr/bin/ditto',str(source),str(staging)],check=True)
    if args.destination.exists():
        backup = args.destination.with_name(f'Lyra.previous-{datetime.now():%Y%m%d-%H%M%S}.app')
        args.destination.rename(backup)
    staging.rename(args.destination)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(args.destination)],check=True)
    print(f'Installed: {args.destination}')
    print(f'Saved data and settings: {args.support}')


if __name__=='__main__': main()
