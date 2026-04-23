# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

# ── Qt .so libs to drop from bundle (not used by this app) ───────────────────
_DROP_QT = [
    'Qt6Bluetooth', 'Qt6Concurrent', 'Qt6Designer',
    'Qt6EglFSDeviceIntegration',
    'Qt6Help',
    'Qt6LabsAnimation', 'Qt6LabsFolderListModel', 'Qt6LabsPlatform',
    'Qt6LabsQmlModels', 'Qt6LabsSettings', 'Qt6LabsSharedImage',
    'Qt6LabsWavefrontMesh',
    'Qt6Multimedia', 'Qt6MultimediaQuick', 'Qt6MultimediaWidgets',
    'Qt6Network', 'Qt6Nfc',
    'Qt6OpenGL', 'Qt6OpenGLWidgets',
    'Qt6Positioning',
    'Qt6Qml', 'Qt6QmlCompiler', 'Qt6QmlCore', 'Qt6QmlMeta',
    'Qt6QmlModels', 'Qt6QmlWorkerScript',
    'Qt6Quick', 'Qt6Quick3D', 'Qt6Quick3DAssetImport',
    'Qt6Quick3DAssetUtils', 'Qt6Quick3DEffects', 'Qt6Quick3DParticles',
    'Qt6Quick3DRuntimeRender', 'Qt6Quick3DUtils',
    'Qt6QuickControls2', 'Qt6QuickControls2Impl',
    'Qt6QuickDialogs2', 'Qt6QuickDialogs2QuickImpl',
    'Qt6QuickDialogs2Utils',
    'Qt6QuickLayouts', 'Qt6QuickParticles', 'Qt6QuickShapes',
    'Qt6QuickTemplates2', 'Qt6QuickTest', 'Qt6QuickTimeline',
    'Qt6QuickWidgets',
    'Qt6RemoteObjects',
    'Qt6Sensors', 'Qt6SensorsQuick',
    'Qt6SerialBus', 'Qt6SerialPort',
    'Qt6ShaderTools',
    'Qt6Sql',
    'Qt6Svg', 'Qt6SvgWidgets',
    'Qt6Test',
    'Qt6TextToSpeech',
    'Qt6VirtualKeyboard',
    'Qt6WebChannel', 'Qt6WebChannelQuick',
    'Qt6WebEngineCore', 'Qt6WebEngineQuick', 'Qt6WebEngineWidgets',
    'Qt6WebSockets', 'Qt6WebView',
    'Qt6Xml',
    # FFmpeg bundled with Qt multimedia — not needed
    'avcodec', 'avformat', 'avutil', 'swresample', 'swscale', 'FFmpegStub',
    # Qt platform plugins we don't need
    'qoffscreen', 'qvnc', 'qlinuxfb', 'qminimal', 'qeglfs',
    # Qt image format plugins not used (fitz handles image decoding)
    'qgif', 'qtiff', 'qwebp', 'qico', 'qsvg',
]

# ── Python modules to exclude ─────────────────────────────────────────────────
_EXCL = [
    # Unused PyQt6 bindings
    'PyQt6.QtBluetooth', 'PyQt6.QtConcurrent', 'PyQt6.QtDesigner',
    'PyQt6.QtHelp', 'PyQt6.QtLocation',
    'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
    'PyQt6.QtNetwork', 'PyQt6.QtNfc',
    'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets',
    'PyQt6.QtPositioning',
    'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtRemoteObjects',
    'PyQt6.QtSensors', 'PyQt6.QtSerialBus', 'PyQt6.QtSerialPort',
    'PyQt6.QtSql',
    'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets',
    'PyQt6.QtTest', 'PyQt6.QtTextToSpeech',
    'PyQt6.QtWebChannel', 'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebEngineQuick', 'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebSockets', 'PyQt6.QtXml',
    'PyQt6.Qt3DAnimation', 'PyQt6.Qt3DCore', 'PyQt6.Qt3DExtras',
    'PyQt6.Qt3DInput', 'PyQt6.Qt3DLogic', 'PyQt6.Qt3DRender',
    'PyQt6.QtStateMachine', 'PyQt6.QtCharts', 'PyQt6.QtDataVisualization',
    # Unused Pillow format plugins (we only need PNG + JPEG for clipboard)
    'PIL.BmpImagePlugin', 'PIL.DdsImagePlugin', 'PIL.EpsImagePlugin',
    'PIL.FliImagePlugin', 'PIL.GifImagePlugin',
    'PIL.IcnsImagePlugin', 'PIL.IcoImagePlugin',
    'PIL.Jpeg2KImagePlugin',
    'PIL.McIdasImagePlugin', 'PIL.MicImagePlugin',
    'PIL.MpoImagePlugin', 'PIL.MspImagePlugin',
    'PIL.PalmImagePlugin', 'PIL.PixarImagePlugin',
    'PIL.PpmImagePlugin', 'PIL.PsdImagePlugin',
    'PIL.QoiImagePlugin', 'PIL.SgiImagePlugin',
    'PIL.SpiderImagePlugin', 'PIL.SunImagePlugin',
    'PIL.TgaImagePlugin', 'PIL.TiffImagePlugin',
    'PIL.WebPImagePlugin', 'PIL.WmfImagePlugin',
    'PIL.XbmImagePlugin', 'PIL.XpmImagePlugin',
    # Heavy / unused stdlib
    'tkinter', '_tkinter',
    'unittest', 'test',
    'distutils', 'setuptools', 'pkg_resources',
    'email', 'http', 'urllib', 'xmlrpc', 'xml',
    'multiprocessing', 'asyncio', 'concurrent.futures',
    'numpy', 'scipy', 'pandas', 'matplotlib',
    'IPython', 'jupyter',
]

# Collect pymupdf data files (fonts, resources, CMap data)
# Collect qtawesome font files (Font Awesome, Material Design, etc.)
_mupdf_datas = collect_data_files('pymupdf') + collect_data_files('fitz')
_qta_datas   = collect_data_files('qtawesome')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('pdftool.png', '.'),
        ('sign.png', '.'),
        ('VERSION', '.'),
    ] + _mupdf_datas + _qta_datas,
    hiddenimports=[
        'fitz',
        'fitz.utils',
        'fitz._extra',
        'pymupdf',
        'PIL.Image',
        'PIL.PngImagePlugin',
        'PIL.JpegImagePlugin',
        'PyQt6.sip',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtPrintSupport',
        'qtawesome',
        'qtawesome.iconic_font',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCL,
    noarchive=False,
)

# Drop unused Qt shared libraries from the bundle
a.binaries = [
    b for b in a.binaries
    if not any(tag in b[0] for tag in _DROP_QT)
]

# Drop GTK/GLib system libs — keep libqgtk3.so plugin itself,
# but rely on system-installed GTK3 (always present on GNOME/Mint/Ubuntu).
# This avoids bundling a duplicate libgtk-3.so and lets the platform theme work.
_DROP_SYSTEM_GTK = [
    'libgtk-3', 'libgdk-3', 'libgdk_pixbuf',
    'libgio-2', 'libglib-2', 'libgobject-2', 'libgmodule-2',
    'libgthread-2',
    'libpango-1', 'libpangocairo-1', 'libpangoft2-1',
    'libcairo', 'libcairo-gobject',
    'libharfbuzz',
    'libatk-1', 'libatk-bridge-2',
    'libepoxy',
    'libfontconfig',
    'libfreetype',
    'libX11', 'libXext', 'libXrender', 'libXi', 'libXfixes',
    'libxkbcommon',
]
a.binaries = [
    b for b in a.binaries
    if not any(tag in b[0] for tag in _DROP_SYSTEM_GTK)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='pdftool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[
        'libQt6Core.so.6',
        'libQt6Gui.so.6',
        'libQt6Widgets.so.6',
        '_mupdf.cpython*.so',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon='pdftool.png',
)
