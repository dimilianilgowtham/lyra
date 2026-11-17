"""Installation preserves saved data and never overwrites an existing profile."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


class InstallMigrationTests(unittest.TestCase):
    def test_sqlite_backup_and_settings_are_private_and_idempotent(self):
        source = Path(__file__).resolve().parents[2] / 'scripts/install_macos.py'
        self.assertTrue(source.exists(), 'Installer migration is required')
        spec = importlib.util.spec_from_file_location('lyra_install', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root, support = Path(folder)/'source', Path(folder)/'profile'
            data = root/'lyra-backend/data'; data.mkdir(parents=True)
            (root/'.env').write_text('OPENAI_API_KEY=synthetic-key\nDATABASE_PATH=lyra-backend/data/lyra.db\n')
            (data/'session_memory.json').write_text('{"notes":["keep me"]}')
            original = sqlite3.connect(data/'lyra.db')
            original.execute('PRAGMA journal_mode=WAL')
            original.execute('CREATE TABLE proof(value TEXT)')
            original.execute('INSERT INTO proof VALUES (?)', ('saved conversation',)); original.commit()
            module.migrate_data(root, support)
            copied = sqlite3.connect(support/'data/lyra.db')
            self.assertEqual(copied.execute('SELECT value FROM proof').fetchone()[0], 'saved conversation')
            copied.execute('INSERT INTO proof VALUES (?)', ('installed change',)); copied.commit(); copied.close()
            module.migrate_data(root, support)
            copied = sqlite3.connect(support/'data/lyra.db')
            self.assertEqual(copied.execute('SELECT COUNT(*) FROM proof').fetchone()[0], 2)
            copied.close(); original.close()
            self.assertIn('synthetic-key', (support/'.env').read_text())
            self.assertEqual((support/'.env').stat().st_mode & 0o777, 0o600)
            self.assertEqual((support/'data/session_memory.json').read_text(), '{"notes":["keep me"]}')
