"""Rebuild bundled Android wheels. See README for the four input paths."""
import argparse, pathlib, subprocess, zipfile, hashlib, base64, csv, io

def build(ndk, python_target, numpy_target, abi):
    root = pathlib.Path(__file__).resolve().parent
    src = root / 'vendor/pyworld-0.3.5'
    out = root / 'vendor' / ('pyworld-0.3.5-cp312-cp312-android_24_' + abi.replace('-', '_') + '.whl')
    arch = {'arm64-v8a': 'aarch64', 'x86_64': 'x86_64'}[abi]
    clang = pathlib.Path(ndk) / f'toolchains/llvm/prebuilt/linux-x86_64/bin/{arch}-linux-android24-clang++'
    temp = root / 'native-build' / abi
    temp.mkdir(parents=True, exist_ok=True)
    so = temp / 'pyworld.so'
    cmd = [str(clang), '-shared', '-fPIC', '-O2', '-std=c++11', '-static-libstdc++',
           '-Wl,-z,max-page-size=16384', '-Wl,--no-undefined',
           '-I'+str(pathlib.Path(python_target)/'include/python3.12'),
           '-I'+str(pathlib.Path(numpy_target)/'numpy/core/include'),
           '-I'+str(src/'lib/World/src'), str(src/'pyworld/pyworld.cpp'),
           *map(str, (src/'lib/World/src').glob('*.cpp')),
           '-L'+str(pathlib.Path(python_target)/'jniLibs'/abi), '-lpython3.12', '-lm', '-o', str(so)]
    subprocess.run(cmd, check=True)
    files = {'pyworld/pyworld.so': so.read_bytes(),
             'pyworld/__init__.py': b'from .pyworld import *\n__version__ = "0.3.5"\n',
             'pyworld-0.3.5.dist-info/METADATA': b'Metadata-Version: 2.1\nName: pyworld\nVersion: 0.3.5\nRequires-Dist: numpy (==1.26.2)\n',
             'pyworld-0.3.5.dist-info/WHEEL': f'Wheel-Version: 1.0\nGenerator: VocalMidi build_pyworld.py\nRoot-Is-Purelib: false\nTag: cp312-cp312-android_24_{abi.replace("-", "_")}\n'.encode(),
             'pyworld-0.3.5.dist-info/LICENSE': (src/'LICENSE').read_bytes(),
             'pyworld-0.3.5.dist-info/WORLD-LICENSE': (src/'lib/World/LICENSE.txt').read_bytes()}
    records = io.StringIO()
    writer = csv.writer(records)
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
        writer.writerow([name, 'sha256='+digest, len(data)])
    writer.writerow(['pyworld-0.3.5.dist-info/RECORD', '', ''])
    files['pyworld-0.3.5.dist-info/RECORD'] = records.getvalue().encode()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items(): z.writestr(name, data)
    print(out)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for arg in ['ndk', 'python-target', 'numpy-target', 'abi']: p.add_argument('--'+arg, required=True)
    a = p.parse_args()
    build(a.ndk, a.python_target, a.numpy_target, a.abi)
