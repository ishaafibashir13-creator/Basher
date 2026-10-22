"""Move detected vocal units to MIDI onsets without resampling or a vocoder.

Conservative segmentation: silence and deep envelope valleys, not phoneme
recognition. Refuse ambiguous counts and overlapping speech rather than silently
repeat/drop syllables or time-compress consonants. Audio memory is block bounded.
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


def detect_units(path, sensitivity, cancel):
    envelope = []
    with wave.open(str(path), 'rb') as src:
        if (src.getnchannels(), src.getsampwidth(), src.getframerate()) != (1, 2, RATE):
            raise ValueError('Ожидается PCM16 mono 32000 Гц')
        count = src.getnframes()
        if not RATE // 10 <= count <= RATE * 600:
            raise ValueError('Длительность вокала должна быть от 0,1 секунды до 10 минут')
        while True:
            check_cancel(cancel)
            raw = src.readframes(HOP * 200)
            if not raw:
                break
            x = np.frombuffer(raw, '<i2').astype(float) / 32768
            x = np.pad(x, (0, (-len(x)) % HOP))
            envelope.extend(np.sqrt(np.mean(x.reshape(-1, HOP)**2, axis=1)))
    env = np.asarray(envelope)
    peak = float(np.max(env))
    if peak < .001:
        raise ValueError('Вокал слишком тихий или запись содержит только тишину')
    threshold = max(.0005, float(np.percentile(env, 95)) * sensitivity)
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
        raise ValueError('Не найдены вокальные фрагменты. Попробуйте другую чувствительность или чистую запись.')
    return units


def render(wav, midi, track, offset, mute_gaps, output, cancel, callback=None,
           sensitivity=.12):
    from engine import track_notes
    offset = float(offset)
    sensitivity = float(sensitivity)
    if not np.isfinite(offset) or abs(offset) > 600 or sensitivity not in (.06, .12, .24):
        raise ValueError('Недопустимый сдвиг или чувствительность')
    check_cancel(cancel)
    notes = track_notes(midi, track)
    # Chord notes with identical onsets form ONE rhythmic event.
    events = {}
    for start, end, _, _ in notes:
        pos = round((start+offset)*RATE)
        stop = round((end+offset)*RATE)
        if pos < 0:
            raise ValueError('Сдвиг помещает начало MIDI раньше нуля. Увеличьте сдвиг.')
        events[pos] = max(events.get(pos, 0), stop)
    targets = sorted(events)
    if max(events.values()) > RATE*600:
        raise ValueError('Результат с учётом сдвига длиннее 10 минут')
    units = detect_units(wav, sensitivity, cancel)
    if len(units) != len(targets):
        raise ValueError(f'Найдено вокальных фрагментов: {len(units)}, начал нот MIDI: {len(targets)}. '
                         'Нужен один слог на одно начало ноты. Измените чувствительность, '
                         'выберите другую дорожку или подготовьте вокал с более ясными паузами. '
                         'Слоги не удалены и не повторены.')
    for i, ((a, b), target) in enumerate(zip(units, targets)):
        limit = targets[i+1] if i+1 < len(targets) else RATE*600
        if mute_gaps:
            limit = min(limit, events[target])
        if target+b-a > limit:
            raise ValueError(f'Фрагмент {i+1} ({(b-a)/RATE:.2f} с) не помещается '
                             f'в интервал MIDI ({(limit-target)/RATE:.2f} с) без сжатия или обрезки. '
                             'Уменьшите темп MIDI или отключите паузы MIDI, если они включены.')
    length = max(max(events.values()), targets[-1]+units[-1][1]-units[-1][0])
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
                gain = np.minimum(1., np.minimum(idx/max(1, fade), (b-a-1-idx)/max(1, fade)))
                pcm = np.rint(pcm*gain).astype('<i2')
                dest.writeframesraw(pcm.tobytes())
            cursor = target+b-a
            if callback is not None:
                callback.progress(min(99, round((i+1)*100/len(units))))
        silence(length-cursor)
    return json.dumps({'mode':'rhythm', 'slices':len(units), 'seconds':length/RATE,
                       'time_stretch':False, 'pitch_shift':False})
