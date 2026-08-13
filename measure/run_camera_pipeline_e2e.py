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

from detection import (
    CLASS_NAMES,
    detections_to_flags
)

# ============================================================
# 설정
# ============================================================

MODEL = (
    "/home/ubuntu/yolov5_test/"
    "yolov5n_2304.xmodel"
)

CAMERA_ID = 0

FRAME_W = 640
FRAME_H = 480

TARGET_FPS = 30


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
# chair는 제외
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
# Threshold
# ============================================================

SCORE_THRESH = 0.25

NMS_IOU_THRESH = 0.55


# ============================================================
# Overlay 색상
#
# OpenCV는 BGR
# ============================================================

STATE_COLORS = {

    "OCCUPIED": (
        0,
        255,
        0
    ),      # Green

    "GHOST": (
        0,
        165,
        255
    ),      # Orange

    "EMPTY": (
        255,
        0,
        0
    ),      # Blue

    "UNKNOWN": (
        0,
        255,
        255
    )       # Yellow
}


# ============================================================
# ★ ROI는 상태와 무관하게 항상 파란색
# ============================================================

ROI_COLOR = (
    255,
    0,
    0
)


# ============================================================
# Detection box 색상
# ============================================================

PERSON_BOX_COLOR = (
    0,
    255,
    0
)

OBJECT_BOX_COLOR = (
    0,
    165,
    255
)


# ============================================================
# State machine
# ============================================================

sm = SeatStateMachine(

    ghost_seconds=10.0,

    hysteresis_frames=10,

    state_change_seconds=5.0
)


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
# Camera Thread
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
# XMODEL load
# ============================================================

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


# ============================================================
# PL init
# ============================================================

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


# ============================================================
# DPU Runner
# ============================================================

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


# ============================================================
# Tensor information
# ============================================================

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


# ============================================================
# Input shape check
# ============================================================

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


# ============================================================
# Output shape check
# ============================================================

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

print(
    "PL quant format matches DPU input."
)


# ============================================================
# DPU output buffers
# ============================================================

raw_heads = [

    np.empty(

        tuple(
            tensor.dims
        ),

        dtype=np.int8
    )

    for tensor in output_tensors
]


# ============================================================
# Output fix points
# ============================================================

fix_points = [

    int(

        tensor.get_attr(
            "fix_point"
        )
    )

    for tensor in output_tensors
]


print()

print(
    "DPU output fix_points:",
    fix_points
)


# ============================================================
# Camera
# ============================================================

print()

print(
    "========================================"
)

print(
    " OPEN CAMERA THREAD"
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


# ============================================================
# Performance
# ============================================================

frame_count = 0

sum_wait_frame_ms = 0.0
sum_preprocess_ms = 0.0
sum_dpu_ms = 0.0
sum_decode_ms = 0.0
sum_logic_ms = 0.0
sum_processing_ms = 0.0
sum_loop_ms = 0.0

sum_pack_ms = 0.0
sum_h2d_ms = 0.0
sum_kernel_ms = 0.0
sum_d2h_ms = 0.0
sum_memcpy_ms = 0.0


program_start = (
    time.monotonic()
)


fps_start = (
    program_start
)

fps_frames = 0

display_fps = 0.0

last_camera_seq = 0


print()

print(
    "========================================"
)

print(
    " START THREADED CAMERA -> PL -> DPU -> C++ DECODE"
)

print(
    "========================================"
)


# ============================================================
# Main Loop
# ============================================================

try:

    while True:

        loop_start = (
            time.perf_counter()
        )


        # ====================================================
        # 1. Camera
        # ====================================================

        wait_start = (
            time.perf_counter()
        )


        frame, camera_seq = (

            camera.get_latest(

                last_camera_seq,

                timeout=1.0
            )
        )


        wait_end = (
            time.perf_counter()
        )


        if frame is None:

            print(
                "Camera frame timeout"
            )

            continue


        last_camera_seq = (
            camera_seq
        )


        # ====================================================
        # 2. PL preprocessing
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


        # ====================================================
        # 3. DPU
        # ====================================================

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


        t3 = (
            time.perf_counter()
        )


        # ====================================================
        # 4. C++ Decode
        # ====================================================

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


        t4 = (
            time.perf_counter()
        )


        # ====================================================
        # 5. Flags
        # ====================================================

        person_present, object_present = (
            detections_to_flags(

                detections,

                ROI_BOX
            )
        )


        # ====================================================
        # 6. State Machine
        # ====================================================

        now = (
            time.monotonic()
        )


        state = sm.update(

            person_present,

            object_present,

            now
        )


        t5 = (
            time.perf_counter()
        )


        # ====================================================
        # 7. Detection Box
        # ====================================================

        for det in detections:

            cls_id = int(
                det["cls"]
            )

            score = float(
                det["score"]
            )


            x1, y1, x2, y2 = (
                det["box"]
            )


            x1 = int(
                max(
                    0,
                    min(
                        FRAME_W - 1,
                        x1
                    )
                )
            )


            y1 = int(
                max(
                    0,
                    min(
                        FRAME_H - 1,
                        y1
                    )
                )
            )


            x2 = int(
                max(
                    0,
                    min(
                        FRAME_W - 1,
                        x2
                    )
                )
            )


            y2 = int(
                max(
                    0,
                    min(
                        FRAME_H - 1,
                        y2
                    )
                )
            )


            if cls_id == 0:

                detection_color = (
                    PERSON_BOX_COLOR
                )

            else:

                detection_color = (
                    OBJECT_BOX_COLOR
                )


            cv2.rectangle(

                frame,

                (
                    x1,
                    y1
                ),

                (
                    x2,
                    y2
                ),

                detection_color,

                2
            )


            label = (

                "{} {:.2f}".format(

                    CLASS_NAMES.get(
                        cls_id,
                        "unknown"
                    ),

                    score
                )
            )


            cv2.putText(

                frame,

                label,

                (
                    x1,

                    max(
                        20,
                        y1 - 5
                    )
                ),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.5,

                detection_color,

                1
            )


        # ====================================================
        # 8. FPS 계산
        # ====================================================

        frame_count += 1

        fps_frames += 1


        fps_now = (
            time.monotonic()
        )


        fps_elapsed = (
            fps_now
            -
            fps_start
        )


        if fps_elapsed >= 1.0:

            display_fps = (
                fps_frames
                /
                fps_elapsed
            )


            fps_start = (
                fps_now
            )

            fps_frames = 0


        # ====================================================
        # 9. Overlay
        # ====================================================

        state_color = (

            STATE_COLORS.get(

                state,

                (
                    0,
                    255,
                    255
                )
            )
        )


        # ----------------------------------------------------
        # FPS - 항상 노랑
        # ----------------------------------------------------

        cv2.putText(

            frame,

            "FPS {:.1f}".format(
                display_fps
            ),

            (
                10,
                25
            ),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (
                0,
                255,
                255
            ),

            2
        )


        # ----------------------------------------------------
        # STATE
        # ----------------------------------------------------

        cv2.putText(

            frame,

            "STATE {}".format(
                state
            ),

            (
                10,
                55
            ),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            state_color,

            2
        )


        # ----------------------------------------------------
        # State transition timer
        # ----------------------------------------------------

        transition_info = (

            sm.transition_info(
                now
            )
        )


        if transition_info is not None:

            next_state = (

                transition_info[
                    "next_state"
                ]
            )


            remaining = float(

                transition_info[
                    "remaining"
                ]
            )


            remaining = max(
                0.0,
                remaining
            )


            next_state_color = (

                STATE_COLORS.get(

                    next_state,

                    (
                        255,
                        255,
                        255
                    )
                )
            )


            timer_text = (

                "-> {} in {:.1f}s".format(

                    next_state,

                    remaining
                )
            )


            cv2.putText(

                frame,

                timer_text,

                (
                    10,
                    82
                ),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.6,

                next_state_color,

                2
            )


        # ----------------------------------------------------
        # ★ ROI BOX
        #
        # 상태와 관계없이 항상 BLUE
        # ----------------------------------------------------

        rx1, ry1, rx2, ry2 = (
            ROI_BOX
        )


        cv2.rectangle(

            frame,

            (
                int(rx1),
                int(ry1)
            ),

            (
                int(rx2),
                int(ry2)
            ),

            ROI_COLOR,

            3
        )


        # ====================================================
        # 10. Timing
        # ====================================================

        wait_frame_ms = (
            (
                wait_end
                -
                wait_start
            )
            *
            1000.0
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


        dpu_ms = (
            (
                t3
                -
                t2
            )
            *
            1000.0
        )


        decode_ms = (
            (
                t4
                -
                t3
            )
            *
            1000.0
        )


        logic_ms = (
            (
                t5
                -
                t4
            )
            *
            1000.0
        )


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
        # 누적
        # ====================================================

        sum_wait_frame_ms += (
            wait_frame_ms
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


        sum_pack_ms += (
            hls_timing[0]
        )

        sum_h2d_ms += (
            hls_timing[1]
        )

        sum_kernel_ms += (
            hls_timing[2]
        )

        sum_d2h_ms += (
            hls_timing[3]
        )

        sum_memcpy_ms += (
            hls_timing[4]
        )


        # ====================================================
        # 30 frame마다 출력
        # ====================================================

        if frame_count % 30 == 0:

            n = float(
                frame_count
            )


            (
                captured_count,

                capture_read_avg,

                camera_acquired_fps

            ) = camera.get_stats()


            dropped = max(

                0,

                captured_count
                -
                frame_count
            )


            print()

            print(
                "----------------------------------------"
            )


            print(
                "processed frames :",
                frame_count
            )


            print(
                "captured frames  :",
                captured_count
            )


            print(
                "dropped/skipped  :",
                dropped
            )


            print(
                "camera read avg  : {:.3f} ms".format(
                    capture_read_avg
                )
            )


            print(
                "camera acquired FPS: {:.2f}".format(
                    camera_acquired_fps
                )
            )


            print(
                "wait latest frame: {:.3f} ms".format(
                    sum_wait_frame_ms
                    /
                    n
                )
            )


            print(
                "preprocess       : {:.3f} ms".format(
                    sum_preprocess_ms
                    /
                    n
                )
            )


            print(
                "  packing        : {:.3f} ms".format(
                    sum_pack_ms
                    /
                    n
                )
            )


            print(
                "  H2D            : {:.3f} ms".format(
                    sum_h2d_ms
                    /
                    n
                )
            )


            print(
                "  HLS            : {:.3f} ms".format(
                    sum_kernel_ms
                    /
                    n
                )
            )


            print(
                "  D2H            : {:.3f} ms".format(
                    sum_d2h_ms
                    /
                    n
                )
            )


            print(
                "  memcpy         : {:.3f} ms".format(
                    sum_memcpy_ms
                    /
                    n
                )
            )


            print(
                "DPU              : {:.3f} ms".format(
                    sum_dpu_ms
                    /
                    n
                )
            )


            print(
                "decode (C++)     : {:.3f} ms".format(
                    sum_decode_ms
                    /
                    n
                )
            )


            print(
                "logic            : {:.3f} ms".format(
                    sum_logic_ms
                    /
                    n
                )
            )


            print(
                "processing       : {:.3f} ms".format(
                    sum_processing_ms
                    /
                    n
                )
            )


            print(
                "loop avg         : {:.3f} ms".format(
                    sum_loop_ms
                    /
                    n
                )
            )


            if sum_processing_ms > 0:

                print(
                    "processing FPS   : {:.2f}".format(

                        1000.0

                        /

                        (
                            sum_processing_ms
                            /
                            n
                        )
                    )
                )


            print(
                "display FPS      : {:.2f}".format(
                    display_fps
                )
            )


        # ====================================================
        # Display
        # ====================================================

        cv2.imshow(

            "KV260 YOLOv5n Leaky B2304 C++ Decode",

            frame
        )


        key = (
            cv2.waitKey(1)
            &
            0xFF
        )


        if key == ord("q"):

            break


# ============================================================
# 종료
# ============================================================

finally:

    camera.stop()

    cv2.destroyAllWindows()


    print()

    print(
        "========================================"
    )

    print(
        " FINAL THREADED PERFORMANCE"
    )

    print(
        "========================================"
    )


    if frame_count > 0:

        n = float(
            frame_count
        )


        (
            captured_count,

            capture_read_avg,

            camera_acquired_fps

        ) = camera.get_stats()


        dropped = max(

            0,

            captured_count
            -
            frame_count
        )


        print(
            "processed frames :",
            frame_count
        )


        print(
            "captured frames  :",
            captured_count
        )


        print(
            "dropped/skipped  :",
            dropped
        )


        print(
            "camera read avg  : {:.3f} ms".format(
                capture_read_avg
            )
        )


        print(
            "camera acquired FPS: {:.2f}".format(
                camera_acquired_fps
            )
        )


        print(
            "wait latest frame: {:.3f} ms".format(
                sum_wait_frame_ms
                /
                n
            )
        )


        print(
            "preprocess       : {:.3f} ms".format(
                sum_preprocess_ms
                /
                n
            )
        )


        print(
            "  packing        : {:.3f} ms".format(
                sum_pack_ms
                /
                n
            )
        )


        print(
            "  H2D            : {:.3f} ms".format(
                sum_h2d_ms
                /
                n
            )
        )


        print(
            "  HLS            : {:.3f} ms".format(
                sum_kernel_ms
                /
                n
            )
        )


        print(
            "  D2H            : {:.3f} ms".format(
                sum_d2h_ms
                /
                n
            )
        )


        print(
            "  memcpy         : {:.3f} ms".format(
                sum_memcpy_ms
                /
                n
            )
        )


        print(
            "DPU              : {:.3f} ms".format(
                sum_dpu_ms
                /
                n
            )
        )


        print(
            "decode (C++)     : {:.3f} ms".format(
                sum_decode_ms
                /
                n
            )
        )


        print(
            "logic            : {:.3f} ms".format(
                sum_logic_ms
                /
                n
            )
        )


        print(
            "processing       : {:.3f} ms".format(
                sum_processing_ms
                /
                n
            )
        )


        print(
            "loop avg         : {:.3f} ms".format(
                sum_loop_ms
                /
                n
            )
        )


        if sum_processing_ms > 0:

            print(
                "processing FPS   : {:.2f}".format(

                    1000.0

                    /

                    (
                        sum_processing_ms
                        /
                        n
                    )
                )
            )


    total_wall = (
        time.monotonic()
        -
        program_start
    )


    if total_wall > 0:

        print(
            "wall FPS         : {:.2f}".format(

                frame_count

                /

                total_wall
            )
        )
