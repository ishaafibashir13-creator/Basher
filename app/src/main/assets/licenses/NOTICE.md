VocalMidi 0.5 and later are distributed as a combined application under
GPL-3.0-or-later. The original VocalMidi code's MIT notice is retained in
licenses/VocalMidi-0.4-MIT.txt. The unmodified Rubber Band 4.0.0 sources are
GPL-2.0-or-later and are used under that licence's GPL-3.0-or-later option.

Rubber Band Library © 2007–2024 Particular Programs Ltd / Chris Cannam.
Upstream release: https://github.com/breakfastquay/rubberband/tree/v4.0.0
Pinned commit: 1d95888bec3ae0a17c0c4af791810d5a63f6bc35
Library source licence: vendor/rubberband-4.0.0/COPYING

The adapter in native/rubberband_module.cpp and build_rubberband.py build the
same R3 engine for host tests and Android. FFT and resampling use the built-in
implementations from the vendored source. No external proprietary audio SDK
or online service is used. There are no changes to the upstream library code.

Other dependencies retain their own licences (NumPy, mido, packaging, PyWORLD,
WORLD, FFmpegKit, libc++, Chaquopy); see licenses/ and the bundled wheels.
Full corresponding application and native-library source and build scripts:
https://github.com/ishaafibashir13-creator/Basher
