# PredComp reproduction environment
# Ubuntu 20.04 = the authors' OS. Build:  docker build -t predcomp:focal docker/
FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive

# System tools: GCC 9.4, perf (Issue 15) and the real libtinfo5 (Issue 12)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libtinfo5 linux-tools-generic wget ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

# Miniforge (conda)
RUN wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/mf.sh \
 && bash /tmp/mf.sh -b -p /opt/conda && rm /tmp/mf.sh
ENV PATH=/opt/conda/bin:$PATH

# Python 3.9.21 (as in the README) + clang 16, matching IR2Vec's LLVM 16 (Issue 11)
RUN conda create -y -n predcomp python=3.9.21 clang=16 && conda clean -afy
ENV PATH=/opt/conda/envs/predcomp/bin:$PATH

# Python packages, with our fixes (Issues 1, 2, 3, 5, 6, 7, 8)
RUN pip install --no-cache-dir torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir IR2Vec==2.1.1 networkx==3.2.1 programl==0.3.2 psutil==6.1.1 SQLAlchemy==2.0.30 torch_geometric==2.6.1 \
 && pip install --no-cache-dir protobuf==3.20.3 "setuptools<70" packaging pandas pyyaml pydantic \
 && pip install --no-cache-dir torchdata==0.8.0 --no-deps \
 && pip uninstall -y dgl \
 && pip install --no-cache-dir dgl==2.4.0 -f https://data.dgl.ai/wheels/torch-2.4/repo.html

# programl uses a class name that newer dgl removed (Issue 9)
RUN sed -i 's/from dgl.heterograph import DGLHeteroGraph/from dgl import DGLGraph as DGLHeteroGraph/' \
    /opt/conda/envs/predcomp/lib/python3.9/site-packages/programl/transform_ops.py

# The PredComp code is mounted at /work/PredComp (Issue 4: imports need the folder name "PredComp")
ENV PYTHONPATH=/work
WORKDIR /work/PredComp
