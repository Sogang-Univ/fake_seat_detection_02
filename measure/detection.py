"""
detection.py - common post-processing interface
"""

from typing import List, Dict, Tuple, Any


CLASS_NAMES = {

    0: "person",

    1: "backpack",

    2: "handbag",

    3: "suitcase",

    4: "bottle",

    5: "cup",

    6: "chair",

    7: "laptop",

    8: "cell_phone",

    9: "book"
}

PERSON_CLASS_ID = 0


BAG_ID = {

    1,  # backpack
    2,  # handbag
    3,  # suitcase
    4,  # bottle
    5,  # cup

    # 6 chair 제외

    7,  # laptop
    8,  # cell_phone
    9   # book
}

Detection = Dict[str, Any]
Box = Tuple[float, float, float, float]


def make_detection(
    cls: int,
    score: float,
    box: Box
) -> Detection:

    x1, y1, x2, y2 = box

    return {
        "cls": int(cls),
        "score": float(score),
        "box": (
            float(x1),
            float(y1),
            float(x2),
            float(y2)
        )
    }


def overlap_ratio(
    inner: Box,
    outer: Box
) -> float:

    ax1, ay1, ax2, ay2 = inner
    bx1, by1, bx2, by2 = outer

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)

    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(
        0.0,
        ix2 - ix1
    )

    ih = max(
        0.0,
        iy2 - iy1
    )

    inter = (
        iw
        *
        ih
    )

    inner_area = (
        max(
            0.0,
            ax2 - ax1
        )
        *
        max(
            0.0,
            ay2 - ay1
        )
    )

    if inner_area <= 0.0:
        return 0.0

    return (
        inter
        /
        inner_area
    )


def detections_to_flags(
    dets: List[Detection],
    roi_box: Box,
    overlap_thresh: float = 0.25
) -> Tuple[bool, bool]:

    person_in_roi = False
    bag_in_roi = False

    for d in dets:

        ratio = overlap_ratio(
            d["box"],
            roi_box
        )

        if ratio <= overlap_thresh:
            continue

        cls_id = int(
            d["cls"]
        )

        if cls_id == PERSON_ID:

            person_in_roi = True

        elif cls_id == BAG_ID:

            bag_in_roi = True

    return (
        person_in_roi,
        bag_in_roi
    )
