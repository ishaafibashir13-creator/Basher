"""Continuous, pitch-preserving MIDI timing with the Rubber Band R3 engine."""
import json
import os
import tempfile
import wave
import numpy as np
from vocal_analysis import RATE, check_cancel, detect_units, voice_events
from alignment import midi_events, align_groups, time_map


def write_silence(dest,count,cancel):
    while count>0:
        check_cancel(cancel);n=min(count,RATE);dest.writeframesraw(bytes(2*n));count-=n


def stretch_to_wav(wav,output,input_start,input_end,output_start,output_end,length,
                   anchors,events,mute,cancel,callback=None):
    import vocalmidi_rubberband as rb
    ni=input_end-input_start;no=output_end-output_start
    state=rb.create(RATE,ni,no,anchors)
    # Legato notes are one voiced interval: fading at every note would re-create
    # the unwanted chopped/tremolo sound. Only real MIDI rests get a gate.
    gates=[]
    for event in events:
        if gates and event['start']<=gates[-1]['end']:
            gates[-1]['end']=max(gates[-1]['end'],event['end'])
        else:gates.append({'start':event['start'],'end':event['end']})
    with wave.open(str(wav),'rb') as src:
        for study in (True,False):
            src.setpos(input_start);remaining=ni
            if not study:temp=tempfile.TemporaryFile()
            done=0;written=0;peak=0.
            while remaining>0:
                check_cancel(cancel)
                n=min(4096 if study else 256,remaining)
                x=np.frombuffer(src.readframes(n),'<i2').astype(np.float32)/32768
                remaining-=n;done+=n
                data=x.tobytes()
                if study:rb.study(state,data,remaining==0)
                else:
                    rb.process(state,data,remaining==0)
                    while rb.available(state)>0:
                        y=np.frombuffer(rb.retrieve(state),np.float32)
                        # R3 offline processing supplies the requested total duration.
                        y=y[:max(0,no-written)]
                        if len(y):temp.write(y.tobytes());peak=max(peak,float(np.max(np.abs(y))));written+=len(y)
                if callback is not None:callback.progress(min(94,25+round(done/ni*34)+(0 if study else 35)))
    gain=min(1.,.98/peak) if peak else 1.
    try:
        if abs(written-no)>32:
            raise RuntimeError(f'Rubber Band вернул неожиданную длину: {written}, ожидалось {no}')
        temp.seek(0)
        with wave.open(str(output),'wb') as dest:
            dest.setnchannels(1);dest.setsampwidth(2);dest.setframerate(RATE)
            write_silence(dest,output_start,cancel)
            position=0;event_index=0
            while position<written:
                check_cancel(cancel)
                y=np.frombuffer(temp.read(min(RATE,written-position)*4),np.float32).copy()*gain
                if mute:
                    absolute=output_start+position
                    gate=np.zeros(len(y))
                    while event_index<len(gates) and gates[event_index]['end']<=absolute:event_index+=1
                    k=event_index
                    while k<len(gates) and gates[k]['start']<absolute+len(y):
                        start,end=gates[k]['start'],gates[k]['end']
                        lo=max(0,start-absolute);hi=min(len(y),end-absolute)
                        idx=np.arange(lo,hi)+absolute
                        gate[lo:hi]=np.maximum(gate[lo:hi],np.minimum(1.,np.minimum((idx-start)/96,(end-1-idx)/160)))
                        k+=1
                    y*=gate
                dest.writeframesraw((np.clip(y,-1,1)*32767).astype('<i2').tobytes());position+=len(y)
            write_silence(dest,no-written+length-output_end,cancel)
    finally:temp.close()
    return gain


def render(wav,midi,track,offset,mute_gaps,output,cancel,callback=None,sensitivity=.12,policy='high'):
    from engine import render_region
    offset=float(offset);sensitivity=float(sensitivity)
    if not np.isfinite(offset) or abs(offset)>600 or sensitivity not in (.06,.12,.24):
        raise ValueError('Недопустимый сдвиг или чувствительность')
    check_cancel(cancel)
    with wave.open(str(wav),'rb') as src:count=src.getnframes()
    notes,length=render_region(midi,track,count,offset)
    events=midi_events(notes,length,offset,policy=policy)
    source,envelope=voice_events(wav,length,sensitivity,cancel,callback)
    if float(np.max(envelope))==0:
        with wave.open(str(output),'wb') as dest:
            dest.setnchannels(1);dest.setsampwidth(2);dest.setframerate(RATE);write_silence(dest,length,cancel)
        return json.dumps({'engine':'Rubber Band 4.0.0 R3','notes':len(events),'source_events':0,'seconds':length/RATE,'time_stretch':True,'silent':True})
    groups=align_groups(source,events,cancel)
    start,end,out_start,out_end,anchors=time_map(source,events,groups)
    gain=stretch_to_wav(wav,output,start,end,out_start,out_end,length,anchors,events,
                        bool(mute_gaps),cancel,callback)
    return json.dumps({'engine':'Rubber Band 4.0.0 R3','notes':len(events),'source_events':len(source),
                       'matched_groups':len(groups),'anchors':anchors,'input_start':start,'output_start':out_start,
                       'seconds':length/RATE,'time_stretch':True,'pitch_shift':False,'gain':gain})
