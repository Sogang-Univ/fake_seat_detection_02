import os
import glob
import time
import numpy as np
from pynq_dpu import DpuOverlay

class YOLOv5DPUEngine:
    def __init__(self, bit_path, xmodel_path):
        """
        DpuOverlay 기반 엔진 초기화. 
        VART 직접 호출을 피하여 Loading Hang 이슈 방지.
        """
        self.overlay = DpuOverlay(bit_path)
        self.overlay.load_model(xmodel_path)
        self.runner = self.overlay.runner

        # 입력 텐서 파싱
        self.in_tensors = self.runner.get_input_tensors()
        self.in_shape = tuple(self.in_tensors[0].dims)  # (1, H, W, C)
        self.in_scale = 2 ** self.in_tensors[0].get_attr("fix_point")

        # 출력 텐서 파싱
        self.out_tensors = self.runner.get_output_tensors()
        self.out_meta = []
        for t in self.out_tensors:
            self.out_meta.append({
                'name': t.name,
                'shape': tuple(t.dims),
                'scale': 2 ** t.get_attr("fix_point")
            })

    def execute(self, float_img):
        """
        전처리된 float32 이미지를 받아 DPU 비동기 추론 후 float32 결과 반환
        """
        # 1. 양자화: float32 -> int8 (C-contiguous 필수)
        input_data = (float_img * self.in_scale).astype(np.int8, order="C")

        # 2. 출력 버퍼 할당
        outputs = [np.empty(m['shape'], dtype=np.int8, order="C") for m in self.out_meta]

        # 3. 비동기 실행 및 동기화
        job_id = self.runner.execute_async([input_data], outputs)
        self.runner.wait(job_id)

        # 4. 역양자화: int8 -> float32
        return [out.astype(np.float32) / m['scale'] for out, m in zip(outputs, self.out_meta)]

def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -10, 10)))

def decode_yolov5_outputs(raw_outputs, input_shape, conf_thres=0.25):
    """
    DPU에서 출력된 Raw Feature Map을 디코딩하여 Box 좌표 복원 (NumPy 기반)
    COCO 80 클래스 기준으로 85 채널 (5 + 80)을 가정합니다.
    """
    # YOLOv5 Nano 기본 앵커
    anchors_cfg = {
        8:  np.array([[10, 13], [16, 30], [33, 23]], dtype=np.float32),
        16: np.array([[30, 61], [62, 45], [59, 119]], dtype=np.float32),
        32: np.array([[116, 90], [156, 198], [373, 326]], dtype=np.float32)
    }

    _, net_h, net_w, _ = input_shape
    predictions = []

    for out_tensor in raw_outputs:
        # out_tensor shape: (1, H, W, 255) -> (H, W, 3, 85)
        _, h, w, channels = out_tensor.shape
        stride = net_h // h
        
        # 텐서 크기 기반으로 올바른 Stride 및 Anchor 매칭
        if stride not in anchors_cfg:
            continue
        
        anchors = anchors_cfg[stride]
        out = out_tensor[0].reshape(h, w, 3, 85)

        # Grid 생성
        grid_y, grid_x = np.mgrid[0:h, 0:w]
        grid = np.stack((grid_x, grid_y), axis=-1).reshape(h, w, 1, 2).astype(np.float32)

        # Sigmoid 연산 (DPU는 보통 Sigmoid 전 단계에서 잘림)
        out[..., :2] = sigmoid(out[..., :2]) * 2.0 - 0.5          # x, y
        out[..., 2:4] = (sigmoid(out[..., 2:4]) * 2.0) ** 2       # w, h
        out[..., 4:] = sigmoid(out[..., 4:])                      # obj, classes

        # 절대 좌표 복원
        out[..., :2] = (out[..., :2] + grid) * stride
        out[..., 2:4] = out[..., 2:4] * anchors

        # 1차원 배열로 펼치기 (N, 85)
        out = out.reshape(-1, 85)
        
        # Objectness Threshold 필터링으로 연산량 최소화
        valid_idx = out[:, 4] > conf_thres
        predictions.append(out[valid_idx])

    if not predictions:
        return np.array([])
    
    return np.concatenate(predictions, axis=0)
    
def nms(predictions, conf_thres=0.25, iou_thres=0.45, interested_classes=None):
    """
    순수 NumPy 기반 NMS (Non-Maximum Suppression)
    predictions: (N, 85) 형태의 배열 [cx, cy, w, h, obj_conf, cls0, cls1, ...]
    """
    if len(predictions) == 0:
        return [], [], []

    # 1. 클래스별 최종 Score 계산 (Objectness * Class_Confidence)
    class_conf = predictions[:, 5:] * predictions[:, 4:5]
    class_ids = np.argmax(class_conf, axis=1)
    class_scores = np.max(class_conf, axis=1)

    # 2. Score Threshold 필터링
    valid_mask = class_scores > conf_thres
    
    if interested_classes is not None:
        interest_mask = np.isin(class_ids, interested_classes)
        valid_mask = valid_mask & interest_mask
        
    valid_preds = predictions[valid_mask]
    class_ids = class_ids[valid_mask]
    class_scores = class_scores[valid_mask]

    if len(valid_preds) == 0:
        return [], [], []

    # 3. Box 좌표 변환: [cx, cy, w, h] -> [x1, y1, x2, y2]
    boxes = np.zeros_like(valid_preds[:, :4])
    boxes[:, 0] = valid_preds[:, 0] - valid_preds[:, 2] / 2  # x1
    boxes[:, 1] = valid_preds[:, 1] - valid_preds[:, 3] / 2  # y1
    boxes[:, 2] = valid_preds[:, 0] + valid_preds[:, 2] / 2  # x2
    boxes[:, 3] = valid_preds[:, 1] + valid_preds[:, 3] / 2  # y2

    # 4. NMS 실행 (IoU 기반 박스 병합)
    max_wh = 4096.0
    offsets = class_ids[:, None] * max_wh
    boxes_for_nms = boxes + offsets
    
    order = class_scores.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)

        if order.size == 1:
            break

        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h

        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_order = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        union = area_i + area_order - inter

        iou = inter / union

        # IoU가 임계치 이하인 박스만 다음 라운드로 넘김
        inds = np.where(iou <= iou_thres)[0]
        order = order[inds + 1]

    return boxes[keep], class_scores[keep], class_ids[keep]

def main():
    bit_path = "dpu.bit"
    xmodel_path = "yolov5n.xmodel"
    
    print("[INFO] DPU 엔진 초기화 중...")
    engine = YOLOv5DPUEngine(bit_path, xmodel_path)
    print(f"[INFO] 모델 입력 Shape: {engine.in_shape}")
    
    npy_files = sorted(glob.glob("src/*.npy"))
    if not npy_files:
        print("[ERROR] src/ 디렉토리에 .npy 파일이 없습니다.")
        return

    for npy_file in npy_files:
        print(f"\n[INFO] 처리 중: {npy_file}")
        
        # 1. 데이터 로드 및 전처리
        arr = np.load(npy_file)
        
        # Batch 차원 추가 (H, W, C) -> (1, H, W, C)
        if arr.ndim == 3:
            arr = np.expand_dims(arr, axis=0)
            
        # 범위 정규화 (0~255 -> 0.0~1.0)
        float_img = arr.astype(np.float32)
        if float_img.max() > 1.0:
            float_img /= 255.0
            
        # 2. DPU 추론
        t1 = time.time()
        raw_outputs = engine.execute(float_img)
        t2 = time.time()
        print(f"[INFO] DPU 순수 연산: {(t2 - t1)*1000:.2f} ms")
        
        # 3. 후처리 (디코딩)
        # 반환된 predictions: (N, 85) 형태의 Bounding Box 정보 
        # (x_center, y_center, width, height, obj_conf, cls_conf_1, ..., cls_conf_80)
        predictions = decode_yolov5_outputs(raw_outputs, engine.in_shape, conf_thres=0.25)
        print(f"[INFO] 검출된 유효 박스 개수 (NMS 전): {len(predictions)}")
        
        # 4. NMS 적용 (최종 Box 추출)
        INTERESTED_CLASSES = [0, 24, 26, 28, 39, 41, 56, 63, 67, 73]
        
        final_boxes, final_scores, final_classes = nms(
            predictions, 
            conf_thres=0.25, 
            iou_thres=0.45,
            interested_classes=INTERESTED_CLASSES
        )
        
        print(f"[INFO] NMS 통과 최종 객체 수: {len(final_boxes)}")
        for box, score, cls_id in zip(final_boxes, final_scores, final_classes):
            print(f"  - Class: {cls_id}, Score: {score:.2f}, Box: [x1:{box[0]:.1f}, y1:{box[1]:.1f}, x2:{box[2]:.1f}, y2:{box[3]:.1f}]")
        

if __name__ == "__main__":
    main()
