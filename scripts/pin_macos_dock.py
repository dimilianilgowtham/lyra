"""Pin the installed Lyra app without replacing other Dock items."""
from pathlib import Path
import plistlib
import subprocess
import xml.etree.ElementTree as ET


def main():
    app = Path('/Applications/Lyra.app')
    if not app.is_dir(): raise RuntimeError('Install Lyra before pinning it in the Dock.')
    raw = subprocess.check_output(['/usr/bin/defaults','export','com.apple.dock','-'])
    preferences = plistlib.loads(raw)
    items = preferences.get('persistent-apps', [])
    def matches(item):
        data = item.get('tile-data', {})
        return data.get('bundle-identifier') == 'com.lyra.desktop' or data.get('file-data', {}).get('_CFURLString', '').rstrip('/') == app.as_uri()
    if not any(matches(item) for item in items):
        backup = Path.home()/'Library/Application Support/Lyra/dock-before-install.plist'
        if not backup.exists(): backup.write_bytes(raw); backup.chmod(0o600)
        entry = {'tile-type':'file-tile','tile-data':{'file-data':{'_CFURLString':app.as_uri()+'/', '_CFURLStringType':15},'file-label':'Lyra','bundle-identifier':'com.lyra.desktop','file-type':41}}
        dictionary = ET.tostring(ET.fromstring(plistlib.dumps(entry)).find('dict'),encoding='unicode')
        subprocess.run(['/usr/bin/defaults','write','com.apple.dock','persistent-apps','-array-add',dictionary],check=True)
        subprocess.run(['/usr/bin/killall','Dock'],check=True)
    verified = plistlib.loads(subprocess.check_output(['/usr/bin/defaults','export','com.apple.dock','-']))
    if not any(matches(item) for item in verified.get('persistent-apps', [])):
        raise RuntimeError('Dock preference verification failed.')
    print('Lyra is pinned in the Dock. Other Dock items were retained.')


if __name__=='__main__': main()
