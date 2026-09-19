"""Native game mapping drafts and learning never activate a device implicitly."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtWidgets import QApplication
from mozaproxy.game_mapping_editor import GameMappingEditor
from mozaproxy.game_mappings import default_mapping


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = GameMappingEditor()
        self.addCleanup(self.editor.deleteLater)
        self.editor.select_game('heat', default_mapping('heat'))

    def test_editing_preserves_draft_across_snapshots_and_games(self):
        self.editor.target.setCurrentIndex(self.editor.target.findData('g920'))
        self.editor.axis_inverts['steering'].setChecked(True)
        self.editor.observe({'axes': [], 'buttons': []})
        self.editor.select_game('ac', default_mapping('ac'))
        self.editor.select_game('heat', default_mapping('heat'))
        self.assertTrue(self.editor.mapping()['axes']['steering']['inverted'])
        self.assertTrue(self.editor.dirty)
        self.assertEqual(self.editor.mapping()['buttons'][4:6], [301,300])

    def test_learning_requires_fresh_single_press_and_cancels_on_game_change(self):
        self.editor.target.setCurrentIndex(1)
        self.editor.observe({'buttons':[{'code':296,'pressed':True}]})
        self.editor.learn_button(0)
        self.editor.observe({'buttons':[{'code':296,'pressed':True}]})
        self.assertEqual(self.editor.mapping()['buttons'][0],639)
        self.editor.observe({'buttons':[{'code':296,'pressed':False}]})
        self.editor.observe({'buttons':[{'code':296,'pressed':True}]})
        self.assertEqual(self.editor.mapping()['buttons'][0],296)
        self.editor.learn_button(1)
        self.editor.select_game('ac', default_mapping('ac'))
        self.assertIsNone(self.editor.learning)

    def test_save_signal_contains_draft_and_apply_disabled_until_saved(self):
        saved=[]; started=[]
        self.editor.save_requested.connect(saved.append)
        self.editor.start_requested.connect(started.append)
        self.editor.target.setCurrentIndex(1)
        self.assertFalse(self.editor.start_button.isEnabled())
        self.editor.save_button.click()
        self.assertEqual(saved,[self.editor.mapping()])
        self.assertEqual(started,[])
        self.editor.saved(saved[0])
        self.assertTrue(self.editor.start_button.isEnabled())
        self.editor.start_button.click()
        self.assertEqual(started,['heat'])

    def test_duplicate_assignments_show_error_without_losing_edits(self):
        self.editor.target.setCurrentIndex(1)
        combo=self.editor.axis_sources['brake']; combo.setCurrentIndex(combo.findData(2))
        self.assertFalse(self.editor.save_button.isEnabled())
        self.assertIn('only once',self.editor.message.text())
        self.assertEqual(combo.currentData(),2)

    def test_live_status_distinguishes_draft_and_direct_restart(self):
        self.editor.target.setCurrentIndex(1)
        saved=self.editor.mapping(); self.editor.saved(saved)
        self.editor.set_runtime(running=True,live_game='heat',live_status={'mapping':saved})
        self.editor.axis_inverts['steering'].setChecked(True)
        self.assertIn('Unsaved',self.editor.message.text())
        self.editor.target.setCurrentIndex(0)
        self.editor.saved(self.editor.mapping())
        self.assertIn('Stop',self.editor.message.text())
        self.assertFalse(self.editor.apply_button.isEnabled())
