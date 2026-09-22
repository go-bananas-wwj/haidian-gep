import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class DeploymentScriptTests(unittest.TestCase):
    def test_backup_and_restore_copy_a_consistent_runtime_database(self):
        """Break caught: a host backup could omit SQLite state or restore over a non-empty runtime."""
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            runtime, backups, restored = work / "runtime", work / "backups", work / "restored"
            runtime.mkdir()
            database = runtime / "tasks.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE evidence (value TEXT)")
                connection.execute("INSERT INTO evidence VALUES ('reviewed-maize')")
            env = {**os.environ, "GEP_RUNTIME_DIR": str(runtime), "GEP_BACKUP_DIR": str(backups)}

            backup = subprocess.run([str(root / "deploy" / "backup.sh")], env=env, text=True, capture_output=True, check=True)
            archive = Path(backup.stdout.strip())
            restore_env = {**env, "GEP_RESTORE_DIR": str(restored), "GEP_RESTORE_CONFIRM": "restore-runtime"}
            subprocess.run([str(root / "deploy" / "restore.sh"), str(archive)], env=restore_env, check=True)

            with sqlite3.connect(restored / "tasks.sqlite3") as connection:
                value = connection.execute("SELECT value FROM evidence").fetchone()[0]
            self.assertEqual(value, "reviewed-maize")
            self.assertTrue((archive / "tasks.sqlite3.sha256").is_file())
