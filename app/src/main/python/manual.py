"""Explicit, accessible fragment editing; positions are MIDI quarter-note beats.

Displayed beats start at 1. The stored quarter coordinate starts at 0 and is
converted through the MIDI's complete tempo map (also for type 1/RMID files).
"""
import bisect
import json
import math
import os
import tempfile
import wave
import numpy as np
from engine import RATE, load_midi, render_region
from vocal_analysis import check_cancel
from rhythm import stretch_to_wav, write_silence
from alignment import midi_events


def tempo_grid(path):
    mid = load_midi(path)
    changes = []
    for ti, track in enumerate(mid.tracks):
        tick = 0
        for order, msg in enumerate(track):
            tick += msg.time
            if msg.type == 'set_tempo':
                changes.append((tick, ti, order, msg.tempo))
    grid = [[0., 0., .5]]  # quarter, seconds, seconds per quarter
    for tick, _, _, tempo in sorted(changes):
        if tempo <= 0:
            raise ValueError('Недопустимый темп MIDI')
        q = tick / mid.ticks_per_beat
        prev = grid[-1]
        item = [q, prev[1] + (q-prev[0])*prev[2], tempo/1000000.]
        if q == prev[0]:
            grid[-1] = item
        else:
            grid.append(item)
    return grid


def to_seconds(grid, quarter):
    item = grid[max(0, bisect.bisect_right([x[0] for x in grid], quarter)-1)]
    return item[1] + (quarter-item[0])*item[2]


def to_quarters(grid, seconds):
    item = grid[max(0, bisect.bisect_right([x[1] for x in grid], seconds)-1)]
    return item[0] + (seconds-item[1])/item[2]


def inspect(wav, midi, track, offset):
    with wave.open(str(wav), 'rb') as src:
        count = src.getnframes()
    _, length = render_region(midi, track, count, float(offset))
    return json.dumps({'source_seconds': count/RATE, 'output_seconds': length/RATE,
                       'grid': tempo_grid(midi)})


def validated(plan_json, source_seconds, output_seconds, grid, offset):
    try:
        plan = json.loads(str(plan_json))
        if plan.get('schema') != 1:
            raise ValueError('Неизвестный формат ручной разметки')
        segments = plan['segments']
        if not isinstance(segments, list) or not 1 <= len(segments) <= 2000:
            raise ValueError('Нужен хотя бы один фрагмент; максимум 2000')
        result = []
        for number, segment in enumerate(segments, 1):
            a,b,q,r = [float(segment[k]) for k in
                       ('source_start','source_end','target_start_q','target_end_q')]
            if not all(math.isfinite(x) for x in (a,b,q,r)):
                raise ValueError()
            start = round((to_seconds(grid,q)+offset)*RATE)
            end = round((to_seconds(grid,r)+offset)*RATE)
            sa,sb = round(a*RATE),round(b*RATE)
            if (sa < 0 or sb > round(source_seconds*RATE) or sb-sa < 320
                    or q < 0 or r <= q or start < 0 or end > round(output_seconds*RATE)
                    or end-start < 320):
                raise ValueError(f'Фрагмент {number}: границы вне записи, вне MIDI или длительность меньше 0,01 секунды')
            result.append(dict(segment, a=sa, b=sb, start=start, end=end, number=number))
        result.sort(key=lambda s:s['start'])
        for prev,cur in zip(result,result[1:]):
            if cur['start'] < prev['end']:
                raise ValueError(f'Фрагменты {prev["number"]} и {cur["number"]} перекрываются в MIDI')
        return result
    except (KeyError, TypeError, json.JSONDecodeError, AttributeError):
        raise ValueError('Некорректная ручная разметка. Откройте редактор и сохраните фрагменты.') from None


class FragmentProgress:
    def __init__(self, callback, index, count):
        self.callback,self.index,self.count = callback,index,count
    def progress(self, percent):
        if self.callback is not None:
            self.callback.progress(round((self.index+percent/100)/self.count*99))


def render(wav,midi,track,offset,mute,output,cancel,plan_json,callback=None,policy='high'):
    offset = float(offset)
    metadata = json.loads(inspect(wav,midi,track,offset))
    segments = validated(plan_json, metadata['source_seconds'], metadata['output_seconds'],metadata['grid'],offset)
    notes,length = render_region(midi,track,round(metadata['source_seconds']*RATE),offset)
    events = midi_events(notes,length,offset,policy=policy)
    check_cancel(cancel)
    # Transactional even when called directly. No partial output on failure/cancel.
    with tempfile.TemporaryDirectory(prefix='manual-',dir=os.path.dirname(os.path.abspath(output))) as folder:
        result = os.path.join(folder,'result.wav')
        has_signal = False
        with wave.open(result,'wb') as dest:
            dest.setnchannels(1);dest.setsampwidth(2);dest.setframerate(RATE)
            position = 0
            for index,s in enumerate(segments):
                check_cancel(cancel)
                write_silence(dest,s['start']-position,cancel)
                ni,no = s['b']-s['a'],s['end']-s['start']
                local_events=[dict(start=max(0,e['start']-s['start']),end=min(no,e['end']-s['start']))
                              for e in events if e['end']>s['start'] and e['start']<s['end']]
                piece=os.path.join(folder,'piece.wav')
                stretch_to_wav(wav,piece,s['a'],s['b'],0,no,no,[(0,0),(ni,no)],
                               local_events,bool(mute),cancel,FragmentProgress(callback,index,len(segments)))
                with wave.open(piece,'rb') as src:
                    p=0
                    while p<no:
                        check_cancel(cancel)
                        y=np.frombuffer(src.readframes(min(RATE,no-p)),'<i2').astype(np.float64)
                        ids=np.arange(p,p+len(y))
                        # Explicit cuts need a short de-click envelope, not note-by-note gating.
                        y*=np.minimum(1.,np.minimum(ids/96,(no-1-ids)/160))
                        has_signal = has_signal or bool(np.any(np.abs(y)>=1))
                        dest.writeframesraw(y.astype('<i2').tobytes());p+=len(y)
                position=s['end']
            write_silence(dest,length-position,cancel)
        check_cancel(cancel)
        os.replace(result,output)
    return json.dumps({'engine':'Rubber Band 4.0.0 R3','manual':True,'fragments':len(segments),'seconds':length/RATE,'silent':not has_signal})


def preview(wav,midi,track,offset,segment_json,output,cancel,metronome=False):
    """One edited fragment with no leading silence; preserve its exact tempo-map duration."""
    metadata=json.loads(inspect(wav,midi,track,offset))
    plan=json.dumps({'schema':1,'segments':[json.loads(segment_json)]})
    s=validated(plan,metadata['source_seconds'],metadata['output_seconds'],metadata['grid'],float(offset))[0]
    ni,no=s['b']-s['a'],s['end']-s['start']
    check_cancel(cancel)
    stretch_to_wav(wav,output,s['a'],s['b'],0,no,no,[(0,0),(ni,no)],[],False,cancel)
    if metronome:
        # Clicks follow the tempo map, not a constant BPM approximation.
        grid=metadata['grid'];segment=json.loads(segment_json)
        positions=[round((to_seconds(grid,q)+float(offset))*RATE)-s['start']
                   for q in range(math.ceil(float(segment['target_start_q'])),math.ceil(float(segment['target_end_q'])))]
        click=.22*np.sin(2*np.pi*1500*np.arange(640)/RATE)*np.exp(-np.arange(640)/90)
        temp=str(output)+'.click.tmp'
        try:
            with wave.open(str(output),'rb') as src,wave.open(temp,'wb') as dest:
                dest.setparams(src.getparams());position=0
                while position<no:
                    check_cancel(cancel)
                    y=np.frombuffer(src.readframes(RATE),'<i2').astype(float)/32768*.75
                    for at in positions:
                        lo=max(0,at-position);hi=min(len(y),at+len(click)-position)
                        if hi>lo:y[lo:hi]+=click[position+lo-at:position+hi-at]
                    dest.writeframesraw((np.clip(y,-1,1)*32767).astype('<i2').tobytes());position+=len(y)
            os.replace(temp,output)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return json.dumps({'seconds':no/RATE})


def constrain_tuned(wav, midi, track, offset, plan_json, output, cancel):
    """WORLD must not fill deliberately empty manual slots with synthesized noise."""
    metadata=json.loads(inspect(wav,midi,track,offset))
    # Original source bounds were already checked before stretching. Only target
    # slots matter here; tuned audio itself has the shorter output duration.
    segments=json.loads(plan_json)['segments']
    intervals=[(round((to_seconds(metadata['grid'],float(s['target_start_q']))+float(offset))*RATE),
                round((to_seconds(metadata['grid'],float(s['target_end_q']))+float(offset))*RATE)) for s in segments]
    with wave.open(str(wav),'rb') as src,wave.open(str(output),'wb') as dest:
        dest.setparams(src.getparams());position=0
        while position<src.getnframes():
            check_cancel(cancel)
            y=np.frombuffer(src.readframes(RATE),'<i2').astype(float)
            mask=np.zeros(len(y));ids=np.arange(position,position+len(y))
            for a,b in intervals:
                lo=max(0,a-position);hi=min(len(y),b-position)
                if hi>lo:mask[lo:hi]=np.maximum(mask[lo:hi],np.minimum(1.,np.minimum((ids[lo:hi]-a)/96,(b-1-ids[lo:hi])/160)))
            dest.writeframesraw((y*mask).astype('<i2').tobytes());position+=len(y)
