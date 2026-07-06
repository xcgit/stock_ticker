"""
PyInstaller runtime hook: patch py_mini_racer._get_lib_path to find mini_racer.dll correctly.

Problem: py_mini_racer's _get_lib_path() only checks sys._MEIPASS root directory for the DLL,
         but PyInstaller may place it in different locations depending on the spec config.

Solution: Monkey-patch _get_lib_path to also check:
  1. sys._MEIPASS root (e.g., _MEIxxx/mini_racer.dll)
  2. sys._MEIPASS/py_mini_racer/ subdirectory (e.g., _MEIxxx/py_mini_racer/mini_racer.dll)
  3. The py_mini_racer package directory within MEIPASS
  4. The exe's own directory (for side-by-side DLL placement)
"""
import sys
import os

def _patched_get_lib_path(name):
    """Patched version of py_mini_racer._get_lib_path that searches multiple locations."""
    if sys.platform == "win32":
        prefix, ext = "", ".dll"
    elif os.name == "posix" and sys.platform == "darwin":
        prefix, ext = "lib", ".dylib"
    else:
        prefix, ext = "lib", ".so"

    dll_name = prefix + name + ext

    # 1. Check MEIPASS root (PyInstaller's default for binaries dest='.')
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        # Original behavior: check MEIPASS root
        fn = os.path.join(meipass, dll_name)
        if os.path.exists(fn):
            return fn
        # Also check py_mini_racer subdirectory in MEIPASS
        fn = os.path.join(meipass, "py_mini_racer", dll_name)
        if os.path.exists(fn):
            return fn

    # 2. Check exe's own directory (side-by-side DLL)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        fn = os.path.join(exe_dir, dll_name)
        if os.path.exists(fn):
            return fn
        fn = os.path.join(exe_dir, "py_mini_racer", dll_name)
        if os.path.exists(fn):
            return fn

    # 3. Fallback to pkg_resources
    try:
        import pkg_resources
        fn = pkg_resources.resource_filename("py_mini_racer", dll_name)
        if os.path.exists(fn):
            return fn
    except (ImportError, Exception):
        pass

    # 4. Fallback to package directory
    try:
        import py_mini_racer
        root_dir = os.path.dirname(os.path.abspath(py_mini_racer.__file__))
        fn = os.path.join(root_dir, dll_name)
        if os.path.exists(fn):
            return fn
    except (ImportError, Exception):
        pass

    # Last resort: return the MEIPASS root path even if file doesn't exist yet
    # (py_mini_racer will raise its own error)
    if meipass is not None:
        return os.path.join(meipass, dll_name)

    return None


def _patch_py_mini_racer():
    """Apply the patch to py_mini_racer."""
    try:
        # Import the submodule and patch _get_lib_path
        from py_mini_racer import py_mini_racer as _pmr_module
        _pmr_module._get_lib_path = _patched_get_lib_path
        # Recalculate EXTENSION_PATH since it's set at module load time
        _pmr_module.EXTENSION_PATH = _patched_get_lib_path("mini_racer")
        _pmr_module.EXTENSION_NAME = os.path.basename(_pmr_module.EXTENSION_PATH) if _pmr_module.EXTENSION_PATH else None
        # Rebuild the extension handle if already loaded
        if hasattr(_pmr_module, '_build_ext_handle'):
            try:
                _pmr_module._build_ext_handle()
            except Exception:
                pass
    except ImportError:
        pass  # py_mini_racer not used in this application


# Apply the patch immediately
_patch_py_mini_racer()
