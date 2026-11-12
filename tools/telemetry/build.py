#!/usr/bin/env python3
"""Build optional telemetry helpers without installing or starting them."""
import argparse
from pathlib import Path
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-cxx', default='x86_64-w64-mingw32-g++', help='Compiler command; e.g. "zig c++ -target x86_64-windows-gnu"')
    parser.add_argument('--linux-cxx', default='c++')
    parser.add_argument('--lmu-sdk', type=Path, help='Installed LMU Support/SharedMemoryInterface directory')
    parser.add_argument('--scs-sdk', type=Path, help='SCS telemetry SDK include directory')
    parser.add_argument('--output', type=Path, default=Path('build/telemetry'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent
    flags = ['-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror']
    windows = shlex.split(args.windows_cxx) + flags
    shared = windows + [str(root / 'shared_memory.cpp')]
    if args.lmu_sdk:
        if not (args.lmu_sdk / 'SharedMemoryInterface.hpp').is_file():
            parser.error('LMU SDK header not found')
        shared += ['-DMOZAPROXY_LMU', '-isystem', str(args.lmu_sdk.resolve())]
    subprocess.run(shared + ['-static', '-lws2_32', '-o', str(args.output / 'mozaproxy-shared-memory.exe')], check=True)
    if args.scs_sdk:
        if not (args.scs_sdk / 'scssdk_telemetry.h').is_file():
            parser.error('SCS SDK header not found')
        plugin = [str(root / 'scs_plugin.cpp'), '-isystem', str(args.scs_sdk.resolve()), '-shared']
        subprocess.run(windows + plugin + [str(root / 'scs_plugin.def'), '-static', '-lws2_32', '-o', str(args.output / 'mozaproxy-ets2.dll')], check=True)
        subprocess.run(shlex.split(args.linux_cxx) + flags + plugin + ['-fPIC', '-o', str(args.output / 'mozaproxy-ets2.so')], check=True)
    print(f'Built helpers in {args.output.resolve()}. Nothing installed or started.')


if __name__ == '__main__':
    main()
