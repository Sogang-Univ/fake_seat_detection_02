"""
cpp_yolo_decode.py

C++ YOLOv5 Decode/NMS shared library를
Python에서 ctypes로 호출하기 위한 wrapper.

입력:
    raw_heads:
        VART DPU raw int8 outputs

출력:
    기존 Python Detection 형식

    {
        "cls": int,
        "score": float,
        "box": (x1,y1,x2,y2)
    }
"""

import ctypes
import os

import numpy as np


# ============================================================
# Shared library path
# ============================================================

THIS_DIR = os.path.dirname(
    os.path.abspath(
        __file__
    )
)


LIB_PATH = os.path.join(
    THIS_DIR,
    "cpp_decode",
    "libyolo_decode.so"
)


# ============================================================
# C Detection 구조체
# ============================================================

class DetectionC(
    ctypes.Structure
):

    _fields_ = [

        (
            "cls",
            ctypes.c_int
        ),

        (
            "score",
            ctypes.c_float
        ),

        (
            "x1",
            ctypes.c_float
        ),

        (
            "y1",
            ctypes.c_float
        ),

        (
            "x2",
            ctypes.c_float
        ),

        (
            "y2",
            ctypes.c_float
        ),
    ]


# ============================================================
# Library load
# ============================================================

_lib = ctypes.CDLL(
    LIB_PATH
)


# ============================================================
# Function signature
# ============================================================

_int8_ptr = ctypes.POINTER(
    ctypes.c_int8
)


_lib.decode_yolov5.argtypes = [

    # head0
    _int8_ptr,

    # head1
    _int8_ptr,

    # head2
    _int8_ptr,

    # fix point
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,

    # threshold
    ctypes.c_float,
    ctypes.c_float,

    # crop
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,

    # output
    ctypes.POINTER(
        DetectionC
    ),

    # max output
    ctypes.c_int,
]


_lib.decode_yolov5.restype = (
    ctypes.c_int
)


# ============================================================
# Head 순서 정리
#
# VART output 순서가 바뀌어도
# H 크기로 80/40/20을 찾아냄
# ============================================================

def _order_raw_heads(
    raw_heads,
    fix_points
):

    if (
        len(raw_heads) != 3
        or
        len(fix_points) != 3
    ):

        raise ValueError(
            "YOLOv5 head는 3개여야 합니다."
        )


    ordered = {}


    for raw, fp in zip(
        raw_heads,
        fix_points
    ):

        a = np.asarray(
            raw
        )


        if a.ndim != 4:

            raise ValueError(
                "DPU raw head shape 오류: "
                f"{a.shape}"
            )


        H = int(
            a.shape[1]
        )


        if H not in (
            80,
            40,
            20
        ):

            raise ValueError(
                "예상하지 못한 head grid: "
                f"{a.shape}"
            )


        ordered[H] = (
            a,
            int(fp)
        )


    if set(
        ordered.keys()
    ) != {
        80,
        40,
        20
    }:

        raise ValueError(
            "80/40/20 head 구성이 아닙니다."
        )


    return (
        ordered[80],
        ordered[40],
        ordered[20]
    )


# ============================================================
# Python API
# ============================================================

def decode_dpu_outputs_cpp(
    raw_heads,
    fix_points,

    crop_x0=80,
    crop_y0=0,
    crop_size=480,

    score_thresh=0.20,
    nms_iou_thresh=0.55,

    max_output=256
):


    # ========================================================
    # Head order
    # ========================================================

    h80, h40, h20 = (
        _order_raw_heads(
            raw_heads,
            fix_points
        )
    )


    head0, fix0 = h80
    head1, fix1 = h40
    head2, fix2 = h20


    # ========================================================
    # contiguous int8 보장
    #
    # VART output은 보통 이미 contiguous이므로
    # 실제 copy가 발생하지 않을 가능성이 높음.
    # ========================================================

    head0 = np.ascontiguousarray(
        head0,
        dtype=np.int8
    )

    head1 = np.ascontiguousarray(
        head1,
        dtype=np.int8
    )

    head2 = np.ascontiguousarray(
        head2,
        dtype=np.int8
    )


    # ========================================================
    # C output buffer
    # ========================================================

    output_array_type = (
        DetectionC
        *
        max_output
    )


    output_buffer = (
        output_array_type()
    )


    # ========================================================
    # C++ 호출
    # ========================================================

    count = _lib.decode_yolov5(

        head0.ctypes.data_as(
            _int8_ptr
        ),

        head1.ctypes.data_as(
            _int8_ptr
        ),

        head2.ctypes.data_as(
            _int8_ptr
        ),

        int(fix0),
        int(fix1),
        int(fix2),

        float(score_thresh),
        float(nms_iou_thresh),

        int(crop_x0),
        int(crop_y0),
        int(crop_size),

        output_buffer,

        int(max_output)
    )


    if count < 0:

        raise RuntimeError(
            "C++ decode_yolov5() failed"
        )


    # ========================================================
    # 기존 Python Detection 형식으로 변환
    # ========================================================

    results = []


    for i in range(
        count
    ):

        d = output_buffer[i]


        results.append(
            {
                "cls": int(
                    d.cls
                ),

                "score": float(
                    d.score
                ),

                "box": (
                    float(d.x1),
                    float(d.y1),
                    float(d.x2),
                    float(d.y2)
                )
            }
        )


    return results
