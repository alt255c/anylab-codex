"""Generated projects must never default to the user's interactive workspace."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.anylogic import isolated_workspace, build_paths


class WorkspaceIsolation(unittest.TestCase):
    def test_default_builds_stay_under_the_run(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            workspace = isolated_workspace(Path(folder) / 'run')
            self.assertEqual(workspace, (Path(folder) / 'run/ide-workspace').resolve())
            os.environ['ANYLAB_IDE_WORKSPACE'] = str(workspace)
            self.assertEqual(list(build_paths('AnyLab_test')), [workspace / 'AnyLab_test_BUILD'])

    def test_explicit_workspace_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'ANYLAB_IDE_WORKSPACE': folder}):
            self.assertEqual(isolated_workspace(Path(folder) / 'run'), Path(folder).resolve())
