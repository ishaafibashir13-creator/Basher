"""Offline MIDI melody retuning. All times are seconds; output is mono PCM16."""
import json
import os
import wave
from collections import defaultdict, deque
import numpy as np
import mido

RATE = 32000
MAX_SECONDS = 600


def read_midi(path):
    # Support Standard MIDI and RIFF RMID without relying on the extension.
    import io
    with open(path, 'rb') as f:
        data = f.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('MIDI больше 8 МБ')
    if data[:4] == b'RIFF' and data[8:12] == b'RMID':
        pos = 12
        while pos + 8 <= len(data):
            size = int.from_bytes(data[pos+4:pos+8], 'little')
            if data[pos:pos+4] == b'data':
                data = data[pos+8:pos+8+size]
                break
            pos += 8 + size + size % 2
    mid = mido.MidiFile(file=io.BytesIO(data))
    if mid.type == 2 or mid.ticks_per_beat <= 0:
        raise ValueError('Поддерживаются MIDI типа 0 и 1 с музыкальной шкалой времени; тип 2 и SMPTE не поддерживаются')
    events = []
    for ti, track in enumerate(mid.tracks):
        tick = 0
        for order, msg in enumerate(track):
            tick += msg.time
            events.append((tick, ti, order, msg))
    events.sort(key=lambda e: e[:3])
    tempo, prev, sec = 500000, 0, 0.0
    pending = defaultdict(deque)
    notes = defaultdict(list)
    names = {}
    for tick, ti, _, msg in events:
        sec += mido.tick2second(tick-prev, mid.ticks_per_beat, tempo)
        prev = tick
        if sec > MAX_SECONDS:
            raise ValueError('MIDI длиннее 10 минут')
        if msg.type == 'set_tempo':
            tempo = msg.tempo
        elif msg.type == 'track_name':
            names[ti] = msg.name
        elif msg.type == 'note_on' and msg.velocity > 0:
            if msg.channel != 9:
                pending[(ti, msg.channel, msg.note)].append((sec, msg.velocity))
        elif msg.type in ('note_on', 'note_off'):
            key = (ti, msg.channel, msg.note)
            if pending[key]:
                start, velocity = pending[key].popleft()
                if sec > start:
                    notes[ti].append((start, sec, msg.note, velocity))
    for (ti, ch, pitch), starts in pending.items():
        for start, velocity in starts:
            if sec > start:
                notes[ti].append((start, sec, pitch, velocity))
    result = []
    for ti in sorted(notes):
        ns = sorted(notes[ti])
        result.append({'id': ti, 'name': names.get(ti, 'Без названия'),
                       'notes': ns, 'count': len(ns), 'duration': max(n[1] for n in ns)})
    if not result:
        raise ValueError('В MIDI нет мелодических нот. Канал ударных исключён.')
    return result


def inspect_midi(path):
    return json.dumps([{k: v for k, v in t.items() if k != 'notes'} for t in read_midi(path)], ensure_ascii=False)


def track_notes(path, track_id):
    for t in read_midi(path):
        if t['id'] == int(track_id):
            return t['notes']
    raise ValueError('Дорожка не найдена')


def melody(times, notes, policy='high', offset=0.0, transpose=0):
    # Stable rule for polyphony: high/low/latest. Same rule used by preview.
    out = np.zeros(len(times), dtype=np.float64)
    if not len(times):
        return out
    for start, end, note, _ in sorted(notes):
        if end + offset <= times[0] or start + offset > times[-1]:
            continue
        mask = (times >= start + offset) & (times < end + offset)
        value = 440.0 * 2.0 ** ((note + transpose - 69) / 12.0)
        if policy == 'high':
            out[mask] = np.maximum(out[mask], value)
        elif policy == 'low':
            out[mask] = np.where(out[mask] == 0, value, np.minimum(out[mask], value))
        else:
            out[mask] = value
    return out


def write_wav(path, x, rate=RATE):
    x = np.nan_to_num(x)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())


def preview(midi, track, policy, transpose, output):
    notes = track_notes(midi, track)
    # Generate in blocks, avoiding a full-track floating-point allocation.
    duration = max(n[1] for n in notes) + .15
    with wave.open(output, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        phase = 0.0
        previous = 0.0
        for start in range(0, int(duration * RATE), RATE):
            times = np.arange(start, min(start + RATE, int(duration * RATE))) / RATE
            f = melody(times, notes, policy, transpose=int(transpose))
            phases = phase + np.cumsum(f * 2 * np.pi / RATE)
            if len(phases): phase = phases[-1] % (2 * np.pi)
            # Fast one-pole envelope eliminates hard clicks at note boundaries.
            gate = (f > 0).astype(float)
            env = np.empty(len(gate))
            for i, target in enumerate(gate):
                previous += (target - previous) * .01
                env[i] = previous
            x = .22 * env * (np.sin(phases) + .2 * np.sin(2 * phases))
            w.writeframes((x * 32767).astype('<i2').tobytes())
    return output


def render(wav_path, midi, track, policy, offset, transpose, mute_gaps,
           output, cancel_path, callback=None):
    import pyworld as pw
    notes = track_notes(midi, track)
    with wave.open(wav_path, 'rb') as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != RATE:
            raise ValueError('Ожидается PCM16 mono 32000 Гц')
        count = w.getnframes()
    if count < RATE // 10 or count > RATE * MAX_SECONDS:
        raise ValueError('Длительность вокала должна быть от 0,1 секунды до 10 минут')
    offset = float(offset)
    transpose = int(transpose)
    if not np.isfinite(offset) or abs(offset) > 600 or not -24 <= transpose <= 24:
        raise ValueError('Недопустимый сдвиг или транспозиция')
    if max(n[1] for n in notes) + offset <= 0 or min(n[0] for n in notes) + offset >= count / RATE:
        raise ValueError('Вокал и ноты MIDI не пересекаются по времени. Измените сдвиг.')
    frequencies = [440 * 2 ** ((n[2]+transpose-69)/12) for n in notes
                   if n[1]+offset > 0 and n[0]+offset < count/RATE]
    if any(f < 40 or f > 2000 for f in frequencies):
        raise ValueError('Ноты выходят за рабочий диапазон 40–2000 Гц. Измените транспозицию или дорожку.')
    block, margin = RATE * 8, RATE // 5
    changed = total_voiced = 0
    # Small overlap-add buffer, bounded memory even for ten-minute recordings.
    with wave.open(wav_path, 'rb') as source, wave.open(output, 'wb') as dest:
        dest.setnchannels(1); dest.setsampwidth(2); dest.setframerate(RATE)
        tail = np.zeros(0)
        for start in range(0, count, block):
            if os.path.exists(cancel_path):
                raise InterruptedError('Обработка отменена')
            left = max(0, start-margin)
            right = min(count, start+block+margin)
            source.setpos(left)
            x = np.frombuffer(source.readframes(right-left), dtype='<i2').astype(np.float64) / 32768
            f0, t = pw.harvest(x, RATE, f0_floor=50, f0_ceil=1100, frame_period=5.0)
            f0 = pw.stonemask(x, f0, t, RATE)
            sp = pw.cheaptrick(x, f0, t, RATE)
            ap = pw.d4c(x, f0, t, RATE)
            target = melody(t+left/RATE, notes, policy, offset, transpose)
            use = (f0 > 0) & (target > 0)
            total_voiced += int(np.count_nonzero(f0))
            changed += int(np.count_nonzero(use))
            f0[use] = target[use]
            y = pw.synthesize(f0, sp, ap, RATE, 5.0)
            y = np.pad(y, (0, max(0, len(x)-len(y))))[:len(x)]
            if mute_gaps:
                gate = np.interp(np.arange(len(y))/RATE, t, (target>0).astype(float))
                # Fade the gate by 5ms to reduce clicks without voicing consonants.
                gate = np.convolve(gate, np.ones(161)/161, mode='same')
                y *= gate
            # Crossfade 400ms across adjacent independently synthesized blocks.
            if len(tail):
                n = min(len(tail), len(y))
                blend = np.linspace(0, 1, n)
                y[:n] = tail[:n]*(1-blend) + y[:n]*blend
            keep = len(y) if start+block >= count else (start+block-margin-left)
            dest.writeframes((np.clip(y[:keep], -1, 1)*32767).astype('<i2').tobytes())
            tail = y[keep:].copy()
            if callback is not None:
                callback.progress(min(99, int((start+block)*100/count)))
    if changed == 0:
        raise ValueError('Не найдено звучащего вокала под нотами MIDI. Проверьте исходник и сдвиг.')
    return json.dumps({'seconds': count/RATE, 'voiced_frames': total_voiced,
                       'retuned_frames': changed, 'engine': pw.__version__})
