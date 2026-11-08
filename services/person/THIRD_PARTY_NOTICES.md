# Inference backbone attribution

`src/fridge_person/backbones.py` adapts only the inference architectures needed by
our selected checkpoints, retaining their module/state-dictionary names. Unused
architectures, training initialization, and training-framework dependencies were
omitted. No checkpoint files are redistributed.

- AdaFace, Minchul Kim, MIT license (`licenses/AdaFace-MIT.txt`).
  Source: https://github.com/mk-minchul/AdaFace/blob/c60eaa786a42c03444f3df7096dbaf9d57ae010d/net.py
- MagFace, IrvingMeng/MagFace contributors, Apache-2.0
  (`licenses/MagFace-Apache-2.0.txt`).
  Source: https://github.com/IrvingMeng/MagFace/blob/99bae614ac2643b9694bf18e0c5645272ff6acfa/models/iresnet.py

Code licenses do not establish pretrained-weight or training-dataset reuse rights.
