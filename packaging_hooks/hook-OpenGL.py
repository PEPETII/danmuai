"""DanmuAI's focused PyOpenGL hook.

The upstream hook copies every file under ``OpenGL/DLLS``. That directory
contains optional legacy GLUT/GLE binaries built against MSVCR90, while the
application uses OpenGL.GL through live2d-py and the system/Qt OpenGL stack.
Keep the import coverage needed by PyOpenGL without shipping those unused
optional binaries.
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    "OpenGL.platform.win32",
    *collect_submodules("OpenGL.arrays"),
]
datas = []
