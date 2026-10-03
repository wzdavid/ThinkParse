# MinerU 4.0 image for the ThinkParse compose gpu profile.
# Based on MinerU docker/global/Dockerfile and docker/china/Dockerfile.
# Deltas: pin mineru[torch]==4.0.10, and download only the weights MINERU_GPU_TIER needs.
# MINERU_GPU_TIER=standard serves every tier and downloads the VLM weights.
# MINERU_GPU_TIER=basic serves flash and basic on smaller GPUs without VLM weights.

ARG VLLM_BASE_IMAGE=vllm/vllm-openai:v0.21.0
FROM ${VLLM_BASE_IMAGE}

RUN apt-get update && \
    apt-get install -y \
        curl \
        libgl1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ARG MINERU_VERSION=4.0.10
ARG MINERU_GPU_TIER=standard
ARG MINERU_DOWNLOAD_SOURCE=modelscope
ARG PIP_INDEX_URL=https://pypi.org/simple

RUN python3 -m pip install -U "mineru[torch]==${MINERU_VERSION}" -i "${PIP_INDEX_URL}" --break-system-packages && \
    python3 -m pip cache purge

ENV MINERU_MODEL_SMALL_BACKEND=torch \
    MINERU_MODEL_VLM_ENGINE=vllm

RUN mineru-kit models download --tier "${MINERU_GPU_TIER}" --small-backend torch --vlm-engine vllm -s "${MINERU_DOWNLOAD_SOURCE}"

COPY mineru_file_gc.py /tmp/mineru_file_gc.py
RUN python3 -c "import pathlib,shutil,site; dest=pathlib.Path(site.getsitepackages()[0]); shutil.copy('/tmp/mineru_file_gc.py', dest/'mineru_file_gc.py'); (dest/'mineru_file_gc.pth').write_text('import mineru_file_gc\n')"

ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
