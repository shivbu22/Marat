# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

datas = [
    ('src/api/static', 'src/api/static'),
    ('data/knowledge', 'data/knowledge'),
    ('configs', 'configs'),
]

hiddenimports = [
    'uvicorn',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'starlette',
    'starlette.middleware',
    'starlette.middleware.cors',
    'starlette.responses',
    'pydantic',
    'pydantic_settings',
    'rich',
    'rich.console',
    'rich.table',
    'rich.panel',
    'rich.progress',
    'rich.markdown',
    'typer',
    'duckduckgo_search',
    'ddgs',
    'youtube_transcript_api',
    'yt_dlp',
    'chromadb',
    'chromadb.telemetry.opentelemetry',
    'langchain_core',
    'langchain_core.messages',
    'langchain_core.tools',
    'langchain_openai',
    'langchain_text_splitters',
    'sqlite3',
    'whisper',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Marat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Marat',
)
