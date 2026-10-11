import copy
import json
from pathlib import Path
import unittest
from tools import application_update_test, control

ROOT = Path(__file__).resolve().parents[1]

class ApplicationUpdateTests(unittest.TestCase):
    def candidate(self):
        value = json.loads((ROOT / 'releases/0.1.3.json').read_text())
        for key in ['releaseId', 'frontendReleaseId', 'frontendVersion', 'backendVersion']:
            value[key] = '0.1.4'
        for key in ['backend', 'frontend', 'gateway', 'tools']:
            value['images'][key] = value['images'][key].replace(':0.1.3@', ':0.1.4@')
        return value

    def test_all_published_baselines_retain_their_exact_infrastructure_and_history(self):
        for filename, version in application_update_test.BASES.values():
            with self.subTest(filename=filename):
                base = json.loads((ROOT / 'releases' / filename).read_text())
                self.assertEqual(base['releaseId'], version)
                selected = application_update_test.compatible(base, self.candidate())
                control.validate_update(base, selected)
                self.assertEqual(set(control.changes(base, selected)), {'backend', 'frontend'})
                for key in ['postgres', 'tools', 'gateway']:
                    self.assertEqual(selected['images'][key], base['images'][key])
                self.assertEqual(selected['migrations'][:len(base['migrations'])], base['migrations'])
                if version == '0.1.3': self.assertEqual(selected['migrations'], base['migrations'])

    def test_acceptance_cannot_change_existing_history_or_strand_pending_clients(self):
        for filename in ['0.1.0.json', '0.1.3.json']:
            base = json.loads((ROOT / 'releases' / filename).read_text())
            for kind in ['history', 'client', 'version', 'schema']:
                value = self.candidate()
                if kind == 'history': value['migrations'][0]['sha256'] = 'e' * 64
                elif kind == 'client': value['supportedClientContractHashes'] = ['e' * 64]
                elif kind == 'version': value['backendVersion'] = '0.1.5'
                else: value['migrations'].pop()
                with self.subTest(filename=filename, kind=kind), self.assertRaises((AssertionError, control.Failure)):
                    application_update_test.compatible(base, value)

    def test_same_application_version_has_three_distinct_retained_infrastructures(self):
        baselines = [json.loads((ROOT / 'releases' / name).read_text()) for name in
                     ['0.1.3.json', '0.1.3-update.json', '0.1.3-update-from-0.1.1.json']]
        self.assertEqual({item['releaseId'] for item in baselines}, {'0.1.3'})
        self.assertEqual(len({item['images']['tools'] for item in baselines}), 3)
        for base in baselines:
            selected = application_update_test.compatible(base, self.candidate())
            self.assertEqual(selected['source']['delivery'], base['source']['delivery'])

if __name__ == '__main__': unittest.main()
