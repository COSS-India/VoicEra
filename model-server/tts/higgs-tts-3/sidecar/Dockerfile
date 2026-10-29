# syntax=docker/dockerfile:1.7
#
# SGLang-Omni v0.1.9 serving Higgs TTS 3 -- the sidecar the higgs-tts-3 adapter
# talks to. Follows upstream's own docker/Dockerfile AT THE v0.1.9 TAG, minus
# what Higgs does not use.
#
# Why not a published image (both tried on ace-h200, 22 Oct 2026):
#   * lmsysorg/sglang-omni:dev is frozen at 16 Jun 2026 (sglang-omni 0.1.0,
#     SGLang 0.5.12, torch 2.11) -- no per-stage gpu_memory_fraction, so no way
#     to stop Higgs reserving ~98% of a card shared with production, and no
#     --allowed-local-media-path. Installing 0.1.9 on top cannot work either:
#     0.1.9 pins torch 2.14.1 / SGLang 0.5.22 / transformers 5.19.
#   * hongccc/sglang-omni:dev is current, but a personal namespace and a
#     moving tag, and its entrypoint git-clones `main` on every start.
#
# So: the official SGLang base upstream pins BY DIGEST at v0.1.9, upstream's UCX
# build, the dependency list from the v0.1.9 pyproject, and the package itself
# from the v0.1.9 tag -- commit checked, so a moved tag fails the build rather
# than silently building something else.
#
# Left out on purpose: the audar-tts / fun-cosyvoice3 / minicpm-o extras (one
# compiles llama.cpp with CUDA) and qwen-tts. Higgs imports none of them.
# Expect a long first build: a large base image and a UCX compile.

ARG SGLANG_IMAGE=lmsysorg/sglang@sha256:5fc09edb6a0bb1d5b6992b543723c66d08f86d7a507e951e87e0d05db4ac766e
FROM ${SGLANG_IMAGE}

ARG SGLANG_OMNI_REF=v0.1.9
ARG SGLANG_OMNI_COMMIT=8200f49934d66de591c035cab1c626c0600905fa
ARG UCX_COMMIT=d8e50df6651b9ea5b76f23aee0aefbf053a4137a

RUN apt-get update \
    && apt-get install -y --no-install-recommends sox git \
    && rm -rf /var/lib/apt/lists/*

# UCX with CUDA, as upstream builds it: SGLang-Omni's inter-stage transport.
RUN git clone --filter=blob:none https://github.com/openucx/ucx.git /tmp/ucx \
    && git -C /tmp/ucx checkout "${UCX_COMMIT}" \
    && cd /tmp/ucx \
    && ./autogen.sh \
    && ./contrib/configure-release-mt \
        --enable-shared --disable-static --disable-doxygen-doc \
        --enable-optimizations --enable-cma --enable-devel-headers \
        --with-cuda=/usr/local/cuda --with-verbs --with-dm --prefix=/usr/local \
    && make -j"$(nproc)" \
    && make install-strip \
    && ldconfig \
    && rm -rf /tmp/ucx

# The release itself, verified. Kept in the image (not cloned at start), so a
# restart never needs the network and never changes what runs.
RUN git clone --depth 1 --branch "${SGLANG_OMNI_REF}" \
        https://github.com/sgl-project/sglang-omni.git /opt/sglang-omni \
    && test "$(git -C /opt/sglang-omni rev-parse HEAD)" = "${SGLANG_OMNI_COMMIT}" \
    || { echo "sglang-omni ${SGLANG_OMNI_REF} is not commit ${SGLANG_OMNI_COMMIT}"; exit 1; }

# Dependencies exactly as upstream's Dockerfile installs them -- into the base
# image's /opt/sglang virtualenv, which PATH resolves (uv needs it named) --
# then the package, without letting it re-resolve that stack. The FlashInfer
# reinstall is upstream's too: the base's AOT kernels stay, the Python package
# matches the pin.
RUN cd /opt/sglang-omni \
    && python3 -c 'import tomllib; print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["tool"]["uv"]["override-dependencies"]))' > /tmp/omni-overrides.txt \
    && uv pip install --python /opt/sglang/bin/python3 --no-build-isolation \
        --overrides /tmp/omni-overrides.txt -r pyproject.toml \
        descript-audiotools==0.7.2 descript-audio-codec==1.0.0 \
    && uv pip install --python /opt/sglang/bin/python3 --no-deps --reinstall flashinfer-python==0.7.1 \
    && uv pip install --python /opt/sglang/bin/python3 --no-deps --no-build-isolation . \
    && rm /tmp/omni-overrides.txt

ENV FLASHINFER_WORKSPACE_BASE=/root \
    FLASHINFER_JIT_DEBUG=0 \
    PYTHONUNBUFFERED=1 \
    LD_LIBRARY_PATH=/opt/sglang/lib/python3.12/site-packages/nvidia/nccl/lib:${LD_LIBRARY_PATH}

# Fail the BUILD, not the first start, if the options compose.extra.yml passes
# do not exist in this sglang-omni. Read from the `serve` command's own
# signature, not its --help: the help is a Rich table laid out for a terminal a
# build does not have, and grepping it reported a flag missing that is there
# (ace-h200, 22 Oct 2026). If the module cannot be imported at all here (no GPU
# is visible during `docker build`, and some imports probe for one), say so and
# let the first start be the check, rather than fail a build that may be fine.
RUN /opt/sglang/bin/python3 - <<'PY'
import inspect, sys
try:
    from sglang_omni.cli.serve import serve
except Exception as exc:  # noqa: BLE001 -- reported, not fatal; see above
    print(f"note: could not import sglang_omni.cli.serve at build time: {exc!r}")
    sys.exit(0)
import sglang_omni
print("sglang_omni", getattr(sglang_omni, "__version__", "?"), "from", sglang_omni.__file__)
have = set(inspect.signature(serve).parameters)
need = {"model_path", "model_name", "host", "port", "allowed_local_media_path", "log_level"}
missing = sorted(need - have)
if missing:
    sys.exit(f"sgl-omni serve lacks: {missing}")
print("sgl-omni serve options ok:", ", ".join(sorted(need)))
PY

WORKDIR /opt/sglang-omni
# The command (sgl-omni serve ...) is in compose.extra.yml / compose.standalone.yml,
# where every flag sits beside the reason for its value.
