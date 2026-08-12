import os
import cv2
import glob
import time
import numpy as np
from pynq_dpu import DpuOverlay

CLASSES = [
    'person', 'backpack', 'handbag', 'suitcase', 'bottle',
    'cup', 'chair', 'laptop', 'cell phone', 'book'
]
cn = len(CLASSES)
NO = 5 + cn  # 15

class YOLOv5DPUEngine:
    def __init__(self, bit_path, xmodel_path):
        self.overlay = DpuOverlay(bit_path)
        self.overlay.load_model(xmodel_path)
        self.runner = self.overlay.runner

        self.in_tensors = self.runner.get_input_tensors()
        self.in_shape = tuple(self.in_tensors[0].dims)
        self.in_scale = 2 ** self.in_tensors[0].get_attr("fix_point")

        self.out_tensors = self.runner.get_output_tensors()
        self.out_meta = []
        for t in self.out_tensors:
            self.out_meta.append({
                'name': t.name,
                'shape': tuple(t.dims),
                'scale': 2 ** t.get_attr("fix_point")
            })

    def execute(self, float_img):
        scaled = float_img * self.in_scale
        
        # 반올림(np.round) 및 INT8 범위 Clip 보정
        input_data = np.round(scaled).clip(-128, 127).astype(np.int8, order="C")

        outputs = [np.empty(m['shape'], dtype=np.int8, order="C") for m in self.out_meta]

        job_id = self.runner.execute_async([input_data], outputs)
        self.runner.wait(job_id)

        # 역양자화 (float32 복원)
        return [out.astype(np.float32) / m['scale'] for out, m in zip(outputs, self.out_meta)]

def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -10, 10)))

def decode_yolov5_outputs(raw_outputs, input_shape, conf_thres=0.25):
    anchors_cfg = {
        8:  np.array([[10, 13], [16, 30], [33, 23]], dtype=np.float32),
        16: np.array([[30, 61], [62, 45], [59, 119]], dtype=np.float32),
        32: np.array([[116, 90], [156, 198], [373, 326]], dtype=np.float32)
    }

    _, net_h, net_w, _ = input_shape
    predictions = []

    for out_tensor in raw_outputs:
        _, h, w, channels = out_tensor.shape
        stride = net_h // h
        
        if stride not in anchors_cfg:
            continue
        
        anchors = anchors_cfg[stride]
        out = out_tensor[0].reshape(h, w, 3, NO).copy()

        grid_y, grid_x = np.mgrid[0:h, 0:w]
        grid = np.stack((grid_x, grid_y), axis=-1).reshape(h, w, 1, 2).astype(np.float32)

        out[..., :2] = sigmoid(out[..., :2]) * 2.0 - 0.5
        out[..., 2:4] = (sigmoid(out[..., 2:4]) * 2.0) ** 2
        out[..., 4:] = sigmoid(out[..., 4:])

        out[..., :2] = (out[..., :2] + grid) * stride
        out[..., 2:4] = out[..., 2:4] * anchors

        out = out.reshape(-1, NO)
        
        # 복합 확신도로 1차 통과 기준 완화 (infer_pc.py와 동일하게 맞춤)
        obj_conf = out[:, 4]
        class_probs = out[:, 5:]
        max_class_scores = np.max(class_probs, axis=1)
        composite_scores = obj_conf * max_class_scores

        valid_idx = composite_scores > (conf_thres * 0.5)
        predictions.append(out[valid_idx])

    if not predictions:
        return np.array([])
    
    return np.concatenate(predictions, axis=0)

def nms(predictions, conf_thres=0.25, iou_thres=0.45, interested_classes=None):
    if len(predictions) == 0:
        return [], [], []

    class_conf = predictions[:, 5:] * predictions[:, 4:5]
     
    if interested_classes is not None:
        mask = np.zeros(class_conf.shape[1], dtype=bool)
        mask[interested_classes] = True
        class_conf[:, ~mask] = 0.0

    class_ids = np.argmax(class_conf, axis=1)
    class_scores = np.max(class_conf, axis=1)

    valid_mask = class_scores > conf_thres

    valid_preds = predictions[valid_mask]
    class_ids = class_ids[valid_mask]
    class_scores = class_scores[valid_mask]

    if len(valid_preds) == 0:
        return [], [], []

    boxes = np.zeros_like(valid_preds[:, :4])
    boxes[:, 0] = valid_preds[:, 0] - valid_preds[:, 2] / 2
    boxes[:, 1] = valid_preds[:, 1] - valid_preds[:, 3] / 2
    boxes[:, 2] = valid_preds[:, 0] + valid_preds[:, 2] / 2
    boxes[:, 3] = valid_preds[:, 1] + valid_preds[:, 3] / 2

    # Bounding Box 테두리 이탈 좌표 Clip 보정
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, 640)
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, 640)

    max_wh = 4096.0
    offsets = class_ids[:, None] * max_wh
    boxes_rev = boxes + offsets
    areas = (boxes_rev[:, 2] - boxes_rev[:, 0]) * (boxes_rev[:, 3] - boxes_rev[:, 1])
    
    order = class_scores.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)

        if order.size == 1:
            break

        xx1 = np.maximum(boxes_rev[i, 0], boxes_rev[order[1:], 0])
        yy1 = np.maximum(boxes_rev[i, 1], boxes_rev[order[1:], 1])
        xx2 = np.minimum(boxes_rev[i, 2], boxes_rev[order[1:], 2])
        yy2 = np.minimum(boxes_rev[i, 3], boxes_rev[order[1:], 3])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h

        union = areas[i] + areas[order[1:]] - inter
        iou = inter / (union + 1e-6)

        inds = np.where(iou <= iou_thres)[0]
        order = order[inds + 1]

    return boxes[keep], class_scores[keep], class_ids[keep]

def main():
    bit_path = "dpu.bit"
    xmodel_path = "yolov5n.xmodel"
    os.makedirs("result", exist_ok=True)
    
    print("[INFO] DPU 엔진 초기화 중...")
    engine = YOLOv5DPUEngine(bit_path, xmodel_path)
    print(f"[INFO] 모델 입력 Shape: {engine.in_shape}")
    
    npy_files = sorted(glob.glob("src/*.npy"))
    if not npy_files:
        print("[ERROR] src/ 디렉토리에 .npy 파일이 없습니다.")
        return

    for npy_file in npy_files:
        print(f"\n==================================================")
        print(f"[INFO] 처리 중: {npy_file}")
        
        arr = np.load(npy_file)
        if arr.ndim == 3:
            arr = np.expand_dims(arr, axis=0)
       
        float_img = arr.astype(np.float32)
        if float_img.max() > 1.0:
            float_img /= 255.0
        
        # 1. DPU 연산 실행
        t1 = time.time()
        raw_outputs = engine.execute(float_img)
        t2 = time.time()
        print(f"[INFO] DPU 순수 연산 시간: {(t2 - t1)*1000:.2f} ms")

        # ---------------------------------------------------------
        # [핵심 디버그 출력문] DPU에서 나오는 Raw 출력 스케일 확인
        # ---------------------------------------------------------
        print(f"[DEBUG] 입력 Scale (in_scale): {engine.in_scale}")
        for idx, out in enumerate(raw_outputs):
            print(
                f"[DEBUG] Raw Layer {idx} ({out.shape}) -> "
                f"Min: {out.min():.4f}, Max: {out.max():.4f}, Mean: {out.mean():.4f}"
            )
        # ---------------------------------------------------------

        # 2. 후처리 (디코딩 및 NMS)
        predictions = decode_yolov5_outputs(raw_outputs, engine.in_shape, conf_thres=0.25)
        print(f"[INFO] NMS 전 1차 필터링 통과 후보 수: {len(predictions)}")
        
        final_boxes, final_scores, final_classes = nms(
            predictions, 
            conf_thres=0.20, 
            iou_thres=0.45
        )
        print(f"[INFO] NMS 최종 통과 객체 수: {len(final_boxes)}")

        for box, score, cls_id in zip(final_boxes, final_scores, final_classes):
            cls_name = CLASSES[cls_id] if cls_id < len(CLASSES) else f"Cls {cls_id}"
            print(
                f"  - Class: {cls_id}({cls_name}), Score: {score:.2f}, "
                f"Box: [{box[0]:.1f}, {box[1]:.1f}, {box[2]:.1f}, {box[3]:.1f}]"
            )

        # 3. 결과 이미지 시각화 및 저장
        img_vis = (float_img[0] * 255.0).clip(0, 255).astype(np.uint8)
        img_vis = cv2.cvtColor(img_vis, cv2.COLOR_RGB2BGR)
        img_h, img_w = img_vis.shape[:2]

        for box, score, cls_id in zip(final_boxes, final_scores, final_classes):
            x1 = max(0, min(img_w, int(box[0])))
            y1 = max(0, min(img_h, int(box[1])))
            x2 = max(0, min(img_w, int(box[2])))
            y2 = max(0, min(img_h, int(box[3])))

            cls_name = CLASSES[cls_id] if cls_id < len(CLASSES) else f"Cls {cls_id}"
            label = f"{cls_name}: {score:.2f}"

            cv2.rectangle(img_vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
            text_y = y1 - 5 if y1 - 5 > 15 else y1 + 15
            cv2.putText(img_vis, label, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        filename = f"result_{os.path.basename(npy_file).replace('.npy', '.jpg')}"
        save_path = os.path.join("result", filename)
        cv2.imwrite(save_path, img_vis)
        print(f"[INFO] 저장 완료: {save_path}")

if __name__ == "__main__":
    main()
