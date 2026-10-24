#!/bin/bash
# Code fixes for the original PredComp repository (https://github.com/LanduBing/PredComp_taco).
# Run once, from the folder that contains PredComp_taco (or PredComp). Safe to run twice.
set -e
# Issue 4: the code imports PredComp.*, so the folder must be called PredComp
[ -d PredComp_taco ] && [ ! -d PredComp ] && mv PredComp_taco PredComp
cd PredComp
# Issue 1: networkx 3.4.2 needs Python >= 3.10, but the README requires 3.9.21
sed -i 's/networkx==3.4.2/networkx==3.2.1/' requirements.txt
# Issue 10: main.py overwrites --bin_path with the authors' own path
sed -i "s|^    bin_path='/home/gby/gcc_install/build/bin'|    # bin_path='/home/gby/gcc_install/build/bin'  # disabled: hard-coded by authors|" main.py
# Issue 13: GCC dump file number depends on the GCC version (090i is hard-coded)
grep -q '^import glob' Dataset/process/heads.py || sed -i '1i import glob' Dataset/process/heads.py
sed -i "s|f'{self.path}/{self.file}.090i.inline'|glob.glob(f'{self.path}/{self.file}.*i.inline')[0]|" Dataset/process/heads.py
sed -i 's|{self.file}.090i.inline"|{self.file}.*i.inline"|' Dataset/process/heads.py
# Issue 14: pre-trained models were saved on a GPU; load them on the CPU
grep -q "map_location='cpu'" Inference/predict.py || sed -i "s|weights_only=False)|weights_only=False,map_location='cpu')|" Inference/predict.py
# Issue 16: cBench run scripts are stored without the executable permission
find Dataset/cBench_V1.1 -type f \( -name '__run' -o -name '__compile' -o -name '_ccc_*' \) -exec chmod +x {} +
# Issue 17: a failed -O3 compile is stored silently and then crashes the whole run
grep -q "compile failed for" Dataset/process/heads.py || sed -i "/CompileError.add(self.session,'',cp.stderr.decode('utf-8'))/a\            print('error: compile failed for', self.name); print(cp.stderr.decode('utf-8')[-3000:])" Dataset/process/heads.py
grep -q "skipped: -O3" main.py || sed -i "s|^        cbench\[p\].prepare()$|        cbench[p].prepare()\n        if cbench[p].O3_perf is None:\n            print(f'{p} skipped: -O3 compile/run failed'); continue|" main.py
# Issue 18: -lm must come after the object files when linking
grep -rl -- "-lm \*.o" --include=*.py . | xargs -r sed -i 's|-lm \*\.o\(.*\)|*.o\1 -lm|'
grep -rq -- "-lm \*.o" --include=*.py . && echo "WARNING: Issue 18 not patched, move -lm after *.o by hand" || true
# Test copy of main.py that runs only one program
sed "s|prog=json.load(f)|prog=json.load(f); prog={'automotive_bitcount': prog['automotive_bitcount']}|" main.py > main_test.py
echo "Patches applied."
