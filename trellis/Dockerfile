# TRELLIS image-to-3D — pinned build.
#
# Base pairs torch 2.4.0 with CUDA 12.1 because that is the exact matrix
# upstream setup.sh publishes prebuilt wheels for (xformers 0.0.27.post2/cu121,
# kaolin torch-2.4.0_cu121, spconv-cu120). The -devel variant ships nvcc,
# needed both here (diffoctreerast / diff-gaussian-rasterization compiles)
# and at runtime (nvdiffrast JIT-compiles its kernels on first use).
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-devel

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl libgl1 libglib2.0-0 libgomp1 ninja-build \
    && rm -rf /var/lib/apt/lists/*

# 8.9 = Ada (RTX 4070 family) — restricting the arch list keeps the two
# source compiles below to minutes instead of building for every GPU.
ENV TORCH_CUDA_ARCH_LIST=8.9 \
    ATTN_BACKEND=xformers \
    SPCONV_ALGO=native

# Prebuilt CUDA wheels (no compile) — versions from TRELLIS setup.sh for
# torch 2.4.0 + cu12.
RUN pip install --no-cache-dir \
        xformers==0.0.27.post2 --index-url https://download.pytorch.org/whl/cu121 \
    && pip install --no-cache-dir spconv-cu120 \
    && pip install --no-cache-dir kaolin \
        -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.4.0_cu121.html

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Source-compiled CUDA extensions, one layer each so a failure retries cheap.
# Pins are upstream HEADs as of 2026-07-06. --no-build-isolation: their
# setup.py imports the installed torch to compile against it.
RUN git clone https://github.com/NVlabs/nvdiffrast.git /opt/nvdiffrast \
    && cd /opt/nvdiffrast \
    && git checkout 253ac4fcea7de5f396371124af597e6cc957bfae \
    && pip install --no-cache-dir --no-build-isolation .

RUN git clone --recurse-submodules https://github.com/JeffreyXiang/diffoctreerast.git /opt/diffoctreerast \
    && cd /opt/diffoctreerast \
    && git checkout b09c20b84ec3aace4729e6e18a613112320eca3a \
    && pip install --no-cache-dir --no-build-isolation .

RUN git clone https://github.com/autonomousvision/mip-splatting.git /opt/mip-splatting \
    && cd /opt/mip-splatting \
    && git checkout dda02ab5ecf45d6edb8c540d9bb65c7e451345a9 \
    && git submodule update --init --recursive submodules/diff-gaussian-rasterization \
    && pip install --no-cache-dir --no-build-isolation ./submodules/diff-gaussian-rasterization

RUN git clone https://github.com/microsoft/TRELLIS.git /opt/trellis \
    && cd /opt/trellis \
    && git checkout 442aa1e1afb9014e80681d3bf604e8d728a86ee7 \
    && git submodule update --init --recursive

ENV PYTHONPATH=/opt/trellis

WORKDIR /app
COPY serve.py /app/serve.py
EXPOSE 8000
CMD ["python", "serve.py"]
