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

    def test_more_fragments_than_notes_are_grouped_in_order(self):
        self.make_midi([0], duration=1.5)
        units = rhythm.detect_units(self.wav, .12, self.cancel, max_frames=48000)
        report = self.render()
        self.assertEqual(report['detected_units'], 2)
        self.assertEqual(report['slices'], 1)
        a, b = units[0][0], units[-1][1]
        np.testing.assert_array_equal(self.pcm(self.out)[256:b-a-256],
                                      self.pcm(self.wav)[a+256:b-256])

    def test_long_fragment_is_cropped_instead_of_rejected(self):
        self.make_midi([0, .1], duration=1.2)
        report = self.render()
        self.assertGreater(report['trimmed_slices'], 0)
        self.assertEqual(len(self.pcm(self.out)), 41600)
        self.assertEqual(self.pcm(self.out)[3199], 0)

    def test_noteoff_constraint_trims_and_mutes_gaps(self):
        x = self.pcm(self.wav).copy()
        x[16000:22400] = x[32000:38400]
        x[32000:38400] = 0
        engine.write_wav(self.wav, x.astype(float)/32767)
        self.make_midi([.1, .8], duration=.1)
        self.assertEqual(self.render()['trimmed_slices'], 1)
        report = self.render(mute=True)
        y = self.pcm(self.out)
        self.assertEqual(report['trimmed_slices'], 2)
        self.assertTrue(np.all(y[6400:25600] == 0))
        self.assertGreater(np.max(np.abs(y[3200:6400])), 1000)
        self.assertGreater(np.max(np.abs(y[25600:28800])), 1000)

    def test_negative_offset_rejected(self):
        with self.assertRaisesRegex(ValueError, 'сдвиг|раньше нуля'):
            self.render(offset=-1)

    def test_silent_input_returns_silence(self):
        engine.write_wav(self.wav, np.zeros(32000))
        self.render()
        self.assertEqual(len(self.pcm(self.out)), 32000)
        self.assertTrue(np.all(self.pcm(self.out) == 0))

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
        np.testing.assert_array_equal(self.pcm(self.wav)[256:76800-256],
                                      self.pcm(self.out)[3200+256:80000-256])


    def test_longer_vocal_discards_tail_before_segmentation(self):
        self.make_midi([.1], duration=.5)
        report = self.render()
        self.assertEqual(len(self.pcm(self.out)), 19200)
        self.assertEqual(report['slices'], 1)

    def test_longer_midi_ignores_later_onsets(self):
        self.make_midi([.1, .8, 2., 3.], duration=.4)
        report = self.render()
        self.assertEqual(len(self.pcm(self.out)), 64000)
        self.assertEqual(report['slices'], 2)

    def test_terminal_syllable_is_cropped_at_midi_end(self):
        t = np.arange(32000)/32000
        engine.write_wav(self.wav, .4*np.sin(2*np.pi*220*t))
        self.make_midi([.1], duration=.25)
        self.render(mute=True)
        x, y = self.pcm(self.wav), self.pcm(self.out)
        self.assertEqual(len(y), 11200)
        np.testing.assert_array_equal(x[256:7744], y[3456:10944])
        self.assertEqual(y[-1], 0)

    def test_boundary_note_is_excluded(self):
        self.make_midi([.1, .8, 2.], duration=.4)
        self.assertEqual(self.render()['slices'], 2)
        self.assertEqual(len(self.pcm(self.out)), 64000)

    def test_midi_trailing_rest_counts_towards_file_duration(self):
        self.make_midi([.1, .8], duration=.4)
        mid = mido.MidiFile(self.mid)
        mid.tracks[0][-1].time += 480
        mid.save(self.mid)
        self.render()
        self.assertEqual(len(self.pcm(self.out)), 54400)

    def test_positive_offset_cannot_extend_past_source(self):
        self.make_midi([.1, .8, 2.], duration=.4)
        self.render(offset=.2)
        self.assertEqual(len(self.pcm(self.out)), 64000)


    def test_user_case_203_fragments_and_390_notes(self):
        count = round(203*.12*32000)
        x = np.zeros(count)
        tone = .4*np.sin(2*np.pi*220*np.arange(2560)/32000)
        for i in range(203):
            a = i*3840+320
            x[a:a+2560] = tone
        engine.write_wav(self.wav, x)
        self.assertEqual(len(rhythm.detect_units(self.wav, .12, self.cancel)), 203)
        spacing = (count/32000)/390
        self.make_midi([i*spacing for i in range(390)], duration=spacing)
        report = self.render()
        self.assertEqual(report['detected_units'], 203)
        self.assertEqual(report['slices'], 390)
        self.assertFalse(report['time_stretch'])
        expected = min(count, round(mido.MidiFile(self.mid).length*32000))
        self.assertEqual(len(self.pcm(self.out)), expected)
        self.assertGreater(np.count_nonzero(self.pcm(self.out)), count//10)

    def test_any_positive_number_of_notes_succeeds(self):
        for n in [1, 2, 3, 7, 20, 100]:
            with self.subTest(notes=n):
                self.make_midi([i*2/n for i in range(n)], duration=2/n)
                report = self.render()
                self.assertEqual(report['slices'], n)
                self.assertEqual(len(self.pcm(self.out)), 64000)

    def test_split_ranges_preserve_all_source_samples_once(self):
        units = [(0, 1200), (1800, 2200), (2700, 4700)]
        env = np.ones(30)
        env[5] = .01
        for count in [4, 7, 11, 100, 5000]:
            with self.subTest(slices=count):
                slices = rhythm.adapt_units(units, count, env, self.cancel)
                self.assertEqual(len(slices), count)
                # Independently mark consumed source samples to prove no loss or repeat.
                consumed = np.zeros(4700, dtype=int)
                for a, b in slices:
                    consumed[a:b] += 1
                expected = np.zeros(4700, dtype=int)
                for a, b in units:
                    expected[a:b] = 1
                np.testing.assert_array_equal(consumed, expected)

    def test_short_attack_below_detector_minimum_still_renders(self):
        x = np.zeros(64000)
        x[6400:6720] = .4*np.sin(2*np.pi*220*np.arange(320)/32000)
        engine.write_wav(self.wav, x)
        report = self.render()
        self.assertEqual(report['slices'], 2)
        self.assertGreater(np.count_nonzero(self.pcm(self.out)), 0)

    def test_quiet_recording_keeps_audible_samples(self):
        t = np.arange(32000)/32000
        engine.write_wav(self.wav, .0003*np.sin(2*np.pi*220*t))
        self.make_midi([0], duration=1)
        self.render()
        np.testing.assert_array_equal(self.pcm(self.wav)[256:-256],
                                      self.pcm(self.out)[256:-256])

    def test_more_note_onsets_than_active_source_samples(self):
        slices = rhythm.adapt_units([(0, 2)], 8, np.ones(1), self.cancel)
        self.assertEqual(len(slices), 8)
        self.assertEqual(sum(b-a for a, b in slices), 2)
        self.assertEqual(slices[0][0], 0)
        self.assertEqual(slices[-1][1], 2)

    def test_cancel_during_adaptation_preserves_existing_result(self):
        self.out.write_bytes(b'previous WAV')
        self.cancel.touch()
        with self.assertRaises(InterruptedError):
            self.render()
        self.assertEqual(self.out.read_bytes(), b'previous WAV')

if __name__ == '__main__':
    unittest.main()
