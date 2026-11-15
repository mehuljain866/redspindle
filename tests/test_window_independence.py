import unittest
import customtkinter as ctk
from pathlib import Path
from gui import (
    register_subwindow,
    unregister_subwindow,
    get_active_subwindows,
    _active_subwindows,
)


class WindowIndependenceTests(unittest.TestCase):
    def setUp(self):
        _active_subwindows.clear()

    def test_registry_tracking(self):
        class DummyWindow:
            def __init__(self, name):
                self.name = name
            def winfo_exists(self):
                return True

        w1 = DummyWindow("w1")
        w2 = DummyWindow("w2")

        register_subwindow(w1)
        register_subwindow(w2)
        active = get_active_subwindows()
        self.assertEqual(len(active), 2)
        self.assertIn(w1, active)
        self.assertIn(w2, active)

        unregister_subwindow(w1)
        active = get_active_subwindows()
        self.assertEqual(len(active), 1)
        self.assertIn(w2, active)

        unregister_subwindow(w2)
        active = get_active_subwindows()
        self.assertEqual(len(active), 0)

    def test_dialog_classes_have_fullscreen_and_destroy(self):
        from gui import DownsizeDialog, FixAlbumTagsDialog, ExplicitLyricsDialog
        from cd_prep import CDBurnPrepDialog
        from cd_art import CDArtStudioDialog

        dialog_classes = [
            DownsizeDialog,
            FixAlbumTagsDialog,
            ExplicitLyricsDialog,
            CDBurnPrepDialog,
            CDArtStudioDialog,
        ]

        for cls in dialog_classes:
            self.assertTrue(
                hasattr(cls, "_toggle_fullscreen"),
                f"{cls.__name__} must define _toggle_fullscreen for F11/maximize support"
            )
            self.assertTrue(
                hasattr(cls, "destroy"),
                f"{cls.__name__} must override destroy to clean up subwindow registry"
            )


if __name__ == "__main__":
    unittest.main()
