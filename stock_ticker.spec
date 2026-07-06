# -*- mode: python ; coding: utf-8 -*-
import os, site

base_dir = os.path.abspath(SPECPATH)
sp = [p for p in site.getsitepackages() if 'site-packages' in p][0]

a = Analysis(
    [os.path.join(base_dir, 'stock_ticker.py')],
    pathex=[base_dir],
    binaries=[
        # Put mini_racer.dll in MEIPASS root directory ('.')
        # The runtime hook will search both root and py_mini_racer/ subdirectory
        (os.path.join(sp, 'py_mini_racer', 'mini_racer.dll'), '.'),
    ],
    datas=[
        (os.path.join(base_dir, '水晶包.png'), '.'),
        (os.path.join(base_dir, '水晶包2.png'), '.'),
    ],
    hiddenimports=[
        'pystray._win32',
        'win32api',
        'win32gui',
        'win32con',
        'py_mini_racer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        os.path.join(base_dir, 'hook_py_mini_racer_rt.py'),
    ],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='stock_ticker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(base_dir, '水晶包.ico'),
)
