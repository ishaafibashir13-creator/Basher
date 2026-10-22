"""One transaction: time alignment first, WORLD tuning second."""
import json
import os
import shutil
import tempfile
import wave
import numpy as np
import engine
import rhythm
import manual
from vocal_analysis import check_cancel


class Progress:
    def __init__(self, callback, start, span):
        self.callback,self.start,self.span=callback,start,span
    def progress(self, value):
        if self.callback is not None:
            self.callback.progress(min(99,self.start+round(value*self.span/100)))


def preserve_silence(reference, tuned, output, cancel):
    """Keep >=10 ms digital-silence runs from the aligned WAV after resynthesis."""
    intervals=[];pending=None;position=0
    with wave.open(reference,'rb') as src:
        while position<src.getnframes():
            check_cancel(cancel)
            x=np.frombuffer(src.readframes(engine.RATE),'<i2')
            edges=np.diff(np.r_[False,x==0,False].astype(np.int8))
            runs=list(zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)))
            if pending is not None and (not runs or runs[0][0]!=0):
                if position-pending>=320:intervals.append((pending,position))
                pending=None
            for a,b in runs:
                start=pending if a==0 and pending is not None else position+int(a)
                pending=None
                if b==len(x):pending=start
                elif position+int(b)-start>=320:intervals.append((start,position+int(b)))
            position+=len(x)
        if pending is not None and position-pending>=320:intervals.append((pending,position))
    with wave.open(tuned,'rb') as src,wave.open(output,'wb') as dest:
        dest.setparams(src.getparams());position=0;index=0
        while position<src.getnframes():
            check_cancel(cancel)
            y=np.frombuffer(src.readframes(engine.RATE),'<i2').copy()
            while index<len(intervals) and intervals[index][1]<=position:index+=1
            k=index
            while k<len(intervals) and intervals[k][0]<position+len(y):
                a,b=intervals[k];y[max(0,a-position):min(len(y),b-position)]=0;k+=1
            dest.writeframesraw(y.tobytes());position+=len(y)


def render(wav,midi,track,policy,offset,transpose,mute,output,cancel,
           callback=None,mode='both',manual_json='',sensitivity=.12):
    wav,midi,output,cancel=map(os.fspath,(wav,midi,output,cancel))
    if mode not in ('rhythm','pitch','both'):
        raise ValueError('Неизвестный режим обработки')
    info={'mode':mode}
    def stage(text):
        check_cancel(cancel)
        if callback is not None:callback.stage(text)
        check_cancel(cancel)
    with tempfile.TemporaryDirectory(prefix='pipeline-',dir=os.path.dirname(os.path.abspath(output))) as folder:
        aligned=os.path.join(folder,'aligned.wav')
        final=os.path.join(folder,'final.wav')
        if mode in ('rhythm','both'):
            stage('1. Ручное выравнивание' if manual_json else '1. Автоматическое выравнивание')
            cb=Progress(callback,0,50 if mode=='both' else 99)
            if manual_json:
                result=manual.render(wav,midi,track,offset,mute,aligned,cancel,manual_json,cb,policy)
            else:
                result=rhythm.render(wav,midi,track,offset,mute,aligned,cancel,cb,sensitivity,policy)
            info['rhythm']=json.loads(result)
        if mode in ('pitch','both'):
            stage('2. Тюнинг по нотам MIDI' if mode=='both' else 'Тюнинг по нотам MIDI')
            if info.get('rhythm',{}).get('silent'):
                shutil.copyfile(aligned,final)
                info['tuning']={'silent':True}
            else:
                result=engine.render(aligned if mode=='both' else wav,midi,track,policy,offset,
                                     transpose,mute,final,cancel,Progress(callback,50 if mode=='both' else 0,49 if mode=='both' else 99))
                info['tuning']=json.loads(result)
        else:
            shutil.copyfile(aligned,final)
        if mode=='both':
            quiet=os.path.join(folder,'quiet.wav')
            preserve_silence(aligned,final,quiet,cancel)
            os.replace(quiet,final)
        if mode=='both' and manual_json:
            gated=os.path.join(folder,'bounded.wav')
            manual.constrain_tuned(final,midi,track,offset,manual_json,gated,cancel)
            os.replace(gated,final)
        check_cancel(cancel)
        os.replace(final,output)
    return json.dumps(info)
