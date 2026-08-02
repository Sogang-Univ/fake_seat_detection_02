"""
demo_webcam.py — [개발용 · 앞단 완성 시 폐기] 웹캠 + YOLOv5n 실시간 데모

★ 이 파일은 배포에 들어가지 않는다.

앞단(① 영상입력 ② ROI crop ④ DPU 추론)이 아직 완성되지 않았기 때문에,
5-b 상태머신의 전체 흐름을 웹캠과 Ultralytics YOLO로 확인하기 위한
개발용 대체 파일이다.

앞단이 완성되면:
    - 웹캠 전체 프레임
        → 2단계 HLS/PL에서 ROI crop이 끝난 영상으로 대체

    - Ultralytics YOLO 추론
        → 4단계 DPU YOLO 추론으로 대체

    - yolo_results_to_detections()
        → 5-a decode_yolo.py로 대체

★ ROI를 소프트웨어에서 따로 처리하지 않는다.

실제 배포에서는 HLS가 좌석 하나의 영역을 crop해서 넘겨준다.
따라서 이 데모에서는 웹캠 프레임 전체가 하나의 좌석 crop 영역이라고 간주한다.

실행:
    python3 demo_webcam.py

종료:
    q 또는 ESC
"""


import os
import sys
import time

import cv2


# ============================================================
# deploy/ 폴더의 배포 모듈 import
# ============================================================

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "deploy"
    )
)

from seat_state_machine import SeatStateMachine  # noqa: E402
from detection import (                         # noqa: E402
    make_detection,
    detections_to_flags,
    CLASS_NAMES,
    PERSON_ID,
    BAG_ID
)


# ============================================================
# 데모용 파라미터
# ============================================================

# 실환경 값: 900초
GHOST_SECONDS = 15.0

# 실환경 값: 100프레임
HYSTERESIS_FRAMES = 15

# 일반 상태 변경 안정화 시간
STATE_CHANGE_SECONDS = 5.0

# YOLO confidence 임계값
CONF_THRESH = 0.35


# ============================================================
# COCO 클래스 ID → 프로젝트 표준 클래스 ID
# ============================================================

# COCO 클래스:
#   person   = 0
#   backpack = 24
#   handbag  = 26
#   suitcase = 28
#   bottle   = 39
#
# 여러 소지품 클래스를 프로젝트의 BAG_ID 하나로 통합한다.

COCO_TO_OURS = {
    0: PERSON_ID,
    24: BAG_ID,
    26: BAG_ID,
    28: BAG_ID,
    39: BAG_ID
}


# ============================================================
# YOLO 결과를 프로젝트 표준 Detection 형식으로 변환
# ============================================================

def yolo_results_to_detections(result):
    """
    Ultralytics Results 객체를 프로젝트 표준 Detection 리스트로 변환한다.

    반환:
        List[Detection]

    Detection 형식:
        {
            "cls": int,
            "score": float,
            "box": (x1, y1, x2, y2)
        }

    box 좌표는 현재 crop 프레임 기준 절대 픽셀 좌표다.
    상태 판정에는 클래스 ID만 사용하고 box는 화면 표시용으로 사용한다.
    """

    dets = []

    if result.boxes is None:
        return dets

    for box in result.boxes:

        coco_cls = int(box.cls[0])

        # 프로젝트에서 사용하지 않는 클래스는 무시
        if coco_cls not in COCO_TO_OURS:
            continue

        score = float(box.conf[0])

        # confidence 기준 미달이면 무시
        if score < CONF_THRESH:
            continue

        x1, y1, x2, y2 = map(
            float,
            box.xyxy[0]
        )

        detection = make_detection(
            COCO_TO_OURS[coco_cls],
            score,
            (x1, y1, x2, y2)
        )

        dets.append(detection)

    return dets


# ============================================================
# 상태별 시각화 설정
# ============================================================

# OpenCV 색상은 RGB가 아니라 BGR 순서다.

STATE_COLOR = {
    "OCCUPIED": (0, 200, 0),       # 초록: 사용 중
    "GHOST": (0, 0, 255),          # 빨강: 유령 좌석
    "EMPTY": (160, 160, 160),      # 회색: 빈 좌석
    "UNKNOWN": (0, 165, 255)       # 주황: 판정 전
}

STATE_LABEL = {
    "OCCUPIED": "OCCUPIED (using)",
    "GHOST": "GHOST seat!",
    "EMPTY": "EMPTY",
    "UNKNOWN": "UNKNOWN..."
}


# ============================================================
# 화면 시각화
# ============================================================

def draw_overlay(frame, sm, now, dets):
    """
    프레임 위에 다음 정보를 표시한다.

    1. 사람/가방 바운딩 박스
    2. 현재 상태를 나타내는 프레임 테두리
    3. 현재 상태 또는 상태 전환 카운트다운

    전환 중 예:
        UNKNOWN -> OCCUPIED : 3.2s
        OCCUPIED -> EMPTY : 2.5s
        OCCUPIED -> GHOST : 10.4s
    """

    height, width = frame.shape[:2]

    color = STATE_COLOR[sm.state]

    # --------------------------------------------------------
    # 검출 객체 바운딩 박스 표시
    # --------------------------------------------------------

    for detection in dets:

        x1, y1, x2, y2 = map(
            int,
            detection["box"]
        )

        if detection["cls"] == PERSON_ID:
            box_color = (255, 120, 0)
        else:
            box_color = (0, 120, 255)

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            box_color,
            2
        )

        class_name = CLASS_NAMES.get(
            detection["cls"],
            "unknown"
        )

        cv2.putText(
            frame,
            class_name,
            (x1, max(y1 - 5, 15)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            box_color,
            2
        )

    # --------------------------------------------------------
    # 프레임 전체를 좌석 crop 영역으로 표시
    # --------------------------------------------------------

    cv2.rectangle(
        frame,
        (0, 0),
        (width - 1, height - 1),
        color,
        4
    )

    # --------------------------------------------------------
    # 통합 상태 전환 정보 조회
    # --------------------------------------------------------

    transition = sm.transition_info(now)

    if transition is None:

        banner = STATE_LABEL[sm.state]

    else:

        current_state = transition["current_state"]
        next_state = transition["next_state"]
        remaining = transition["remaining"]

        banner = (
            f"{current_state} -> {next_state}"
            f" : {remaining:.1f}s"
        )

    # --------------------------------------------------------
    # 상태 배너 크기 계산
    # --------------------------------------------------------

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    font_thickness = 2

    text_size, _ = cv2.getTextSize(
        banner,
        font,
        font_scale,
        font_thickness
    )

    banner_width = text_size[0] + 16
    banner_width = max(220, banner_width)
    banner_width = min(banner_width, width)

    banner_height = 32

    cv2.rectangle(
        frame,
        (0, 0),
        (banner_width, banner_height),
        color,
        -1
    )

    cv2.putText(
        frame,
        banner,
        (6, 22),
        font,
        font_scale,
        (255, 255, 255),
        font_thickness
    )

    return frame


# ============================================================
# 웹캠 데모 실행
# ============================================================

def run_webcam(cam_index=0):
    """
    웹캠 프레임 전체를 하나의 좌석 crop 영상으로 간주하여
    YOLO 추론과 좌석 상태머신을 실행한다.
    """

    # --------------------------------------------------------
    # Ultralytics import
    # --------------------------------------------------------

    try:
        from ultralytics import YOLO

    except ImportError:

        print(
            "[에러] ultralytics가 설치되어 있지 않습니다.\n"
            "다음 명령으로 설치한 뒤 다시 실행하세요.\n"
            "pip install ultralytics"
        )

        return

    # --------------------------------------------------------
    # YOLO 모델 로드
    # --------------------------------------------------------

    model = YOLO("yolov5n.pt")

    # --------------------------------------------------------
    # 웹캠 열기
    # --------------------------------------------------------

    cap = cv2.VideoCapture(cam_index)

    cap.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        640
    )

    cap.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        480
    )

    if not cap.isOpened():

        print("[에러] 웹캠을 열 수 없습니다.")

        return

    ok, first_frame = cap.read()

    if not ok:

        print("[에러] 웹캠에서 첫 프레임을 읽을 수 없습니다.")

        cap.release()

        return

    print(
        "[안내] 웹캠 화각 전체가 좌석 하나만 비추도록 설정하세요."
    )

    print(
        "[안내] 실제 배포에서는 현재 프레임 대신 "
        "HLS가 crop한 좌석 영상이 입력됩니다."
    )

    print("[안내] q 또는 ESC를 누르면 종료됩니다.")

    # --------------------------------------------------------
    # 상태머신 생성
    # --------------------------------------------------------

    sm = SeatStateMachine(
        ghost_seconds=GHOST_SECONDS,
        hysteresis_frames=HYSTERESIS_FRAMES,
        state_change_seconds=STATE_CHANGE_SECONDS
    )

    prev_state = sm.state
    prev_frame_time = time.perf_counter()

    frame_count = 0

    # --------------------------------------------------------
    # 메인 루프
    # --------------------------------------------------------

    while True:

        ok, frame = cap.read()

        if not ok:

            print("[에러] 웹캠 프레임 읽기에 실패했습니다.")

            break

        frame_count += 1

        now = time.time()

        # ----------------------------------------------------
        # YOLO 추론
        # ----------------------------------------------------

        inference_start = time.perf_counter()

        result = model(
            frame,
            verbose=False
        )[0]

        inference_time = (
            time.perf_counter()
            - inference_start
        )

        # ----------------------------------------------------
        # YOLO 결과를 표준 Detection 리스트로 변환
        # ----------------------------------------------------

        dets = yolo_results_to_detections(
            result
        )

        # ----------------------------------------------------
        # Detection 리스트를 사람/가방 플래그로 변환
        # ----------------------------------------------------
        #
        # ROI 좌표를 전달하지 않는다.
        # 현재 detection.py는 crop 프레임 안에 클래스가 존재하는지만 본다.

        person_present, bag_present = detections_to_flags(
            dets
        )

        # ----------------------------------------------------
        # 상태머신 갱신
        # ----------------------------------------------------

        state = sm.update(
            person_present,
            bag_present,
            now
        )

        # 최종 확정 상태가 변경된 경우에만 로그 출력
        if state != prev_state:

            print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"STATE : {prev_state} -> {state}"
            )

            prev_state = state

        # ----------------------------------------------------
        # 화면 시각화
        # ----------------------------------------------------

        draw_overlay(
            frame,
            sm,
            now,
            dets
        )

        # ----------------------------------------------------
        # FPS 계산
        # ----------------------------------------------------

        current_frame_time = time.perf_counter()

        frame_interval = (
            current_frame_time
            - prev_frame_time
        )

        if frame_interval > 0.0:
            fps = 1.0 / frame_interval
        else:
            fps = 0.0

        prev_frame_time = current_frame_time

        # FPS 표시
        cv2.putText(
            frame,
            f"FPS : {fps:.1f}",
            (10, 62),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2
        )

        # 추론 시간 표시
        cv2.putText(
            frame,
            f"Inference : {inference_time * 1000.0:.1f} ms",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )

        # 사람/가방 플래그 표시
        cv2.putText(
            frame,
            (
                f"Person : {person_present}  "
                f"Bag : {bag_present}"
            ),
            (10, 118),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2
        )

        # 프레임 번호 표시
        cv2.putText(
            frame,
            f"Frame : {frame_count}",
            (10, 146),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2
        )

        cv2.imshow(
            "Ghost Seat Demo (5-b)",
            frame
        )

        key = cv2.waitKey(1) & 0xFF

        if key in (
            ord("q"),
            27
        ):
            break

    # --------------------------------------------------------
    # 자원 정리
    # --------------------------------------------------------

    cap.release()
    cv2.destroyAllWindows()


# ============================================================
# 프로그램 시작점
# ============================================================

if __name__ == "__main__":
    run_webcam(0)



