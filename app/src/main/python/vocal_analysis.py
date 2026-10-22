"""Energy and stable-pitch events for continuous vocal time alignment."""
import os
import wave
import numpy as np
RATE=32000
HOP=160

def check_cancel(path):
    if os.path.exists(path):
        raise InterruptedError('Обработка отменена')


def detect_units(path, sensitivity, cancel, max_frames=None, with_envelope=False):
    envelope = []
    with wave.open(str(path), 'rb') as src:
        if (src.getnchannels(), src.getsampwidth(), src.getframerate()) != (1, 2, RATE):
            raise ValueError('Ожидается PCM16 mono 32000 Гц')
        count = src.getnframes()
        if not RATE // 10 <= count <= RATE * 600:
            raise ValueError('Длительность вокала должна быть от 0,1 секунды до 10 минут')
        if max_frames is not None:
            count = min(count, max_frames)
        remaining = count
        while remaining > 0:
            check_cancel(cancel)
            raw = src.readframes(min(HOP * 200, remaining))
            remaining -= len(raw)//2
            if not raw:
                break
            x = np.frombuffer(raw, '<i2').astype(float) / 32768
            x = np.pad(x, (0, (-len(x)) % HOP))
            envelope.extend(np.sqrt(np.mean(x.reshape(-1, HOP)**2, axis=1)))
    env = np.asarray(envelope)
    peak = float(np.max(env))
    threshold = max(peak*1e-6, float(np.percentile(env, 95)) * sensitivity)
    active = env > threshold
    # Close holes shorter than 25 ms, preserving consonant clusters.
    edges = np.diff(np.r_[True, active, True].astype(int))
    for a, b in zip(np.flatnonzero(edges == -1), np.flatnonzero(edges == 1)):
        if b-a < 5:
            active[a:b] = True
    edges = np.diff(np.r_[False, active, False].astype(int))
    units = []
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if b-a < 8:  # Reject isolated clicks (<40 ms).
            continue
        # A deep valley can separate connected syllables without a silent gap.
        cuts = [int(a)]
        for j in range(a+16, b-16):
            if j-cuts[-1] < 20:
                continue
            local = env[j-8:j+9]
            prominence = min(np.max(env[j-16:j]), np.max(env[j+1:j+17]))
            if env[j] == np.min(local) and env[j] < prominence * .32:
                cuts.append(j)
        cuts.append(int(b))
        for k, (left, right) in enumerate(zip(cuts, cuts[1:])):
            # Keep up to 10 ms of quiet onset/tail. Never duplicate samples.
            start = max(0, left*HOP)
            end = min(count, right*HOP)
            if units:
                start = max(start, units[-1][1])
            units.append((start, end))
    if not units:
        # Silence, very short attacks and faint recordings are valid source audio.
        # The fallback still uses actual source samples and never invents speech.
        units = [(0, count)]
    return (units, env) if with_envelope else units



def voice_events(path, length, sensitivity, cancel, callback=None):
    """Locate energy attacks and stable sung-note changes, without altering audio."""
    import pyworld as pw
    import warnings
    units, env = detect_units(path, sensitivity, cancel, with_envelope=True)
    # The shared duration limits the output and later phrases. Keep the full
    # tail of a phrase that begins before that boundary: it must be compressed
    # naturally into its last MIDI note, not chopped before stretching.
    units = [(a,b) for a,b in units if a < length]
    if not units:
        units=[(0,length)]
    length=units[-1][1]
    env=env[:(length+HOP-1)//HOP]
    if float(np.max(env)) == 0:
        return [{'start':0,'end':length,'pitch':None}], env
    step = RATE//100
    pitches = np.full((length+step-1)//step+1, np.nan)
    block, margin = RATE*8, RATE//5
    with wave.open(str(path), 'rb') as src:
        for start in range(0, length, block):
            check_cancel(cancel)
            left=max(0,start-margin);right=min(length,start+block+margin)
            src.setpos(left)
            x=np.frombuffer(src.readframes(right-left),'<i2').astype(np.float64)/32768
            if len(x)<RATE//10:x=np.pad(x,(0,RATE//10-len(x)))
            f0,t=pw.harvest(x,RATE,f0_floor=50,f0_ceil=1100,frame_period=10.0)
            f0=pw.stonemask(x,f0,t,RATE)
            indices=np.rint((t*RATE+left)/step).astype(int)
            use=(indices>=start//step)&(indices<min(len(pitches),(start+block+step-1)//step))&(f0>0)
            pitches[indices[use]]=69+12*np.log2(f0[use]/440)
            if callback is not None:callback.progress(min(24,round((start+block)*24/length)))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        smooth=np.nanmedian(np.lib.stride_tricks.sliding_window_view(np.pad(pitches,(2,2),constant_values=np.nan),5),axis=1)
    events=[]
    for a,b in units:
        lo=max(0,int(np.ceil(a/step)));hi=min(len(smooth),b//step)
        cuts=[a];baseline=None
        for j in range(lo,hi):
            value=smooth[j]
            if not np.isfinite(value):continue
            if baseline is None:baseline=value;continue
            if j*step-cuts[-1]<RATE*.06 or b-j*step<RATE*.06:continue
            future=smooth[j:min(j+6,hi)]
            good=future[np.isfinite(future)]
            if len(good)>=5 and abs(float(np.median(good))-baseline)>=.85 and np.max(good)-np.min(good)<.7:
                cuts.append(j*step);baseline=float(np.median(good))
        cuts.append(b)
        for left,right in zip(cuts,cuts[1:]):
            values=pitches[max(0,left//step):min(len(pitches),(right+step-1)//step)]
            values=values[np.isfinite(values)]
            events.append({'start':left,'end':right,'pitch':float(np.median(values)) if len(values) else None})
    return events,env
