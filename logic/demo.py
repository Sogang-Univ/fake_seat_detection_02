#!/usr/bin/env python
# coding: utf-8

import os
import time
import numpy as np
import cv2
import colorsys

# 1. DPU Overlay 및 모델 로드
from pynq_dpu import DpuOverlay
overlay = DpuOverlay("dpu.bit")
overlay.load_model("tf_yolov3_voc.xmodel")

# Anchor & Class 설정
anchor_list = [10,13,16,30,33,23,30,61,62,45,59,119,116,90,156,198,373,326]
anchors = np.array([float(x) for x in anchor_list]).reshape(-1, 2)

def get_class(classes_path):
    with open(classes_path) as f:
        return [c.strip() for c in f.readlines()]
    
classes_path = "img/voc_classes.txt"
class_names = get_class(classes_path)

num_classes = len(class_names)
hsv_tuples = [(1.0 * x / num_classes, 1., 1.) for x in range(num_classes)]
colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
colors = list(map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)), colors))

def letterbox_image(image, size):
    ih, iw, _ = image.shape
    w, h = size
    scale = min(w/iw, h/ih)
    nw, nh = int(iw*scale), int(ih*scale)
    image = cv2.resize(image, (nw,nh), interpolation=cv2.INTER_LINEAR)
    new_image = np.ones((h,w,3), np.uint8) * 128
    h_start, w_start = (h-nh)//2, (w-nw)//2
    new_image[h_start:h_start+nh, w_start:w_start+nw, :] = image
    return new_image

def pre_process(image, model_image_size):
    image = image[...,::-1]
    image_h, image_w, _ = image.shape
    if model_image_size != (None, None):
        boxed_image = letterbox_image(image, tuple(reversed(model_image_size)))
    else:
        new_image_size = (image_w - (image_w % 32), image_h - (image_h % 32))
        boxed_image = letterbox_image(image, new_image_size)
    image_data = np.array(boxed_image, dtype='float32') / 255.
    return np.expand_dims(image_data, 0)

def _get_feats(feats, anchors, num_classes, input_shape):
    num_anchors = len(anchors)
    anchors_tensor = np.reshape(np.array(anchors, dtype=np.float32), [1, 1, 1, num_anchors, 2])
    grid_size = np.shape(feats)[1:3]
    nu = num_classes + 5
    predictions = np.reshape(feats, [-1, grid_size[0], grid_size[1], num_anchors, nu])
    grid_y = np.tile(np.reshape(np.arange(grid_size[0]), [-1, 1, 1, 1]), [1, grid_size[1], 1, 1])
    grid_x = np.tile(np.reshape(np.arange(grid_size[1]), [1, -1, 1, 1]), [grid_size[0], 1, 1, 1])
    grid = np.concatenate([grid_x, grid_y], axis = -1)
    grid = np.array(grid, dtype=np.float32)

    box_xy = (1/(1+np.exp(-predictions[..., :2])) + grid) / np.array(grid_size[::-1], dtype=np.float32)
    box_wh = np.exp(predictions[..., 2:4]) * anchors_tensor / np.array(input_shape[::-1], dtype=np.float32)
    box_confidence = 1/(1+np.exp(-predictions[..., 4:5]))
    box_class_probs = 1/(1+np.exp(-predictions[..., 5:]))
    return box_xy, box_wh, box_confidence, box_class_probs

def correct_boxes(box_xy, box_wh, input_shape, image_shape):
    box_yx, box_hw = box_xy[..., ::-1], box_wh[..., ::-1]
    input_shape, image_shape = np.array(input_shape, dtype=np.float32), np.array(image_shape, dtype=np.float32)
    new_shape = np.around(image_shape * np.min(input_shape / image_shape))
    offset = (input_shape - new_shape) / 2. / input_shape
    scale = input_shape / new_shape
    box_yx = (box_yx - offset) * scale
    box_hw *= scale
    box_mins = box_yx - (box_hw / 2.)
    box_maxes = box_yx + (box_hw / 2.)
    boxes = np.concatenate([box_mins[..., 0:1], box_mins[..., 1:2], box_maxes[..., 0:1], box_maxes[..., 1:2]], axis=-1)
    boxes *= np.concatenate([image_shape, image_shape], axis=-1)
    return boxes

def boxes_and_scores(feats, anchors, classes_num, input_shape, image_shape):
    box_xy, box_wh, box_confidence, box_class_probs = _get_feats(feats, anchors, classes_num, input_shape)
    boxes = correct_boxes(box_xy, box_wh, input_shape, image_shape)
    boxes = np.reshape(boxes, [-1, 4])
    box_scores = np.reshape(box_confidence * box_class_probs, [-1, classes_num])
    return boxes, box_scores

def nms_boxes(boxes, scores):
    if len(boxes) == 0: return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w1, h1 = np.maximum(0.0, xx2 - xx1 + 1), np.maximum(0.0, yy2 - yy1 + 1)
        inter = w1 * h1
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= 0.55)[0] + 1]
    return keep

def evaluate(yolo_outputs, image_shape, class_names, anchors):
    score_thresh = 0.35
    anchor_mask = [[6, 7, 8], [3, 4, 5], [0, 1, 2]]
    boxes, box_scores = [], []
    input_shape = np.array(np.shape(yolo_outputs[0])[1:3]) * 32

    for i in range(len(yolo_outputs)):
        _b, _s = boxes_and_scores(yolo_outputs[i], anchors[anchor_mask[i]], len(class_names), input_shape, image_shape)
        boxes.append(_b)
        box_scores.append(_s)
    boxes, box_scores = np.concatenate(boxes, axis=0), np.concatenate(box_scores, axis=0)

    mask = box_scores >= score_thresh
    boxes_, scores_, classes_ = [], [], []
    for c in range(len(class_names)):
        c_boxes = boxes[mask[:, c]]
        c_scores = box_scores[:, c][mask[:, c]]
        nms_idx = nms_boxes(c_boxes, c_scores)
        boxes_.append(c_boxes[nms_idx])
        scores_.append(c_scores[nms_idx])
        classes_.append(np.ones_like(c_scores[nms_idx], dtype=np.int32) * c)
        
    return np.concatenate(boxes_, axis=0), np.concatenate(scores_, axis=0), np.concatenate(classes_, axis=0)

# 2. DPU Setup
dpu = overlay.runner
shapeIn = tuple(dpu.get_input_tensors()[0].dims)
shapeOut0 = tuple(dpu.get_output_tensors()[0].dims)
shapeOut1 = tuple(dpu.get_output_tensors()[1].dims)
shapeOut2 = tuple(dpu.get_output_tensors()[2].dims)

input_data = [np.empty(shapeIn, dtype=np.float32, order="C")]
output_data = [np.empty(shapeOut0, dtype=np.float32, order="C"), 
               np.empty(shapeOut1, dtype=np.float32, order="C"),
               np.empty(shapeOut2, dtype=np.float32, order="C")]

def run_cam(frame):
    image_size = frame.shape[:2]
    image_data = np.array(pre_process(frame, (416, 416)), dtype=np.float32)
    input_data[0][0,...] = image_data.reshape(shapeIn[1:])
    job_id = dpu.execute_async(input_data, output_data)
    dpu.wait(job_id)
    return evaluate([np.reshape(output_data[0], shapeOut0), 
                     np.reshape(output_data[1], shapeOut1), 
                     np.reshape(output_data[2], shapeOut2)], image_size, class_names, anchors)

def check_overlap(boxA, boxB):
    xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
    xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    return interArea / float(boxAArea) if boxAArea > 0 else 0

# 3. 카메라 및 ROI 선택
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

ret, first_frame = cap.read()
if not ret: exit()

print("\n[안내] 좌석 영역(ROI)을 드래그 후 ENTER를 누르세요.")
roi = cv2.selectROI("Select Seat Area", first_frame, showCrosshair=True)
cv2.destroyWindow("Select Seat Area")
rx, ry, rw, rh = roi
roi_box = [rx, ry, rx + rw, ry + rh]

# 4. 타이머 및 상태 변수 정의
HOLD_TIME = 5.0          # 상태 변경에 필요한 누적 대기 시간 (10초)
current_state = "EMPTY"  # 현재 고정된 상태 (EMPTY, OCCUPIED, GHOST)
pending_state = None     # 전환 예정인 상태
transition_timer = 0.0   # 누적 타이머

last_clock = time.time()

while True:
    ret, frame = cap.read()
    if not ret: break

    now = time.time()
    dt = now - last_clock
    last_clock = now

    boxes, scores, classes = run_cam(frame)
    
    person_in_roi = False
    bag_in_roi = False

    # --- [YOLO 감지 객체 시각화 및 ROI 체크] ---
    for box, sc, cls in zip(boxes.astype(int), scores, classes):
        c_name = class_names[cls]
        y1, x1, y2, x2 = box
        obj_box = [x1, y1, x2, y2]
        
        # 화면에 바운딩 박스 및 라벨 표기
        box_color = colors[cls]
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
        label_text = f"{c_name} {sc:.2f}"
        cv2.putText(frame, label_text, (x1, max(y1 - 5, 15)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)
        
        # ROI 영역 오버랩 체크
        if check_overlap(roi_box, obj_box) > 0.25:
            if c_name == 'person':
                person_in_roi = True
            # chair를 제외하고 소지품 대상(bottle 등)만 감지
            elif c_name in ['bottle', 'chair']:
                bag_in_roi = True

    # --- [현재 프레임 기준의 감지 상태 판단] ---
    if person_in_roi:
        target_state = "OCCUPIED"
    elif bag_in_roi:
        target_state = "GHOST"
    else:
        target_state = "EMPTY"

    # --- [10초 누적 타이머 알고리즘] ---
    if target_state != current_state:
        if pending_state != target_state:
            pending_state = target_state
            transition_timer = 0.0  # 타겟 상태가 변경되면 타이머 리셋
            
        transition_timer += dt
        
        if transition_timer >= HOLD_TIME:
            current_state = target_state
            pending_state = None
            transition_timer = 0.0
    else:
        pending_state = None
        transition_timer = 0.0

    # --- [ROI 영역 상태 시각화] ---
    if rw > 0 and rh > 0:
        if current_state == "OCCUPIED":
            color = (0, 0, 255)      # 빨간색
        elif current_state == "GHOST":
            color = (0, 165, 255)    # 주황색
        else:
            color = (0, 255, 0)      # 초록색
            
        if pending_state is not None:
            status_text = f"{current_state} -> {pending_state} ({transition_timer:.1f}s / {HOLD_TIME:.0f}s)"
        else:
            status_text = f"State: {current_state}"
            
        cv2.rectangle(frame, (rx, ry), (rx + rw, ry + rh), color, 3)
        cv2.putText(frame, status_text, (rx, max(ry - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    cv2.imshow('cam', frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27: break

cap.release()
cv2.destroyAllWindows()
