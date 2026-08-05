import numpy as np

DEFAULT_ANCHORS = [
    [[10, 13], [16, 30], [33, 23]],
    [[30, 61], [62, 45], [59, 119]],
    [[116, 90], [156, 198], [373, 326]],
]
DEFAULT_STRIDES = [8, 16, 32]

def sigmoid(x):
    # DPU 정수 연산의 편차로 인한 오버플로우 방지 처리 추가
    x = np.clip(x, -88.72, 88.72)
    return 1 / (1 + np.exp(-x))

def decode_single_head(raw, anchors, stride):
    # 💡 [치명적 오류 수정]: Kria DPU에서 나온 가공 안 된 4차원(NCHW) 피처맵을 
    # YOLOv5 수식을 적용할 수 있도록 5차원(B, Anchor, H, W, Output)으로 정밀 재배열합니다.
    if len(raw.shape) == 4:
        bs, ch, gh, gw = raw.shape
        na = len(anchors)
        no = ch // na # 3*(5+80) 에서 5+80(=85)을 추출
        
        # NCHW -> NHWC 형태로 축을 바꾼 뒤 5차원으로 쪼갭니다.
        raw = raw.transpose(0, 2, 3, 1) # (B, H, W, C)
        raw = raw.reshape(bs, gh, gw, na, no) # (B, H, W, Anchor, Output)
        raw = raw.transpose(0, 3, 1, 2, 4) # (B, Anchor, H, W, Output) 완성

    bs, na, gh, gw, no = raw.shape
    y = sigmoid(raw)
    
    grid_y, grid_x = np.meshgrid(np.arange(gh), np.arange(gw), indexing = 'ij')
    grid = np.stack((grid_x, grid_y), axis = -1).reshape(1, 1, gh, gw, 2)
    anchors = np.array(anchors, dtype = np.float32).reshape(1, na, 1, 1, 2)
    
    xy = (y[..., 0:2] * 2 - 0.5 + grid) * stride
    wh = (y[..., 2:4] * 2) ** 2 * anchors
    obj_conf = y[..., 4]
    class_probs = y[..., 5:]
    
    class_id = np.argmax(class_probs, axis = -1)
    class_conf = np.max(class_probs, axis = -1)
    
    x1y1 = xy - wh / 2
    x2y2 = xy + wh / 2
    boxes = np.concatenate([x1y1, x2y2], axis = -1).reshape(-1, 4)
    
    return boxes, obj_conf.reshape(-1), class_id.reshape(-1), class_conf.reshape(-1)

def decode_yolo_output(raw_outputs, anchors = DEFAULT_ANCHORS, strides = DEFAULT_STRIDES):
    all_boxes, all_scores, all_class_ids = [], [], []
    for raw, anc, stride in zip(raw_outputs, anchors, strides):
        boxes, obj_conf, class_id, class_conf = decode_single_head(raw, anc, stride)
        all_boxes.append(boxes)
        all_scores.append(obj_conf * class_conf)
        all_class_ids.append(class_id)
        
    return (np.concatenate(all_boxes, axis = 0),
            np.concatenate(all_scores, axis = 0),
            np.concatenate(all_class_ids, axis = 0))

def nms(boxes, scores, iou_threshold=0.45):
    if len(boxes) == 0: 
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
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
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(ovr <= iou_threshold)[0]
        order = order[inds + 1]
    return keep
    
def build_results(boxes, scores, class_ids, class_names, conf_threshold = 0.25, letterbox_scale = 1.0, letterbox_pad = (0, 0)):
    results = []
    for box, score, cid in zip(boxes, scores, class_ids):
        if score < conf_threshold:
            continue
        x1, y1, x2, y2 = box
        x1 = (x1 - letterbox_pad[0]) / letterbox_scale
        y1 = (y1 - letterbox_pad[1]) / letterbox_scale
        x2 = (x2 - letterbox_pad[0]) / letterbox_scale
        y2 = (y2 - letterbox_pad[1]) / letterbox_scale
        
        results.append({
            'class_id': int(cid),
            'class': class_names[cid] if cid < len(class_names) else f'cls{cid}',
            'confidence': round(float(score), 3),
            'box': [round(float(x1), 1), round(float(y1), 1),
                    round(float(x2), 1), round(float(y2), 1)]
        })
        
    return results

