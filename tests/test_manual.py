"""Real-DSP checks for manual timing, tempo maps, and sequential retuning."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import wave
import numpy as np
import mido
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'native-build/host'),str(ROOT/'app/src/main/python')]
import engine,manual,pipeline


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.d=pathlib.Path(self.temp.name)
        self.wav=self.d/'voice.wav';self.mid=self.d/'music.mid';self.out=self.d/'out.wav';self.cancel=self.d/'cancel'
        t=np.arange(64000)/32000
        x=sum(.18/h*np.sin(2*np.pi*220*h*t) for h in range(1,9))
        engine.write_wav(self.wav,x)
        mid=mido.MidiFile();tr=mido.MidiTrack();mid.tracks.append(tr)
        tr.append(mido.Message('note_on',note=69,velocity=100))
        tr.append(mido.Message('note_off',note=69,time=1920));mid.save(self.mid)
    def tearDown(self):self.temp.cleanup()
    def plan(self,*segments):
        return json.dumps({'schema':1,'segments':[dict(zip(('source_start','source_end','target_start_q','target_end_q'),s)) for s in segments]})
    def audio(self):
        with wave.open(str(self.out)) as src:return np.frombuffer(src.readframes(src.getnframes()),'<i2').astype(float)/32768
    def frequency(self,y):
        return np.fft.rfftfreq(len(y),1/32000)[np.argmax(abs(np.fft.rfft(y*np.hanning(len(y)))))]
    def render(self,plan,offset=0):
        return json.loads(manual.render(self.wav,self.mid,0,offset,False,self.out,self.cancel,plan))
    def test_manual_positions_gaps_duration_and_pitch(self):
        info=self.render(self.plan((0,.5,.5,1.5),(1,2,2,3.5)))
        y=self.audio();self.assertEqual(len(y),64000);self.assertTrue(info['manual'])
        self.assertEqual(np.max(abs(y[:8000])),0)
        self.assertEqual(np.max(abs(y[24000:32000])),0)
        self.assertEqual(np.max(abs(y[56000:])),0)
        self.assertGreater(np.sqrt(np.mean(y[12000:20000]**2)),.1)
        self.assertAlmostEqual(self.frequency(y[12000:20000]),220,delta=4)
    def test_explicit_source_reordering_and_reuse(self):
        info=self.render(self.plan((1,2,0,1),(0,1,1,2),(0,1,2,4)))
        self.assertEqual(info['fragments'],3);self.assertEqual(len(self.audio()),64000)
    def test_overlap_rejected_preserves_output(self):
        self.out.write_bytes(b'previous')
        with self.assertRaisesRegex(ValueError,'перекрываются'):
            self.render(self.plan((0,1,0,3),(1,2,2,4)))
        self.assertEqual(self.out.read_bytes(),b'previous')
    def test_invalid_boundaries_rejected(self):
        for segment in [(-1,1,0,2),(0,3,0,2),(0,1,0,5),(0,.001,0,1),(0,1,float('nan'),2),(0,1,-1,2)]:
            with self.subTest(segment=segment),self.assertRaises(ValueError):self.render(self.plan(segment))
    def test_shorter_input_rule_with_long_midi_and_offset(self):
        self.render(self.plan((0,2,0,3)),.25);self.assertEqual(len(self.audio()),64000)
        self.render(self.plan((0,2,0,3)),-.0);self.assertEqual(len(self.audio()),64000)
        self.render(self.plan((0,2,0,2)),-.0)
        # Short MIDI is not padded back to the longer source.
        m=mido.MidiFile(self.mid);m.tracks[0][-2].time=960;m.save(self.mid)
        self.render(self.plan((0,2,0,2)));self.assertEqual(len(self.audio()),32000)
    def test_preview_has_no_leading_silence(self):
        s=json.loads(self.plan((0,1,2,3)))['segments'][0]
        manual.preview(self.wav,self.mid,0,0,json.dumps(s),self.out,self.cancel)
        self.assertEqual(len(self.audio()),16000)
        self.assertGreater(np.sqrt(np.mean(self.audio()[1000:5000]**2)),.1)
    def test_combined_order_pitch_and_duration(self):
        events=[]
        class Callback:
            def stage(_,text):events.append(text)
            def progress(_,value):pass
        info=json.loads(pipeline.render(self.wav,self.mid,0,'high',0,0,False,self.out,self.cancel,Callback(),'both',self.plan((0,2,0,4))))
        self.assertIn('Ручное',events[0]);self.assertIn('Тюнинг',events[1])
        self.assertTrue(info['rhythm']['manual']);self.assertGreater(info['tuning']['retuned_frames'],0)
        self.assertEqual(len(self.audio()),64000)
        self.assertAlmostEqual(self.frequency(self.audio()[16000:48000]),440,delta=3)
    def test_combined_offset_not_applied_twice(self):
        pipeline.render(self.wav,self.mid,0,'high',.25,0,False,self.out,self.cancel,None,'both',self.plan((0,2,0,3.5)))
        y=self.audio();self.assertEqual(len(y),64000)
        self.assertEqual(np.max(abs(y[:7800])),0)
        self.assertAlmostEqual(self.frequency(y[20000:40000]),440,delta=4)
    def test_cancel_between_stages_preserves_output_and_cleans_temp(self):
        self.out.write_bytes(b'previous')
        class Callback:
            def stage(_,text):
                if text.startswith('2.'):self.cancel.touch()
            def progress(_,value):pass
        with self.assertRaises(Exception):pipeline.render(self.wav,self.mid,0,'high',0,0,False,self.out,self.cancel,Callback(),'both',self.plan((0,2,0,4)))
        self.assertEqual(self.out.read_bytes(),b'previous')
        self.assertFalse(list(self.d.glob('pipeline-*')));self.assertFalse(list(self.d.glob('manual-*')))
    def test_combined_automatic_and_pitch_only_modes(self):
        for mode in ('both','pitch'):
            with self.subTest(mode=mode):
                info=json.loads(pipeline.render(self.wav,self.mid,0,'high',0,0,False,self.out,self.cancel,None,mode))
                self.assertEqual(info['mode'],mode)
                self.assertEqual(len(self.audio()),64000)
                self.assertAlmostEqual(self.frequency(self.audio()[16000:48000]),440,delta=3)
    def test_silent_manual_combined_result(self):
        engine.write_wav(self.wav,np.zeros(64000))
        info=json.loads(pipeline.render(self.wav,self.mid,0,'high',0,0,False,self.out,self.cancel,None,'both',self.plan((0,2,0,4))))
        self.assertTrue(info['tuning']['silent']);self.assertEqual(np.max(abs(self.audio())),0)
    def test_preview_metronome_follows_changes(self):
        engine.write_wav(self.wav,np.zeros(64000))
        m=mido.MidiFile();tr=mido.MidiTrack();m.tracks.append(tr)
        tr.extend([mido.Message('note_on',note=69),mido.MetaMessage('set_tempo',tempo=1000000,time=480),mido.Message('note_off',note=69,time=480)])
        m.save(self.mid)
        segment=json.loads(self.plan((0,1,0,2)))['segments'][0]
        manual.preview(self.wav,self.mid,0,0,json.dumps(segment),self.out,self.cancel,True)
        y=self.audio();self.assertEqual(len(y),48000)
        self.assertGreater(np.max(abs(y[:640])),.1)
        self.assertGreater(np.max(abs(y[16000:16640])),.1)
        self.assertEqual(np.max(abs(y[32000:32640])),0)
    def test_combined_preserves_reference_silence_across_block_boundary(self):
        x=np.ones(64000)*.1;x[31700:32500]=0;x[:300]=0;x[-350:]=0;x[100:200]=.1
        reference=self.d/'aligned.wav';engine.write_wav(reference,x)
        engine.write_wav(self.out,np.ones(64000)*.2)
        dest=self.d/'quiet.wav'
        pipeline.preserve_silence(str(reference),str(self.out),str(dest),str(self.cancel))
        with wave.open(str(dest)) as src:y=np.frombuffer(src.readframes(src.getnframes()),'<i2')
        self.assertEqual(np.max(abs(y[31700:32500])),0)
        self.assertEqual(np.max(abs(y[-350:])),0)
        self.assertGreater(np.min(abs(y[400:1000])),0)
        self.assertGreater(np.min(abs(y[:100])),0)  # sub-10-ms zeros are not re-gated
    def test_tempo_map_rmid_and_java_contract(self):
        m=mido.MidiFile();a=mido.MidiTrack();b=mido.MidiTrack();m.tracks.extend([a,b])
        a.append(mido.MetaMessage('set_tempo',tempo=600000))
        a.append(mido.MetaMessage('set_tempo',tempo=1000000,time=480))
        b.append(mido.MetaMessage('set_tempo',tempo=250000,time=960));m.save(self.mid)
        grid=manual.tempo_grid(self.mid)
        self.assertEqual(grid,[[0.,0.,.6],[1.,.6,1.],[2.,1.6,.25]])
        for q in [0,.25,1,1.5,2,3,10]:self.assertAlmostEqual(manual.to_quarters(grid,manual.to_seconds(grid,q)),q)
        self.assertAlmostEqual(manual.to_seconds(grid,3),1.85)
        data=self.mid.read_bytes();riff=b'RMIDdata'+len(data).to_bytes(4,'little')+data
        self.mid.write_bytes(b'RIFF'+len(riff).to_bytes(4,'little')+riff)
        self.assertEqual(manual.tempo_grid(self.mid),grid)
        java=pathlib.Path(os.environ.get('JAVA_HOME','/workspace/jdk-21.0.8+9'))/'bin'
        if not (java/'javac').exists():self.skipTest('JDK unavailable for UI grid contract')
        harness=self.d/'GridCheck.java'
        harness.write_text('''package org.bashir.vocalmidi; public class GridCheck {public static void main(String[] a){MidiGrid g=new MidiGrid(new double[][]{{0,0,.6},{1,.6,1},{2,1.6,.25}});for(double q:new double[]{0,.25,1,1.5,2,3,10}){if(Math.abs(g.quarter(g.seconds(q))-q)>1e-9)throw new AssertionError();}if(Math.abs(g.seconds(3)-1.85)>1e-9)throw new AssertionError();}}''')
        subprocess.run([str(java/'javac'),'-d',str(self.d),str(ROOT/'app/src/main/java/org/bashir/vocalmidi/MidiGrid.java'),str(harness)],check=True,capture_output=True)
        subprocess.run([str(java/'java'),'-cp',str(self.d),'org.bashir.vocalmidi.GridCheck'],check=True,capture_output=True)
