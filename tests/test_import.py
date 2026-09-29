import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('importer', Path(__file__).resolve().parents[1] / 'tools/import_actions.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImportTests(unittest.TestCase):
    def test_all_channels_and_read_only_source(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'example.d6a'
            with sqlite3.connect(p) as db:
                db.execute('CREATE TABLE ActionGroup ("Index" INTEGER, Time INTEGER,' + ','.join(f'Servo{i} INTEGER' for i in range(1,19)) + ')')
                db.execute('INSERT INTO ActionGroup VALUES (' + ','.join('?' * 20) + ')', [1,500]+[500]*18)
            db.close()
            before=p.read_bytes()
            a=module.read_action(p,{'pitch':1500,'yaw':1530})
            self.assertEqual(len(a['frames'][0]['target']),20)
            self.assertEqual(a['duration'],.5)
            self.assertEqual(p.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
