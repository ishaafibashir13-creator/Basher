"""Build the bundled Rubber Band 4.0.0 R3 adapter for host tests or Android.

The Android path requires the same NDK and target ZIPs as the existing PyWORLD
build. All Rubber Band sources are vendored; no network is used here.
"""
import argparse, pathlib, subprocess, sysconfig, zipfile, hashlib, base64, csv, io
ROOT=pathlib.Path(__file__).resolve().parent
SRC=ROOT/'vendor/rubberband-4.0.0'
SOURCES=[ROOT/'native/rubberband_module.cpp',SRC/'single/RubberBandSingle.cpp']
INIT=b'from ._native import create, study, process, available, retrieve\n__version__ = "4.0.0"\n'

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',action='store_true')
    p.add_argument('--ndk');p.add_argument('--targets');p.add_argument('--abi',choices=['arm64-v8a','x86_64'])
    a=p.parse_args(); flags=['-shared','-fPIC','-O3','-DNDEBUG','-std=c++11','-I'+str(SRC)]
    if a.host:
        target=ROOT/'native-build/host/vocalmidi_rubberband';target.mkdir(parents=True,exist_ok=True)
        (target/'__init__.py').write_bytes(INIT)
        subprocess.run(['g++',*flags,'-I'+sysconfig.get_paths()['include'],*map(str,SOURCES),'-o',str(target/('_native'+sysconfig.get_config_var('EXT_SUFFIX')))],check=True)
        print(target.parent);return
    if not (a.ndk and a.targets and a.abi):p.error('--ndk, --targets and --abi required for Android')
    tmp=ROOT/'native-build'/a.abi;tmp.mkdir(parents=True,exist_ok=True)
    py=tmp/'python';py.mkdir(exist_ok=True)
    zips=list(pathlib.Path(a.targets).glob('*-'+a.abi+'.zip'))
    if len(zips)!=1:raise ValueError('Expected one Python target ZIP per ABI')
    with zipfile.ZipFile(zips[0]) as z:z.extractall(py)
    arch={'arm64-v8a':'aarch64','x86_64':'x86_64'}[a.abi]
    clang=pathlib.Path(a.ndk)/f'toolchains/llvm/prebuilt/linux-x86_64/bin/{arch}-linux-android24-clang++'
    so=tmp/'_native.so'
    subprocess.run([str(clang),*flags,'-static-libstdc++','-Wl,-z,max-page-size=16384','-Wl,--no-undefined','-I'+str(py/'include/python3.12'),*map(str,SOURCES),'-L'+str(py/'jniLibs'/a.abi),'-lpython3.12','-lm','-o',str(so)],check=True)
    tag='cp312-cp312-android_24_'+a.abi.replace('-','_');dist='vocalmidi_rubberband-4.0.0.dist-info'
    files={'vocalmidi_rubberband/__init__.py':INIT,'vocalmidi_rubberband/_native.so':so.read_bytes(),
           dist+'/METADATA':b'Metadata-Version: 2.1\nName: vocalmidi-rubberband\nVersion: 4.0.0\nLicense: GPL-2.0-or-later\n',
           dist+'/WHEEL':f'Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {tag}\n'.encode(),
           dist+'/COPYING':(SRC/'COPYING').read_bytes()}
    records=io.StringIO();writer=csv.writer(records)
    for name,data in files.items():writer.writerow([name,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('='),len(data)])
    writer.writerow([dist+'/RECORD','','']);files[dist+'/RECORD']=records.getvalue().encode()
    wheel=ROOT/'vendor'/f'vocalmidi_rubberband-4.0.0-{tag}.whl'
    with zipfile.ZipFile(wheel,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
    print(wheel)
if __name__=='__main__':main()
