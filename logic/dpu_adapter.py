"""
dpu_adapter.py — [배포 본체 · 신규] DPU 런타임 ↔ 디코더 사이의 얇은 어댑터

★ 이 파일의 존재 이유:
  - xmodel의 실제 DPU 출력은 conv raw 텐서다:
        NHWC, shape = (1, H, W, 255),  dtype = int8 (XINT8, 고정소수점)
    (reshape / permute / sigmoid 가 그래프 안에 들어있지 않음. 마지막 1x1 conv 그대로.)

  - 그런데 decode_yolov5n.py 의 디코더는 다음을 기대한다:
        float,  shape = (1, num_anchor=3, H, W, 5+num_classes=85)

  이 둘 사이의 (1) 역양자화  (2) 레이아웃 변환 을 여기서 처리한다.
  → decode_yolov5n.py, detection.py, seat_state_machine.py 는 손대지 않는다.

★ 런타임 격리:
  DPU를 실제로 호출하는 코드(VART / pyxir / 기타)는 run_dpu.py 쪽 DpuRunner에
  둔다. 이 파일은 "런타임이 뭘 뱉든, int8 NHWC 텐서 3개"만 받으면 된다.
"""

import numpy as np
from typing import List, Sequence

NUM_ANCHORS = 3
NUM_CLASSES = 80
NO = 5 + NUM_CLASSES          # 85 (per-anchor 채널 수)
CH = NUM_ANCHORS * NO         # 255 (conv 출력 채널 수)


def dequant_nhwc_to_decoder(raw: np.ndarray, fix_point: int) -> np.ndarray:
    """
    단일 헤드 변환.

    입력:
        raw       : DPU 원시 출력. int8, NHWC, shape (1, H, W, 255)
                    (batch=1 가정. VART 출력이 (H,W,255)로 batch 축이 없으면
                     아래에서 자동으로 앞에 축을 붙인다.)
        fix_point : 이 출력 텐서의 고정소수점 위치.
                    실제 float 값 = int8_value * 2^(-fix_point)
                    (VART: tensor.get_attr("fix_point") 또는 output_fixpos 로 얻음)

    출력:
        float32, shape (1, 3, H, W, 85)   — decode_yolov5n._decode_head 가 원하는 형식
    """
    a = np.asarray(raw)

    # batch 축 보정: (H,W,255) -> (1,H,W,255)
    if a.ndim == 3:
        a = a[None, ...]
    if a.ndim != 4:
        raise ValueError(
            f"DPU 헤드 텐서 차원이 예상과 다름: ndim={a.ndim}, shape={a.shape} "
            f"(기대: (1,H,W,{CH}) NHWC)"
        )

    _, H, W, C = a.shape
    if C != CH:
        raise ValueError(
            f"채널 수 불일치: C={C} != {CH}. "
            f"모델이 정말 YOLOv5(anchor 3, class {NUM_CLASSES})가 맞는지, "
            f"또는 출력이 NCHW로 나오는지(그럴 경우 transpose 필요) 확인 필요."
        )

    # (1) 역양자화: int8 -> float
    scale = 2.0 ** (-fix_point)
    f = a.astype(np.float32) * scale

    # (2) 레이아웃 변환: (1,H,W,255) -> (1,H,W,3,85) -> (1,3,H,W,85)
    f = f.reshape(1, H, W, NUM_ANCHORS, NO)
    f = f.transpose(0, 3, 1, 2, 4)
    return np.ascontiguousarray(f)


def adapt_dpu_heads(raw_heads: Sequence[np.ndarray],
                    fix_points: Sequence[int]) -> List[np.ndarray]:
    """
    헤드 3개를 한 번에 변환.

    입력:
        raw_heads  : DPU 원시 출력 3개. 각 int8 NHWC (1,H,W,255).
                     순서는 상관없다 — decode_yolov5n 이 grid 크기로 stride를
                     자동 정렬(auto_order_heads=True)하므로.
        fix_points : 각 헤드의 fix_point. raw_heads 와 같은 순서/길이.

    출력:
        decode_dpu_outputs 에 그대로 넘길 수 있는 float (1,3,H,W,85) 리스트.
    """
    if len(raw_heads) != len(fix_points):
        raise ValueError(
            f"raw_heads({len(raw_heads)})와 fix_points({len(fix_points)}) 길이 불일치"
        )
    return [
        dequant_nhwc_to_decoder(raw, fp)
        for raw, fp in zip(raw_heads, fix_points)
    ]
