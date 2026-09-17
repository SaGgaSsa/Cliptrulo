from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
GUARDS = """
import builtins
import os
import sys

sys.modules['google'] = None
sys.modules['gemini_worker'] = None
original_open = builtins.open

def guarded_open(file, *args, **kwargs):
    if isinstance(file, (str, bytes, os.PathLike)):
        if os.path.basename(os.fsdecode(file)).lower() == '.env':
            raise AssertionError('.env must not be opened')
    return original_open(file, *args, **kwargs)

builtins.open = guarded_open
"""


class PipelineContractTests(unittest.TestCase):
    def run_isolated(self, code, timeout=30):
        env = os.environ.copy()
        for key in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS'):
            env.pop(key, None)
        result = subprocess.run(
            [sys.executable, '-B', '-c', GUARDS + code],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_real_montage_synthetic(self):
        from openshorts_common import FF, FPROBE

        probe = shutil.which(FPROBE)
        if probe is None:
            candidate = Path(FF).with_name('ffprobe.exe')
            self.assertTrue(candidate.is_file(), f'FFprobe unavailable: {FPROBE}, {candidate}')
            probe = str(candidate)

        def run_media(command):
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=120,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                self.fail(f'Media command failed: {command!r}: {error}')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result

        with tempfile.TemporaryDirectory(
            dir=r'C:\Users\saggassa\AppData\Local\Temp\opencode'
        ) as directory:
            base = Path(directory)
            video = base / 'synthetic.mp4'
            words = base / 'words.json'
            out = base / 'output'
            out.mkdir()
            run_media([
                FF, '-nostdin', '-v', 'error',
                '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=24',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                '-t', '17', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-threads', '1', str(video),
            ])
            words.write_text(json.dumps([
                {'word': 'inicio', 'start': 0, 'end': 0.5},
                {'word': 'regresion', 'start': 1, 'end': 2},
                {'word': 'final', 'start': 14, 'end': 15},
            ]), encoding='utf-8')
            items = base / 'items.json'
            picks = base / 'picks.json'
            silences = base / 'silences.json'
            montages = out / 'montages.json'
            item = {
                'start': 0, 'end': 17, 'kind': 'presentacion',
                'score': 85, 'summary': 'Prueba sintetica',
            }
            items.write_text(json.dumps({'items': [item]}), encoding='utf-8')
            picks.write_text(json.dumps({
                'clips': [{
                    'rank': 1,
                    'item': item,
                    'spans': [{'start': 0, 'end': 15, 'role': 'presentacion'}],
                }],
            }), encoding='utf-8')
            silences.write_text(json.dumps([
                {'start': 0.5, 'end': 1},
                {'start': 2, 'end': 14},
                {'start': 15, 'end': 17},
            ]), encoding='utf-8')
            picks_argv = [
                'montage_from_picks.py', '--words', str(words),
                '--items', str(items), '--picks', str(picks),
                '--silences', str(silences), '--montages', str(montages),
            ]
            validated = self.run_isolated(
                f'\nimport runpy\nsys.argv = {picks_argv!r}\n'
                'runpy.run_path("montage_from_picks.py", run_name="__main__")\n'
            )
            self.assertTrue(montages.is_file(), validated.stdout + validated.stderr)
            montage_list = json.loads(montages.read_text(encoding='utf-8'))['montages']
            self.assertEqual(len(montage_list), 1)
            self.assertEqual(montage_list[0]['rank'], 1)
            total = montage_list[0]['total']
            self.assertGreaterEqual(total, 15)
            self.assertLessEqual(total, 17)
            for span in montage_list[0]['spans']:
                self.assertGreaterEqual(span['start'], 0)
                self.assertLessEqual(span['end'], 17)
            argv = [
                'openshorts_v2.py', '--video', str(video), '--words', str(words),
                '--section', '00:00-00:17', '--offset', '0', '--out', str(out),
                '--phase', 'montage',
            ]
            result = self.run_isolated(
                f'\nimport runpy\nsys.argv = {argv!r}\n'
                'runpy.run_path("openshorts_v2.py", run_name="__main__")\n',
                timeout=120,
            )
            diagnostics = result.stdout + result.stderr
            self.assertNotIn('MONTAGE-FAIL', diagnostics, diagnostics)
            mp4 = out / 'clip_01.mp4'
            srt = out / 'clip_01.srt'
            for artifact in (mp4, srt):
                self.assertTrue(artifact.is_file(), diagnostics)
                self.assertGreater(artifact.stat().st_size, 0, diagnostics)
            self.assertIn('regresion', srt.read_text(encoding='utf-8'))
            metadata = json.loads(run_media([
                probe, '-v', 'error', '-show_streams', '-show_format',
                '-of', 'json', str(mp4),
            ]).stdout)
            videos = [s for s in metadata['streams'] if s['codec_type'] == 'video']
            audios = [s for s in metadata['streams'] if s['codec_type'] == 'audio']
            self.assertEqual(len(videos), 1, metadata)
            self.assertEqual(len(audios), 1, metadata)
            self.assertEqual(videos[0]['codec_name'], 'h264')
            self.assertEqual(audios[0]['codec_name'], 'aac')
            self.assertEqual((videos[0]['width'], videos[0]['height']), (160, 90))
            self.assertEqual(Fraction(videos[0]['avg_frame_rate']), 24)
            duration = float(metadata['format']['duration'])
            self.assertAlmostEqual(duration, total, delta=0.2)
            self.assertGreaterEqual(duration, 15)
            self.assertLessEqual(duration, 17)

    def test_only_montage_phase_is_available(self):
        import openshorts_common
        import openshorts_v2
        import openshorts_v2lib

        self.assertFalse(hasattr(openshorts_common, 'stage'))
        self.assertFalse(hasattr(openshorts_v2, 'phase_segment'))
        self.assertFalse(hasattr(openshorts_v2, 'phase_highlight'))
        self.assertFalse(hasattr(openshorts_v2lib, 'HIGHLIGHT_PROMPT_TEMPLATE'))
        self.assertFalse((ROOT / 'openshorts_run.py').exists())
        result = self.run_isolated(
            '\nimport runpy\nsys.argv = ["openshorts_v2.py", "--help"]\n'
            'runpy.run_path("openshorts_v2.py", run_name="__main__")\n'
        )
        self.assertIn('--phase {montage}', result.stdout)
        self.assertNotIn('--clips', result.stdout)

    def test_montage_imports_without_sdk_or_credentials(self):
        self.run_isolated(
            '\nimport openshorts_common\nimport montage_from_picks\nimport openshorts_v2\n'
        )

    def test_montage_scripts_help_without_sdk_or_credentials(self):
        for script in ('montage_from_picks.py', 'openshorts_v2.py'):
            with self.subTest(script=script):
                result = self.run_isolated(
                    f'\nimport runpy\nsys.argv = [{script!r}, "--help"]\n'
                    f'runpy.run_path({script!r}, run_name="__main__")\n'
                )
                self.assertIn('--help', result.stdout)
                self.assertIn('--words', result.stdout)


if __name__ == '__main__':
    unittest.main()
