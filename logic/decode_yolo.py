"""
decode_yolo.py — [조건부 배포 · 5-a] DPU raw tensor → Detection 디코딩 + NMS

★ 배포 여부는 팀 회의 확정 사항에 달림 (문서 항목 5-a/7):
   - 5-a(raw tensor 디코딩)가 '내(③) 담당' 이면  → 배포 본체로 남음
   - 앞단 ① 또는 별도 담당이 이미 Detection으로 디코딩해서 넘겨주면 → 이 파일 삭제

KV260 레퍼런스(tf_yolov3_voc)의 디코딩 수식을 옮기되, 출력은 detection.py 의
표준 Detection 리스트로 통일한다. 웹캠 데모(ultralytics)는 자체 NMS가 있어
이 모듈을 타지 않으므로, 이 파일은 순수 '하드웨어 DPU raw tensor 경로' 전용이다.

앵커/스트라이드는 YOLOv3(voc) 기준. v5n으로 바꾸면 ANCHORS/ANCHOR_MASK/스트라이드만 교체.
검증용 self-test는 tests/test_decode_yolo.py 로 분리했다.
"""

import numpy as np
from typing import List
from detection import make_detection, Detection

# --- YOLOv3(voc) 레퍼런스 앵커. v5n으로 바꾸면 이 값/스트라이드만 교체 ---
_ANCHOR_LIST = [10, 13, 16, 30, 33, 23, 30, 61, 62, 45,
                59, 119, 116, 90, 156, 198, 373, 326]
ANCHORS = np.array(_ANCHOR_LIST, dtype=np.float32).reshape(-1, 2)
ANCHOR_MASK = [[6, 7, 8], [3, 4, 5], [0, 1, 2]]

SCORE_THRESH = 0.35
NMS_IOU_THRESH = 0.55


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _get_feats(feats, anchors, num_classes, input_shape):
    num_anchors = len(anchors)
    anchors_t = np.reshape(anchors.astype(np.float32), [1, 1, 1, num_anchors, 2])
    grid_size = np.shape(feats)[1:3]
    nu = num_classes + 5
    pred = np.reshape(feats, [-1, grid_size[0], grid_size[1], num_anchors, nu])

    grid_y = np.tile(np.reshape(np.arange(grid_size[0]), [-1, 1, 1, 1]),
                     [1, grid_size[1], 1, 1])
    grid_x = np.tile(np.reshape(np.arange(grid_size[1]), [1, -1, 1, 1]),
                     [grid_size[0], 1, 1, 1])
    grid = np.concatenate([grid_x, grid_y], axis=-1).astype(np.float32)

    box_xy = (_sigmoid(pred[..., :2]) + grid) / np.array(grid_size[::-1], np.float32)
    box_wh = np.exp(pred[..., 2:4]) * anchors_t / np.array(input_shape[::-1], np.float32)
    box_conf = _sigmoid(pred[..., 4:5])
    box_cls = _sigmoid(pred[..., 5:])
    return box_xy, box_wh, box_conf, box_cls


def _correct_boxes(box_xy, box_wh, input_shape, image_shape):
    """letterbox 좌표 → 원본 프레임 절대 픽셀로 역변환 (★계약: 여기서 역변환 완료)."""
    box_yx = box_xy[..., ::-1]
    box_hw = box_wh[..., ::-1]
    input_shape = np.array(input_shape, np.float32)
    image_shape = np.array(image_shape, np.float32)
    new_shape = np.around(image_shape * np.min(input_shape / image_shape))
    offset = (input_shape - new_shape) / 2.0 / input_shape
    scale = input_shape / new_shape
    box_yx = (box_yx - offset) * scale
    box_hw *= scale
    box_mins = box_yx - (box_hw / 2.0)
    box_maxes = box_yx + (box_hw / 2.0)
    boxes = np.concatenate([box_mins[..., 0:1], box_mins[..., 1:2],
                            box_maxes[..., 0:1], box_maxes[..., 1:2]], axis=-1)
    boxes *= np.concatenate([image_shape, image_shape], axis=-1)
    return boxes


def _boxes_and_scores(feats, anchors, num_classes, input_shape, image_shape):
    box_xy, box_wh, box_conf, box_cls = _get_feats(feats, anchors, num_classes, input_shape)
    boxes = _correct_boxes(box_xy, box_wh, input_shape, image_shape)
    boxes = np.reshape(boxes, [-1, 4])
    scores = np.reshape(box_conf * box_cls, [-1, num_classes])
    return boxes, scores


def _nms(boxes, scores, iou_thresh=NMS_IOU_THRESH):
    if len(boxes) == 0:
        return []
    # correct_boxes 출력은 (y1,x1,y2,x2) 순서지만 NMS는 순서 무관(대칭)하므로 그대로 사용
    y1, x1, y2, x2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (y2 - y1 + 1) * (x2 - x1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        h = np.maximum(0.0, yy2 - yy1 + 1)
        w = np.maximum(0.0, xx2 - xx1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= iou_thresh)[0] + 1]
    return keep


def decode_dpu_outputs(yolo_outputs: List[np.ndarray],
                       image_shape,
                       num_classes: int,
                       cls_remap=None) -> List[Detection]:
    """
    DPU raw tensor 리스트 → 표준 Detection 리스트.

    yolo_outputs: DPU 출력 텐서 리스트 [(1,H,W,A*(5+C)), ...] (스케일 3개)
    image_shape : 원본 프레임 (H, W)
    cls_remap   : {원본클래스ID: 우리클래스ID}. None이면 그대로.
                  예) VOC person=14 → 우리 person=0 처럼 매핑할 때 사용.
    반환: List[Detection]  (★ box는 원본 프레임 절대 픽셀, 역변환 완료)
    """
    input_shape = np.array(np.shape(yolo_outputs[0])[1:3]) * 32
    all_boxes, all_scores = [], []
    for i, feats in enumerate(yolo_outputs):
        b, s = _boxes_and_scores(feats, ANCHORS[ANCHOR_MASK[i]],
                                 num_classes, input_shape, image_shape)
        all_boxes.append(b)
        all_scores.append(s)
    boxes = np.concatenate(all_boxes, axis=0)
    scores = np.concatenate(all_scores, axis=0)

    mask = scores >= SCORE_THRESH
    results: List[Detection] = []
    for c in range(num_classes):
        c_boxes = boxes[mask[:, c]]
        c_scores = scores[:, c][mask[:, c]]
        if len(c_boxes) == 0:
            continue
        for idx in _nms(c_boxes, c_scores):
            y1, x1, y2, x2 = c_boxes[idx]           # correct_boxes는 (y1,x1,y2,x2)
            out_cls = cls_remap.get(c, None) if cls_remap else c
            if out_cls is None:
                continue                            # 우리가 안 쓰는 클래스는 버림
            results.append(make_detection(out_cls, float(c_scores[idx]),
                                          (x1, y1, x2, y2)))  # (x1,y1,x2,y2)로 정렬
    return results
