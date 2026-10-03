# CPU MinerU for the ThinkParse compose cpu profile.
# ONNX small models only. This image has no CUDA and cannot serve standard or advanced.

ARG CPU_BASE_IMAGE=python:3.12-slim
FROM ${CPU_BASE_IMAGE}

RUN apt-get update && \
    apt-get install -y \
        curl \
        libgl1 \
        libglib2.0-0 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ARG MINERU_VERSION=4.0.10
ARG MINERU_DOWNLOAD_SOURCE=modelscope
ARG PIP_INDEX_URL=https://pypi.org/simple

RUN python3 -m pip install -U "mineru==${MINERU_VERSION}" -i "${PIP_INDEX_URL}" && \
    python3 -m pip cache purge

ENV MINERU_MODEL_SMALL_BACKEND=onnx \
    MINERU_MODEL_SOURCE=local

RUN mineru-kit models download --tier basic --small-backend onnx -s "${MINERU_DOWNLOAD_SOURCE}"

COPY mineru_file_gc.py /tmp/mineru_file_gc.py
RUN python3 -c "import pathlib,shutil,site; dest=pathlib.Path(site.getsitepackages()[0]); shutil.copy('/tmp/mineru_file_gc.py', dest/'mineru_file_gc.py'); (dest/'mineru_file_gc.pth').write_text('import mineru_file_gc\n')"

ENTRYPOINT ["mineru-kit"]
