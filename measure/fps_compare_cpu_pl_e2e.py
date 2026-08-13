import cv2
import numpy as np
import xir
import vart
import time
import threading

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
# MODEL
# ============================================================

MODEL = (
    "/home/ubuntu/yolov5_test/"
    "yolov5n_2304.xmodel"
)


# ============================================================
# Camera
# ============================================================

CAMERA_ID = 0

FRAME_W = 640
FRAME_H = 480

TARGET_FPS = 30


# ============================================================
# Benchmark
# ============================================================

NUM_FRAMES = 1000

WARMUP_FRAMES = 30


# ============================================================
# ROI
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
# chair 제외
# ============================================================

OBJECT_CLASS_IDS = {

    1,
    2,
    3,
    4,
    5,

    # 6 = chair 제외

    7,
    8,
    9
}


# ============================================================
# Threshold
# ============================================================

SCORE_THRESH = 0.25

NMS_IOU_THRESH = 0.55


# ============================================================
# State machine settings
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


    return dpu_subgraphs[0]


# ============================================================
# State machine 생성
#
# CPU / PL 각각 별도 사용
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
# FOURCC
# ============================================================

def fourcc_to_string(value):

    value = int(
        value
    )


    return "".join(

        chr(

            (
                value
                >>
                (
                    8 * i
                )
            )
            &
            0xFF
        )

        for i in range(4)
    )


# ============================================================
# Detection -> State flags
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
# Camera Thread
#
# 기존 latest-frame 구조 그대로 사용
#
# 화면 출력은 하지 않음
# ============================================================

class LatestFrameCamera:

    def __init__(
        self,
        camera_id,
        width,
        height,
        fps
    ):

        self.camera_id = camera_id

        self.width = int(
            width
        )

        self.height = int(
            height
        )

        self.fps = int(
            fps
        )


        self.cap = cv2.VideoCapture(

            self.camera_id,

            cv2.CAP_V4L2
        )


        self.cap.set(

            cv2.CAP_PROP_FOURCC,

            cv2.VideoWriter_fourcc(
                *"MJPG"
            )
        )


        self.cap.set(

            cv2.CAP_PROP_FRAME_WIDTH,

            self.width
        )


        self.cap.set(

            cv2.CAP_PROP_FRAME_HEIGHT,

            self.height
        )


        self.cap.set(

            cv2.CAP_PROP_FPS,

            self.fps
        )


        if not self.cap.isOpened():

            raise RuntimeError(
                "Could not open camera"
            )


        self.condition = (
            threading.Condition()
        )


        self.latest_frame = None

        self.latest_seq = 0


        self.running = False

        self.thread = None

        self.error = None


        self.capture_count = 0

        self.capture_read_sum_ms = 0.0

        self.capture_start_time = None


    def print_info(self):

        print(

            "Camera resolution:",

            int(
                self.cap.get(
                    cv2.CAP_PROP_FRAME_WIDTH
                )
            ),

            "x",

            int(
                self.cap.get(
                    cv2.CAP_PROP_FRAME_HEIGHT
                )
            )
        )


        print(

            "Camera FPS:",

            self.cap.get(
                cv2.CAP_PROP_FPS
            )
        )


        print(

            "Camera FOURCC:",

            fourcc_to_string(

                self.cap.get(
                    cv2.CAP_PROP_FOURCC
                )
            )
        )


    def start(self):

        if self.running:
            return


        self.running = True


        self.capture_start_time = (
            time.monotonic()
        )


        self.thread = threading.Thread(

            target=self._capture_loop,

            name="camera-capture",

            daemon=True
        )


        self.thread.start()


    def _capture_loop(self):

        try:

            while self.running:

                t0 = (
                    time.perf_counter()
                )


                ret, frame = (
                    self.cap.read()
                )


                t1 = (
                    time.perf_counter()
                )


                if not ret:

                    with self.condition:

                        self.error = (
                            "Camera read failed"
                        )

                        self.running = False

                        self.condition.notify_all()

                    return


                read_ms = (

                    (
                        t1
                        -
                        t0
                    )

                    *
                    1000.0
                )


                if (

                    frame.shape[1]
                    !=
                    self.width

                    or

                    frame.shape[0]
                    !=
                    self.height
                ):

                    frame = cv2.resize(

                        frame,

                        (
                            self.width,
                            self.height
                        )
                    )


                frame = np.ascontiguousarray(

                    frame,

                    dtype=np.uint8
                )


                with self.condition:

                    self.latest_frame = frame

                    self.latest_seq += 1

                    self.capture_count += 1

                    self.capture_read_sum_ms += (
                        read_ms
                    )

                    self.condition.notify_all()


        except Exception as e:

            with self.condition:

                self.error = str(e)

                self.running = False

                self.condition.notify_all()


    def get_latest(
        self,
        last_seq,
        timeout=1.0
    ):

        deadline = (

            time.monotonic()

            +

            timeout
        )


        with self.condition:

            while (

                self.running

                and

                self.latest_seq
                <=
                last_seq
            ):

                remaining = (

                    deadline

                    -

                    time.monotonic()
                )


                if remaining <= 0:

                    return (
                        None,
                        last_seq
                    )


                self.condition.wait(
                    remaining
                )


            if self.error is not None:

                raise RuntimeError(
                    self.error
                )


            if self.latest_frame is None:

                return (
                    None,
                    last_seq
                )


            return (

                self.latest_frame,

                self.latest_seq
            )


    def get_stats(self):

        with self.condition:

            count = (
                self.capture_count
            )

            sum_ms = (
                self.capture_read_sum_ms
            )


        if count > 0:

            avg_read_ms = (

                sum_ms

                /

                count
            )

        else:

            avg_read_ms = 0.0


        if self.capture_start_time is not None:

            elapsed = (

                time.monotonic()

                -

                self.capture_start_time
            )

        else:

            elapsed = 0.0


        if elapsed > 0:

            acquired_fps = (

                count

                /

                elapsed
            )

        else:

            acquired_fps = 0.0


        return (

            count,

            avg_read_ms,

            acquired_fps
        )


    def stop(self):

        self.running = False


        with self.condition:

            self.condition.notify_all()


        if self.thread is not None:

            self.thread.join(
                timeout=2.0
            )


        self.cap.release()


# ============================================================
# CPU preprocessing
#
# CPU:
# ROI crop
# -> resize
# -> BGR->RGB
# -> INT8 quant
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
    # 4. INT8 quant
    #
    # fix_point = 6
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


    input_data = np.ascontiguousarray(

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

        (
            t1
            -
            t0
        )

        *
        1000.0
    )


    resize_ms = (

        (
            t2
            -
            t1
        )

        *
        1000.0
    )


    color_ms = (

        (
            t3
            -
            t2
        )

        *
        1000.0
    )


    quant_ms = (

        (
            t4
            -
            t3
        )

        *
        1000.0
    )


    preprocess_ms = (

        (
            t4
            -
            t0
        )

        *
        1000.0
    )


    return (

        input_data,

        (
            crop_ms,
            resize_ms,
            color_ms,
            quant_ms,
            preprocess_ms
        )
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

        (
            t1
            -
            t0
        )

        *
        1000.0
    )


# ============================================================
# Decode
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

            crop_x0=CROP_X0,

            crop_y0=CROP_Y0,

            crop_size=ROI_W,

            score_thresh=SCORE_THRESH,

            nms_iou_thresh=NMS_IOU_THRESH
        )
    )


    t1 = (
        time.perf_counter()
    )


    return (

        detections,

        (
            (
                t1
                -
                t0
            )

            *
            1000.0
        )
    )


# ============================================================
# Logic
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


    now = (
        time.monotonic()
    )


    state = sm.update(

        person_present,

        object_present,

        now
    )


    t1 = (
        time.perf_counter()
    )


    return (

        state,

        (
            (
                t1
                -
                t0
            )

            *
            1000.0
        )
    )


# ============================================================
# CPU Benchmark
# ============================================================

def benchmark_cpu(

    camera,

    runner,

    raw_heads,

    fix_points
):

    print()
    print(
        "========================================"
    )
    print(
        " CPU 1000-FRAME BENCHMARK"
    )
    print(
        "========================================"
    )


    sm = (
        create_state_machine()
    )


    frame_count = 0

    last_seq = 0


    sum_wait_ms = 0.0

    sum_crop_ms = 0.0
    sum_resize_ms = 0.0
    sum_color_ms = 0.0
    sum_quant_ms = 0.0

    sum_preprocess_ms = 0.0
    sum_dpu_ms = 0.0
    sum_decode_ms = 0.0
    sum_logic_ms = 0.0
    sum_processing_ms = 0.0
    sum_loop_ms = 0.0


    start_capture_count = (
        camera.get_stats()[0]
    )


    benchmark_start = (
        time.monotonic()
    )


    final_state = "UNKNOWN"


    while frame_count < NUM_FRAMES:

        loop_start = (
            time.perf_counter()
        )


        # ====================================================
        # Camera latest frame
        # ====================================================

        wait_start = (
            time.perf_counter()
        )


        frame, seq = (

            camera.get_latest(

                last_seq,

                timeout=1.0
            )
        )


        wait_end = (
            time.perf_counter()
        )


        if frame is None:

            continue


        last_seq = (
            seq
        )


        wait_ms = (

            (
                wait_end
                -
                wait_start
            )

            *
            1000.0
        )


        # ====================================================
        # CPU preprocess
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

        final_state, logic_ms = (

            run_logic(

                detections,

                sm
            )
        )


        # ====================================================
        # Processing
        # ====================================================

        processing_ms = (

            preprocess_ms

            +

            dpu_ms

            +

            decode_ms

            +

            logic_ms
        )


        loop_end = (
            time.perf_counter()
        )


        loop_ms = (

            (
                loop_end
                -
                loop_start
            )

            *
            1000.0
        )


        # ====================================================
        # Sum
        # ====================================================

        frame_count += 1


        sum_wait_ms += (
            wait_ms
        )

        sum_crop_ms += (
            crop_ms
        )

        sum_resize_ms += (
            resize_ms
        )

        sum_color_ms += (
            color_ms
        )

        sum_quant_ms += (
            quant_ms
        )

        sum_preprocess_ms += (
            preprocess_ms
        )

        sum_dpu_ms += (
            dpu_ms
        )

        sum_decode_ms += (
            decode_ms
        )

        sum_logic_ms += (
            logic_ms
        )

        sum_processing_ms += (
            processing_ms
        )

        sum_loop_ms += (
            loop_ms
        )


        if frame_count % 100 == 0:

            print(
                "CPU processed:",
                frame_count,
                "/",
                NUM_FRAMES
            )


    benchmark_end = (
        time.monotonic()
    )


    end_capture_count = (
        camera.get_stats()[0]
    )


    captured_during_test = (

        end_capture_count

        -

        start_capture_count
    )


    skipped = max(

        0,

        captured_during_test

        -

        frame_count
    )


    n = float(
        frame_count
    )


    avg_processing = (

        sum_processing_ms

        /

        n
    )


    return {

        "frames":
            frame_count,

        "captured":
            captured_during_test,

        "skipped":
            skipped,

        "wait":
            sum_wait_ms / n,

        "crop":
            sum_crop_ms / n,

        "resize":
            sum_resize_ms / n,

        "color":
            sum_color_ms / n,

        "quant":
            sum_quant_ms / n,

        "preprocess":
            sum_preprocess_ms / n,

        "dpu":
            sum_dpu_ms / n,

        "decode":
            sum_decode_ms / n,

        "logic":
            sum_logic_ms / n,

        "processing":
            avg_processing,

        "loop":
            sum_loop_ms / n,

        "processing_fps":
            (
                1000.0
                /
                avg_processing
            ),

        "wall_fps":
            (
                frame_count

                /

                (
                    benchmark_end
                    -
                    benchmark_start
                )
            ),

        "state":
            final_state
    }


# ============================================================
# PL Benchmark
# ============================================================

def benchmark_pl(

    camera,

    hls_preprocess,

    runner,

    raw_heads,

    fix_points
):

    print()
    print(
        "========================================"
    )
    print(
        " PL 1000-FRAME BENCHMARK"
    )
    print(
        "========================================"
    )


    sm = (
        create_state_machine()
    )


    frame_count = 0

    last_seq = 0


    sum_wait_ms = 0.0

    sum_preprocess_ms = 0.0

    sum_pack_ms = 0.0
    sum_h2d_ms = 0.0
    sum_hls_ms = 0.0
    sum_d2h_ms = 0.0
    sum_memcpy_ms = 0.0

    sum_dpu_ms = 0.0
    sum_decode_ms = 0.0
    sum_logic_ms = 0.0
    sum_processing_ms = 0.0
    sum_loop_ms = 0.0


    start_capture_count = (
        camera.get_stats()[0]
    )


    benchmark_start = (
        time.monotonic()
    )


    final_state = "UNKNOWN"


    while frame_count < NUM_FRAMES:

        loop_start = (
            time.perf_counter()
        )


        # ====================================================
        # Camera latest frame
        # ====================================================

        wait_start = (
            time.perf_counter()
        )


        frame, seq = (

            camera.get_latest(

                last_seq,

                timeout=1.0
            )
        )


        wait_end = (
            time.perf_counter()
        )


        if frame is None:

            continue


        last_seq = (
            seq
        )


        wait_ms = (

            (
                wait_end
                -
                wait_start
            )

            *
            1000.0
        )


        # ====================================================
        # PL preprocess
        # ====================================================

        t1 = (
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


        t2 = (
            time.perf_counter()
        )


        preprocess_ms = (

            (
                t2
                -
                t1
            )

            *
            1000.0
        )


        pack_ms = float(
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

        final_state, logic_ms = (

            run_logic(

                detections,

                sm
            )
        )


        # ====================================================
        # Processing
        # ====================================================

        processing_ms = (

            preprocess_ms

            +

            dpu_ms

            +

            decode_ms

            +

            logic_ms
        )


        loop_end = (
            time.perf_counter()
        )


        loop_ms = (

            (
                loop_end
                -
                loop_start
            )

            *
            1000.0
        )


        # ====================================================
        # Sum
        # ====================================================

        frame_count += 1


        sum_wait_ms += (
            wait_ms
        )

        sum_preprocess_ms += (
            preprocess_ms
        )

        sum_pack_ms += (
            pack_ms
        )

        sum_h2d_ms += (
            h2d_ms
        )

        sum_hls_ms += (
            hls_ms
        )

        sum_d2h_ms += (
            d2h_ms
        )

        sum_memcpy_ms += (
            memcpy_ms
        )

        sum_dpu_ms += (
            dpu_ms
        )

        sum_decode_ms += (
            decode_ms
        )

        sum_logic_ms += (
            logic_ms
        )

        sum_processing_ms += (
            processing_ms
        )

        sum_loop_ms += (
            loop_ms
        )


        if frame_count % 100 == 0:

            print(
                "PL processed:",
                frame_count,
                "/",
                NUM_FRAMES
            )


    benchmark_end = (
        time.monotonic()
    )


    end_capture_count = (
        camera.get_stats()[0]
    )


    captured_during_test = (

        end_capture_count

        -

        start_capture_count
    )


    skipped = max(

        0,

        captured_during_test

        -

        frame_count
    )


    n = float(
        frame_count
    )


    avg_processing = (

        sum_processing_ms

        /

        n
    )


    return {

        "frames":
            frame_count,

        "captured":
            captured_during_test,

        "skipped":
            skipped,

        "wait":
            sum_wait_ms / n,

        "packing":
            sum_pack_ms / n,

        "h2d":
            sum_h2d_ms / n,

        "hls":
            sum_hls_ms / n,

        "d2h":
            sum_d2h_ms / n,

        "memcpy":
            sum_memcpy_ms / n,

        "preprocess":
            sum_preprocess_ms / n,

        "dpu":
            sum_dpu_ms / n,

        "decode":
            sum_decode_ms / n,

        "logic":
            sum_logic_ms / n,

        "processing":
            avg_processing,

        "loop":
            sum_loop_ms / n,

        "processing_fps":
            (
                1000.0
                /
                avg_processing
            ),

        "wall_fps":
            (
                frame_count

                /

                (
                    benchmark_end
                    -
                    benchmark_start
                )
            ),

        "state":
            final_state
    }


# ============================================================
# Final print
# ============================================================

def print_final_results(
    camera,
    cpu,
    pl
):

    (
        total_captured,
        camera_read_avg,
        camera_acquired_fps

    ) = camera.get_stats()


    preprocess_speedup = (

        cpu["preprocess"]

        /

        pl["preprocess"]
    )


    processing_speedup = (

        cpu["processing"]

        /

        pl["processing"]
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


    processing_reduction = (

        (
            cpu["processing"]
            -
            pl["processing"]
        )

        /

        cpu["processing"]

        *

        100.0
    )


    # ========================================================
    # CPU
    # ========================================================

    print()
    print()
    print(
        "========================================"
    )
    print(
        " FINAL CPU PERFORMANCE"
    )
    print(
        "========================================"
    )


    print(
        "processed frames :",
        cpu["frames"]
    )


    print(
        "captured frames  :",
        cpu["captured"]
    )


    print(
        "dropped/skipped  :",
        cpu["skipped"]
    )


    print(
        "wait latest frame: {:.3f} ms".format(
            cpu["wait"]
        )
    )


    print(
        "preprocess       : {:.3f} ms".format(
            cpu["preprocess"]
        )
    )


    print(
        "  crop           : {:.3f} ms".format(
            cpu["crop"]
        )
    )


    print(
        "  resize         : {:.3f} ms".format(
            cpu["resize"]
        )
    )


    print(
        "  BGR->RGB       : {:.3f} ms".format(
            cpu["color"]
        )
    )


    print(
        "  quant          : {:.3f} ms".format(
            cpu["quant"]
        )
    )


    print(
        "DPU              : {:.3f} ms".format(
            cpu["dpu"]
        )
    )


    print(
        "decode (C++)     : {:.3f} ms".format(
            cpu["decode"]
        )
    )


    print(
        "logic            : {:.3f} ms".format(
            cpu["logic"]
        )
    )


    print(
        "processing       : {:.3f} ms".format(
            cpu["processing"]
        )
    )


    print(
        "loop avg         : {:.3f} ms".format(
            cpu["loop"]
        )
    )


    print(
        "processing FPS   : {:.2f}".format(
            cpu["processing_fps"]
        )
    )


    print(
        "wall FPS         : {:.2f}".format(
            cpu["wall_fps"]
        )
    )


    # ========================================================
    # PL
    # ========================================================

    print()
    print(
        "========================================"
    )
    print(
        " FINAL PL PERFORMANCE"
    )
    print(
        "========================================"
    )


    print(
        "processed frames :",
        pl["frames"]
    )


    print(
        "captured frames  :",
        pl["captured"]
    )


    print(
        "dropped/skipped  :",
        pl["skipped"]
    )


    print(
        "wait latest frame: {:.3f} ms".format(
            pl["wait"]
        )
    )


    print(
        "preprocess       : {:.3f} ms".format(
            pl["preprocess"]
        )
    )


    print(
        "  packing        : {:.3f} ms".format(
            pl["packing"]
        )
    )


    print(
        "  H2D            : {:.3f} ms".format(
            pl["h2d"]
        )
    )


    print(
        "  HLS            : {:.3f} ms".format(
            pl["hls"]
        )
    )


    print(
        "  D2H            : {:.3f} ms".format(
            pl["d2h"]
        )
    )


    print(
        "  memcpy         : {:.3f} ms".format(
            pl["memcpy"]
        )
    )


    print(
        "DPU              : {:.3f} ms".format(
            pl["dpu"]
        )
    )


    print(
        "decode (C++)     : {:.3f} ms".format(
            pl["decode"]
        )
    )


    print(
        "logic            : {:.3f} ms".format(
            pl["logic"]
        )
    )


    print(
        "processing       : {:.3f} ms".format(
            pl["processing"]
        )
    )


    print(
        "loop avg         : {:.3f} ms".format(
            pl["loop"]
        )
    )


    print(
        "processing FPS   : {:.2f}".format(
            pl["processing_fps"]
        )
    )


    print(
        "wall FPS         : {:.2f}".format(
            pl["wall_fps"]
        )
    )


    # ========================================================
    # Comparison
    # ========================================================

    print()
    print(
        "========================================"
    )
    print(
        " FINAL CPU vs PL COMPARISON"
    )
    print(
        "========================================"
    )


    print(
        "frames per test      :",
        NUM_FRAMES
    )


    print(
        "camera read avg      : {:.3f} ms".format(
            camera_read_avg
        )
    )


    print(
        "camera acquired FPS  : {:.2f}".format(
            camera_acquired_fps
        )
    )


    print()

    print(
        "CPU preprocess       : {:.3f} ms".format(
            cpu["preprocess"]
        )
    )


    print(
        "PL preprocess        : {:.3f} ms".format(
            pl["preprocess"]
        )
    )


    print(
        "preprocess speedup   : {:.3f} x".format(
            preprocess_speedup
        )
    )


    print(
        "preprocess reduction : {:.2f} %".format(
            preprocess_reduction
        )
    )


    print()

    print(
        "CPU DPU              : {:.3f} ms".format(
            cpu["dpu"]
        )
    )


    print(
        "PL DPU               : {:.3f} ms".format(
            pl["dpu"]
        )
    )


    print(
        "CPU decode           : {:.3f} ms".format(
            cpu["decode"]
        )
    )


    print(
        "PL decode            : {:.3f} ms".format(
            pl["decode"]
        )
    )


    print()

    print(
        "CPU processing       : {:.3f} ms".format(
            cpu["processing"]
        )
    )


    print(
        "PL processing        : {:.3f} ms".format(
            pl["processing"]
        )
    )


    print(
        "processing speedup   : {:.3f} x".format(
            processing_speedup
        )
    )


    print(
        "latency reduction    : {:.2f} %".format(
            processing_reduction
        )
    )


    print()

    print(
        "CPU processing FPS   : {:.2f}".format(
            cpu["processing_fps"]
        )
    )


    print(
        "PL processing FPS    : {:.2f}".format(
            pl["processing_fps"]
        )
    )


    print()

    print(
        "CPU wall FPS         : {:.2f}".format(
            cpu["wall_fps"]
        )
    )


    print(
        "PL wall FPS          : {:.2f}".format(
            pl["wall_fps"]
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # XMODEL
    # ========================================================

    print(
        "========================================"
    )
    print(
        " LOAD NEW 10-CLASS XMODEL"
    )
    print(
        "========================================"
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
    # PL init
    # ========================================================

    print()
    print(
        "========================================"
    )
    print(
        " INIT PL CROP + RESIZE + QUANT"
    )
    print(
        "========================================"
    )


    hls_preprocess = (

        HLSCropResizePLQuant(

            dst_size=DST_SIZE
        )
    )


    # ========================================================
    # DPU
    # ========================================================

    print()
    print(
        "========================================"
    )
    print(
        " CREATE DPU RUNNER"
    )
    print(
        "========================================"
    )


    runner = vart.Runner.create_runner(

        dpu_subgraph,

        "run"
    )


    print(
        "Runner created successfully."
    )


    # ========================================================
    # Tensor
    # ========================================================

    input_tensor = (
        runner.get_input_tensors()[0]
    )


    output_tensors = (
        runner.get_output_tensors()
    )


    input_fix = int(

        input_tensor.get_attr(
            "fix_point"
        )
    )


    print()

    print(
        "INPUT:",
        list(
            input_tensor.dims
        ),
        "fix_point:",
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
    # Input check
    # ========================================================

    if list(
        input_tensor.dims
    ) != [
        1,
        640,
        640,
        3
    ]:

        raise RuntimeError(

            "Unexpected DPU input shape: {}".format(

                list(
                    input_tensor.dims
                )
            )
        )


    if input_fix != 6:

        raise RuntimeError(

            "Unexpected DPU input fix_point: {}".format(
                input_fix
            )
        )


    # ========================================================
    # Output check
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

        for tensor in output_tensors
    }


    if actual_shapes != expected_shapes:

        raise RuntimeError(

            "Unexpected DPU outputs: {}".format(
                actual_shapes
            )
        )


    print()

    print(
        "NEW MODEL FORMAT CHECK: PASS"
    )


    # ========================================================
    # DPU output buffers
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
        "DPU output fix_points:",
        fix_points
    )


    # ========================================================
    # Camera
    # ========================================================

    print()
    print(
        "========================================"
    )
    print(
        " OPEN CAMERA THREAD - NO DISPLAY"
    )
    print(
        "========================================"
    )


    camera = LatestFrameCamera(

        CAMERA_ID,

        FRAME_W,

        FRAME_H,

        TARGET_FPS
    )


    camera.print_info()

    camera.start()


    print(
        "Camera capture thread started."
    )


    try:

        # ====================================================
        # Camera 안정화
        # ====================================================

        print()
        print(
            "Camera warm-up..."
        )


        time.sleep(
            2.0
        )


        # ====================================================
        # CPU
        # ====================================================

        cpu_result = benchmark_cpu(

            camera,

            runner,

            raw_heads,

            fix_points
        )


        # ====================================================
        # 짧은 휴식
        # ====================================================

        print()
        print(
            "Cooldown 5 seconds..."
        )


        time.sleep(
            5.0
        )


        # ====================================================
        # PL
        # ====================================================

        pl_result = benchmark_pl(

            camera,

            hls_preprocess,

            runner,

            raw_heads,

            fix_points
        )


        # ====================================================
        # Final
        # ====================================================

        print_final_results(

            camera,

            cpu_result,

            pl_result
        )


    finally:

        camera.stop()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
