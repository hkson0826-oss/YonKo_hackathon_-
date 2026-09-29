import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
import package_deadline_candidate as package


class DeadlinePackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yk-deadline-package-test-', dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.arena = self.root / 'arena'
        self.arena.mkdir()
        self.manifest = {'status': 'ready', 'source_commit': 'fixture', 'bots': {},
                         'frozen_sha256': {}, 'input_sha256': {}, 'policy_rng_seed': 20260927}
        for rel in ['engine/config.py', 'engine/pipeline.py', 'runner/match.py', 'mapgen/generator.py', 'config/balance.json']:
            relative = 'yk-development-tools/' + rel
            target = self.arena / 'snapshot' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package.package.ROOT / relative, target)
            self.manifest['input_sha256'][relative] = package.sha(target)
        for name in ('v4', 'new'):
            folder = self.arena / 'snapshot/candidates' / name
            folder.mkdir(parents=True)
            for file in ('main.cpp', 'protocol.hpp', 'generated.hpp', 'submission.json'):
                (folder / file).write_text(name + '/' + file)
            source = folder / 'main.cpp'
            self.manifest['bots'][name] = {'source': str(source.relative_to(self.arena)), 'source_sha256': package.sha(source)}
        self.manifest['frozen_sha256'] = {str(p.relative_to(self.arena)): package.sha(p) for p in self.arena.rglob('*') if p.is_file()}
        package.write(self.arena / 'manifest.json', self.manifest)
        self.decision = {'schema_version': 1, 'approved': True, 'candidate': 'new', 'baseline': 'v4',
                         'source_sha256': self.manifest['bots']['new']['source_sha256'],
                         'baseline_source_sha256': self.manifest['bots']['v4']['source_sha256'],
                         'rationale': 'Fixture acceptance', 'gates': {'planned_acceptance': True}}
        for stage, seed in [('selection', 120), ('final', 130)]:
            self.decision[stage] = self.add_run(stage, seed)
        self.path = self.root / 'decision.json'
        self.save_decision()

    def save_decision(self):
        package.write(self.path, self.decision)

    def add_run(self, stage, seed):
        folder = self.arena / 'runs' / stage
        folder.mkdir(parents=True)
        plan = {'candidates': ['v4', 'new'], 'opponents': ['v4'], 'map_seeds': [seed], 'replays': 'none'}
        jobs = package.league.make_jobs(plan, self.manifest['bots'])
        rows = []
        for job in jobs:
            row = {**job, 'status': 'complete', 'forfeit': False, 'win': job['candidate'] == 'new', 'draw': False,
                   'max_turn_ms': 10, 'opponent_max_turn_ms': 10, 'score_margin': 1,
                   'response_ms': [10], 'opponent_response_ms': [10],
                   'diagnostics': {side: {'engineering_turns': 1, 'late_engineering_turns': 1,
                                         'flag_contest_turns': 1, 'production': {'W': 1}} for side in 'YK'}}
            rows.append(row)
        package.write(folder / 'plan.json', plan)
        package.write(folder / 'jobs.json', jobs)
        (folder / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        package.write(folder / 'summary.json', package.league.summarize(rows, jobs))
        stamp = '2026-09-29T10:00:00+00:00' if stage == 'selection' else '2026-09-29T11:00:00+00:00'
        package.write(folder / 'session-1.json', {'status': 'complete', 'finished_utc': stamp})
        (self.arena / 'plans').mkdir(exist_ok=True)
        package.write(self.arena / 'plans' / (stage + '-policy.json'),
                      {'stage': stage, 'baseline': 'v4', 'source_sha256': {n: b['source_sha256'] for n, b in self.manifest['bots'].items()},
                       'created_utc': stamp, 'map_seeds': [seed], 'scheduled_jobs': len(jobs),
                       'source_commit': self.manifest['source_commit'], 'policy_rng_seed': self.manifest['policy_rng_seed']})
        return {'arena': str(self.arena), 'run_id': stage, 'summary_sha256': package.sha(folder / 'summary.json'),
                'results_sha256': package.sha(folder / 'results.jsonl')}

    def check(self):
        return package.check_decision(self.arena, 'new', self.path, 15000)

    def test_complete_separate_evidence_is_accepted_without_old_gates(self):
        with patch.object(package.package, 'check_gates', side_effect=AssertionError('old campaign gate must remain separate')):
            decision, manifest, evidence = self.check()
        self.assertEqual(evidence['selection']['games'], 4)
        self.assertEqual(evidence['final']['maps'], [130])

    def test_failed_acceptance_and_source_tampering_are_rejected(self):
        self.decision['gates']['planned_acceptance'] = False
        self.save_decision()
        with self.assertRaisesRegex(ValueError, 'Acceptance gates'):
            self.check()
        self.decision['gates']['planned_acceptance'] = True
        self.save_decision()
        (self.arena / self.manifest['bots']['new']['source']).write_text('different')
        with self.assertRaisesRegex(ValueError, 'Frozen hash mismatch'):
            self.check()

    def test_incomplete_results_cannot_be_hidden_by_updated_digest(self):
        path = self.arena / 'runs/final/results.jsonl'
        lines = path.read_text().splitlines()
        path.write_text('\n'.join(lines[:-1]) + '\n')
        self.decision['final']['results_sha256'] = package.sha(path)
        self.save_decision()
        with self.assertRaisesRegex(ValueError, 'Incomplete or duplicate'):
            self.check()

    def test_forged_summary_cannot_be_hidden_by_updated_digest(self):
        path = self.arena / 'runs/final/summary.json'
        summary = package.read(path)
        summary['overall']['wins'] += 1
        package.write(path, summary)
        self.decision['final']['summary_sha256'] = package.sha(path)
        self.save_decision()
        with self.assertRaisesRegex(ValueError, 'Summary does not match'):
            self.check()

    def test_selection_relabeling_and_cpu_map_reuse_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'CPU validation maps reuse'):
            package.check_decision(self.arena, 'new', self.path, 130)
        self.decision['final'] = self.decision['selection']
        self.save_decision()
        with self.assertRaisesRegex(ValueError, 'Run stage/baseline differs'):
            self.check()

    def test_policy_metadata_must_match_actual_plan_and_manifest(self):
        path = self.arena / 'plans/final-policy.json'
        original = package.read(path)
        for field, value, message in [('map_seeds', [999], 'Policy maps'),
                                      ('scheduled_jobs', 99, 'Policy scheduled job'),
                                      ('source_commit', 'different', 'Policy source commit'),
                                      ('policy_rng_seed', 0, 'Policy RNG seed')]:
            with self.subTest(field=field):
                package.write(path, {**original, field: value})
                with self.assertRaisesRegex(ValueError, message):
                    self.check()
        package.write(path, original)

    def test_record_output_cannot_mutate_an_evidence_arena(self):
        other = self.root / 'other'
        other.mkdir()
        args = argparse.Namespace(arena=other, decision_json=self.path, output_zip=self.root / 'new.zip',
                                  records=self.arena / 'unsafe-output', cpu_seed_start=15000,
                                  candidate='new', compiler='g++')
        with self.assertRaisesRegex(ValueError, 'Output overlaps frozen input'):
            package.normalized(args)
        self.assertFalse(args.records.exists())


if __name__ == '__main__':
    unittest.main()
