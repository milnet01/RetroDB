#!/usr/bin/env bash
# Installs `libhipblas.so.2` and `librocsolver.so.0` (the legacy hipBLAS
# + rocSOLVER ABIs) system-wide so the pre-built `onnxruntime-rocm`
# 1.22.2 wheel can load its ROCm provider.
#
# Why this exists
# ---------------
# onnxruntime-rocm 1.22.2 (current PyPI build) was linked against the
# legacy `libhipblas.so.2` ABI, which transitively NEEDs `librocsolver.so.0`.
# openSUSE Tumbleweed's ROCm 6.4 packaging replaced `hipblas` with
# `hipblaslt` (a different Tensile-based GEMM library) and dropped
# `librocsolver.so.0` along with it — so the host now has `librocblas.so.4`
# and `libhipblaslt.so.0`, but neither legacy library. Result: the ROCm
# provider .so fails to load with
#
#     Failed to load library libonnxruntime_providers_rocm.so with error:
#     libhipblas.so.2: cannot open shared object file
#
# and onnxruntime falls back to CPU. ESRGAN inference drops from GPU
# back to CPU silently.
#
# What this does
# --------------
# Copies known-good `libhipblas.so.2` and `librocsolver.so.0` from the
# most recent PyInstaller standalone bundle (which baked them in via
# PyInstaller's static analysis at build time) into `/usr/local/lib/`,
# then refreshes the dynamic linker cache. All other transitive deps of
# those .so files resolve from the host's current ROCm 6.4 install
# (`librocblas.so.4`, `libamdhip64.so.6`, `libhipblaslt.so.0`, etc.).
#
# Re-run this script after any system update that touches ROCm or any
# `pip install` that reinstalls `onnxruntime-rocm`. Also see its sibling
# `fix_onnxruntime_rocm_execstack.py` for the exec-stack patch.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="${REPO_ROOT}/dist/retrodb/_internal"
LDCONFIG=/sbin/ldconfig  # /sbin not in user PATH on openSUSE

# Each entry: <basename of .so>
SOS=(libhipblas.so.2 librocsolver.so.0)

# Pre-flight: every source .so present?
for so in "${SOS[@]}"; do
    if [[ ! -f "${BUNDLE_DIR}/${so}" ]]; then
        echo "ERROR: source .so not found at ${BUNDLE_DIR}/${so}" >&2
        echo "  Run \`python3 build_dist.py --standalone\` first to rebuild the bundle," >&2
        echo "  or place known-good ROCm 6.4-compatible copies at those paths." >&2
        exit 1
    fi
done

# Resolve-deps check using the bundle dir on LD_LIBRARY_PATH (bundle is
# self-contained so all the source .so's deps satisfy here even if the
# host is missing some). We just want to confirm the .so files are not
# corrupt / wrong-arch before we sudo-copy.
for so in "${SOS[@]}"; do
    if LD_LIBRARY_PATH="${BUNDLE_DIR}:/opt/rocm/lib" ldd "${BUNDLE_DIR}/${so}" 2>&1 | grep -q "not found"; then
        echo "WARNING: ${so} has unresolved deps even with bundle dir on LD_LIBRARY_PATH:" >&2
        LD_LIBRARY_PATH="${BUNDLE_DIR}:/opt/rocm/lib" ldd "${BUNDLE_DIR}/${so}" 2>&1 | grep "not found" >&2 || true
        echo "  Bundle may be incomplete — rebuild via \`python3 build_dist.py --standalone\`." >&2
    fi
done

echo "Installing into /usr/local/lib/ (sudo required) ..."
for so in "${SOS[@]}"; do
    sudo install -m 0644 "${BUNDLE_DIR}/${so}" "/usr/local/lib/${so}"
    echo "  installed /usr/local/lib/${so}"
done
sudo "${LDCONFIG}"

echo
echo "Verifying (via ${LDCONFIG} -p):"
all_ok=1
for so in "${SOS[@]}"; do
    if "${LDCONFIG}" -p | grep -qE "^[[:space:]]*${so//./\\.} "; then
        "${LDCONFIG}" -p | grep -E "^[[:space:]]*${so//./\\.} "
    else
        echo "FAIL — ldconfig cache does not list ${so} after install." >&2
        all_ok=0
    fi
done
[[ ${all_ok} -eq 1 ]] || exit 2
echo "OK — all legacy ROCm .so files now resolvable system-wide."

echo
echo "Sanity-test (loads onnxruntime-rocm provider .so):"
python3 -c "
import os
import onnxruntime as ort
model = os.path.expanduser('~/.cache/realesrgan/RealESRGAN_x4plus.onnx')
if not os.path.exists(model):
    print('  (model not cached — skipping session test)')
else:
    sess = ort.InferenceSession(
        model, providers=['ROCMExecutionProvider', 'CPUExecutionProvider']
    )
    print(f'  active providers: {sess.get_providers()}')
"
