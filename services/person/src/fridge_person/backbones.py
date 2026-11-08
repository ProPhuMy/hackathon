"""Inference-only IR-50 networks adapted from AdaFace and MagFace.

AdaFace: c60eaa786a42c03444f3df7096dbaf9d57ae010d (MIT).
MagFace: 99bae614ac2643b9694bf18e0c5645272ff6acfa (Apache-2.0).
See licenses/ and THIRD_PARTY_NOTICES.md. Architecture/state-dict names preserved;
training initialization and unused backbones omitted; all inference weights load strictly.
"""
import torch
from torch import nn


class _AdaBlock(nn.Module):
    def __init__(self, inputs, outputs, stride):
        super().__init__()
        self.shortcut_layer = (nn.MaxPool2d(1, stride) if inputs == outputs else
                               nn.Sequential(nn.Conv2d(inputs, outputs, 1, stride, bias=False), nn.BatchNorm2d(outputs)))
        self.res_layer = nn.Sequential(
            nn.BatchNorm2d(inputs), nn.Conv2d(inputs, outputs, 3, 1, 1, bias=False),
            nn.BatchNorm2d(outputs), nn.PReLU(outputs),
            nn.Conv2d(outputs, outputs, 3, stride, 1, bias=False), nn.BatchNorm2d(outputs))

    def forward(self, inputs):
        return self.res_layer(inputs) + self.shortcut_layer(inputs)


class AdaFaceIR50(nn.Module):
    def __init__(self):
        super().__init__()
        self.input_layer = nn.Sequential(nn.Conv2d(3, 64, 3, 1, 1, bias=False), nn.BatchNorm2d(64), nn.PReLU(64))
        blocks = []
        channels = 64
        for outputs, count in ((64, 3), (128, 4), (256, 14), (512, 3)):
            for index in range(count):
                blocks.append(_AdaBlock(channels, outputs, 2 if index == 0 else 1))
                channels = outputs
        self.body = nn.Sequential(*blocks)
        self.output_layer = nn.Sequential(nn.BatchNorm2d(512), nn.Dropout(.4), nn.Flatten(),
                                          nn.Linear(512 * 7 * 7, 512), nn.BatchNorm1d(512, affine=False))

    def forward(self, inputs):
        raw = self.output_layer(self.body(self.input_layer(inputs)))
        norm = torch.linalg.vector_norm(raw, dim=1, keepdim=True)
        return raw / norm, norm


class _MagBlock(nn.Module):
    def __init__(self, inputs, outputs, stride, downsample):
        super().__init__()
        self.bn1 = nn.BatchNorm2d(inputs, eps=2e-5, momentum=.9)
        self.conv1 = nn.Conv2d(inputs, outputs, 3, 1, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(outputs, eps=2e-5, momentum=.9)
        self.prelu = nn.PReLU(outputs)
        self.conv2 = nn.Conv2d(outputs, outputs, 3, stride, 1, bias=False)
        self.bn3 = nn.BatchNorm2d(outputs, eps=2e-5, momentum=.9)
        self.downsample = downsample

    def forward(self, inputs):
        identity = inputs if self.downsample is None else self.downsample(inputs)
        output = self.conv1(self.bn1(inputs))
        output = self.conv2(self.prelu(self.bn2(output)))
        return self.bn3(output) + identity


class MagFaceIR50(nn.Module):
    def __init__(self):
        super().__init__()
        self.inplanes = 64
        self.conv1 = nn.Conv2d(3, 64, 3, 1, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(64, eps=2e-5, momentum=.9)
        self.prelu = nn.PReLU(64)
        self.layer1 = self._layer(64, 3)
        self.layer2 = self._layer(128, 4)
        self.layer3 = self._layer(256, 14)
        self.layer4 = self._layer(512, 3)
        self.bn2 = nn.BatchNorm2d(512, eps=2e-5, momentum=.9)
        self.dropout = nn.Dropout2d(.4, inplace=True)
        self.fc = nn.Linear(512 * 7 * 7, 512)
        self.features = nn.BatchNorm1d(512, eps=2e-5, momentum=.9)

    def _layer(self, outputs, count):
        downsample = nn.Sequential(nn.Conv2d(self.inplanes, outputs, 1, 2, bias=False),
                                   nn.BatchNorm2d(outputs, eps=2e-5, momentum=.9))
        layers = [_MagBlock(self.inplanes, outputs, 2, downsample)]
        self.inplanes = outputs
        layers.extend(_MagBlock(outputs, outputs, 1, None) for _ in range(count - 1))
        return nn.Sequential(*layers)

    def forward(self, inputs):
        output = self.prelu(self.bn1(self.conv1(inputs)))
        output = self.layer4(self.layer3(self.layer2(self.layer1(output))))
        output = self.dropout(self.bn2(output)).flatten(1)
        return self.features(self.fc(output))
