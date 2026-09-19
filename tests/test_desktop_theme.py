"""Exercise desktop startup and live palette changes without wheel hardware."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from PySide6.QtCore import QPluginLoader, qVersion


class DesktopThemeTests(unittest.TestCase):
    def test_qt6ct_palette_loads_and_changes_without_restarting(self):
        plugin = Path('/usr/lib/qt6/plugins/platformthemes/libqt6ct.so')
        metadata = QPluginLoader(str(plugin)).metaData()
        version = tuple(map(int, qVersion().split('.')[:2]))
        compiled = metadata.get('version', 0)
        if (compiled >> 16, (compiled >> 8) & 255) != version:
            self.skipTest('A matching system qt6ct plugin is not installed')
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='qt6ct',
                       XDG_CONFIG_HOME=directory, XDG_RUNTIME_DIR=directory)
            env.pop('QT_PLUGIN_PATH', None)
            env.pop('QT_STYLE_OVERRIDE', None)
            script = textwrap.dedent('''\
                import json, os, time
                from pathlib import Path
                from unittest.mock import patch
                from PySide6.QtCore import QSettings, QTimer
                from PySide6.QtGui import QColor, QPalette
                from PySide6.QtWidgets import QApplication
                from mozaproxy import desktop
                from tests.test_desktop import Fake

                root = Path(os.environ['XDG_CONFIG_HOME']) / 'qt6ct'
                root.mkdir()
                config = QSettings(str(root / 'qt6ct.conf'), QSettings.IniFormat)
                palette = QPalette()
                for name, background, text in [('dark', '#23242c', '#ffffff'),
                                                ('light', '#e9e5f0', '#16131d')]:
                    colors = QSettings(str(root / (name + '.conf')), QSettings.IniFormat)
                    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                        for role in (QPalette.Window, QPalette.Base, QPalette.Button):
                            palette.setColor(group, role, QColor(background))
                        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
                            palette.setColor(group, role, QColor(text))
                        palette.setColor(group, QPalette.Highlight, QColor('#a179d0'))
                    for key, group in [('active', QPalette.Active),
                                       ('inactive', QPalette.Inactive),
                                       ('disabled', QPalette.Disabled)]:
                        colors.setValue('ColorScheme/' + key + '_colors',
                            [palette.color(group, QPalette.ColorRole(i)).name(QColor.HexArgb)
                             for i in range(QPalette.NColorRoles.value)])
                    colors.sync()
                config.setValue('Appearance/style', 'Fusion')
                config.setValue('Appearance/custom_palette', True)
                config.setValue('Appearance/color_scheme_path', str(root / 'dark.conf'))
                config.setValue('Appearance/icon_theme', 'test-icons')
                config.sync()
                result = {}
                original = desktop.MainWindow
                class Window(original):
                    def __init__(self, backend):
                        super().__init__(backend, start_polling=False)
                        self.set_draft('rotation', 900)
                        result['startup'] = self.palette().color(QPalette.Window).name()
                        result['paths'] = QApplication.libraryPaths()
                        self.deadline = time.monotonic() + 7
                        QTimer.singleShot(100, self.change_theme)
                    def change_theme(self):
                        config.setValue('Appearance/color_scheme_path', str(root / 'light.conf'))
                        config.sync()
                        self.check_theme()
                    def check_theme(self):
                        color = self.palette().color(QPalette.Window).name()
                        if color == '#e9e5f0' or time.monotonic() >= self.deadline:
                            result['changed'] = color
                            result['draft'] = self.draft
                            self.close()
                        else:
                            QTimer.singleShot(50, self.check_theme)
                with patch.object(desktop, 'MainWindow', Window), \
                     patch('mozaproxy.service_client.select_backend', return_value=Fake()):
                    desktop.main([])
                print(json.dumps(result))
            ''')
            run = subprocess.run([sys.executable, '-c', script], env=env,
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertEqual(result['startup'], '#23242c', run.stderr)
            self.assertEqual(result['changed'], '#e9e5f0', run.stderr)
            self.assertEqual(result['draft'], {'rotation': 900})
            # Keep bundled platform plugins first; add desktop integration after.
            self.assertIn('PySide6', result['paths'][0])
