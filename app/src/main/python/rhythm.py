"""Move detected vocal units to MIDI onsets without resampling or a vocoder.

Energy-based segmentation is adapted to any number of MIDI onsets by splitting
or grouping consecutive source ranges. Tight slots are cropped with fades, never
time-compressed. The output ends at the shorter input. Audio memory is bounded.
"""
import os
import json
import wave
import numpy as np

RATE = 32000
HOP = 160  # 5 ms analysis grid; target placement is sample accurate.


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
            start = max(0, left*HOP - (2*HOP if k == 0 else 0))
            end = min(count, right*HOP + (2*HOP if k == len(cuts)-2 else 0))
            if units:
                start = max(start, units[-1][1])
            units.append((start, end))
    if not units:
        # Silence, very short attacks and faint recordings are valid source audio.
        # The fallback still uses actual source samples and never invents speech.
        units = [(0, count)]
    return (units, env) if with_envelope else units



def adapt_units(units, count, envelope, cancel):
    """Return exactly count source ranges, in order, without sample repetition.

    Splitting distributes additional cuts by source duration and searches quiet
    envelope valleys near each proposed cut. Grouping retains the silence between
    joined units. Sample-sized MIDI slots may receive an empty source range.
    """
    if len(units) == count:
        return units
    if len(units) > count:
        return [(units[i*len(units)//count][0],
                 units[(i+1)*len(units)//count-1][1]) for i in range(count)]
    spans = np.array([b-a for a, b in units], dtype=np.float64)
    quotas = (count-len(units))*spans/np.sum(spans)
    extra = np.floor(quotas).astype(int)
    remainder = count-len(units)-int(np.sum(extra))
    order = np.argsort(-(quotas-extra), kind='stable')
    extra[order[:remainder]] += 1
    result = []
    for (a, b), more in zip(units, extra):
        check_cancel(cancel)
        parts = int(more)+1
        previous = a
        for j in range(1, parts):
            if j % 128 == 0:
                check_cancel(cancel)
            ideal = a+(b-a)*j/parts
            cut = round(ideal)
            if parts <= b-a:
                lo, hi = previous+1, b-(parts-j)
                radius = min(800, (b-a)/parts*.25)
                first = max(0, int(np.ceil((max(lo, ideal-radius)-HOP/2)/HOP)))
                last = min(len(envelope)-1, int(np.floor((min(hi, ideal+radius)-HOP/2)/HOP)))
                if first <= last:
                    indices = np.arange(first, last+1)
                    candidates = indices*HOP+HOP//2
                    energy = envelope[indices]
                    score = energy/max(float(np.max(energy)), 1e-12)
                    score += .15*np.abs(candidates-ideal)/max(radius, 1)
                    cut = int(candidates[np.argmin(score)])
                cut = max(lo, min(hi, cut))
            else:
                # More onsets than available source samples: some ranges are empty.
                cut = max(previous, min(b, cut))
            result.append((previous, cut))
            previous = cut
        result.append((previous, b))
    return result


def render(wav, midi, track, offset, mute_gaps, output, cancel, callback=None,
           sensitivity=.12):
    from engine import render_region
    offset = float(offset)
    sensitivity = float(sensitivity)
    if not np.isfinite(offset) or abs(offset) > 600 or sensitivity not in (.06, .12, .24):
        raise ValueError('Недопустимый сдвиг или чувствительность')
    check_cancel(cancel)
    with wave.open(str(wav), 'rb') as src:
        source_frames = src.getnframes()
    notes, length = render_region(midi, track, source_frames, offset)
    # Chord notes with identical onsets form ONE rhythmic event.
    events = {}
    for start, end, _, _ in notes:
        pos = round((start+offset)*RATE)
        stop = min(length, round((end+offset)*RATE))
        if pos < 0:
            raise ValueError('Сдвиг помещает начало MIDI раньше нуля. Увеличьте сдвиг.')
        events[pos] = max(events.get(pos, 0), stop)
    targets = sorted(events)
    detected, envelope = detect_units(wav, sensitivity, cancel, max_frames=length,
                                      with_envelope=True)
    units = adapt_units(detected, len(targets), envelope, cancel)
    trimmed = 0
    fitted = []
    for i, ((a, b), target) in enumerate(zip(units, targets)):
        limit = targets[i+1] if i+1 < len(targets) else length
        if mute_gaps:
            limit = min(limit, events[target])
        end = min(b, a+max(0, limit-target))
        trimmed += int(end < b)
        fitted.append((a, end))
    units = fitted
    with wave.open(str(wav), 'rb') as src, wave.open(str(output), 'wb') as dest:
        dest.setnchannels(1); dest.setsampwidth(2); dest.setframerate(RATE)
        cursor = 0
        def silence(n):
            while n:
                check_cancel(cancel)
                size = min(n, RATE)
                dest.writeframesraw(bytes(size*2))
                n -= size
        for i, ((a, b), target) in enumerate(zip(units, targets)):
            silence(target-cursor)
            src.setpos(a)
            fade = min(256, (b-a)//4)  # <= 8 ms, no timing or pitch change.
            for pos in range(0, b-a, RATE):
                check_cancel(cancel)
                n = min(RATE, b-a-pos)
                pcm = np.frombuffer(src.readframes(n), '<i2').copy()
                idx = np.arange(pos, pos+n)
                gain = (np.minimum(1., np.minimum(idx/fade, (b-a-1-idx)/fade))
                        if fade else np.ones(n))
                pcm = np.rint(pcm*gain).astype('<i2')
                dest.writeframesraw(pcm.tobytes())
            cursor = target+b-a
            if callback is not None:
                callback.progress(min(99, round((i+1)*100/len(units))))
        silence(length-cursor)
    return json.dumps({'mode':'rhythm', 'slices':len(units), 'detected_units':len(detected),
                       'trimmed_slices':trimmed, 'seconds':length/RATE,
                       'time_stretch':False, 'pitch_shift':False})
