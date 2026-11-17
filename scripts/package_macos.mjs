/** Build a local macOS app from the installed Electron runtime and frozen backend. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {packager} from '@electron/packager';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
if (process.platform !== 'darwin') throw new Error('Build this application on macOS.');
const build = path.join(root,'build');
const backend = path.join(build,'backend/lyra-backend');
const model = path.join(root,'lyra-backend/data/models/faster-whisper-tiny');
await fs.access(path.join(backend,'lyra-backend'));
await fs.access(path.join(model,'model.bin'));
const stage = path.join(build,'mac-stage');
await fs.rm(stage,{recursive:true,force:true});
await fs.mkdir(stage,{recursive:true});
for (const name of ['electron.js','preload.js','electron','dist']) await fs.cp(path.join(root,name),path.join(stage,name),{recursive:true});
await fs.mkdir(path.join(stage,'public'),{recursive:true});
await fs.copyFile(path.join(root,'public/lyra_logo.png'),path.join(stage,'public/lyra_logo.png'));
const project = JSON.parse(await fs.readFile(path.join(root,'package.json'),'utf8'));
await fs.writeFile(path.join(stage,'package.json'),JSON.stringify({name:'lyra',productName:'Lyra',version:project.version,main:'electron.js',description:project.description},null,2));

const iconset = path.join(build,'Lyra.iconset');
await fs.mkdir(iconset,{recursive:true});
for (const size of [16,32,128,256,512]) {
  for (const scale of [1,2]) execFileSync('/usr/bin/sips',['-s','format','png','-z',String(size*scale),String(size*scale),path.join(root,'public/lyra_logo.png'),'--out',path.join(iconset,`icon_${size}x${size}${scale===2?'@2x':''}.png`)],{stdio:'ignore'});
}
const icon = path.join(build,'Lyra.icns');
execFileSync('/usr/bin/iconutil',['-c','icns',iconset,'-o',icon]);

// Reuse the vendor runtime already installed by npm, with no second download.
const electronVersion = JSON.parse(await fs.readFile(path.join(root,'node_modules/electron/package.json'),'utf8')).version;
const cache = path.join(build,'electron-cache');
await fs.mkdir(cache,{recursive:true});
const archive = path.join(cache,`electron-v${electronVersion}-darwin-${process.arch}.zip`);
try { await fs.access(archive); } catch {
  execFileSync('/usr/bin/ditto',['-c','-k','--sequesterRsrc',path.join(root,'node_modules/electron/dist'),archive]);
}
const apps = await packager({dir:stage,name:'Lyra',appBundleId:'com.lyra.desktop',appCategoryType:'public.app-category.productivity',
  platform:'darwin',arch:process.arch,electronVersion,electronZipDir:cache,out:path.join(root,'release'),overwrite:true,
  prune:false,asar:false,icon,extendInfo:{CFBundleDisplayName:'Lyra',LSUIElement:false,LSBackgroundOnly:false,
    NSMicrophoneUsageDescription:'Lyra records your voice only when you use its microphone control.',
    NSHighResolutionCapable:true}});
const appPath = path.join(apps[0], 'Lyra.app');
const resources = path.join(appPath,'Contents/Resources');
await fs.cp(backend,path.join(resources,'backend'),{recursive:true,dereference:false,verbatimSymlinks:true});
await fs.cp(model,path.join(resources,'models/faster-whisper-tiny'),{recursive:true,
  filter:source => !source.split(path.sep).includes('.cache')});
// Ad-hoc signing is for this local installation. No notarization is claimed.
execFileSync('/usr/bin/codesign',['--force','--deep','--sign','-',appPath],{stdio:'inherit'});
execFileSync('/usr/bin/codesign',['--verify','--deep','--strict',appPath],{stdio:'inherit'});
await fs.writeFile(path.join(build,'mac-artifact.json'),JSON.stringify({appPath,version:project.version,arch:process.arch},null,2));
console.log(`Lyra app ready: ${appPath}`);
