import sys, pathlib, tempfile, unittest, wave, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'app/src/main/python'))
import engine
import numpy as np
import mido

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def midi(self, seconds=1, pitch=69):
        mid=mido.MidiFile()
        tempo=mido.MidiTrack(); mid.tracks.append(tempo)
        tempo.append(mido.MetaMessage('set_tempo',tempo=500000,time=0))
        track=mido.MidiTrack(); mid.tracks.append(track)
        track.append(mido.MetaMessage('track_name', name='Voice'))
        track.append(mido.Message('note_on',note=pitch,velocity=100,time=0))
        track.append(mido.Message('note_off',note=pitch,time=round(seconds*960)))
        p=self.d/'test.mid';mid.save(p);return p
    def test_global_tempo_map_and_noteoff_zero(self):
        m=mido.MidiFile(); t=mido.MidiTrack(); m.tracks.append(t)
        t.extend([mido.MetaMessage('set_tempo',tempo=500000),mido.MetaMessage('set_tempo',tempo=1000000,time=480)])
        v=mido.MidiTrack();m.tracks.append(v)
        v.extend([mido.Message('note_on',note=60,velocity=90),mido.Message('note_on',note=60,velocity=0,time=960)])
        p=self.d/'tempo';m.save(p)
        self.assertAlmostEqual(engine.read_midi(p)[0]['notes'][0][1],1.5)
    def test_polyphony_offset_transposition(self):
        notes=[(0,1,60,100),(0,1,72,100)]
        t=np.array([0.,.5,1.,1.5])
        high=engine.melody(t,notes,'high',.5,-12)
        low=engine.melody(t,notes,'low',.5,0)
        np.testing.assert_allclose(high,low)
        self.assertEqual(high[0],0);self.assertEqual(high[-1],0)
    def test_rmid(self):
        p=self.midi();data=p.read_bytes();chunk=b'data'+len(data).to_bytes(4,'little')+data
        p.write_bytes(b'RIFF'+(len(chunk)+4).to_bytes(4,'little')+b'RMID'+chunk)
        self.assertEqual(engine.read_midi(p)[0]['count'],1)
    def test_reject_type2(self):
        m=mido.MidiFile(type=2);m.tracks.append(mido.MidiTrack());p=self.d/'bad.mid';m.save(p)
        with self.assertRaises(ValueError): engine.read_midi(p)
    def test_preview_pitch(self):
        p=self.midi(pitch=69);out=self.d/'preview.wav';engine.preview(p,1,'high',0,str(out))
        with wave.open(str(out)) as w: x=np.frombuffer(w.readframes(w.getnframes()),'<i2')
        f=np.fft.rfftfreq(16000,1/engine.RATE)[np.argmax(abs(np.fft.rfft(x[3200:19200])))]
        self.assertAlmostEqual(f,440,delta=3)
    def test_render_pitch_and_exact_duration_across_boundary(self):
        import pyworld as pw
        # Exceeds an eight-second block by less than its margin: regression case.
        seconds=8.1; count=int(seconds*engine.RATE)
        t=np.arange(count)/engine.RATE
        x=sum(.18/h*np.sin(2*np.pi*220*h*t) for h in range(1,9))
        wav=self.d/'source.wav';out=self.d/'result.wav';engine.write_wav(wav,x)
        engine.render(str(wav),self.midi(seconds,pitch=69),1,'high',0,0,False,str(out),str(self.d/'cancel'))
        with wave.open(str(out)) as w:
            self.assertEqual(w.getnframes(),count)
            y=np.frombuffer(w.readframes(count),'<i2').astype(np.float64)/32768
        # Independent frequency measurement, rather than testing WORLD against itself.
        section=y[engine.RATE:2*engine.RATE]
        spectrum=abs(np.fft.rfft(section*np.hanning(len(section))))
        frequency=np.fft.rfftfreq(len(section),1/engine.RATE)
        peak=float(frequency[np.argmax(spectrum)])
        self.assertAlmostEqual(peak,440,delta=3)
        self.assertGreater(spectrum[440],spectrum[220]*4)
        self.assertTrue(np.isfinite(y).all())
    def test_cancel(self):
        w=self.d/'in.wav';engine.write_wav(w,np.zeros(engine.RATE))
        c=self.d/'cancel';c.touch()
        with self.assertRaises(InterruptedError):
            engine.render(str(w),self.midi(),1,'high',0,0,False,str(self.d/'out.wav'),str(c))

    def test_output_duration_uses_shorter_file(self):
        count = engine.RATE
        t = np.arange(count)/engine.RATE
        x = sum(.18/h*np.sin(2*np.pi*220*h*t) for h in range(1,9))
        wav=self.d/'in.wav';engine.write_wav(wav,x)
        for midi_seconds, offset, expected in [(.65,0,.65),(1.7,0,1),(1,0,1),(.65,.1,.75)]:
            with self.subTest(midi_seconds=midi_seconds, offset=offset):
                out=self.d/'out.wav'
                engine.render(str(wav),self.midi(midi_seconds),1,'high',offset,0,False,str(out),str(self.d/'cancel'))
                with wave.open(str(out)) as w:
                    self.assertEqual(w.getnframes(),round(expected*engine.RATE))

if __name__=='__main__': unittest.main()
