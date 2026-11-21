import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')


def run(*cmd):
    print('>', ' '.join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def main():
    os.makedirs(os.path.join(APP, 'copfly'), exist_ok=True)
    run(sys.executable, '-m', 'ziglang', 'cc', '-target', 'x86-windows-gnu', '-shared', '-O2', '-s',
        '-o', os.path.join(APP, 'copfly', 'NFSMWCopFly.asi'), os.path.join(ROOT, 'copfly', 'copfly.c'))
    for junk in ('NFSMWCopFly.lib', 'NFSMWCopFly.pdb'):
        p = os.path.join(APP, 'copfly', junk)
        if os.path.exists(p):
            os.remove(p)
    if not os.path.exists(os.path.join(APP, 'assets', 'icon.ico')):
        run(sys.executable, os.path.join('tools', 'make_icon.py'))
    sep = os.pathsep
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
        '--name', 'NFSMW-Mod-Studio', '--icon', os.path.join(APP, 'assets', 'icon.ico'),
        '--add-data', os.path.join(APP, 'assets') + sep + 'assets',
        '--add-data', os.path.join(APP, 'ui') + sep + 'ui',
        '--add-data', os.path.join(APP, 'copfly', 'NFSMWCopFly.asi') + sep + 'copfly',
        '--collect-all', 'webview', '--exclude-module', 'tkinter', '--exclude-module', 'customtkinter',
        '--distpath', os.path.join(ROOT, 'dist'), '--workpath', os.path.join(ROOT, 'build'),
        '--specpath', os.path.join(ROOT, 'build'),
        os.path.join(APP, 'modstudio.py'))
    shutil.copy2(os.path.join(APP, 'copfly', 'NFSMWCopFly.asi'), os.path.join(ROOT, 'dist', 'NFSMWCopFly.asi'))
    print('\nBuilt dist/NFSMW-Mod-Studio.exe (and dist/NFSMWCopFly.asi for manual installs)')


if __name__ == '__main__':
    main()
