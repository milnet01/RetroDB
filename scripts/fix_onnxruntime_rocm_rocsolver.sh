#!/usr/bin/env bash
# Installs the `rocsolver` package (provides `librocsolver.so.0`) that the
# pre-built `onnxruntime-rocm` wheel's ROCm provider depends on.
#
# Why this exists
# ---------------
# AMD's `onnxruntime-rocm` wheel dynamically links `librocsolver.so.0`. A ROCm
# install that brings in `rocblas`/`hipblaslt` but omits `rocsolver` (the box's
# original state — rocsolver was never installed) leaves the provider unable to
# load:
#
#     Failed to load library libonnxruntime_providers_rocm.so with error:
#     librocsolver.so.0: cannot open shared object file
#
# and onnxruntime silently falls back to CPU. This is distinct from the
# exec-stack patch (`fix_onnxruntime_rocm_execstack.py`) and the legacy hipBLAS
# ABI bridge (`fix_onnxruntime_rocm_libhipblas.sh`).
#
# What this does
# --------------
# Idempotent. If `librocsolver.so.0` already resolves, it exits OK. Otherwise it
# installs the `rocsolver` package that MATCHES the host's installed `rocblas`
# build (same ROCm point release / SLES release tag) from AMD's official ROCm
# repo, then refreshes the dynamic linker cache. Using the package manager (not
# a copy into /usr/local/lib) means rpm tracks the file and a later `zypper up`
# from the same repo keeps it current.
#
# Re-run this after any system update or manual ROCm (re)install that drops
# rocSOLVER. Needs network access to repo.radeon.com and sudo.
set -euo pipefail

LDCONFIG=/sbin/ldconfig   # /sbin not on user PATH on openSUSE
SONAME=librocsolver.so.0

# ---------------------------------------------------------------------------
# 0. Idempotency — already resolvable? Nothing to do.
# ---------------------------------------------------------------------------
if "${LDCONFIG}" -p 2>/dev/null | grep -qE "^[[:space:]]*${SONAME//./\\.} "; then
    echo "OK — ${SONAME} already resolvable system-wide; nothing to do."
    "${LDCONFIG}" -p | grep -E "^[[:space:]]*${SONAME//./\\.} "
    exit 0
fi

# ---------------------------------------------------------------------------
# 1. Determine the matching rocsolver from the installed rocblas.
#    rocblas vendor=AMD release tag e.g. "4.4.0.60400-sles156.47" pins the
#    ROCm build (60400 -> 6.4.0) and SLES release suffix we must match.
# ---------------------------------------------------------------------------
if ! command -v rpm >/dev/null 2>&1; then
    echo "ERROR: rpm not found — this script targets the openSUSE/SLES host." >&2
    exit 1
fi
if ! rpm -q rocblas >/dev/null 2>&1; then
    echo "ERROR: rocblas is not installed — install the AMD ROCm stack first." >&2
    echo "  Cannot determine which rocsolver build to fetch without it." >&2
    exit 1
fi

ROCBLAS_NVR="$(rpm -q --qf '%{VERSION}-%{RELEASE}' rocblas)"   # 4.4.0.60400-sles156.47
REL_TAG="${ROCBLAS_NVR#*-}"                                    # sles156.47
# ROCm minor version for the repo path (e.g. 6.4) from /opt/rocm/.info/version.
ROCM_VER="$(cat /opt/rocm/.info/version 2>/dev/null | cut -d- -f1)"  # 6.4.0
ROCM_MINOR="${ROCM_VER%.*}"                                          # 6.4
ROCM_MAJOR="${ROCM_VER%%.*}"                                         # 6

if [[ -z "${ROCM_MINOR}" || -z "${REL_TAG}" ]]; then
    echo "ERROR: could not derive ROCm version (${ROCM_VER:-?}) / release tag (${REL_TAG:-?})." >&2
    exit 1
fi

# The onnxruntime-rocm wheel links librocblas.so.4 (ROCm 6.x). A ROCm 7.x
# rocsolver links librocblas.so.5 and would NOT satisfy the wheel — refuse.
if [[ "${ROCM_MAJOR}" != "6" ]]; then
    echo "ERROR: detected ROCm ${ROCM_VER}. The onnxruntime-rocm wheel expects the" >&2
    echo "  ROCm 6.x ABI (librocblas.so.4); a ${ROCM_MAJOR}.x rocsolver won't load it." >&2
    echo "  Install a ROCm 6.x rocsolver manually, or use a matching onnxruntime-rocm wheel." >&2
    exit 1
fi

REPO="https://repo.radeon.com/rocm/zyp/${ROCM_MINOR}/main"
echo "Host: rocblas ${ROCBLAS_NVR}  (ROCm ${ROCM_VER}, tag ${REL_TAG})"
echo "Locating matching rocsolver in ${REPO}/ ..."

# Find the exact rocsolver rpm whose release tag matches the installed rocblas.
RPM_NAME="$(curl -fsS --max-time 60 "${REPO}/" \
    | grep -oE "rocsolver-[0-9][^\"<> ]*-${REL_TAG}\.x86_64\.rpm" \
    | sort -u | head -1)"
if [[ -z "${RPM_NAME}" ]]; then
    echo "ERROR: no rocsolver-*-${REL_TAG}.x86_64.rpm found at ${REPO}/" >&2
    echo "  The repo layout may have changed, or this ROCm build isn't published there." >&2
    exit 1
fi
echo "  -> ${RPM_NAME}"

# ---------------------------------------------------------------------------
# 2. Download, trust AMD's signing key (if needed), install, refresh cache.
# ---------------------------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
echo "Downloading ${RPM_NAME} ..."
curl -fsS --max-time 300 -o "${TMP}/${RPM_NAME}" "${REPO}/${RPM_NAME}"

# Import AMD's ROCm signing key so zypper can verify the rpm (NOKEY otherwise).
if ! rpm -q gpg-pubkey --qf '%{SUMMARY}\n' 2>/dev/null | grep -qi 'AMD'; then
    echo "Importing AMD ROCm signing key (sudo) ..."
    sudo rpm --import https://repo.radeon.com/rocm/rocm.gpg.key
fi

echo "Installing ${RPM_NAME} (sudo) ..."
sudo zypper -n install "${TMP}/${RPM_NAME}"

echo "Refreshing dynamic linker cache (sudo ${LDCONFIG}) ..."
sudo "${LDCONFIG}"

# ---------------------------------------------------------------------------
# 3. Verify.
# ---------------------------------------------------------------------------
echo
if "${LDCONFIG}" -p | grep -qE "^[[:space:]]*${SONAME//./\\.} "; then
    "${LDCONFIG}" -p | grep -E "^[[:space:]]*${SONAME//./\\.} "
    echo "OK — ${SONAME} now resolvable system-wide."
else
    echo "FAIL — ${SONAME} still not in the linker cache after install." >&2
    exit 2
fi

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
