# Reproducibility issues

Problems we hit while following the authors' instructions for the original
[PredComp repository](https://github.com/LanduBing/PredComp_taco), and how we fixed them.

**Seen on:** T = Teodora (Ubuntu 20.04 in Docker, GCC 9.4), A = Aleksei (Ubuntu 22.04 in WSL, GCC 11.4).
**Fixed in:** `Dockerfile` (environment) or `apply_patches.sh` (code).

## Summary by category

| Category | Issues |
|---|---|
| Package versions that do not work together | 1, 3, 5, 6, 8, 9 |
| Dependencies and tools not documented | 2, 7, 11, 12, 15 |
| Things hard-coded for the authors' machine | 4, 10, 13, 14 |
| Bugs in the scripts and files | 16, 17, 18 |

## All issues

| # | Issue | What happened | Our fix | Seen on | Fixed in |
|---|---|---|---|---|---|
| 1 | networkx vs Python | The README requires Python 3.9.21, but `requirements.txt` pins networkx 3.4.2, which needs Python 3.10 or newer. | Used networkx 3.2.1. | T, A | patches, Dockerfile |
| 2 | Huge GPU download | Installing torch 2.4.0 pulls several GB of CUDA packages, though the pre-trained models only need a CPU. | Installed the CPU-only build of torch 2.4.0. | T, A | Dockerfile |
| 3 | protobuf not pinned | programl 0.3.2 fails to import with the protobuf version pip picks by default (6.33): "Descriptors cannot be created directly". | Installed protobuf 3.20.3. | T, A | Dockerfile |
| 4 | Folder name | The code imports `PredComp.*`, but the repository clones into `PredComp_taco`, so `main.py` fails with "No module named PredComp". Not mentioned in the README. | Renamed the folder to `PredComp` and set `PYTHONPATH` to its parent. | T, A | patches, Dockerfile |
| 5 | dgl vs setuptools | dgl (needed by programl, not listed in `requirements.txt`) fails to import with recent setuptools: "No module named setuptools.extern". | Installed `setuptools<70`. | T | Dockerfile |
| 6 | dgl vs torchdata | pip installs torchdata 0.11, which removed the `datapipes` module dgl uses. | Installed torchdata 0.8.0 (matches torch 2.4) with `--no-deps`. | T, A | Dockerfile |
| 7 | Missing Python packages | dgl and the code need `pandas`, `pyyaml`, `pydantic` and `packaging`, which nothing installs. | Installed them. | T, A | Dockerfile |
| 8 | dgl not pinned | pip picks dgl 2.1.0, which has no GraphBolt library for torch 2.4.0. | Installed the official dgl 2.4.0 build for torch 2.4. | T, A | Dockerfile |
| 9 | programl vs new dgl | programl imports `DGLHeteroGraph`, a class name newer dgl removed. | Patched programl to import `DGLGraph` under the old name. | T, A | Dockerfile |
| 10 | Hard-coded GCC path | `main.py` overwrites the `--bin_path` option with the authors' own path (`/home/gby/gcc_install/build/bin`). | Disabled that line, so `--bin_path` works. | T, A | patches |
| 11 | clang required, not documented | Feature extraction calls `clang -emit-llvm` to make LLVM IR for IR2Vec. The README never mentions clang. IR2Vec 2.1.1 is built on LLVM 16, so the clang version matters. | Installed clang 16 from conda-forge. | T, A | Dockerfile |
| 12 | Old system library | The tools need `libtinfo.so.5`, which newer Ubuntu releases do not ship. | Used an Ubuntu 20.04 container (the authors' OS), which has the real `libtinfo5`. | T | Dockerfile |
| 13 | GCC dump file name | The code expects `*.090i.inline`, but the number depends on the GCC version: GCC 9.4 writes `.076i`, GCC 11.4 writes `.083i`. | Search for `*i.inline` instead. | T, A | patches |
| 14 | Models saved on a GPU | The pre-trained models were saved with CUDA, so `torch.load` fails on a machine without a GPU. | Added `map_location='cpu'` in `Inference/predict.py`. | A, T | patches |
| 15 | perf required, not documented | Timing uses `perf stat`, which is not installed or mentioned. In Docker, perf is blocked unless the container runs with `--privileged`. | Installed `linux-tools-generic`, run the container with `--privileged`. | T, A | Dockerfile |
| 16 | Scripts not executable | `__run`, `_ccc_check_output.copy` and similar cBench scripts are stored without the executable permission: "Workload failed: Permission denied". | `chmod +x` on all cBench run scripts. | T, A | patches |
| 17 | One failure crashes everything | If one program fails to compile, the error is stored silently and the whole run crashes later, without saying why. | Print the compiler error, and skip a program whose -O3 build fails. | T | patches |
| 18 | Library order when linking | Programs are linked as `gcc -lm *.o`. Ubuntu's linker only uses a library listed after the files that need it, so `automotive_susan_s` fails ("undefined reference to exp"). | Moved `-lm` after the object files. | T | patches |
