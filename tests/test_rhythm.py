import sys
import pathlib
import tempfile
import unittest
import wave
import json
import numpy as np
import mido
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'app/src/main/python'))
import rhythm
import engine


class RhythmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.tmp.name)
        self.wav = self.d/'in.wav'
        self.out = self.d/'out.wav'
        self.cancel = self.d/'cancel'
        self.mid = self.d/'notes.mid'
        x = np.zeros(64000)
        # Different waveforms: verify ordering and bit-identical interiors.
        for a, frequency in [(6400, 220), (32000, 330)]:
            t = np.arange(6400)/32000
            x[a:a+6400] = .4*np.sin(2*np.pi*frequency*t)
        engine.write_wav(self.wav, x)
        self.make_midi([.1, .8])

    def tearDown(self):
        self.tmp.cleanup()

    def make_midi(self, starts, duration=.4, chord=False):
        mid = mido.MidiFile()
        track = mido.MidiTrack(); mid.tracks.append(track)
        events = []
        for start in starts:
            for pitch in ([60, 64] if chord else [60]):
                events.extend([(round(start*960), 'note_on', pitch),
                               (round((start+duration)*960), 'note_off', pitch)])
        prev = 0
        for tick, kind, pitch in sorted(events):
            track.append(mido.Message(kind, note=pitch, time=tick-prev))
            prev = tick
        mid.save(self.mid)

    def render(self, offset=0, mute=False):
        return json.loads(rhythm.render(str(self.wav), self.mid, 0, offset, mute,
                                       str(self.out), str(self.cancel)))

    def pcm(self, path):
        with wave.open(str(path)) as src:
            return np.frombuffer(src.readframes(src.getnframes()), '<i2')

    def test_sample_placement_and_unmodified_interiors(self):
        units = rhythm.detect_units(self.wav, .12, self.cancel)
        self.assertEqual(len(units), 2)
        report = self.render(offset=.12345)
        x, y = self.pcm(self.wav), self.pcm(self.out)
        for (a, b), target in zip(units, [.22345, .92345]):
            pos = round(target*32000)
            np.testing.assert_array_equal(y[pos+256:pos+b-a-256], x[a+256:b-256])
        self.assertEqual(len(y), round(1.32345*32000))
        self.assertFalse(report['time_stretch'])
        self.assertTrue(np.all(y[:round(.22345*32000)] == 0))

    def test_chords_one_event(self):
        self.make_midi([.1, .8], chord=True)
        self.assertEqual(self.render()['slices'], 2)

    def test_mismatch_preserves_existing_output(self):
        self.make_midi([0])
        self.out.write_bytes(b'existing')
        with self.assertRaisesRegex(ValueError, 'фрагментов: 2'):
            self.render()
        self.assertEqual(self.out.read_bytes(), b'existing')

    def test_no_compression_or_truncation(self):
        self.make_midi([0, .1])
        with self.assertRaisesRegex(ValueError, 'не помещается'):
            self.render()

    def test_noteoff_constraint_optional(self):
        self.make_midi([.1, .8], duration=.1)
        self.render()
        with self.assertRaisesRegex(ValueError, 'не помещается'):
            self.render(mute=True)

    def test_negative_offset_rejected(self):
        with self.assertRaisesRegex(ValueError, 'раньше нуля'):
            self.render(offset=-1)

    def test_silent_input(self):
        engine.write_wav(self.wav, np.zeros(32000))
        with self.assertRaisesRegex(ValueError, 'тихий'):
            self.render()

    def test_cancellation(self):
        self.cancel.touch()
        with self.assertRaises(InterruptedError):
            self.render()

    def test_connected_units_split_at_deep_valley(self):
        t = np.arange(32000)/32000
        env = .3 - .28*np.exp(-((t-.5)/.025)**2)
        engine.write_wav(self.wav, env*np.sin(2*np.pi*220*t))
        units = rhythm.detect_units(self.wav, .06, self.cancel)
        self.assertEqual(len(units), 2)
        self.assertLess(abs(units[0][1]/32000-.5), .02)
        self.assertEqual(units[0][1], units[1][0])

    def test_long_fragment_streaming(self):
        self.make_midi([.1], duration=3)
        t = np.arange(80000)/32000
        engine.write_wav(self.wav, .4*np.sin(2*np.pi*220*t))
        self.render()
        np.testing.assert_array_equal(self.pcm(self.wav)[256:-256],
                                      self.pcm(self.out)[3200+256:83200-256])

if __name__ == '__main__':
    unittest.main()
