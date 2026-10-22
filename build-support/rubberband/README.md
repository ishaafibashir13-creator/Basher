# Rubber Band R3 integration

This application uses Rubber Band Library **4.0.0**, R3/Finer, offline two-pass
study/process mode. Upstream tag v4.0.0, commit
1d95888bec3ae0a17c0c4af791810d5a63f6bc35. Corresponding source is vendored at
`vendor/rubberband-4.0.0`. Adapter source: `native/rubberband_module.cpp`.

The single-file build uses the bundled FFT and BQ resampler, with no external
DSP library. The adapter fixes the time ratio and pitch ratio (1.0), supplies
a monotonic sample-frame map, studies the input, then renders continuously.
The `(0, 0)` origin is implicit in R3's map and is deliberately omitted from
the actual library call to avoid upstream R3 dividing 0/0. Python-side maps
include it for validation and readability. Processing blocks are **256 samples**
at 32 kHz (8 ms). Large processing blocks make R3 update the map too late and
can introduce audible onset errors. Study blocks may be 4096 samples.

## Host build and real-library tests

Requires g++ and Python 3.12 development headers:

    python3 build_rubberband.py --host
    PYTHONPATH=native-build/host python3 -m unittest discover -s tests -v

## Android wheels

Requires Android NDK 27.2.12479018 and official Chaquopy Python target 3.12.12-0
ZIPs from Maven Central (`com/chaquo/python/target/3.12.12-0`). Put both ABI
ZIPs in one directory, then run for each ABI:

    python3 build_rubberband.py --ndk /path/to/ndk/27.2.12479018 --targets /path/to/target-zips --abi arm64-v8a
    python3 build_rubberband.py --ndk /path/to/ndk/27.2.12479018 --targets /path/to/target-zips --abi x86_64

The script compiles the adapter and unmodified single-file Rubber Band source
and creates CPython 3.12 / Android API 24 wheels in vendor. C++ runtime is
linked statically, Python dynamically. ELF segment alignment is 16 KB.
The prebuilt wheels are included, so ordinary app builds do not need the NDK.

See root NOTICE.md and LICENSE for GPL distribution terms. The application
includes the licence text in assets/licenses and publishes full source.
