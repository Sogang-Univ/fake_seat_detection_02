"""
detection.py — 후처리 공용 인터페이스 (팀 회의에서 확정 제안할 '계약')

[표준 Detection 형식]  ★ 이걸 팀 인터페이스로 고정하자
  Detection = {
      "cls":   int,                 # 정수 클래스 ID (문자열 아님, 매핑표는 CLASS_NAMES)
      "score": float,               # conf * class_prob, NMS까지 끝난 최종 점수
      "box":   (x1, y1, x2, y2),    # ★ 원본 프레임 기준 절대 픽셀, 좌표 역변환 완료
  }

계약 규칙 (다음 회의 확인 항목 1~5 를 여기서 못박음):
  1. 자료구조   : dict 의 list   (List[Detection])
  2. 클래스 표현: 정수 ID + CLASS_NAMES 매핑표
  3. box 기준   : 원본 프레임 절대 픽셀 (ROI/letterbox 아님, 역변환 '완료' 상태로 받음)
  4. box 형식   : (x1, y1, x2, y2) 절대 픽셀 (corner)
  5. 필터링     : conf 필터 + NMS 가 '이미 끝난' 리스트를 받음

5-a(디코딩/NMS)와 5-b(상태머신)는 이 형식에서만 만나므로, 앞단이 무엇이든
이 계약만 지키면 5-b는 손대지 않는다. (하드웨어/webcam/mock 모두 동일)
"""

from typing import List, Dict, Tuple, Any

# --- 우리 시나리오에서 쓰는 클래스만 정의 (VOC/COCO에서 필요한 것만 재매핑) ---
# 실제 배포 때 앞단 클래스 ID와 이 표를 맞추면 됨.
CLASS_NAMES = {
    0: "person",
    1: "bag",     # 소지품 대표 (backpack/handbag/suitcase/bottle 등을 여기로 묶어도 됨)
}
PERSON_ID = 0
BAG_ID = 1

Detection = Dict[str, Any]
Box = Tuple[float, float, float, float]


def make_detection(cls: int, score: float, box: Box) -> Detection:
    """표준 Detection 하나 생성 (형식 강제용 헬퍼)."""
    x1, y1, x2, y2 = box
    return {"cls": int(cls), "score": float(score),
            "box": (float(x1), float(y1), float(x2), float(y2))}


def overlap_ratio(inner: Box, outer: Box) -> float:
    """
    inner 박스가 outer(ROI) 안에 얼마나 들어와 있는지 = 교집합 / inner 면적.
    ROI가 물체를 얼마나 덮는지가 아니라, '물체가 ROI에 얼마나 걸쳐 있는지'를 본다.
    (사람이 ROI보다 커도 ROI 안에 몸통이 걸치면 점유로 잡기 위함)
    """
    ax1, ay1, ax2, ay2 = inner
    bx1, by1, bx2, by2 = outer
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    inner_area = max(0.0, (ax2 - ax1)) * max(0.0, (ay2 - ay1))
    return inter / inner_area if inner_area > 0 else 0.0


def detections_to_flags(dets: List[Detection], roi_box: Box,
                        overlap_thresh: float = 0.25) -> Tuple[bool, bool]:
    """
    표준 Detection 리스트 + ROI → (person_in_roi, bag_in_roi) 두 불리언.
    5-b 상태머신이 필요로 하는 것은 이 두 플래그뿐이다.
    """
    person_in_roi = False
    bag_in_roi = False
    for d in dets:
        if overlap_ratio(d["box"], roi_box) > overlap_thresh:
            if d["cls"] == PERSON_ID:
                person_in_roi = True
            elif d["cls"] == BAG_ID:
                bag_in_roi = True
    return person_in_roi, bag_in_roi
