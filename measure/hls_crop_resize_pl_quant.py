"""
hls_crop_resize_pl_quant.py

현재 KV260 PL의 crop_and_resize kernel 전용 Python wrapper.

현재 HLS 동작:

Camera BGR uint8
    ↓
C++:
    BGR -> RGBx packing
    ↓
PL:
    ROI crop
    bilinear resize
    INT8 quantization
    RGB packing
    ↓
C++:
    raw RGB INT8 memcpy
    ↓
Python:
    int8 [1, 640, 640, 3]

중요:
- CPU resize 없음
- CPU BGR->RGB 없음
- CPU quantization 없음
- PL 출력이 이미 DPU input용 INT8 RGB
"""

import ctypes
import glob
import os

import numpy as np


# ============================================================
# 현재 파일 기준 경로
# ============================================================

THIS_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


# ============================================================
# C++ shared library
# ============================================================

LIB_PATH = os.path.join(
    THIS_DIR,
    "cpp_hls_crop",
    "libhls_crop.so"
)


if not os.path.exists(LIB_PATH):

    raise FileNotFoundError(
        "libhls_crop.so not found: {}".format(
            LIB_PATH
        )
    )


_lib = ctypes.CDLL(
    LIB_PATH
)


# ============================================================
# ctypes pointer
# ============================================================

_uint8_ptr = ctypes.POINTER(
    ctypes.c_uint8
)

_int8_ptr = ctypes.POINTER(
    ctypes.c_int8
)

_double_ptr = ctypes.POINTER(
    ctypes.c_double
)


# ============================================================
# C++ API prototype
# ============================================================

_lib.hls_crop_init.argtypes = [
    ctypes.c_char_p
]

_lib.hls_crop_init.restype = (
    ctypes.c_int
)


_lib.hls_crop_run_int8_rgb.argtypes = [

    # src BGR
    _uint8_ptr,

    # src_w
    ctypes.c_int,

    # src_h
    ctypes.c_int,

    # x0
    ctypes.c_int,

    # y0
    ctypes.c_int,

    # roi_w
    ctypes.c_int,

    # roi_h
    ctypes.c_int,

    # dst_size
    ctypes.c_int,

    # output RGB INT8
    _int8_ptr,
]

_lib.hls_crop_run_int8_rgb.restype = (
    ctypes.c_int
)


_lib.hls_crop_run_int8_rgb_profile.argtypes = [

    # src BGR
    _uint8_ptr,

    ctypes.c_int,
    ctypes.c_int,

    ctypes.c_int,
    ctypes.c_int,

    ctypes.c_int,
    ctypes.c_int,

    ctypes.c_int,

    # output RGB INT8
    _int8_ptr,

    # timing double[5]
    _double_ptr,
]

_lib.hls_crop_run_int8_rgb_profile.restype = (
    ctypes.c_int
)


# ============================================================
# XCLBIN 찾기
# ============================================================

def find_xclbin():

    # --------------------------------------------------------
    # 환경변수 지정 시 최우선
    # --------------------------------------------------------

    env_path = os.environ.get(
        "XCLBIN_PATH"
    )


    if env_path:

        if not os.path.exists(env_path):

            raise FileNotFoundError(
                "XCLBIN_PATH does not exist: {}".format(
                    env_path
                )
            )

        return env_path


    # --------------------------------------------------------
    # 현재 firmware app
    # --------------------------------------------------------

    firmware_dir = (
        "/lib/firmware/xilinx/"
        "kv260-b2304-roi-resize-v5"
    )


    preferred = os.path.join(
        firmware_dir,
        "kv260-b2304-roi-resize.xclbin"
    )


    if os.path.exists(preferred):

        return preferred


    candidates = glob.glob(
        os.path.join(
            firmware_dir,
            "*.xclbin"
        )
    )


    if not candidates:

        raise FileNotFoundError(
            "No xclbin found: {}".format(
                firmware_dir
            )
        )


    return candidates[0]


# ============================================================
# PL quant preprocessing wrapper
# ============================================================

class HLSCropResizePLQuant:

    def __init__(
        self,
        dst_size=640
    ):

        self.dst_size = int(
            dst_size
        )


        # ----------------------------------------------------
        # PL 최종 출력
        #
        # RGB
        # INT8
        # NHWC
        #
        # shape:
        # (640,640,3)
        # ----------------------------------------------------

        self.output_int8 = np.empty(
            (
                self.dst_size,
                self.dst_size,
                3
            ),
            dtype=np.int8
        )


        # ----------------------------------------------------
        # DPU에 넘길 batch view
        #
        # 복사하지 않음.
        #
        # (640,640,3)
        # ->
        # (1,640,640,3)
        # ----------------------------------------------------

        self.output_batch = (
            self.output_int8[
                None,
                ...
            ]
        )


        # ----------------------------------------------------
        # profile
        #
        # [0] BGR -> RGBx packing
        # [1] H2D
        # [2] HLS
        # [3] D2H
        # [4] BO -> NumPy memcpy
        # ----------------------------------------------------

        self.timing_ms = np.zeros(
            5,
            dtype=np.float64
        )


        # ----------------------------------------------------
        # XCLBIN
        # ----------------------------------------------------

        self.xclbin_path = (
            find_xclbin()
        )


        print(
            "HLS XCLBIN:",
            self.xclbin_path
        )


        # ----------------------------------------------------
        # XRT init
        # ----------------------------------------------------

        ret = _lib.hls_crop_init(
            self.xclbin_path.encode(
                "utf-8"
            )
        )


        if ret != 0:

            raise RuntimeError(
                "hls_crop_init failed: {}".format(
                    ret
                )
            )


        print(
            "PL crop + resize + quant ready."
        )


    # ========================================================
    # 입력 frame 검사
    # ========================================================

    def _prepare_frame(
        self,
        frame_bgr
    ):

        frame = np.asarray(
            frame_bgr
        )


        if frame.ndim != 3:

            raise ValueError(
                "frame ndim must be 3, got {}".format(
                    frame.ndim
                )
            )


        if frame.shape[2] != 3:

            raise ValueError(
                "frame channel must be 3, got {}".format(
                    frame.shape
                )
            )


        if frame.dtype != np.uint8:

            raise ValueError(
                "frame dtype must be uint8, got {}".format(
                    frame.dtype
                )
            )


        if not frame.flags[
            "C_CONTIGUOUS"
        ]:

            frame = np.ascontiguousarray(
                frame
            )


        return frame


    # ========================================================
    # 일반 실행
    # ========================================================

    def run(
        self,
        frame_bgr,
        x0,
        y0,
        roi_w,
        roi_h
    ):

        frame = self._prepare_frame(
            frame_bgr
        )


        src_h = int(
            frame.shape[0]
        )

        src_w = int(
            frame.shape[1]
        )


        ret = (
            _lib.hls_crop_run_int8_rgb(

                frame.ctypes.data_as(
                    _uint8_ptr
                ),

                src_w,
                src_h,

                int(x0),
                int(y0),

                int(roi_w),
                int(roi_h),

                self.dst_size,

                self.output_int8.ctypes.data_as(
                    _int8_ptr
                )
            )
        )


        if ret != 0:

            raise RuntimeError(
                "hls_crop_run_int8_rgb failed: {}".format(
                    ret
                )
            )


        # ----------------------------------------------------
        # batch view 그대로 반환
        #
        # shape = (1,640,640,3)
        # dtype = int8
        # ----------------------------------------------------

        return self.output_batch


    # ========================================================
    # 프로파일링 실행
    # ========================================================

    def run_profile(
        self,
        frame_bgr,
        x0,
        y0,
        roi_w,
        roi_h
    ):

        frame = self._prepare_frame(
            frame_bgr
        )


        src_h = int(
            frame.shape[0]
        )

        src_w = int(
            frame.shape[1]
        )


        self.timing_ms[:] = 0.0


        ret = (
            _lib.hls_crop_run_int8_rgb_profile(

                frame.ctypes.data_as(
                    _uint8_ptr
                ),

                src_w,
                src_h,

                int(x0),
                int(y0),

                int(roi_w),
                int(roi_h),

                self.dst_size,

                self.output_int8.ctypes.data_as(
                    _int8_ptr
                ),

                self.timing_ms.ctypes.data_as(
                    _double_ptr
                )
            )
        )


        if ret != 0:

            raise RuntimeError(
                "hls_crop_run_int8_rgb_profile failed: {}".format(
                    ret
                )
            )


        return (
            self.output_batch,
            self.timing_ms
        )
