#!/usr/bin/env bash
# Fetch the pretrained backbone and the public validation datasets (all public, via GitHub).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data/weights" "$ROOT/data/external"
W="$ROOT/data/weights/mobilenetv2-c5e733a8.pth"
[ -f "$W" ] || curl -fsSL -o "$W" https://raw.githubusercontent.com/d-li14/mobilenetv2.pytorch/master/pretrained/mobilenetv2-c5e733a8.pth
echo "c5e733a8  expected filename hash prefix; sha256: $(sha256sum "$W" | cut -c1-8)"
cd "$ROOT/data/external"
[ -d Magnetic-tile-defect-datasets ] || git clone --depth 1 "https://github.com/abin24/Magnetic-tile-defect-datasets." Magnetic-tile-defect-datasets
[ -d DeepPCB ] || git clone --depth 1 https://github.com/tangsanli5201/DeepPCB
[ -d CrackForest-dataset ] || git clone --depth 1 https://github.com/cuilimeng/CrackForest-dataset
echo "Assets ready. Train + validate with: (cd backend && python scripts/benchmarks.py)"
