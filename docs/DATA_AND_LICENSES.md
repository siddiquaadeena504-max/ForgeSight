# Third-party data and weights

Nothing below is redistributed in this repository; `scripts/fetch_assets.sh` downloads it. Check each licence against your
intended (especially commercial) use before deploying models trained on these datasets.

| Asset | Source | Licence / terms | Used for |
|---|---|---|---|
| MobileNetV2 ImageNet checkpoint `mobilenetv2-c5e733a8.pth` and network definition | github.com/d-li14/mobilenetv2.pytorch | Apache-2.0 (weights derive from ImageNet, which has its own research-use terms) | frozen feature extractor (PatchCore, material identifier), encoder initialisation (SegNet) |
| Magnetic Tile Surface Defects | github.com/abin24/Magnetic-tile-defect-datasets. (Huang, Qiu, Yuan, "Saliency of magnetic tile surface defects") | no licence file; the authors ask for citation | ceramics profile: training and validation |
| DeepPCB | github.com/tangsanli5201/DeepPCB (Tang et al.) | MIT | electronics profile: training and validation |
| CrackForest (CFD) | github.com/cuilimeng/CrackForest-dataset (Shi et al., 2016; Cui et al., 2015) | non-commercial research use; citation requested | construction profile: training and validation |

Dataset requirements for a new material (rule of thumb used by the platform):

* **Anomaly model (PatchCore):** ≥ 8 defect-free training images to fit at all; 50-200 representative good images for a
  useful model; ≥ 5 good + ≥ 5 defective images in *each* of validation and test for calibration and a validated decision
  rule; several thousand test images per class before any "three nines" claim.
* **Supervised segmentation / detection:** pixel masks or boxes for every defect class, ideally ≥ 100 instances per class,
  from the production camera and lighting.
* **Golden-reference profiles:** a registered defect-free template per product view.
