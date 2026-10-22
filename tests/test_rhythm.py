"""Audio-level regression tests use the real Rubber Band R3 implementation.

Build host bindings first: python3 build_rubberband.py --host
"""
import sys,pathlib,tempfile,unittest,wave,json
import numpy as np
import mido
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'native-build/host'),str(ROOT/'app/src/main/python')]
import engine,rhythm
from alignment import midi_events,align_groups,time_map
from vocal_analysis import detect_units,voice_events


class RhythmTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=pathlib.Path(self.tmp.name)
        self.wav=self.d/'voice.wav';self.mid=self.d/'melody.mid';self.out=self.d/'out.wav';self.cancel=self.d/'cancel'
    def tearDown(self):self.tmp.cleanup()
    def source(self,events,duration):
        x=np.zeros(round(duration*32000))
        for a,b,f in events:
            n=round((b-a)*32000);t=np.arange(n)/32000
            tone=sum(.25/h*np.sin(2*np.pi*f*h*t) for h in range(1,5))
            fade=min(160,n//4)
            tone[:fade]*=np.linspace(0,1,fade);tone[-fade:]*=np.linspace(1,0,fade)
            start=round(a*32000);x[start:start+n]+=tone
        engine.write_wav(self.wav,x);return x
    def midi(self,events,trailing=0):
        mid=mido.MidiFile();tr=mido.MidiTrack();mid.tracks.append(tr);msgs=[]
        for a,b,pitch in events:msgs.extend([(round(a*960),'note_on',pitch),(round(b*960),'note_off',pitch)])
        prev=0
        for tick,kind,p in sorted(msgs):tr.append(mido.Message(kind,note=p,time=tick-prev));prev=tick
        tr.append(mido.MetaMessage('end_of_track',time=round(trailing*960)));mid.save(self.mid)
    def render(self,offset=0,mute=False,callback=None):
        return json.loads(rhythm.render(self.wav,self.mid,0,offset,mute,self.out,self.cancel,callback))
    def audio(self,path=None):
        with wave.open(str(path or self.out)) as w:
            self.assertEqual((w.getframerate(),w.getnchannels(),w.getsampwidth()),(32000,1,2))
            return np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(float)/32768
    def fundamental(self,y):
        y=y*np.hanning(len(y));spectrum=abs(np.fft.rfft(y));f=np.fft.rfftfreq(len(y),1/32000)
        return float(f[np.argmax(spectrum)])
    def variable_fixture(self):
        self.source([(.2,.5,220),(.9,1.7,330),(2.,2.4,440)],3.2)
        # Different target melody: timing must not depend on matching pitches.
        self.midi([(.1,.7,65),(.9,1.3,54),(2.,3.,60)])
    def test_real_r3_stretches_and_compresses_without_changing_pitch(self):
        self.source([(0,1,220)],1)
        for samples in [16000,32000,64000]:
            with self.subTest(output_frames=samples):
                rhythm.stretch_to_wav(self.wav,self.out,0,32000,0,samples,samples,[(0,0),(32000,samples)],[{'start':0,'end':samples}],False,self.cancel)
                y=self.audio();self.assertEqual(len(y),samples)
                self.assertAlmostEqual(self.fundamental(y[1600:-1600]),220,delta=3)
                self.assertGreater(np.sqrt(np.mean(y[-4800:-800]**2)),.08)
    def test_attack_timing_measured_from_output_audio(self):
        self.variable_fixture();report=self.render(mute=False);y=self.audio()
        env=np.sqrt(np.mean(y.reshape(-1,160)**2,axis=1));active=env>.03
        edges=np.diff(np.r_[False,active,False].astype(int))
        starts=np.flatnonzero(edges==1)*.005;ends=np.flatnonzero(edges==-1)*.005
        np.testing.assert_allclose(starts,[.1,.9,2.],atol=.015)
        np.testing.assert_allclose(ends,[.7,1.3,3.],atol=.02)
        self.assertEqual(report['engine'],'Rubber Band 4.0.0 R3')
        self.assertTrue(report['time_stretch']);self.assertFalse(report['pitch_shift'])
    def test_different_midi_melody_does_not_change_original_pitches(self):
        self.variable_fixture();self.render();y=self.audio()
        for a,b,f in [(.2,.6,220),(1.,1.2,330),(2.2,2.8,440)]:
            self.assertAlmostEqual(self.fundamental(y[round(a*32000):round(b*32000)]),f,delta=5)
    def test_long_note_contains_sustained_voice_instead_of_padding_or_cropping(self):
        self.source([(.1,.4,220)],1.8);self.midi([(.1,1.6,65)]);self.render(mute=True)
        y=self.audio();windows=y[round(.2*32000):round(1.5*32000)].reshape(-1,320)
        rms=np.sqrt(np.mean(windows**2,axis=1))
        self.assertGreater(float(np.min(rms)),.05)
        self.assertLess(float(np.max(np.abs(np.diff(y[6400:48000])))),.2)
    def test_legato_notes_do_not_create_tremolo_or_chopped_gaps(self):
        self.source([(0,1,220)],1)
        self.midi([(i/10,(i+1)/10,60+i%3) for i in range(10)])
        self.render(mute=True);y=self.audio()[1600:30400]
        rms=np.sqrt(np.mean(y.reshape(-1,160)**2,axis=1))
        self.assertGreater(float(np.min(rms)),float(np.median(rms))*.65)
    def test_short_note_preserves_tail_tone_after_compression(self):
        self.source([(.1,.6,220),(.6,1.1,330)],1.5);self.midi([(.1,.7,69)])
        self.render();y=self.audio()
        self.assertAlmostEqual(self.fundamental(y[round(.5*32000):round(.65*32000)]),330,delta=8)
    def test_midi_rests_are_silent_when_enabled(self):
        self.variable_fixture();self.render(mute=True);y=self.audio()
        self.assertTrue(np.all(y[22400:28800]==0));self.assertTrue(np.all(y[41600:64000]==0))
    def test_result_duration_uses_shorter_file(self):
        self.source([(.1,.5,220)],1)
        for end,offset,expected in [(.6,0,.6),(1.7,0,1),(.6,.1,.7)]:
            with self.subTest(midi_end=end,offset=offset):
                self.midi([(.1,end,62)]);self.render(offset=offset)
                self.assertEqual(len(self.audio()),round(expected*32000))
    def test_trailing_midi_rest_is_preserved(self):
        self.source([(.1,.5,220)],2);self.midi([(.1,.8,60)],trailing=.4);self.render()
        y=self.audio();self.assertEqual(len(y),38400);self.assertTrue(np.all(y[25600:]==0))
    def test_silent_and_quiet_recordings(self):
        self.midi([(0,1,60)])
        for level in [0,.0003]:
            t=np.arange(32000)/32000;engine.write_wav(self.wav,level*np.sin(2*np.pi*220*t));self.render()
            y=self.audio();self.assertEqual(len(y),32000)
            if level==0:self.assertTrue(np.all(y==0))
            else:self.assertGreater(np.max(np.abs(y)),.0001)
    def test_short_attack_is_not_rejected(self):
        self.source([(.2,.22,220)],1);self.midi([(.1,.6,60)]);self.render()
        self.assertEqual(len(self.audio()),19200)
    def test_chords_use_selected_melody_policy(self):
        ns=[(0,1,60,100),(0,.5,72,100)]
        self.assertEqual(midi_events(ns,32000,0,policy='high')[0]['pitch'],72)
        self.assertEqual(midi_events(ns,32000,0,policy='low')[0]['pitch'],60)
    def test_negative_offset_clips_notes_at_zero(self):
        self.source([(.1,.6,220)],1);self.midi([(.1,.8,60)]);self.render(offset=-.2)
        self.assertEqual(len(self.audio()),19200)
    def test_cancel_during_native_study_preserves_previous_output(self):
        self.source([(.1,.7,220)],1);self.midi([(.1,.8,60)]);self.out.write_bytes(b'previous')
        parent=self
        class Callback:
            def progress(self,value):
                if value>=30:parent.cancel.touch()
        with self.assertRaises(InterruptedError):self.render(callback=Callback())
        self.assertEqual(self.out.read_bytes(),b'previous')
    def test_invalid_audio_still_reports_format_error(self):
        with wave.open(str(self.wav),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(32000);w.writeframes(bytes(32000*4))
        self.midi([(0,1,60)])
        with self.assertRaisesRegex(ValueError,'PCM16'):self.render()
    def test_many_to_one_keeps_all_events_in_chronological_order(self):
        self.source([(.1,.4,220),(.5,.8,330),(.9,1.2,440)],1.6);self.midi([(.1,1.4,66)])
        report=self.render();self.assertEqual(report['matched_groups'],1)
        y=self.audio();self.assertGreater(np.max(abs(y[round(1.1*32000):round(1.35*32000)])),.05)
    def test_203_vocal_events_390_midi_notes_no_forced_chopping(self):
        events=[(i*.12+.01,i*.12+.09,220) for i in range(203)]
        self.source(events,24.36)
        self.assertEqual(len(detect_units(self.wav,.12,self.cancel)),203)
        spacing=24.36/390
        self.midi([(i*spacing,(i+1)*spacing,60+(i%4)) for i in range(390)])
        report=self.render(mute=True);self.assertEqual(report['notes'],390)
        self.assertGreater(report['matched_groups'],0);self.assertTrue(report['time_stretch'])
        self.assertEqual(len(self.audio()),min(round(mido.MidiFile(self.mid).length*32000),round(24.36*32000)))
    def test_alignment_is_independent_of_target_pitch(self):
        src=[{'start':i*1000,'end':i*1000+800,'pitch':60+i} for i in range(4)]
        target=[{'start':i*1200,'end':i*1200+900,'pitch':p} for i,p in enumerate([60,61,62,63])]
        groups=align_groups(src,target,self.cancel)
        for x in target:x['pitch']=float(90-x['pitch'])
        self.assertEqual(groups,align_groups(src,target,self.cancel))
    def test_large_tracks_use_monotonic_bounded_alignment(self):
        src=[{'start':i*1000,'end':i*1000+800,'pitch':None} for i in range(800)]
        target=[{'start':i*800,'end':i*800+600,'pitch':60} for i in range(1200)]
        groups=align_groups(src,target,self.cancel)
        self.assertEqual(groups[0][:3],(0,1,0));self.assertEqual(groups[-1][1],800);self.assertEqual(groups[-1][3],1200)
        for left,right in zip(groups,groups[1:]):self.assertEqual(left[1],right[0]);self.assertEqual(left[3],right[2])
        _,_,_,_,anchors=time_map(src,target,groups)
        for left,right in zip(anchors,anchors[1:]):self.assertGreater(right[0],left[0]);self.assertGreater(right[1],left[1])

if __name__=='__main__':unittest.main()
