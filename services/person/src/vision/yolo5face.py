"""Local YOLO5Face ONNX detector adapter for deepcam-cn/yolov5-face.

Pinned upstream revision:
    Repository: https://github.com/deepcam-cn/yolov5-face
    Commit: 152c688d551aefb973b7b589fb0691c93dab3564
    Authors: deepcam-cn / YOLOv5-Face contributors (GPL-3.0)

Supported export schema:
    export.py with model.model[-1].export_cat = True
    Invocation:
        python export.py --weights weights/yolov5s-face.pt --img_size 640 --batch_size 1
    Input:
        name: 'input' (exactly 1 float32 NCHW input)
        shape: (batch, 3, height, width), default (1, 3, 640, 640) float32 in [0, 1]
    Output:
        name: 'output' (exactly 1 rank-3 output)
        shape: (batch, num_candidates, 16)
        Columns (dimension -1, 16 channels):
            [0:2]  center x, center y (cx, cy) in letterbox coordinates
            [2:4]  width, height (bw, bh) in letterbox coordinates
            [4]    objectness confidence (sigmoid applied in forward)
            [5:15] 5 facial landmarks in letterbox coordinates:
                   (x1, y1), (x2, y2), (x3, y3), (x4, y4), (x5, y5)
                   ordered: left eye, right eye, nose, left mouth, right mouth
            [15]   face class probability (sigmoid applied in forward, nc=1)

Preprocessing verified recipe:
    Input image: BGR uint8 (H, W, 3).
    Letterbox padding: resize keeping aspect ratio, pad with color (114, 114, 114) to model input size.
    Color: BGR -> RGB (matching official training/datasets loader; detect_face.py has an extra flip).
    Scale: float32 in [0.0, 1.0] (divide by 255.0).
    Tensor shape: (1, 3, height, width).
"""
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort

from .boxes import letterbox, nms, valid_points
from .detection import FaceDetection
from ..storage import file_hash


class YOLO5Face:
    def __init__(self, model_path, conf_threshold=0.3, iou_threshold=0.5, input_size=None):
        if not np.isfinite(conf_threshold) or not 0 <= conf_threshold <= 1:
            raise ValueError(f"Invalid conf_threshold: {conf_threshold}")
        if not np.isfinite(iou_threshold) or not 0 <= iou_threshold <= 1:
            raise ValueError(f"Invalid iou_threshold: {iou_threshold}")

        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)

        self.path = Path(model_path)
        if not self.path.is_file():
            raise ValueError(f"Missing local file: {self.path}. See SETUP.md; weights are never downloaded automatically.")
        self.sha256 = file_hash(self.path)

        try:
            self.session = ort.InferenceSession(str(self.path), providers=['CPUExecutionProvider'])
        except Exception as error:
            raise ValueError(f"Failed to load ONNX model from {self.path}: {error}") from error

        # Validate input tensor metadata
        inputs = self.session.get_inputs()
        if len(inputs) != 1:
            raise ValueError(f"Expected exactly 1 model input, got {len(inputs)}")
        inp = inputs[0]
        if inp.type not in ('tensor(float)', 'tensor(float32)', 'float32', 'float'):
            raise ValueError(f"Expected float32 model input, got {inp.type}")
        if len(inp.shape) != 4:
            raise ValueError(f"Expected 4-D NCHW model input, got {len(inp.shape)}-D shape {inp.shape}")

        batch_dim = inp.shape[0]
        if isinstance(batch_dim, int) and batch_dim != 1:
            raise ValueError(f"Expected batch dimension 1 (or dynamic batch), got {batch_dim}")

        channels = inp.shape[1]
        if channels != 3:
            raise ValueError(f"Expected 3 input channels (NCHW), got {channels}")

        h_dim, w_dim = inp.shape[2], inp.shape[3]
        if not isinstance(h_dim, int) or not isinstance(w_dim, int) or isinstance(h_dim, bool) or isinstance(w_dim, bool):
            raise ValueError(
                f"Model input spatial dimensions must be fixed integers, got shape {inp.shape}. "
                "Dynamic spatial dimensions are not supported by the pinned exporter."
            )
        static_size = (h_dim, w_dim)
        if input_size is not None:
            req_size = (int(input_size[0]), int(input_size[1]))
            if req_size != static_size:
                raise ValueError(f"Model input spatial dimensions are fixed to {static_size}, but input_size={req_size} was requested")
        self.input_size = static_size

        if (self.input_size[0] <= 0 or self.input_size[1] <= 0
                or self.input_size[0] % 32 != 0 or self.input_size[1] % 32 != 0):
            raise ValueError(f"Invalid model input size: {self.input_size}. Both dimensions must be positive multiples of 32.")

        self.input_name = inp.name

        # Validate output tensor metadata
        outputs = self.session.get_outputs()
        if len(outputs) != 1:
            raise ValueError(f"Expected exactly 1 model output, got {len(outputs)}")
        out = outputs[0]
        if out.type not in ('tensor(float)', 'tensor(float32)', 'float32', 'float'):
            raise ValueError(f"Expected float32 model output, got {out.type}")
        if len(out.shape) != 3:
            raise ValueError(f"Expected rank-3 model output (batch, num_candidates, 16), got {len(out.shape)}-D shape {out.shape}")

        out_batch = out.shape[0]
        if isinstance(out_batch, int) and out_batch != 1:
            raise ValueError(f"Expected output batch dimension 1, got {out_batch}")

        out_cols = out.shape[2]
        if out_cols != 16:
            raise ValueError(
                f"Incompatible YOLO5Face ONNX output schema: expected trailing dimension 16, got {out_cols}. "
                "This adapter requires deepcam-cn/yolov5-face export with export_cat=True (16 channels: 4 box + 1 obj + 10 landmarks + 1 cls)."
            )

        self.output_name = out.name

    def preprocess(self, image):
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("Invalid input image: expected uint8 BGR array of shape (H, W, 3)")
        h, w = image.shape[:2]
        if h <= 0 or w <= 0:
            raise ValueError(f"Invalid image dimensions: ({h}, {w})")

        padded, gain, pad = letterbox(image, self.input_size)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        blob = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
        tensor = np.expand_dims(blob, axis=0)
        return tensor, gain, pad

    def postprocess(self, raw, gain, pad, orig_shape):
        if not isinstance(raw, np.ndarray) or raw.ndim != 3 or raw.shape[0] != 1 or raw.shape[2] != 16:
            raise ValueError(f"Incompatible YOLO5Face ONNX output schema: expected (1, N, 16), got {getattr(raw, 'shape', None)}")
        if not np.issubdtype(raw.dtype, np.floating):
            raise ValueError(f"Expected floating point model output, got {raw.dtype}")
        if not np.isfinite(raw).all():
            raise ValueError("YOLO5Face output contains non-finite values")

        preds = raw[0]
        if preds.shape[0] == 0:
            return []

        cx = preds[:, 0]
        cy = preds[:, 1]
        bw = preds[:, 2]
        bh = preds[:, 3]
        obj_conf = preds[:, 4]
        landmarks = preds[:, 5:15]
        cls_conf = preds[:, 15]

        # Validate each probability independently in [0, 1]
        valid_prob = (obj_conf >= 0.0) & (obj_conf <= 1.0) & (cls_conf >= 0.0) & (cls_conf <= 1.0)
        conf = obj_conf * cls_conf
        mask = valid_prob & (conf >= self.conf_threshold) & (bw > 0) & (bh > 0)
        if not np.any(mask):
            return []

        cx = cx[mask]
        cy = cy[mask]
        bw = bw[mask]
        bh = bh[mask]
        conf = conf[mask]
        landmarks = landmarks[mask]

        x1 = cx - bw / 2.0
        y1 = cy - bh / 2.0
        x2 = cx + bw / 2.0
        y2 = cy + bh / 2.0

        left, top = pad
        orig_h, orig_w = orig_shape[:2]

        ox1 = np.clip((x1 - left) / gain, 0.0, float(orig_w))
        oy1 = np.clip((y1 - top) / gain, 0.0, float(orig_h))
        ox2 = np.clip((x2 - left) / gain, 0.0, float(orig_w))
        oy2 = np.clip((y2 - top) / gain, 0.0, float(orig_h))

        valid_box = (ox2 > ox1) & (oy2 > oy1)
        if not np.any(valid_box):
            return []

        ox1 = ox1[valid_box]
        oy1 = oy1[valid_box]
        ox2 = ox2[valid_box]
        oy2 = oy2[valid_box]
        conf = conf[valid_box]
        landmarks = landmarks[valid_box]

        boxes = np.stack([ox1, oy1, ox2, oy2], axis=1)

        lx = (landmarks[:, 0::2] - left) / gain
        ly = (landmarks[:, 1::2] - top) / gain
        pts = np.stack([lx, ly], axis=-1)

        keep = nms(boxes, conf, self.iou_threshold)

        results = []
        for k in keep:
            box = boxes[k]
            score = float(conf[k])
            valid_p = valid_points(pts[k], box)
            results.append(FaceDetection(box=box.copy(), confidence=score, landmarks=valid_p))
        return results

    def detect(self, image):
        tensor, gain, pad = self.preprocess(image)
        try:
            raw = self.session.run([self.output_name], {self.input_name: tensor})[0]
        except Exception as error:
            raise ValueError(f"Inference failed on ONNX model: {error}") from error
        return self.postprocess(raw, gain, pad, image.shape)
