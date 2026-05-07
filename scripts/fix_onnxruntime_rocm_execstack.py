#!/usr/bin/env python3
# Clears PF_X in the PT_GNU_STACK program header of the onnxruntime-rocm
# wheel's two affected shared libraries. AMD's wheel is built without
# `-z noexecstack`, so glibc 2.41+ refuses to load it. The flag is purely
# declarative — clearing it is safe; ROCm onnxruntime does not need an
# executable stack at runtime.
#
# Re-run this after any `pip install -r requirements.txt` that reinstalls
# onnxruntime-rocm.

import importlib.util
import os
import struct
import sys

PT_GNU_STACK = 0x6474E551
PF_X = 0x1


def clear_execstack(path: str) -> bool:
    with open(path, "r+b") as f:
        data = f.read()
        if data[:4] != b"\x7fELF" or data[4] != 2:
            print(f"{path}: not ELF64, skipping", file=sys.stderr)
            return False
        e_phoff = struct.unpack_from("<Q", data, 32)[0]
        e_phentsize = struct.unpack_from("<H", data, 54)[0]
        e_phnum = struct.unpack_from("<H", data, 56)[0]
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            p_type, p_flags = struct.unpack_from("<II", data, off)
            if p_type == PT_GNU_STACK:
                if p_flags & PF_X:
                    new_flags = p_flags & ~PF_X
                    f.seek(off + 4)
                    f.write(struct.pack("<I", new_flags))
                    print(f"{path}: PT_GNU_STACK 0x{p_flags:x} -> 0x{new_flags:x}")
                    return True
                print(f"{path}: already clean (flags 0x{p_flags:x})")
                return False
        print(f"{path}: no PT_GNU_STACK header found", file=sys.stderr)
        return False


def main() -> int:
    spec = importlib.util.find_spec("onnxruntime")
    if spec is None or not spec.origin:
        print(
            "onnxruntime not importable — is onnxruntime-rocm installed for this interpreter?",
            file=sys.stderr,
        )
        return 1
    capi = os.path.join(os.path.dirname(spec.origin), "capi")
    if not os.path.isdir(capi):
        print(f"{capi}: capi/ subdir missing under onnxruntime package", file=sys.stderr)
        return 1
    print(f"Targeting {capi}")
    targets = [
        os.path.join(capi, "onnxruntime_pybind11_state.so"),
        # libonnxruntime.so.<ver> — match whatever version is present
        *(
            os.path.join(capi, fn)
            for fn in os.listdir(capi)
            if fn.startswith("libonnxruntime.so.")
        ),
    ]
    patched = 0
    for path in targets:
        if os.path.exists(path) and clear_execstack(path):
            patched += 1
    print(f"\nPatched {patched} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
