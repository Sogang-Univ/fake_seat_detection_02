import cv2
import numpy as np
import xir
import vart
import time
import subprocess
import threading
import re

from hls_crop_resize_pl_quant import (
    HLSCropResizePLQuant
)

from cpp_yolo_decode import (
    decode_dpu_outputs_cpp
)

from seat_state_machine import (
    SeatStateMachine
)


# ============================================================
# Configuration
#
# 현재 테스트 대상:
# DPUCZDX8G B2304
# ============================================================

DPU_ARCH = "B2304"


MODEL = (
    "/home/ubuntu/yolov5_test/"
    "yolov5n_2304.xmodel"
)


CAMERA_ID = 0

FRAME_W = 640
FRAME_H = 480

TARGET_FPS = 30


# ============================================================
# Power measurement duration
# ============================================================

IDLE_SECONDS = 30.0

CPU_SECONDS = 60.0

PL_SECONDS = 60.0


# ============================================================
# Power sampling interval
# ============================================================

POWER_SAMPLE_INTERVAL = 1.0


# ============================================================
# Input frames
#
# Camera에서 먼저 동일한 300 frame 확보
#
# CPU / PL 모두 동일 frames[] 반복 사용
#
# 따라서 camera read 자체는
# CPU vs PL 성능/전력 비교에 포함하지 않음
# ============================================================

NUM_TEST_FRAMES = 300


# ============================================================
# Warm-up
# ============================================================

WARMUP_FRAMES = 20


# ============================================================
# ROI
#
# Original camera:
# 640 x 480
#
# ROI:
# x = 80 ~ 559
# y = 0  ~ 479
#
# 480 x 480
#
# ->
#
# resize
#
# ->
#
# 640 x 640
# ============================================================

CROP_X0 = 80
CROP_Y0 = 0

ROI_W = 480
ROI_H = 480

DST_SIZE = 640


ROI_BOX = (
    80,
    0,
    560,
    480
)


# ============================================================
# YOLOv5 10-class
# ============================================================

NUM_CLASSES = 10


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


# ============================================================
# State machine에서 object로 취급할 class
#
# chair = 6 제외
#
# 좌석 자체가 chair로 검출될 수 있기 때문에
# GHOST 판정에는 사용하지 않음
# ============================================================

OBJECT_CLASS_IDS = {

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


# ============================================================
# YOLO threshold
#
# 현재 새 INT8 모델 실측 기준:
#
# person 없음:
# 약 0.02 ~ 0.03
#
# person 있음:
# 약 0.22 ~ 0.27
#
# 따라서 0.20 사용
# ============================================================

SCORE_THRESH = 0.25

NMS_IOU_THRESH = 0.55


# ============================================================
# State Machine
# ============================================================

GHOST_SECONDS = 10.0

HYSTERESIS_FRAMES = 10

STATE_CHANGE_SECONDS = 5.0


# ============================================================
# DPU subgraph
# ============================================================

def get_dpu_subgraph(graph):

    root = (
        graph.get_root_subgraph()
    )


    dpu_subgraphs = []


    for sg in (
        root.toposort_child_subgraph()
    ):

        if not sg.has_attr(
            "device"
        ):
            continue


        device = str(
            sg.get_attr(
                "device"
            )
        ).upper()


        if device == "DPU":

            dpu_subgraphs.append(
                sg
            )


    if len(
        dpu_subgraphs
    ) != 1:

        raise RuntimeError(

            "Expected exactly 1 DPU subgraph, got {}".format(

                len(
                    dpu_subgraphs
                )
            )
        )


    return (
        dpu_subgraphs[0]
    )


# ============================================================
# State machine 생성
# ============================================================

def create_state_machine():

    return SeatStateMachine(

        ghost_seconds=
        GHOST_SECONDS,

        hysteresis_frames=
        HYSTERESIS_FRAMES,

        state_change_seconds=
        STATE_CHANGE_SECONDS
    )


# ============================================================
# Detection -> State flags
#
# 새 10-class model 기준
#
# person:
#   cls 0
#
# object:
#   1,2,3,4,5,7,8,9
#
# chair 6:
#   무시
# ============================================================

def detections_to_flags_new(
    detections
):

    person_present = False

    object_present = False


    for det in detections:

        cls_id = int(
            det["cls"]
        )


        if cls_id == 0:

            person_present = True


        elif cls_id in OBJECT_CLASS_IDS:

            object_present = True


    return (
        person_present,
        object_present
    )


# ============================================================
# Camera에서 test frame 확보
#
# Camera read 시간은
# benchmark에 포함하지 않음
# ============================================================

def capture_test_frames():

    print()
    print(
        "============================================"
    )
    print(
        " CAPTURE TEST FRAMES"
    )
    print(
        "============================================"
    )


    cap = cv2.VideoCapture(

        CAMERA_ID,

        cv2.CAP_V4L2
    )


    cap.set(

        cv2.CAP_PROP_FOURCC,

        cv2.VideoWriter_fourcc(
            *"MJPG"
        )
    )


    cap.set(

        cv2.CAP_PROP_FRAME_WIDTH,

        FRAME_W
    )


    cap.set(

        cv2.CAP_PROP_FRAME_HEIGHT,

        FRAME_H
    )


    cap.set(

        cv2.CAP_PROP_FPS,

        TARGET_FPS
    )


    if not cap.isOpened():

        raise RuntimeError(
            "Could not open camera"
        )


    print(
        "Camera resolution:",
        int(
            cap.get(
                cv2.CAP_PROP_FRAME_WIDTH
            )
        ),
        "x",
        int(
            cap.get(
                cv2.CAP_PROP_FRAME_HEIGHT
            )
        )
    )


    print(
        "Camera reported FPS:",
        cap.get(
            cv2.CAP_PROP_FPS
        )
    )


    frames = []


    print()

    print(
        "Capturing {} frames...".format(
            NUM_TEST_FRAMES
        )
    )


    while len(frames) < NUM_TEST_FRAMES:

        ret, frame = (
            cap.read()
        )


        if not ret:

            print(
                "Camera read failed"
            )

            continue


        if (
            frame.shape[1] != FRAME_W
            or
            frame.shape[0] != FRAME_H
        ):

            frame = cv2.resize(

                frame,

                (
                    FRAME_W,
                    FRAME_H
                ),

                interpolation=
                cv2.INTER_LINEAR
            )


        frame = np.ascontiguousarray(

            frame,

            dtype=np.uint8
        )


        frames.append(
            frame
        )


        if (
            len(frames) % 50
            ==
            0
        ):

            print(
                "captured:",
                len(frames)
            )


    cap.release()


    print()

    print(
        "Capture complete."
    )


    print(
        "Captured frames:",
        len(frames)
    )


    return frames


# ============================================================
# CPU preprocessing
#
# crop
# resize
# BGR -> RGB
# INT8 quantization
# ============================================================

def cpu_preprocess_profile(
    frame
):

    # ========================================================
    # 1. Crop
    # ========================================================

    t0 = (
        time.perf_counter()
    )


    roi = frame[

        CROP_Y0:
        CROP_Y0 + ROI_H,

        CROP_X0:
        CROP_X0 + ROI_W
    ]


    t1 = (
        time.perf_counter()
    )


    # ========================================================
    # 2. Resize
    # ========================================================

    resized = cv2.resize(

        roi,

        (
            DST_SIZE,
            DST_SIZE
        ),

        interpolation=
        cv2.INTER_LINEAR
    )


    t2 = (
        time.perf_counter()
    )


    # ========================================================
    # 3. BGR -> RGB
    # ========================================================

    rgb = cv2.cvtColor(

        resized,

        cv2.COLOR_BGR2RGB
    )


    t3 = (
        time.perf_counter()
    )


    # ========================================================
    # 4. INT8 quantization
    #
    # DPU input fix_point = 6
    #
    # scale = 2^6 = 64
    #
    # q = round(pixel / 255 * 64)
    # ========================================================

    q = np.rint(

        rgb.astype(
            np.float32
        )

        *

        64.0

        /

        255.0
    )


    q = np.clip(

        q,

        -128,
        127

    ).astype(
        np.int8
    )


    output = np.ascontiguousarray(

        q[
            None,
            ...
        ],

        dtype=np.int8
    )


    t4 = (
        time.perf_counter()
    )


    crop_ms = (
        (t1 - t0)
        *
        1000.0
    )


    resize_ms = (
        (t2 - t1)
        *
        1000.0
    )


    color_ms = (
        (t3 - t2)
        *
        1000.0
    )


    quant_ms = (
        (t4 - t3)
        *
        1000.0
    )


    preprocess_ms = (
        (t4 - t0)
        *
        1000.0
    )


    timing = (

        crop_ms,
        resize_ms,
        color_ms,
        quant_ms,
        preprocess_ms
    )


    return (
        output,
        timing
    )


# ============================================================
# DPU
# ============================================================

def run_dpu(
    runner,
    input_data,
    raw_heads
):

    t0 = (
        time.perf_counter()
    )


    job_id = (
        runner.execute_async(

            [
                input_data
            ],

            raw_heads
        )
    )


    runner.wait(
        job_id
    )


    t1 = (
        time.perf_counter()
    )


    return (
        (t1 - t0)
        *
        1000.0
    )


# ============================================================
# C++ Decode + NMS
# ============================================================

def run_decode(
    raw_heads,
    fix_points
):

    t0 = (
        time.perf_counter()
    )


    detections = (
        decode_dpu_outputs_cpp(

            raw_heads,

            fix_points,

            crop_x0=
            CROP_X0,

            crop_y0=
            CROP_Y0,

            crop_size=
            ROI_W,

            score_thresh=
            SCORE_THRESH,

            nms_iou_thresh=
            NMS_IOU_THRESH
        )
    )


    t1 = (
        time.perf_counter()
    )


    decode_ms = (
        (t1 - t0)
        *
        1000.0
    )


    return (
        detections,
        decode_ms
    )


# ============================================================
# State logic
# ============================================================

def run_logic(
    detections,
    sm
):

    t0 = (
        time.perf_counter()
    )


    person_present, object_present = (

        detections_to_flags_new(
            detections
        )
    )


    state = sm.update(

        person_present,

        object_present,

        time.monotonic()
    )


    t1 = (
        time.perf_counter()
    )


    logic_ms = (
        (t1 - t0)
        *
        1000.0
    )


    return (
        state,
        logic_ms
    )


# ============================================================
# SOM power reading
#
# xlnx_platformstats:
#
# SOM total power = mW
#
# ->
#
# W 변환
# ============================================================

def read_som_power():

    try:

        result = subprocess.run(

            [
                "xlnx_platformstats"
            ],

            stdout=subprocess.PIPE,

            stderr=subprocess.DEVNULL,

            text=True,

            timeout=10
        )


        text = (
            result.stdout
        )


        for line in text.splitlines():

            if (
                "SOM total power"
                in line
            ):

                numbers = re.findall(

                    r"[-+]?\d*\.\d+|\d+",

                    line
                )


                if len(numbers) > 0:

                    power_mw = float(
                        numbers[-1]
                    )


                    power_w = (
                        power_mw
                        /
                        1000.0
                    )


                    return power_w


    except Exception as e:

        print(
            "Power read error:",
            e
        )


    return None


# ============================================================
# Power Sampler
# ============================================================

class PowerSampler:

    def __init__(
        self,
        interval=1.0
    ):

        self.interval = float(
            interval
        )

        self.samples = []

        self.running = False

        self.thread = None


    def _loop(self):

        while self.running:

            power = (
                read_som_power()
            )


            if power is not None:

                self.samples.append(
                    (
                        time.monotonic(),
                        power
                    )
                )


            time.sleep(
                self.interval
            )


    def start(self):

        self.samples = []

        self.running = True


        self.thread = threading.Thread(

            target=self._loop,

            daemon=True
        )


        self.thread.start()


    def stop(self):

        self.running = False


        if self.thread is not None:

            self.thread.join(
                timeout=15.0
            )


    def values(self):

        return [

            x[1]

            for x
            in self.samples
        ]


# ============================================================
# Idle power
# ============================================================

def measure_idle_power():

    print()
    print(
        "============================================"
    )
    print(
        " IDLE POWER"
    )
    print(
        "============================================"
    )


    sampler = PowerSampler(
        POWER_SAMPLE_INTERVAL
    )


    sampler.start()


    start = (
        time.monotonic()
    )


    while (
        time.monotonic()
        -
        start
        <
        IDLE_SECONDS
    ):

        time.sleep(
            0.1
        )


    sampler.stop()


    values = np.asarray(

        sampler.values(),

        dtype=np.float64
    )


    if len(values) == 0:

        raise RuntimeError(
            "No idle power samples collected"
        )


    result = {

        "samples":
            len(values),

        "avg":
            float(
                values.mean()
            ),

        "std":
            float(
                values.std()
            ),

        "min":
            float(
                values.min()
            ),

        "max":
            float(
                values.max()
            )
    }


    print(
        "samples     :",
        result["samples"]
    )


    print(
        "idle avg    : "
        "{:.3f} W".format(
            result["avg"]
        )
    )


    print(
        "idle std    : "
        "{:.3f} W".format(
            result["std"]
        )
    )


    print(
        "idle min    : "
        "{:.3f} W".format(
            result["min"]
        )
    )


    print(
        "idle max    : "
        "{:.3f} W".format(
            result["max"]
        )
    )


    return result


# ============================================================
# CPU power benchmark
# ============================================================

def benchmark_cpu_power(

    frames,

    runner,

    raw_heads,

    fix_points
):

    print()
    print(
        "============================================"
    )
    print(
        " CPU E2E POWER TEST"
    )
    print(
        "============================================"
    )


    sm = (
        create_state_machine()
    )


    stats = {

        "frames": 0,

        "crop": 0.0,

        "resize": 0.0,

        "color": 0.0,

        "quant": 0.0,

        "preprocess": 0.0,

        "dpu": 0.0,

        "decode": 0.0,

        "logic": 0.0,

        "e2e": 0.0
    }


    sampler = PowerSampler(
        POWER_SAMPLE_INTERVAL
    )


    sampler.start()


    workload_start = (
        time.monotonic()
    )


    index = 0


    while (
        time.monotonic()
        -
        workload_start
        <
        CPU_SECONDS
    ):

        frame = frames[
            index % len(frames)
        ]


        index += 1


        e2e_start = (
            time.perf_counter()
        )


        # ====================================================
        # CPU preprocessing
        # ====================================================

        input_data, timing = (

            cpu_preprocess_profile(
                frame
            )
        )


        (
            crop_ms,

            resize_ms,

            color_ms,

            quant_ms,

            preprocess_ms

        ) = timing


        # ====================================================
        # DPU
        # ====================================================

        dpu_ms = (
            run_dpu(

                runner,

                input_data,

                raw_heads
            )
        )


        # ====================================================
        # Decode
        # ====================================================

        detections, decode_ms = (

            run_decode(

                raw_heads,

                fix_points
            )
        )


        # ====================================================
        # Logic
        # ====================================================

        _, logic_ms = (

            run_logic(

                detections,

                sm
            )
        )


        e2e_end = (
            time.perf_counter()
        )


        e2e_ms = (
            (
                e2e_end
                -
                e2e_start
            )
            *
            1000.0
        )


        # ====================================================
        # Statistics
        # ====================================================

        stats["frames"] += 1

        stats["crop"] += crop_ms

        stats["resize"] += resize_ms

        stats["color"] += color_ms

        stats["quant"] += quant_ms

        stats["preprocess"] += preprocess_ms

        stats["dpu"] += dpu_ms

        stats["decode"] += decode_ms

        stats["logic"] += logic_ms

        stats["e2e"] += e2e_ms


    workload_end = (
        time.monotonic()
    )


    sampler.stop()


    power_values = np.asarray(

        sampler.values(),

        dtype=np.float64
    )


    if len(power_values) == 0:

        raise RuntimeError(
            "No CPU power samples collected"
        )


    n = float(
        stats["frames"]
    )


    duration = (
        workload_end
        -
        workload_start
    )


    return {

        "frames":
            stats["frames"],

        "duration":
            duration,

        "crop":
            stats["crop"] / n,

        "resize":
            stats["resize"] / n,

        "color":
            stats["color"] / n,

        "quant":
            stats["quant"] / n,

        "preprocess":
            stats["preprocess"] / n,

        "dpu":
            stats["dpu"] / n,

        "decode":
            stats["decode"] / n,

        "logic":
            stats["logic"] / n,

        "e2e":
            stats["e2e"] / n,

        "fps":
            stats["frames"]
            /
            duration,

        "power_samples":
            len(
                power_values
            ),

        "power_avg":
            float(
                power_values.mean()
            ),

        "power_std":
            float(
                power_values.std()
            ),

        "power_min":
            float(
                power_values.min()
            ),

        "power_max":
            float(
                power_values.max()
            )
    }


# ============================================================
# PL power benchmark
# ============================================================

def benchmark_pl_power(

    frames,

    hls_preprocess,

    runner,

    raw_heads,

    fix_points
):

    print()
    print(
        "============================================"
    )
    print(
        " PL E2E POWER TEST"
    )
    print(
        "============================================"
    )


    sm = (
        create_state_machine()
    )


    stats = {

        "frames": 0,

        "packing": 0.0,

        "h2d": 0.0,

        "hls": 0.0,

        "d2h": 0.0,

        "memcpy": 0.0,

        "preprocess": 0.0,

        "dpu": 0.0,

        "decode": 0.0,

        "logic": 0.0,

        "e2e": 0.0
    }


    sampler = PowerSampler(
        POWER_SAMPLE_INTERVAL
    )


    sampler.start()


    workload_start = (
        time.monotonic()
    )


    index = 0


    while (
        time.monotonic()
        -
        workload_start
        <
        PL_SECONDS
    ):

        frame = frames[
            index % len(frames)
        ]


        index += 1


        e2e_start = (
            time.perf_counter()
        )


        # ====================================================
        # PL preprocessing
        # ====================================================

        preprocess_start = (
            time.perf_counter()
        )


        input_data, hls_timing = (

            hls_preprocess.run_profile(

                frame,

                x0=CROP_X0,

                y0=CROP_Y0,

                roi_w=ROI_W,

                roi_h=ROI_H
            )
        )


        preprocess_end = (
            time.perf_counter()
        )


        preprocess_ms = (
            (
                preprocess_end
                -
                preprocess_start
            )
            *
            1000.0
        )


        packing_ms = float(
            hls_timing[0]
        )


        h2d_ms = float(
            hls_timing[1]
        )


        hls_ms = float(
            hls_timing[2]
        )


        d2h_ms = float(
            hls_timing[3]
        )


        memcpy_ms = float(
            hls_timing[4]
        )


        # ====================================================
        # DPU
        # ====================================================

        dpu_ms = (

            run_dpu(

                runner,

                input_data,

                raw_heads
            )
        )


        # ====================================================
        # Decode
        # ====================================================

        detections, decode_ms = (

            run_decode(

                raw_heads,

                fix_points
            )
        )


        # ====================================================
        # Logic
        # ====================================================

        _, logic_ms = (

            run_logic(

                detections,

                sm
            )
        )


        e2e_end = (
            time.perf_counter()
        )


        e2e_ms = (
            (
                e2e_end
                -
                e2e_start
            )
            *
            1000.0
        )


        # ====================================================
        # Statistics
        # ====================================================

        stats["frames"] += 1

        stats["packing"] += packing_ms

        stats["h2d"] += h2d_ms

        stats["hls"] += hls_ms

        stats["d2h"] += d2h_ms

        stats["memcpy"] += memcpy_ms

        stats["preprocess"] += preprocess_ms

        stats["dpu"] += dpu_ms

        stats["decode"] += decode_ms

        stats["logic"] += logic_ms

        stats["e2e"] += e2e_ms


    workload_end = (
        time.monotonic()
    )


    sampler.stop()


    power_values = np.asarray(

        sampler.values(),

        dtype=np.float64
    )


    if len(power_values) == 0:

        raise RuntimeError(
            "No PL power samples collected"
        )


    n = float(
        stats["frames"]
    )


    duration = (
        workload_end
        -
        workload_start
    )


    return {

        "frames":
            stats["frames"],

        "duration":
            duration,

        "packing":
            stats["packing"] / n,

        "h2d":
            stats["h2d"] / n,

        "hls":
            stats["hls"] / n,

        "d2h":
            stats["d2h"] / n,

        "memcpy":
            stats["memcpy"] / n,

        "preprocess":
            stats["preprocess"] / n,

        "dpu":
            stats["dpu"] / n,

        "decode":
            stats["decode"] / n,

        "logic":
            stats["logic"] / n,

        "e2e":
            stats["e2e"] / n,

        "fps":
            stats["frames"]
            /
            duration,

        "power_samples":
            len(
                power_values
            ),

        "power_avg":
            float(
                power_values.mean()
            ),

        "power_std":
            float(
                power_values.std()
            ),

        "power_min":
            float(
                power_values.min()
            ),

        "power_max":
            float(
                power_values.max()
            )
    }


# ============================================================
# Final output
# ============================================================

def print_final_results(
    idle,
    cpu,
    pl
):

    # ========================================================
    # Dynamic power
    # ========================================================

    cpu_dynamic_power = max(

        0.0,

        cpu["power_avg"]
        -
        idle["avg"]
    )


    pl_dynamic_power = max(

        0.0,

        pl["power_avg"]
        -
        idle["avg"]
    )


    # ========================================================
    # FPS / W
    # ========================================================

    cpu_fps_per_watt = (

        cpu["fps"]
        /
        cpu["power_avg"]
    )


    pl_fps_per_watt = (

        pl["fps"]
        /
        pl["power_avg"]
    )


    # ========================================================
    # Whole SOM energy / frame
    # ========================================================

    cpu_energy_j = (

        cpu["power_avg"]
        /
        cpu["fps"]
    )


    pl_energy_j = (

        pl["power_avg"]
        /
        pl["fps"]
    )


    # ========================================================
    # Dynamic energy / frame
    # ========================================================

    cpu_dynamic_energy_j = (

        cpu_dynamic_power
        /
        cpu["fps"]
    )


    pl_dynamic_energy_j = (

        pl_dynamic_power
        /
        pl["fps"]
    )


    # ========================================================
    # Comparison
    # ========================================================

    preprocess_speedup = (

        cpu["preprocess"]
        /
        pl["preprocess"]
    )


    preprocess_reduction = (

        (
            cpu["preprocess"]
            -
            pl["preprocess"]
        )

        /

        cpu["preprocess"]

        *

        100.0
    )


    e2e_speedup = (

        cpu["e2e"]
        /
        pl["e2e"]
    )


    e2e_reduction = (

        (
            cpu["e2e"]
            -
            pl["e2e"]
        )

        /

        cpu["e2e"]

        *

        100.0
    )


    power_difference_percent = (

        (
            pl["power_avg"]
            -
            cpu["power_avg"]
        )

        /

        cpu["power_avg"]

        *

        100.0
    )


    fps_w_improvement = (

        pl_fps_per_watt
        /
        cpu_fps_per_watt
    )


    energy_reduction = (

        (
            cpu_energy_j
            -
            pl_energy_j
        )

        /

        cpu_energy_j

        *

        100.0
    )


    if cpu_dynamic_energy_j > 0.0:

        dynamic_energy_reduction = (

            (
                cpu_dynamic_energy_j
                -
                pl_dynamic_energy_j
            )

            /

            cpu_dynamic_energy_j

            *

            100.0
        )

    else:

        dynamic_energy_reduction = 0.0


    # ========================================================
    # IDLE
    # ========================================================

    print()
    print()

    print(
        "============================================"
    )

    print(
        " FINAL IDLE POWER"
    )

    print(
        "============================================"
    )


    print(
        "DPU architecture    :",
        DPU_ARCH
    )


    print(
        "samples             :",
        idle["samples"]
    )


    print(
        "average             : "
        "{:.3f} W".format(
            idle["avg"]
        )
    )


    print(
        "std                 : "
        "{:.3f} W".format(
            idle["std"]
        )
    )


    print(
        "min                 : "
        "{:.3f} W".format(
            idle["min"]
        )
    )


    print(
        "max                 : "
        "{:.3f} W".format(
            idle["max"]
        )
    )


    # ========================================================
    # CPU
    # ========================================================

    print()
    print(
        "============================================"
    )
    print(
        " FINAL CPU E2E + POWER"
    )
    print(
        "============================================"
    )


    print(
        "processed frames    :",
        cpu["frames"]
    )


    print(
        "measurement time    : "
        "{:.3f} s".format(
            cpu["duration"]
        )
    )


    print()


    print(
        "CPU preprocess      : "
        "{:.3f} ms".format(
            cpu["preprocess"]
        )
    )


    print(
        "  crop              : "
        "{:.3f} ms".format(
            cpu["crop"]
        )
    )


    print(
        "  resize            : "
        "{:.3f} ms".format(
            cpu["resize"]
        )
    )


    print(
        "  BGR->RGB          : "
        "{:.3f} ms".format(
            cpu["color"]
        )
    )


    print(
        "  quant             : "
        "{:.3f} ms".format(
            cpu["quant"]
        )
    )


    print(
        "DPU                 : "
        "{:.3f} ms".format(
            cpu["dpu"]
        )
    )


    print(
        "decode C++          : "
        "{:.3f} ms".format(
            cpu["decode"]
        )
    )


    print(
        "logic               : "
        "{:.3f} ms".format(
            cpu["logic"]
        )
    )


    print(
        "E2E                 : "
        "{:.3f} ms".format(
            cpu["e2e"]
        )
    )


    print(
        "processing FPS      : "
        "{:.2f}".format(
            cpu["fps"]
        )
    )


    print()


    print(
        "power samples       :",
        cpu["power_samples"]
    )


    print(
        "SOM power avg       : "
        "{:.3f} W".format(
            cpu["power_avg"]
        )
    )


    print(
        "SOM power std       : "
        "{:.3f} W".format(
            cpu["power_std"]
        )
    )


    print(
        "SOM power min       : "
        "{:.3f} W".format(
            cpu["power_min"]
        )
    )


    print(
        "SOM power max       : "
        "{:.3f} W".format(
            cpu["power_max"]
        )
    )


    print(
        "dynamic power       : "
        "{:.3f} W".format(
            cpu_dynamic_power
        )
    )


    print(
        "FPS/W               : "
        "{:.3f}".format(
            cpu_fps_per_watt
        )
    )


    print(
        "energy/frame        : "
        "{:.3f} mJ".format(
            cpu_energy_j
            *
            1000.0
        )
    )


    print(
        "dynamic energy/frame: "
        "{:.3f} mJ".format(
            cpu_dynamic_energy_j
            *
            1000.0
        )
    )


    # ========================================================
    # PL
    # ========================================================

    print()
    print(
        "============================================"
    )
    print(
        " FINAL PL E2E + POWER"
    )
    print(
        "============================================"
    )


    print(
        "processed frames    :",
        pl["frames"]
    )


    print(
        "measurement time    : "
        "{:.3f} s".format(
            pl["duration"]
        )
    )


    print()


    print(
        "PL preprocess       : "
        "{:.3f} ms".format(
            pl["preprocess"]
        )
    )


    print(
        "  packing           : "
        "{:.3f} ms".format(
            pl["packing"]
        )
    )


    print(
        "  H2D               : "
        "{:.3f} ms".format(
            pl["h2d"]
        )
    )


    print(
        "  HLS               : "
        "{:.3f} ms".format(
            pl["hls"]
        )
    )


    print(
        "  D2H               : "
        "{:.3f} ms".format(
            pl["d2h"]
        )
    )


    print(
        "  memcpy            : "
        "{:.3f} ms".format(
            pl["memcpy"]
        )
    )


    print(
        "DPU                 : "
        "{:.3f} ms".format(
            pl["dpu"]
        )
    )


    print(
        "decode C++          : "
        "{:.3f} ms".format(
            pl["decode"]
        )
    )


    print(
        "logic               : "
        "{:.3f} ms".format(
            pl["logic"]
        )
    )


    print(
        "E2E                 : "
        "{:.3f} ms".format(
            pl["e2e"]
        )
    )


    print(
        "processing FPS      : "
        "{:.2f}".format(
            pl["fps"]
        )
    )


    print()


    print(
        "power samples       :",
        pl["power_samples"]
    )


    print(
        "SOM power avg       : "
        "{:.3f} W".format(
            pl["power_avg"]
        )
    )


    print(
        "SOM power std       : "
        "{:.3f} W".format(
            pl["power_std"]
        )
    )


    print(
        "SOM power min       : "
        "{:.3f} W".format(
            pl["power_min"]
        )
    )


    print(
        "SOM power max       : "
        "{:.3f} W".format(
            pl["power_max"]
        )
    )


    print(
        "dynamic power       : "
        "{:.3f} W".format(
            pl_dynamic_power
        )
    )


    print(
        "FPS/W               : "
        "{:.3f}".format(
            pl_fps_per_watt
        )
    )


    print(
        "energy/frame        : "
        "{:.3f} mJ".format(
            pl_energy_j
            *
            1000.0
        )
    )


    print(
        "dynamic energy/frame: "
        "{:.3f} mJ".format(
            pl_dynamic_energy_j
            *
            1000.0
        )
    )


    # ========================================================
    # FINAL COMPARISON
    # ========================================================

    print()
    print(
        "============================================"
    )
    print(
        " FINAL CPU vs PL POWER COMPARISON"
    )
    print(
        "============================================"
    )


    print(
        "DPU architecture    :",
        DPU_ARCH
    )


    print(
        "Idle SOM power      : "
        "{:.3f} W".format(
            idle["avg"]
        )
    )


    print()


    print(
        "CPU preprocess      : "
        "{:.3f} ms".format(
            cpu["preprocess"]
        )
    )


    print(
        "PL preprocess       : "
        "{:.3f} ms".format(
            pl["preprocess"]
        )
    )


    print(
        "Preprocess speedup  : "
        "{:.3f} x".format(
            preprocess_speedup
        )
    )


    print(
        "Preprocess reduction: "
        "{:.2f} %".format(
            preprocess_reduction
        )
    )


    print()


    print(
        "CPU E2E             : "
        "{:.3f} ms".format(
            cpu["e2e"]
        )
    )


    print(
        "PL E2E              : "
        "{:.3f} ms".format(
            pl["e2e"]
        )
    )


    print(
        "E2E speedup         : "
        "{:.3f} x".format(
            e2e_speedup
        )
    )


    print(
        "E2E latency reduction: "
        "{:.2f} %".format(
            e2e_reduction
        )
    )


    print()


    print(
        "CPU processing FPS  : "
        "{:.2f}".format(
            cpu["fps"]
        )
    )


    print(
        "PL processing FPS   : "
        "{:.2f}".format(
            pl["fps"]
        )
    )


    print()


    print(
        "CPU SOM power       : "
        "{:.3f} W".format(
            cpu["power_avg"]
        )
    )


    print(
        "PL SOM power        : "
        "{:.3f} W".format(
            pl["power_avg"]
        )
    )


    print(
        "PL power difference : "
        "{:+.2f} %".format(
            power_difference_percent
        )
    )


    print()


    print(
        "CPU dynamic power   : "
        "{:.3f} W".format(
            cpu_dynamic_power
        )
    )


    print(
        "PL dynamic power    : "
        "{:.3f} W".format(
            pl_dynamic_power
        )
    )


    print()


    print(
        "CPU FPS/W           : "
        "{:.3f}".format(
            cpu_fps_per_watt
        )
    )


    print(
        "PL FPS/W            : "
        "{:.3f}".format(
            pl_fps_per_watt
        )
    )


    print(
        "FPS/W improvement   : "
        "{:.3f} x".format(
            fps_w_improvement
        )
    )


    print()


    print(
        "CPU energy/frame    : "
        "{:.3f} mJ".format(
            cpu_energy_j
            *
            1000.0
        )
    )


    print(
        "PL energy/frame     : "
        "{:.3f} mJ".format(
            pl_energy_j
            *
            1000.0
        )
    )


    print(
        "Energy reduction    : "
        "{:.2f} %".format(
            energy_reduction
        )
    )


    print()


    print(
        "CPU dynamic E/frame : "
        "{:.3f} mJ".format(
            cpu_dynamic_energy_j
            *
            1000.0
        )
    )


    print(
        "PL dynamic E/frame  : "
        "{:.3f} mJ".format(
            pl_dynamic_energy_j
            *
            1000.0
        )
    )


    print(
        "Dynamic E reduction : "
        "{:.2f} %".format(
            dynamic_energy_reduction
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # 1. XMODEL
    # ========================================================

    print(
        "============================================"
    )

    print(
        " POWER BENCHMARK"
    )

    print(
        "============================================"
    )

    print(
        "DPU architecture:",
        DPU_ARCH
    )

    print(
        "XMODEL:",
        MODEL
    )


    print()

    print(
        "============================================"
    )

    print(
        " LOAD XMODEL"
    )

    print(
        "============================================"
    )


    graph = xir.Graph.deserialize(
        MODEL
    )


    dpu_subgraph = (

        get_dpu_subgraph(
            graph
        )
    )


    # ========================================================
    # 2. PL init
    #
    # 현재 B2304 firmware / xclbin 사용
    # ========================================================

    print()

    print(
        "============================================"
    )

    print(
        " INIT B2304 PL"
    )

    print(
        "============================================"
    )


    hls_preprocess = (

        HLSCropResizePLQuant(

            dst_size=DST_SIZE
        )
    )


    # ========================================================
    # 3. DPU runner
    # ========================================================

    print()

    print(
        "============================================"
    )

    print(
        " CREATE B2304 DPU RUNNER"
    )

    print(
        "============================================"
    )


    runner = vart.Runner.create_runner(

        dpu_subgraph,

        "run"
    )


    print(
        "Runner created successfully."
    )


    # ========================================================
    # 4. Tensor
    # ========================================================

    input_tensor = (

        runner.get_input_tensors()[0]
    )


    output_tensors = (

        runner.get_output_tensors()
    )


    input_dims = list(
        input_tensor.dims
    )


    input_fix = int(

        input_tensor.get_attr(
            "fix_point"
        )
    )


    print()

    print(
        "INPUT:",
        input_dims
    )


    print(
        "INPUT fix_point:",
        input_fix
    )


    for i, tensor in enumerate(
        output_tensors
    ):

        print(

            "OUTPUT {}: dims={} fix_point={}".format(

                i,

                list(
                    tensor.dims
                ),

                tensor.get_attr(
                    "fix_point"
                )
            )
        )


    # ========================================================
    # Input 검사
    # ========================================================

    if input_dims != [

        1,

        640,

        640,

        3
    ]:

        raise RuntimeError(

            "Unexpected DPU input shape: {}".format(
                input_dims
            )
        )


    if input_fix != 6:

        raise RuntimeError(

            "Unexpected DPU input fix_point: {}".format(
                input_fix
            )
        )


    # ========================================================
    # ★ 새 10-class output 검사
    #
    # 반드시 45 channel이어야 함
    # ========================================================

    expected_shapes = {

        (
            1,
            80,
            80,
            45
        ),

        (
            1,
            40,
            40,
            45
        ),

        (
            1,
            20,
            20,
            45
        )
    }


    actual_shapes = {

        tuple(
            tensor.dims
        )

        for tensor
        in output_tensors
    }


    if (
        actual_shapes
        !=
        expected_shapes
    ):

        raise RuntimeError(

            "Unexpected DPU outputs: {}".format(

                actual_shapes
            )
        )


    print()

    print(
        "10-class YOLO output check: PASS"
    )


    # ========================================================
    # Output buffers
    # ========================================================

    raw_heads = [

        np.empty(

            tuple(
                tensor.dims
            ),

            dtype=np.int8
        )

        for tensor
        in output_tensors
    ]


    fix_points = [

        int(

            tensor.get_attr(
                "fix_point"
            )
        )

        for tensor
        in output_tensors
    ]


    print(
        "Output fix_points:",
        fix_points
    )


    # ========================================================
    # 5. Capture same input frames
    # ========================================================

    frames = (
        capture_test_frames()
    )


    # ========================================================
    # 6. Warm-up
    # ========================================================

    print()

    print(
        "============================================"
    )

    print(
        " WARM-UP"
    )

    print(
        "============================================"
    )


    for i in range(
        WARMUP_FRAMES
    ):

        frame = frames[
            i % len(frames)
        ]


        # ----------------------------------------------------
        # CPU preprocessing warm-up
        # ----------------------------------------------------

        cpu_input, _ = (

            cpu_preprocess_profile(
                frame
            )
        )


        job_id = (

            runner.execute_async(

                [
                    cpu_input
                ],

                raw_heads
            )
        )


        runner.wait(
            job_id
        )


        # ----------------------------------------------------
        # PL preprocessing warm-up
        # ----------------------------------------------------

        pl_input = (

            hls_preprocess.run(

                frame,

                x0=CROP_X0,

                y0=CROP_Y0,

                roi_w=ROI_W,

                roi_h=ROI_H
            )
        )


        job_id = (

            runner.execute_async(

                [
                    pl_input
                ],

                raw_heads
            )
        )


        runner.wait(
            job_id
        )


    print(
        "Warm-up complete."
    )


    # ========================================================
    # 7. Idle
    # ========================================================

    idle_result = (

        measure_idle_power()
    )


    # ========================================================
    # 8. CPU E2E + power
    # ========================================================

    cpu_result = (

        benchmark_cpu_power(

            frames,

            runner,

            raw_heads,

            fix_points
        )
    )


    # ========================================================
    # Cooldown
    # ========================================================

    print()

    print(
        "Cooldown 10 seconds..."
    )


    time.sleep(
        10.0
    )


    # ========================================================
    # 9. PL E2E + power
    # ========================================================

    pl_result = (

        benchmark_pl_power(

            frames,

            hls_preprocess,

            runner,

            raw_heads,

            fix_points
        )
    )


    # ========================================================
    # 10. Final
    # ========================================================

    print_final_results(

        idle_result,

        cpu_result,

        pl_result
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
