# SGLang-Omni serving Higgs TTS 3 -- the sidecar the higgs-tts-3 adapter talks to.
#
# Why build at all instead of naming the upstream image directly: upstream
# publishes only a moving `dev` tag, and that image's entrypoint git-clones
# sglang-omni `main` and pip-installs it EVERY TIME THE CONTAINER STARTS. That is
# a network dependency on every restart and a different server on every restart.
# This file keeps the image (CUDA, SGLang, UCX, flash-attn -- the hard parts) and
# replaces the moving part with a released, pinned sglang-omni:
#
#   * SGLANG_OMNI_AUTO_CLONE=0 turns the clone-on-start off;
#   * sglang-omni is installed from PyPI at SGLANG_OMNI_VERSION, --no-deps so
#     the image's own CUDA stack is never re-resolved.
#
# PIN THE BASE BY DIGEST after the first good pull. `dev` moves with upstream
# main, so a rebuild next month gets a different CUDA/SGLang underneath the same
# sglang-omni release:
#
#   docker inspect --format '{{index .RepoDigests 0}}' lmsysorg/sglang-omni:dev
#   # then in model-server/.env:
#   HIGGS_SGLANG_BASE_IMAGE=lmsysorg/sglang-omni@sha256:<digest>
#
# 0.1.9 (21 Oct 2026) is the release whose source this folder was written
# against: its Higgs pipeline, the per-stage gpu_memory_fraction flags in
# compose.extra.yml, and the disconnect-abort on streaming /v1/audio/speech were
# all read in that release, not assumed.
ARG SGLANG_BASE_IMAGE=lmsysorg/sglang-omni:dev
FROM ${SGLANG_BASE_IMAGE}

ARG SGLANG_OMNI_VERSION=0.1.9

ENV SGLANG_OMNI_AUTO_CLONE=0 \
    PYTHONUNBUFFERED=1

RUN python3 -m pip install --no-cache-dir --no-deps --no-build-isolation \
        "sglang-omni==${SGLANG_OMNI_VERSION}" \
    && sgl-omni --help >/dev/null

# Upstream's entrypoint is kept: with AUTO_CLONE off it only runs NVIDIA's own
# entrypoint and then the command. The command (sgl-omni serve ...) is in
# compose.extra.yml, where every flag sits beside the reason for its value.
