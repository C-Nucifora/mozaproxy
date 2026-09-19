"""Let bundled PySide6 discover the Linux desktop's native theme plugins."""
import logging
from pathlib import Path
import sys
import sysconfig

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QPluginLoader, qVersion

log = logging.getLogger(__name__)


def system_plugin_roots():
    roots = [Path('/usr/lib/qt6/plugins'), Path('/usr/lib64/qt6/plugins'),
             Path('/usr/local/lib/qt6/plugins')]
    multiarch = sysconfig.get_config_var('MULTIARCH')
    if multiarch:
        roots.append(Path('/usr/lib') / multiarch / 'qt6/plugins')
    return roots


def configure_desktop_plugins():
    """Run before QApplication; preserve existing plugin and theme preferences.

    Platform themes use Qt private APIs, so only add system roots containing a
    theme built for the same Qt major/minor and build mode. Qt still performs
    its own plugin checks. Missing/incompatible integrations keep Qt's defaults.
    Append roots so bundled Wayland/XCB plugins retain precedence. No global
    environment, colour configuration, or palette is changed by the app.
    """
    if sys.platform != 'linux' or QCoreApplication.instance() is not None:
        return []
    version = tuple(map(int, qVersion().split('.')[:2]))
    paths = QCoreApplication.libraryPaths()
    added = []
    for root in system_plugin_roots():
        if str(root) in paths:
            continue
        for plugin in (root / 'platformthemes').glob('*.so'):
            metadata = QPluginLoader(str(plugin)).metaData()
            compiled = metadata.get('version', 0)
            if (compiled >> 16, (compiled >> 8) & 255) != version:
                continue
            if metadata.get('debug', False) != QLibraryInfo.isDebugBuild():
                continue
            if 'QPlatformThemeFactoryInterface' not in metadata.get('IID', ''):
                continue
            paths.append(str(root))
            added.append(str(root))
            break
    if added:
        QCoreApplication.setLibraryPaths(paths)
        log.debug('Added native desktop plugin paths: %s', added)
    return added
