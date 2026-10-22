NumPy 1.26.2 Android wheels are built from official PyPI sources with the
Chaquopy build tool, commit 884ec5f14591d69844e20c9dc6a6a9c5d1ba0a41.

Recipe differences: remove chaquopy-openblas host dependency and permit NumPy's
bundled BLAS/LAPACK fallback. No DSP code here depends on accelerated BLAS.
Use the included meta.yaml and chaquopy.patch as packages/numpy/meta.yaml and
packages/numpy/patches/chaquopy.patch in a checkout of that commit.
Set ndk_version=27.2.12479018 in target/android-env.sh. Download target
3.12.12-0 arm64-v8a and x86_64 ZIPs from Maven Central into
maven/com/chaquo/python/target/3.12.12-0/.

Install server/pypi build dependencies (use setuptools 69.1.1 in the launcher
venv; patchelf is also available from PyPI). The per-package build environment
uses setuptools 69.0.2 per meta.yaml. With Python 3.12 and ANDROID_HOME set:

    python server/pypi/build-wheel.py --python 3.12 --abi arm64-v8a numpy
    python server/pypi/build-wheel.py --python 3.12 --abi x86_64 numpy

Copy dist/numpy/*.whl from server/pypi into VocalMidi/vendor.
The archive includes prebuilt wheels, so rebuilding NumPy is optional.
Licenses are inside the wheels. The Chaquopy tool is MIT licensed.

Also build the unchanged chaquopy-libcxx recipe for both ABIs with the same
NDK (omit --python), and copy dist/chaquopy-libcxx/*.whl into vendor. These
wheels provide libc++_shared.so and include its license.
