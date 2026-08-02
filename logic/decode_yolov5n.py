"""
decode_yolov5n.py — [A → 나(변환) → B] DPU raw tensor → 표준 Detection 리스트

전제:
  - A(디자인 모델)가 넘겨주는 raw tensor: 헤드 3개, 각각
      shape = (batch=1, num_anchor=3, H, W, 5+num_classes)
      640 입력 기준: H,W = (80,80), (40,40), (20,20)  (stride 8, 16, 32)
  - 모델: YOLOv5n, 데이터셋: COCO (80 class)
  - 파이프라인: 원본 640x480 캡쳐 → 480x480 중앙 크롭 → 640x640 리사이즈 → 모델 입력
    (비율 유지 letterbox가 아니라 "정사각 크롭 + 단순 업스케일"이므로
     기존 v3 레퍼런스의 letterbox 역변환 공식은 여기 적용하면 안 됨)

출력: detection.py 의 표준 Detection 리스트 (B가 그대로 받는 형식)
  Detection = {"cls": int, "score": float, "box": (x1,y1,x2,y2)}   # 원본 프레임(640x480) 절대 픽셀

★ 팀 회의에서 확인/합의가 필요한 지점은 파일 하단 NOTE 참고.
"""

import numpy as np
from typing import List, Tuple, Optional, Dict
from detection import make_detection, Detection

# ------------------------------------------------------------------
# YOLOv5n (COCO, 640 입력) 기본 앵커 — ultralytics 공식값
# 순서: stride 작은 것(고해상도, 작은 물체) -> 큰 것(저해상도, 큰 물체)
# ------------------------------------------------------------------
ANCHORS = {
    8:  np.array([[10, 13], [16, 30], [33, 23]], dtype=np.float32),   # P3, 80x80
    16: np.array([[30, 61], [62, 45], [59, 119]], dtype=np.float32),  # P4, 40x40
    32: np.array([[116, 90], [156, 198], [373, 326]], dtype=np.float32),  # P5, 20x20
}
STRIDES = [8, 16, 32]
NUM_CLASSES = 80
MODEL_INPUT = 640  # 모델 입력 한 변 (정사각)

SCORE_THRESH = 0.35
NMS_IOU_THRESH = 0.55

# COCO(0-indexed, ultralytics 순서) -> 우리 클래스 매핑
# 우리 클래스: 0=person, 1=bag(소지품류로 묶음)
# ※ 음료(beverage)까지 점유 지표로 쓸 경우 detection.py의 CLASS_NAMES에
#   2: "cup" 같은 항목을 추가하고 아래 매핑도 39(bottle)/41(cup) 등을 살려야 함.
#   지금은 계약(detection.py)이 person/bag 2개뿐이라 bottle/cup은 일단 버리도록(None) 처리.
COCO_TO_OURS: Dict[int, Optional[int]] = {
    0: 0,    # person
    24: 1,   # backpack
    26: 1,   # handbag
    28: 1,   # suitcase
    39: None,  # bottle  -> TODO: 팀 회의에서 3번째 클래스로 승격할지 결정
    41: None,  # cup     -> TODO: 상동
}


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _decode_head(feats: np.ndarray, stride: int, anchors: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    단일 헤드 디코딩 (YOLOv5 공식).
    feats: (1, 3, H, W, 5+num_classes)
    반환: boxes (N,4) [x1,y1,x2,y2] in 모델 입력(640x640) 픽셀, scores (N,num_classes)
    """
    _, num_anchors, gh, gw, nu = feats.shape
    assert nu == 5 + NUM_CLASSES, f"채널 수 불일치: {nu} != {5+NUM_CLASSES}"
    pred = feats[0]  # (3, H, W, 5+C)  batch=1 squeeze

    grid_y, grid_x = np.meshgrid(np.arange(gh), np.arange(gw), indexing="ij")
    grid = np.stack([grid_x, grid_y], axis=-1).astype(np.float32)  # (H,W,2)
    grid = grid[None, ...]  # (1,H,W,2) -> anchor 축 broadcast

    anchors_r = anchors.reshape(num_anchors, 1, 1, 2)  # (3,1,1,2)

    txy = pred[..., 0:2]
    twh = pred[..., 2:4]
    tconf = pred[..., 4:5]
    tcls = pred[..., 5:]

    # YOLOv5 디코딩 공식 (v3의 exp 기반과 다름 — 여기가 핵심 변경점)
    box_xy = (_sigmoid(txy) * 2.0 - 0.5 + grid) * stride           # (3,H,W,2) 픽셀(640 기준)
    box_wh = (_sigmoid(twh) * 2.0) ** 2 * anchors_r                # (3,H,W,2) 픽셀(640 기준)
    box_conf = _sigmoid(tconf)                                     # (3,H,W,1)
    box_cls = _sigmoid(tcls)                                       # (3,H,W,C)

    box_mins = box_xy - box_wh / 2.0
    box_maxes = box_xy + box_wh / 2.0
    boxes = np.concatenate([box_mins, box_maxes], axis=-1)         # (3,H,W,4) x1,y1,x2,y2

    boxes = boxes.reshape(-1, 4)
    scores = (box_conf * box_cls).reshape(-1, NUM_CLASSES)
    return boxes, scores


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float = NMS_IOU_THRESH) -> List[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[np.where(ovr <= iou_thresh)[0] + 1]
    return keep


def _map_model_to_original(boxes: np.ndarray,
                            crop_x0: int, crop_y0: int, crop_size: int,
                            model_input: int = MODEL_INPUT) -> np.ndarray:
    """
    모델 입력(640x640) 좌표 -> 원본 캡쳐 프레임(640x480) 절대 픽셀.
    letterbox 아님: 정사각 크롭(crop_size x crop_size)을 단순 업/다운스케일한 것뿐이므로
    스케일 1개 + 오프셋 1개로 역변환 끝남.

    crop_x0, crop_y0: 원본 프레임에서 크롭이 시작하는 좌상단 좌표
    crop_size: 크롭한 정사각 한 변 (예: 480)
    """
    scale = crop_size / float(model_input)   # 예: 480/640 = 0.75
    out = boxes.copy()
    out[:, [0, 2]] = out[:, [0, 2]] * scale + crop_x0   # x
    out[:, [1, 3]] = out[:, [1, 3]] * scale + crop_y0   # y
    return out


def decode_dpu_outputs(yolo_outputs: List[np.ndarray],
                        crop_x0: int = 80, crop_y0: int = 0, crop_size: int = 480,
                        cls_remap: Optional[Dict[int, Optional[int]]] = None) -> List[Detection]:
    """
    A가 준 raw tensor 리스트(헤드 3개) -> 표준 Detection 리스트.

    yolo_outputs: [(1,3,80,80,5+80), (1,3,40,40,5+80), (1,3,20,20,5+80)]
                  (P3->P5 순서라고 가정. 순서가 다르면 STRIDES 매칭이 깨지니 A와 확인 필요)
    crop_x0/crop_y0/crop_size: 640x480 원본 프레임 기준, 정사각 크롭 정보
                                (기본값은 640x480에서 좌우 80px씩 잘라 480x480 만든 케이스)
    cls_remap: COCO id -> 우리 class id. None이면 COCO_TO_OURS 기본값 사용.
               값이 None인 클래스는 버림(우리가 안 쓰는 클래스).
    """
    if cls_remap is None:
        cls_remap = COCO_TO_OURS

    assert len(yolo_outputs) == len(STRIDES), \
        f"헤드 개수 불일치: {len(yolo_outputs)} != {len(STRIDES)}"

    all_boxes, all_scores = [], []
    for feats, stride in zip(yolo_outputs, STRIDES):
        b, s = _decode_head(feats, stride, ANCHORS[stride])
        all_boxes.append(b)
        all_scores.append(s)
    boxes = np.concatenate(all_boxes, axis=0)     # 모델 입력(640) 픽셀 기준
    scores = np.concatenate(all_scores, axis=0)   # (N, 80)

    mask = scores >= SCORE_THRESH
    results: List[Detection] = []
    for c in range(NUM_CLASSES):
        out_cls = cls_remap.get(c, None)
        if out_cls is None:
            continue  # 우리가 안 쓰는 COCO 클래스는 애초에 NMS도 돌릴 필요 없음
        c_boxes = boxes[mask[:, c]]
        c_scores = scores[:, c][mask[:, c]]
        if len(c_boxes) == 0:
            continue
        c_boxes_orig = _map_model_to_original(c_boxes, crop_x0, crop_y0, crop_size)
        for idx in _nms(c_boxes_orig, c_scores):
            x1, y1, x2, y2 = c_boxes_orig[idx]
            results.append(make_detection(out_cls, float(c_scores[idx]), (x1, y1, x2, y2)))
    return results


# ------------------------------------------------------------------
# NOTE — 팀 회의에서 확인/합의 필요한 항목
# ------------------------------------------------------------------
# 1. 헤드 순서: yolo_outputs가 항상 [P3(80x80), P4(40x40), P5(20x20)] 순서로
#    오는지 A와 확정 필요. 순서가 뒤바뀌면 stride-anchor 매칭이 깨짐.
#    -> shape의 H,W로 자동 판별하는 방어 코드를 넣을 수도 있음 (원하면 추가해드림).
#
# 2. 크롭 좌표(crop_x0, crop_y0, crop_size)를 "고정값"으로 넣을지,
#    아니면 프레임마다 A 또는 카메라 모듈에서 함께 넘겨줄지 확정 필요.
#    지금은 640x480 -> 480x480 중앙 크롭(좌우 80px씩 제거) 가정으로 기본값을 넣어둠.
#
# 3. 음료(beverage/bottle/cup)까지 점유 지표로 쓴다면:
#    - detection.py의 CLASS_NAMES에 클래스 추가 (예: 2: "cup")
#    - COCO_TO_OURS에서 39(bottle), 41(cup)을 None 대신 새 ID로 매핑
#    - detections_to_flags()도 3번째 플래그(beverage_in_roi)를 반환하도록 확장
#    이건 detection.py 계약을 바꾸는 일이라 B와 먼저 맞춰야 함.
#
# 4. SCORE_THRESH=0.35, NMS_IOU_THRESH=0.55는 v3 레퍼런스 값 그대로 가져온 것.
#    YOLOv5n + COCO 기준으로는 conf 0.25~0.4 사이에서 실측 튜닝 권장.
