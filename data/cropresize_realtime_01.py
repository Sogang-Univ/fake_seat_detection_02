# ============================================================
# 0. 라이브러리 불러오기 / 설치 확인
# ============================================================
import os
import gc
import time
import queue
import socket
import threading
import http.server
import subprocess

import numpy as np

try:
    import cv2
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        "cv2(OpenCV)가 설치되어 있지 않습니다.\n"
        "KV260 보드에서는 pynq-venv 커널을 사용 중인지 확인하세요."
    ) from e

try:
    import pynq
    from pynq import Overlay, allocate
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        "pynq 모듈을 불러올 수 없습니다. 이 노트북은 KV260(PYNQ) 보드에서만 동작합니다."
    ) from e

print("OpenCV :", cv2.__version__)
print("NumPy  :", np.__version__)
print("PYNQ   :", pynq.__version__)

# ============================================================
# 1. 사용자 설정
# ============================================================

# ---- 경로: realtime_roi_v2.py / Untitled1.ipynb / resize_01.ipynb 가 있던 위치를 순서대로 탐색 ----
BASE_DIR_CANDIDATES = [
    "/root/jupyter_notebooks/work/roi_crop",
    "/home/ubuntu/roi_crop/roi_crop",
    "/home/ubuntu/roi_crop",
]
BIT_NAME = "design_1_wrapper.bit"

# 이 노트북의 실시간 결과(영상/npy)를 저장할 폴더
OUTPUT_DIR = "/home/ubuntu/work/cropresize_realtime_output"

CAMERA_INDEX = 0

# ---- 카메라 / crop 설정 (realtime_roi_v2.py 와 동일) ----
INPUT_SHAPE = (480, 640, 3)   # (H, W, C) 카메라 원본
CROP_SHAPE  = (480, 480, 3)   # (H, W, C) HLS crop 결과 (정사각형)

# PS 쪽에서 참고하는 crop 원점. HLS IP 의 crop 원점과 반드시 동일해야 함 (중앙 crop 기준)
CROP_X0 = (INPUT_SHAPE[1] - CROP_SHAPE[1]) // 2   # 80
CROP_Y0 = (INPUT_SHAPE[0] - CROP_SHAPE[0]) // 2   # 0

# ---- resize 설정 (resize_01.ipynb 와 동일) ----
TARGET_SIZE   = 640                       # YOLO 입력 크기
RESIZE_SHAPE  = (TARGET_SIZE, TARGET_SIZE, 3)
INTERPOLATION = cv2.INTER_LINEAR          # 480->640 업스케일용 (다운스케일이면 INTER_AREA)

DTYPE = np.uint8

# ---- 저장 설정 (crop+resize 최종 결과 하나만 저장 : mp4 1개 + npy 1개) ----
SAVE_MP4 = True
SAVE_NPY = True

CAMERA_TARGET_FPS = 30.0   # 카메라에 요청할 FPS (실제로 달성 가능한 값은 다를 수 있음)

# ---- FPS 보정 (녹화 영상이 뚝뚝 끊기는 문제 방지) ----
# 카메라+PL crop+resize 를 실제로 얼마나 빨리 처리할 수 있는지 녹화 시작 전에 짧게 측정해서
# 그 값을 mp4 FPS 로 사용한다. CAMERA_TARGET_FPS 를 그대로 mp4 FPS 로 쓰면, 실제 처리 속도가
# 더 느릴 때 프레임 간 실제 시간 간격보다 빠르게 재생되어 움직임이 끊겨 보인다.
CALIBRATE_FPS = True
CALIBRATION_FRAMES = 30        # 측정에 사용할 프레임 수
CALIBRATION_TIMEOUT_SEC = 8    # 측정이 너무 오래 걸리면 포기하고 기본값 사용
MIN_RECORD_FPS = 5.0           # mp4 FPS 하한 (너무 낮으면 재생 프로그램에서 문제될 수 있음)

# ---- 실행 시간 제한 (디스크 보호 / 무한루프 방지용, 필요하면 값만 바꾸세요) ----
# 둘 중 먼저 도달하는 조건에서 자동 종료됩니다. 언제든 Ctrl+C 로도 즉시 종료 가능.
RUN_SECONDS = 15
MAX_FRAMES  = 450

# ---- 실시간 웹 미리보기 (SSH/원격 접속 환경 대상) ----
# 보드에 모니터가 없고 SSH 로 접속해서 돌리는 상황이므로, cv2.imshow 대신
# crop+resize 결과를 MJPEG 스트림으로 띄운다. PC/노트북 브라우저에서
# http://<보드IP>:STREAM_PORT/ 를 열면 촬영 중인 화면을 실시간으로 볼 수 있다.
SHOW_PREVIEW = True
STREAM_PORT = 8090
SHOW_LOCAL_WINDOW = True   # ssh -X(X11 forwarding) 로 cv2.imshow 창을 띄운다.
                           # 주의: X11 forwarding 은 프레임마다 네트워크로 이미지를 보내야 해서
                           # 간헐적 끊김의 원인이 될 수 있다. 만약 끊김이 다시 심해지면
                           # 이 값을 False 로 되돌리고 브라우저 미리보기(http://보드IP:8090)를
                           # 대신 쓰는 걸 권장한다. [STALL] 로그로 어느 쪽이 원인인지 비교 가능.

# 자동노출/화이트밸런스를 끄면 색이 이상해질 수 있다 (자동 WB를 끄면서 수동 색온도 값을
# 지정하지 않으면 임의의 값에 고정됨). 큐/로컬미리보기 분리로 끊김 문제는 이미 해결됐으므로
# 기본은 꺼둔다. 정말 필요하면 True 로 바꾸고, 색이 이상해지면 v4l2-ctl 로 
# white_balance_temperature 값을 직접 맞춰야 한다.
LOCK_CAMERA_AUTO_CONTROLS = False
STATS_EVERY_N_FRAMES = 30   # 콘솔에 진행 상황을 출력하는 주기

# SD카드 쓰기(mp4 인코딩 + npy 기록)는 가끔 순간적으로 느려질 수 있다(카드 내부 GC 등).
# QUEUE_DEPTH 가 작으면 이 순간에 버퍼가 바로 바닥나서 캡처 루프 자체가 멈춰버리므로
# ("중간중간 끊김"의 흔한 원인), 넉넉하게 잡아서 SD카드가 잠깐 느려져도 흡수하게 한다.
# 버퍼 1개 = 480x480x3 ≈ 0.66MB 이므로 60개(+2) 여도 RAM 사용량은 ~40MB 수준으로 무시할 만하다.
QUEUE_DEPTH = 60

INPUT_BYTES = int(np.prod(INPUT_SHAPE))
CROP_BYTES  = int(np.prod(CROP_SHAPE))

# ============================================================
# 2. 경로 확인 + 디스크 용량 점검
# ============================================================
BASE_DIR = None
for cand in BASE_DIR_CANDIDATES:
    if os.path.isfile(os.path.join(cand, BIT_NAME)):
        BASE_DIR = cand
        break

if BASE_DIR is None:
    raise FileNotFoundError(
        "design_1_wrapper.bit 를 찾을 수 없습니다. 다음 경로들을 확인하세요:\n  "
        + "\n  ".join(BASE_DIR_CANDIDATES)
    )

BIT_PATH = os.path.join(BASE_DIR, BIT_NAME)
HWH_PATH = os.path.splitext(BIT_PATH)[0] + ".hwh"

if not os.path.isfile(HWH_PATH):
    raise FileNotFoundError(HWH_PATH)

print("BASE_DIR :", BASE_DIR)
print("BIT_PATH :", BIT_PATH, "OK")
print("HWH_PATH :", HWH_PATH, "OK")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# crop+resize 최종 결과만 저장 (mp4 1개 + npy 1개)
OUTPUT_MP4_PATH = os.path.join(OUTPUT_DIR, "cropresize_640_realtime.mp4")
OUTPUT_NPY_PATH = os.path.join(OUTPUT_DIR, "cropresize_640_realtime.npy")

# ---- 예상 NPY 사용량 vs 남은 디스크 용량 확인 (녹화 중 ENOSPC 방지) ----
est_bytes = MAX_FRAMES * int(np.prod(RESIZE_SHAPE)) if SAVE_NPY else 0

vfs = os.statvfs(OUTPUT_DIR)
free_bytes = vfs.f_bavail * vfs.f_frsize

print("예상 NPY 최대 사용량 : %.2f GB" % (est_bytes / 1e9))
print("남은 디스크 용량     : %.2f GB" % (free_bytes / 1e9))

if est_bytes > free_bytes * 0.8:
    raise RuntimeError(
        "디스크 여유 공간이 부족할 수 있습니다. MAX_FRAMES 를 줄이거나 "
        "SAVE_NPY 설정을 조정한 뒤 다시 실행하세요."
    )

# ============================================================
# 3. 헬퍼 함수
# ============================================================

def resize_for_yolo(roi_img, target_size=TARGET_SIZE, interpolation=INTERPOLATION):
    '''
    ROI 이미지를 YOLO 입력 크기로 resize. (resize_01.ipynb 의 resize_for_yolo 와 동일 로직)

    Args:
        roi_img: (480, 480, 3) uint8, HWC
        target_size: 출력 정사각형 크기 (기본 640)

    Returns:
        (640, 640, 3) uint8, HWC
    '''
    assert roi_img is not None, "ROI 이미지가 None입니다"
    assert roi_img.ndim == 3 and roi_img.shape[2] == 3, f"예상치 못한 shape: {roi_img.shape}"
    assert roi_img.dtype == DTYPE, f"예상치 못한 dtype: {roi_img.dtype} (예상: {DTYPE})"
    return cv2.resize(roi_img, (target_size, target_size), interpolation=interpolation)


def finalize_npy(path, n_frames, frame_shape, dtype=np.uint8):
    '''
    open_memmap 으로 MAX_FRAMES 크기로 만들어 둔 .npy 를
    실제 기록된 n_frames 크기로 '헤더만 고쳐서' 잘라낸다. (realtime_roi_v2.py 와 동일, O(1))
    '''
    dt = np.dtype(dtype)
    frame_bytes = int(np.prod(frame_shape)) * dt.itemsize

    with open(path, "r+b") as f:
        if f.read(6) != b"\x93NUMPY":
            raise ValueError("npy magic mismatch: %s" % path)
        major, _ = f.read(2)
        if major == 1:
            hlen = int.from_bytes(f.read(2), "little")
            hoff = 10
        else:
            hlen = int.from_bytes(f.read(4), "little")
            hoff = 12

        descr = np.lib.format.dtype_to_descr(dt)
        shape_txt = ", ".join(str(int(x)) for x in frame_shape)
        header = ("{'descr': '%s', 'fortran_order': False, "
                   "'shape': (%d, %s), }" % (descr, n_frames, shape_txt))
        if len(header) + 1 > hlen:
            raise ValueError("new header longer than original")
        header = header + " " * (hlen - len(header) - 1) + "\n"

        f.seek(hoff)
        f.write(header.encode("latin1"))
        f.flush()
        os.fsync(f.fileno())

    os.truncate(path, hoff + hlen + n_frames * frame_bytes)


def read_hls_status(ip):
    ctrl = ip.read(0x00)
    return {
        "raw": ctrl,
        "ap_start": bool(ctrl & (1 << 0)),
        "ap_done":  bool(ctrl & (1 << 1)),
        "ap_idle":  bool(ctrl & (1 << 2)),
        "ap_ready": bool(ctrl & (1 << 3)),
    }


def get_local_ip():
    '''보드가 실제로 트래픽을 내보내는 인터페이스의 IP를 추정한다 (패킷을 실제로 보내지는 않음).'''
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def lock_camera_auto_controls(index):
    '''
    카메라의 자동노출 / 자동 화이트밸런스를 꺼서 고정한다.
    이 기능들이 켜져 있으면 조명이 조금만 바뀌어도 카메라가 노출을 재조정하면서
    순간적으로 프레임 속도가 떨어지는 경우가 있다 (간헐적 끊김의 흔한 원인).

    단순히 auto 만 끄면, 해당 수동 컨트롤(exposure_time_absolute /
    white_balance_temperature)이 카메라의 저장된 기본값으로 돌아가면서 화면이
    너무 어둡거나 색이 이상하게 나올 수 있다 (실제로 한 번 이 문제가 있었다).
    그래서 auto 를 끄기 '직전'에 지금 auto 가 맞춰놓은 값을 먼저 읽어두고,
    끈 직후 그 값을 그대로 수동값으로 넣어서 끄는 순간의 밝기/색을 그대로 유지한다.

    드라이버/카메라마다 컨트롤 이름이 다를 수 있어 흔한 대체 이름들을 순서대로 시도한다.
    v4l2-ctl 이 없거나 카메라가 해당 컨트롤을 전혀 지원하지 않으면 경고만 출력하고
    넘어간다 (녹화 자체를 막지는 않는다).
    '''
    device = "/dev/video%d" % index

    def get_ctrl(name):
        try:
            r = subprocess.run(["v4l2-ctl", "-d", device, "--get-ctrl", name],
                                capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and ":" in r.stdout:
                return r.stdout.strip().split(":")[-1].strip()
        except Exception:
            pass
        return None

    def set_ctrl(name, value):
        try:
            r = subprocess.run(["v4l2-ctl", "-d", device, "-c", "%s=%s" % (name, value)],
                                capture_output=True, text=True, timeout=3)
            return (r.returncode == 0), r.stderr.strip()
        except FileNotFoundError:
            print("[WARN] v4l2-ctl 명령을 찾을 수 없습니다. "
                  "'sudo apt install v4l-utils' 로 설치할 수 있습니다.")
            return False, "v4l2-ctl not found"
        except Exception as e:
            return False, str(e)

    def lock_one(off_names, off_value, manual_ctrl_name):
        # auto 를 끄기 전에, 지금 auto 가 맞춰놓은 수동값을 먼저 읽어둔다.
        current_manual_val = get_ctrl(manual_ctrl_name) if manual_ctrl_name else None

        applied, last_err = False, None
        for name in off_names:
            ok, err = set_ctrl(name, off_value)
            if ok:
                applied = True
                break
            last_err = err
        if not applied:
            print("[WARN] %s 계열 컨트롤을 설정하지 못했습니다 (시도: %s) : %s"
                  % (off_names[0], off_names, last_err))
            print("       'v4l2-ctl -d %s --list-ctrls' 로 실제 지원되는 컨트롤 이름을 확인해보세요."
                  % device)
            return

        # auto 를 끈 직후, 방금 읽어둔 값을 그대로 수동값으로 넣어서
        # 밝기/색이 갑자기 바뀌지 않게 한다.
        if manual_ctrl_name and current_manual_val is not None:
            ok, err = set_ctrl(manual_ctrl_name, current_manual_val)
            if not ok:
                print("[WARN] %s=%s 적용 실패: %s" % (manual_ctrl_name, current_manual_val, err))

    lock_one(["exposure_auto", "auto_exposure"], 1, "exposure_time_absolute")
    lock_one(["white_balance_temperature_auto", "white_balance_automatic"], 0,
              "white_balance_temperature")

# ============================================================
# 4. 카메라 캡처 스레드 (latest-frame-wins, realtime_roi_v2.py 와 동일)
# ============================================================

class CameraThread(threading.Thread):
    '''
    실시간(LIVE) 스트림에서는 밀린 프레임을 계속 처리하면 지연이 쌓인다.
    항상 가장 최근 프레임만 유지하고 나머지는 버린다(드롭).
    '''

    def __init__(self, cap):
        super().__init__(daemon=True)
        self.cap = cap
        self.lock = threading.Lock()
        self.frame = None
        self.seq = 0
        self.dropped = 0
        self.running = True
        self.failed = False
        self.consumed = True

    def run(self):
        while self.running:
            ret, f = self.cap.read()
            if not ret:
                self.failed = True
                self.running = False
                break
            with self.lock:
                if self.frame is not None and not self.consumed:
                    self.dropped += 1
                self.frame = f
                self.seq += 1
                self.consumed = False

    def read_latest(self, last_seq):
        with self.lock:
            if self.frame is None or self.seq == last_seq:
                return None, last_seq
            self.consumed = True
            return self.frame, self.seq

    def stop(self):
        self.running = False
        self.join(timeout=2.0)

# ============================================================
# 5. 실시간 웹 미리보기 (MJPEG 스트림)
# ============================================================
# 보드에 모니터가 없고 SSH로 접속해서 돌리는 상황을 위한 것. 최신 프레임을 JPEG 로
# 인코딩해서 들고 있다가, 브라우저가 "/stream" 에 접속하면 multipart/x-mixed-replace
# 로 계속 흘려보낸다. 카메라/DMA 코드와는 완전히 분리되어 있어 이 부분이 실패해도
# 녹화(mp4/npy)에는 영향이 없다.

class LiveStream:
    '''가장 최근 프레임(JPEG로 인코딩된 bytes)을 여러 스레드가 안전하게 주고받기 위한 저장소.'''

    def __init__(self):
        self.condition = threading.Condition()
        self.jpg_bytes = None
        self.frame_id = 0

    def update(self, frame_bgr):
        ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return
        with self.condition:
            self.jpg_bytes = buf.tobytes()
            self.frame_id += 1
            self.condition.notify_all()

    def wait_for_next(self, last_id, timeout=5.0):
        with self.condition:
            if self.frame_id == last_id:
                self.condition.wait(timeout=timeout)
            return self.jpg_bytes, self.frame_id


live_stream = LiveStream()


class LocalPreview:
    '''
    cv2.imshow(X11) 는 프레임마다 네트워크 왕복이 필요해서 느릴 수 있다 (수십~수백 ms).
    메인 캡처+crop 루프에서 직접 부르면 그 시간만큼 루프 전체가 막혀서 카메라 프레임을
    못 따라간다 (드롭 급증의 직접적인 원인). 그래서 화면 표시는 전담 스레드 하나가 계속
    맡고, 메인 루프는 "종료 요청이 들어왔는지"만 아주 가벼운 플래그로 확인한다
    (메인 루프에서는 cv2 함수를 전혀 호출하지 않는다).

    창을 만드는 것(imshow)과 없애는 것(destroyAllWindows)을 반드시 같은 스레드에서
    처리해야 "다른 스레드에서 타이머를 건드렸다"는 Qt 경고 없이 안정적으로 동작하므로,
    이 스레드 안에서 생성부터 종료까지 전부 처리한다.
    '''

    def __init__(self, window_name="ROI Crop+Resize (live)"):
        self.window_name = window_name
        self.lock = threading.Lock()
        self.frame = None
        self.has_new = False
        self.running = True
        self.quit_requested = False   # 메인 루프는 이 플래그만 가볍게 확인하면 된다
        self.window_created = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def update(self, frame_bgr):
        '''SaveWorker 에서 호출. 락만 잡고 바로 반환 (non-blocking).'''
        with self.lock:
            self.frame = frame_bgr
            self.has_new = True

    def _run(self):
        while self.running:
            frame = None
            with self.lock:
                if self.has_new:
                    frame = self.frame
                    self.has_new = False

            if frame is not None:
                cv2.imshow(self.window_name, frame)
                self.window_created = True

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):   # 'q' 또는 ESC
                self.quit_requested = True

            if self.window_created:
                try:
                    # 사용자가 창의 X 버튼을 눌러서 닫은 경우 (waitKey 는 이걸 못 잡는다)
                    if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                        self.quit_requested = True
                except cv2.error:
                    pass   # 창이 아직 안 만들어졌거나 이미 닫힌 경우

            time.sleep(0.01)

        cv2.destroyAllWindows()   # 창을 만든 것과 같은 스레드에서 닫는다
        cv2.waitKey(1)

    def stop(self):
        self.running = False
        self.thread.join(timeout=2.0)


class MJPEGHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass   # 요청마다 콘솔에 로그가 찍히는 것을 막는다 (녹화 로그와 섞이지 않게)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = ("<html><head><title>ROI Crop+Resize Live</title></head>"
                    "<body style='margin:0;background:#111;'>"
                    "<img src='/stream' style='width:100%;height:auto;display:block;margin:auto;'>"
                    "</body></html>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            last_id = 0
            try:
                while True:
                    jpg, last_id = live_stream.wait_for_next(last_id)
                    if not jpg:
                        continue
                    self.wfile.write(b"--FRAME\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(("Content-Length: %d\r\n\r\n" % len(jpg)).encode("ascii"))
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass   # 브라우저 탭을 닫으면 정상적으로 여기로 빠진다
            return

        self.send_error(404)


def start_stream_server(port):
    '''
    MJPEG 서버를 백그라운드 스레드로 띄운다. 포트 충돌 등으로 실패해도 예외를 던지지 않고
    None 을 반환한다 (미리보기는 부가 기능이므로 실패해도 녹화 자체는 계속되어야 한다).
    '''
    try:
        httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), MJPEGHandler)
    except OSError as e:
        print("[WARN] 실시간 미리보기 서버를 열지 못했습니다 (포트 %d): %s" % (port, e))
        return None

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    ip = get_local_ip()
    print("========== 실시간 미리보기 ==========")
    print("브라우저에서 아래 주소를 열면 촬영 중인 화면을 볼 수 있습니다:")
    print("  http://%s:%d/" % (ip, port))
    print("  (보드와 같은 네트워크에 있는 PC/노트북에서 접속하세요)")
    return httpd

# ============================================================
# 6. 저장 워커 스레드 (resize + mp4 인코딩 + npy 기록을 메인 루프에서 분리)
# ============================================================

class SaveWorker(threading.Thread):
    '''
    PL crop 결과(480x480, BGR)를 큐로 받아서 이 스레드에서
      1) YOLO 입력 크기(640x640)로 resize
      2) crop+resize 최종 결과 mp4/npy 기록 (파일은 각각 1개씩만 생성)
      3) (SHOW_PREVIEW=True 이면) 실시간 웹 미리보기용 프레임 갱신
    을 처리한다. mp4 인코딩/resize 비용을 메인 캡처+crop 루프에서 떼어내
    실시간 FPS 가 떨어지지 않도록 하기 위함 (realtime_roi_v2.py 의 SaveWorker 설계와 동일).

    mp4 는 OpenCV VideoWriter 가 기대하는 BGR 그대로 저장하고,
    npy 는 다음 단계(YOLO 추론 등)에서 바로 쓸 수 있도록 RGB 로 변환해서 저장한다.
    '''

    def __init__(self, writer, npy_data, max_frames, live_stream=None, local_preview=None):
        super().__init__(daemon=True)
        self.writer = writer
        self.npy_data = npy_data
        self.max_frames = max_frames
        self.live_stream = live_stream
        self.local_preview = local_preview   # LocalPreview 인스턴스 또는 None

        self.work_q = queue.Queue(maxsize=QUEUE_DEPTH)
        self.free_q = queue.Queue()
        self.npy_index = 0
        self.write_ms = []
        self.error = None

        for _ in range(QUEUE_DEPTH + 2):
            self.free_q.put(np.empty(CROP_SHAPE, dtype=np.uint8))

    def get_buffer(self):
        return self.free_q.get()

    def submit(self, buf):
        self.work_q.put(buf)

    def run(self):
        while True:
            buf = self.work_q.get()
            if buf is None:
                break
            try:
                t0 = time.perf_counter()

                resized = resize_for_yolo(buf)

                if self.writer is not None:
                    self.writer.write(resized)
                if self.npy_data is not None and self.npy_index < self.max_frames:
                    self.npy_data[self.npy_index] = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

                if self.npy_index < self.max_frames:
                    self.npy_index += 1

                if self.live_stream is not None:
                    self.live_stream.update(resized)

                if self.local_preview is not None:
                    self.local_preview.update(resized)   # 락만 잡고 바로 반환 (non-blocking)

                self.write_ms.append((time.perf_counter() - t0) * 1e3)
            except Exception as e:
                self.error = e
            finally:
                self.free_q.put(buf)

    def stop(self):
        self.work_q.put(None)
        self.join(timeout=10.0)

# ============================================================
# 7. Overlay(비트스트림) 로드 + DMA/IP 핸들 확보
# ============================================================
print("========== Overlay 로드 ==========")

t_ov = time.perf_counter()
overlay = Overlay(BIT_PATH, download=True)
t_ov = (time.perf_counter() - t_ov) * 1000.0

if not overlay.is_loaded():
    raise RuntimeError("Overlay 로드에 실패했습니다.")

print("Overlay load : %.1f ms" % t_ov)

dma_in      = overlay.axi_dma_0
dma_out     = overlay.axi_dma_1
roi_crop_ip = overlay.roi_crop_top_0

print("HLS IP  :", roi_crop_ip)
print("DMA IN  max :", dma_in.sendchannel._max_size)
print("DMA OUT max :", dma_out.recvchannel._max_size)

if dma_in.sendchannel._max_size < INPUT_BYTES:
    raise RuntimeError("DMA 입력 버퍼 최대 크기가 한 프레임(%d bytes)보다 작습니다." % INPUT_BYTES)

if dma_out.recvchannel._max_size < CROP_BYTES:
    raise RuntimeError("DMA 출력 버퍼 최대 크기가 한 프레임(%d bytes)보다 작습니다." % CROP_BYTES)

# ============================================================
# 8. PL crop 함수 (HLS IP + DMA 왕복)
# ============================================================

def pl_crop(input_buffer, output_buffer):
    '''
    카메라 프레임(input_buffer, 640x480x3)을 HLS IP 로 보내
    output_buffer(480x480x3)에 crop 결과를 받는다. (realtime_roi_v2.py 의 pl_crop 과 동일)
    '''
    t0 = time.perf_counter()

    dma_out.recvchannel.transfer(output_buffer)   # 수신을 먼저 준비
    roi_crop_ip.write(0x00, 0x01)                 # ap_start
    dma_in.sendchannel.transfer(input_buffer)

    dma_in.sendchannel.wait()
    t1 = time.perf_counter()

    dma_out.recvchannel.wait()
    t2 = time.perf_counter()

    output_buffer.invalidate()
    t3 = time.perf_counter()

    return (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t0) * 1e3   # send, drain, total(ms)

# ============================================================
# 9. 실시간 미리보기 서버 시작
# ============================================================
# Overlay 다운로드/카메라 초기화가 진행되는 동안에도 이미 브라우저 탭을 열어둘 수 있도록
# 가능한 한 앞에서 띄운다. 녹화가 시작되기 전까지는 화면이 비어 있다가, calibration 단계부터
# 프레임이 채워진다.
stream_httpd = start_stream_server(STREAM_PORT) if SHOW_PREVIEW else None

# ============================================================
# 10. 카메라 열기  ***여기가 수정된 부분입니다***
# ============================================================
print("========== Camera Start ==========")

# ---- 중요 ----
# cv2.VideoCapture(index) 처럼 backend 를 지정하지 않으면, OpenCV 빌드/환경에 따라
# V4L2 가 아닌 다른 backend(GStreamer 등)가 자동으로 선택될 수 있다. 이 경우
# 아래에서 cv2.CAP_PROP_FOURCC 로 MJPG 를 요청해도 조용히 무시되고 계속 YUYV 로
# 열리는 경우가 있다 (버벅임/저프레임의 흔한 원인). CAP_V4L2 를 명시해서 이 문제를 없앤다.
cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)
if not cap.isOpened():
    raise RuntimeError(
        f"카메라(index={CAMERA_INDEX})를 열 수 없습니다. /dev/video{CAMERA_INDEX} 연결을 확인하세요."
    )

# FOURCC 는 해상도보다 먼저 설정해야 한다. YUYV 로 negotiate 되면
# 640x480 에서도 USB 대역폭 때문에 5~10 FPS 로 떨어지는 경우가 많다.
ok_fourcc = cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
ok_w      = cap.set(cv2.CAP_PROP_FRAME_WIDTH,  INPUT_SHAPE[1])
ok_h      = cap.set(cv2.CAP_PROP_FRAME_HEIGHT, INPUT_SHAPE[0])
ok_fps    = cap.set(cv2.CAP_PROP_FPS, CAMERA_TARGET_FPS)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not (ok_fourcc and ok_w and ok_h and ok_fps):
    print("[WARN] cap.set() 중 일부가 False 를 반환했습니다 "
          "(fourcc=%s, width=%s, height=%s, fps=%s). "
          "드라이버가 해당 설정을 지원하지 않을 수 있습니다."
          % (ok_fourcc, ok_w, ok_h, ok_fps))

act_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
act_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
act_fps = cap.get(cv2.CAP_PROP_FPS)
fcc = int(cap.get(cv2.CAP_PROP_FOURCC))
fcc_txt = "".join(chr((fcc >> (8 * i)) & 0xFF) for i in range(4))

print("Camera : %dx%d @ %.1f FOURCC=%s" % (act_w, act_h, act_fps, fcc_txt))

# ---- 실제로 MJPG 로 열렸는지 재확인 ----
# cap.set() 이 True 를 반환해도, 드라이버가 조용히 무시하고 다른 포맷으로 여는 경우가
# 있으므로 cap.get() 으로 실측값을 다시 확인해서 알려준다.
if fcc_txt.upper() != "MJPG":
    print("[WARN] 요청한 MJPG 가 아니라 %s 로 열렸습니다. "
          "끊김/저프레임의 원인일 가능성이 높습니다." % fcc_txt)
    print("       터미널에서 아래 명령으로 카메라가 실제 지원하는 포맷을 확인해보세요:")
    print("       v4l2-ctl -d /dev/video%d --list-formats-ext" % CAMERA_INDEX)

NEED_RESIZE_IN = (act_w, act_h) != (INPUT_SHAPE[1], INPUT_SHAPE[0])
if NEED_RESIZE_IN:
    print("[WARN] 요청 해상도와 실제 해상도가 달라 매 프레임 resize 가 추가로 발생합니다.")

# 자동노출 / 자동 화이트밸런스 고정 (필요할 때만; 기본은 꺼둠 - 색 이상 유발 가능)
if LOCK_CAMERA_AUTO_CONTROLS:
    lock_camera_auto_controls(CAMERA_INDEX)

# 카메라 워밍업 (첫 프레임들은 노출/화이트밸런스가 안정되지 않은 경우가 많음)
for _ in range(5):
    cap.read()

# ============================================================
# 11. 녹화용 FPS 실측 (calibration)
# ============================================================
# 카메라가 낼 수 있는 FPS 와, 카메라+PL crop+resize 를 실제로 감당할 수 있는 FPS 는 다를 수 있다.
# mp4 를 CAMERA_TARGET_FPS(예: 30)로 고정해서 저장하면, 실제 처리 속도가 더 느릴 때
# 프레임 사이 실제 경과 시간보다 빠르게 재생되어(사실상 프레임을 건너뛴 것처럼) 움직임이
# 뚝뚝 끊겨 보인다. 녹화를 시작하기 전에 실제 파이프라인과 동일한 작업(캡처+PL crop+resize)을
# 짧게 반복해서 실측 FPS 를 구하고, 그 값을 최종 mp4 FPS 로 사용한다.
print("========== FPS 실측(calibration) ==========")

RECORD_FPS = CAMERA_TARGET_FPS

if CALIBRATE_FPS:
    calib_in = allocate(shape=INPUT_SHAPE, dtype=np.uint8)
    calib_out = allocate(shape=CROP_SHAPE, dtype=np.uint8)

    n_ok = 0
    t_calib_start = time.perf_counter()

    while (n_ok < CALIBRATION_FRAMES
           and (time.perf_counter() - t_calib_start) < CALIBRATION_TIMEOUT_SEC):
        ret, frame = cap.read()
        if not ret:
            continue
        if NEED_RESIZE_IN:
            frame = cv2.resize(frame, (INPUT_SHAPE[1], INPUT_SHAPE[0]))

        np.copyto(calib_in, frame)
        calib_in.flush()
        pl_crop(calib_in, calib_out)
        calib_resized = resize_for_yolo(calib_out)   # 실제 저장 파이프라인과 동일한 작업량을 부여
        if SHOW_PREVIEW:
            live_stream.update(calib_resized)   # calibration 중에도 미리보기 화면이 채워지도록
        n_ok += 1

    t_calib = time.perf_counter() - t_calib_start
    calib_in.freebuffer()
    calib_out.freebuffer()

    if n_ok >= 5 and t_calib > 0:
        measured_fps = n_ok / t_calib
        RECORD_FPS = max(MIN_RECORD_FPS, min(CAMERA_TARGET_FPS, measured_fps))
        print("실측 처리 속도 : %.2f FPS (%d frame / %.2fs)" % (measured_fps, n_ok, t_calib))
    else:
        print("[WARN] 측정 프레임이 부족하여(%d개) 기본값(%.1f FPS)을 사용합니다."
              % (n_ok, RECORD_FPS))
else:
    print("CALIBRATE_FPS=False -> 설정값(%.1f FPS) 그대로 사용" % RECORD_FPS)

print("최종 녹화(mp4) FPS : %.2f" % RECORD_FPS)

# ============================================================
# 12. 출력 준비 (VideoWriter 1개 + npy memmap 1개)
# ============================================================
writer = None
npy_data = None

if SAVE_MP4:
    writer = cv2.VideoWriter(OUTPUT_MP4_PATH, cv2.VideoWriter_fourcc(*"mp4v"),
                              RECORD_FPS, (TARGET_SIZE, TARGET_SIZE))
    if not writer.isOpened():
        raise RuntimeError("VideoWriter 를 열 수 없습니다.")
    print("VIDEO : %s (%.2f FPS)" % (OUTPUT_MP4_PATH, RECORD_FPS))

if SAVE_NPY:
    npy_data = np.lib.format.open_memmap(OUTPUT_NPY_PATH, mode="w+", dtype=np.uint8,
                                          shape=(MAX_FRAMES,) + RESIZE_SHAPE)
    print("NPY   :", OUTPUT_NPY_PATH, "shape=", (MAX_FRAMES,) + RESIZE_SHAPE)

# ============================================================
# 13. 실시간 crop + resize 메인 루프
# ============================================================
input_buffer = None
output_buffer = None
saver = None
cam_thread = None
local_preview = None
gc_was_enabled = gc.isenabled()

processed = 0
rec_pre, rec_pl, rec_sys = [], [], []

print("\n========== REALTIME CROP+RESIZE START ==========")
print(f"자동 종료 조건 : {RUN_SECONDS}초 경과 또는 {MAX_FRAMES}프레임 도달")
print("즉시 종료하려면 Ctrl+C 를 누르세요.")

try:
    # 루프 중간에 GC 가 끼어들면 그 프레임만 처리 시간이 튀어 재생 시 끊김으로 보일 수 있다.
    # 루프가 끝나면 finally 에서 다시 켠다.
    gc.disable()

    input_buffer  = allocate(shape=INPUT_SHAPE, dtype=np.uint8)
    output_buffer = allocate(shape=CROP_SHAPE,  dtype=np.uint8)

    if SHOW_LOCAL_WINDOW:
        local_preview = LocalPreview()
        local_preview.start()

    saver = SaveWorker(writer, npy_data, MAX_FRAMES,
                        live_stream=live_stream if SHOW_PREVIEW else None,
                        local_preview=local_preview)
    saver.start()

    cam_thread = CameraThread(cap)
    cam_thread.start()

    last_seq = 0
    loop_prev = time.perf_counter()
    t_start_all = loop_prev

    while True:
        if saver.error is not None:
            raise saver.error

        loop_now = time.perf_counter()
        if loop_now - t_start_all >= RUN_SECONDS:
            print("\n[INFO] 설정된 실행 시간(%ds)에 도달하여 종료합니다." % RUN_SECONDS)
            break
        if processed >= MAX_FRAMES:
            print("\n[INFO] 설정된 최대 프레임 수(%d)에 도달하여 종료합니다." % MAX_FRAMES)
            break

        if not cam_thread.running and cam_thread.failed:
            print("[ERROR] 카메라 프레임을 읽지 못했습니다.")
            break

        # ---------- 로컬 미리보기 종료 요청 확인 ----------
        # 실제 imshow/waitKey 는 LocalPreview 전담 스레드에서 처리되므로, 메인 루프는
        # 플래그 하나만 확인한다 (cv2 함수를 여기서 직접 부르지 않음 -> 캡처 루프를 막지 않음).
        if local_preview is not None and local_preview.quit_requested:
            print("\n[INFO] 미리보기 창에서 종료가 요청되어 녹화를 마칩니다.")
            break

        frame, last_seq = cam_thread.read_latest(last_seq)
        if frame is None:
            time.sleep(0.001)
            continue

        if NEED_RESIZE_IN:
            frame = cv2.resize(frame, (INPUT_SHAPE[1], INPUT_SHAPE[0]))

        # ---------- PRE : 호스트 준비 ----------
        t0 = time.perf_counter()
        np.copyto(input_buffer, frame)
        input_buffer.flush()
        t_pre = (time.perf_counter() - t0) * 1e3

        # ---------- CROP (PL) ----------
        try:
            _, _, t_pl = pl_crop(input_buffer, output_buffer)
        except Exception as e:
            print("[ERROR] HLS crop 실패:", e)
            break

        if output_buffer.shape != CROP_SHAPE:
            print("[ERROR] crop 출력 shape 오류:", output_buffer.shape)
            break

        # ---------- 저장 큐로 전달 (resize + 웹 미리보기 갱신은 워커 스레드에서 수행) ----------
        # get_buffer()/submit() 은 SaveWorker 가 못 따라오면 그대로 여기서 대기(block)한다.
        # 이 대기 시간을 재서, "중간중간 끊김"이 실제로 여기서 발생하는지 눈으로 확인한다.
        t_gb0 = time.perf_counter()
        buf = saver.get_buffer()
        t_gb = (time.perf_counter() - t_gb0) * 1e3
        if t_gb > 50:
            print("[STALL] 빈 버퍼 대기 %.1f ms -> SaveWorker(저장/인코딩)가 카메라 속도를 "
                  "못 따라가고 있습니다. (SD카드 쓰기 지연 의심)" % t_gb)

        np.copyto(buf, output_buffer)

        t_sb0 = time.perf_counter()
        saver.submit(buf)
        t_sb = (time.perf_counter() - t_sb0) * 1e3
        if t_sb > 50:
            print("[STALL] 저장 큐(work_q) 대기 %.1f ms -> 큐가 가득 찼습니다." % t_sb)

        # ---------- 통계 ----------
        processed += 1
        now = time.perf_counter()
        sys_fps = 1.0 / max(now - loop_prev, 1e-9)
        loop_prev = now
        rec_pre.append(t_pre)
        rec_pl.append(t_pl)
        rec_sys.append(sys_fps)

        if processed % STATS_EVERY_N_FRAMES == 0:
            print("%5d frame | PRE %5.2f ms | PL %6.3f ms | SYS %5.1f FPS | drop %d | free_buf %d/%d"
                  % (processed, t_pre, t_pl, sys_fps, cam_thread.dropped,
                     saver.free_q.qsize(), QUEUE_DEPTH + 2))

except KeyboardInterrupt:
    print("\n[INFO] 사용자가 정지시켰습니다.")

finally:
    print("\n========== CLEANUP ==========")

    if gc_was_enabled:
        gc.enable()

    if cam_thread is not None:
        cam_thread.stop()
    if cap is not None:
        cap.release()

    if saver is not None:
        saver.stop()
        npy_written = saver.npy_index
        # saver 객체가 npy_data(memmap)/writer 를 계속 참조하고 있으면, 아래에서
        # 파일을 truncate 한 뒤 이 참조가 늦게 회수되면서 이미 잘려나간 mmap 영역을
        # 건드려 Bus error(SIGBUS)가 날 수 있다. truncate 전에 참조를 미리 끊는다.
        saver.npy_data = None
        saver.writer = None
    else:
        npy_written = 0

    if local_preview is not None:
        local_preview.stop()

    if writer is not None:
        writer.release()

    if input_buffer is not None:
        input_buffer.freebuffer()
    if output_buffer is not None:
        output_buffer.freebuffer()

    if npy_data is not None:
        try:
            npy_data.flush()
        except Exception:
            pass
        mm = getattr(npy_data, "_mmap", None)
        del npy_data
        if mm is not None:
            try:
                mm.close()   # 남은 참조와 무관하게 mmap 을 확실히 닫는다.
            except Exception:
                pass
        gc.collect()   # truncate 전에 위에서 끊은 참조들을 즉시 회수한다.

        if npy_written > 0:
            finalize_npy(OUTPUT_NPY_PATH, npy_written, RESIZE_SHAPE)
            print("NPY 저장 :", OUTPUT_NPY_PATH, "frames=", npy_written)
        elif os.path.exists(OUTPUT_NPY_PATH):
            os.remove(OUTPUT_NPY_PATH)
            print("NPY : 기록된 프레임 없음 -> 파일 삭제")

    if stream_httpd is not None:
        stream_httpd.shutdown()
        stream_httpd.server_close()

    gc.collect()
    print("정리 완료. 저장된 프레임 수 :", npy_written)

# ============================================================
# 14. 결과 요약
# ============================================================
print("========== RESULT ==========")
print("총 처리 프레임 수 :", processed)

def summarize(name, arr, unit="ms"):
    a = np.asarray(arr, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        print("  %-16s (데이터 없음)" % name)
        return
    print("  %-16s mean %8.4f  med %8.4f  p95 %8.4f  max %8.4f %s"
          % (name, a.mean(), np.median(a), np.percentile(a, 95), a.max(), unit))

if processed > 0:
    summarize("PRE(host)",  rec_pre)
    summarize("PL crop",    rec_pl)
    summarize("SYSTEM FPS", rec_sys, unit="FPS")
    if saver is not None and saver.write_ms:
        summarize("SAVE(resize+mp4+npy)", saver.write_ms)

    achieved_fps = float(np.mean(rec_sys)) if rec_sys else float("nan")
    print("\n녹화 mp4 FPS : %.2f  (실측 처리 FPS 평균 : %.2f)" % (RECORD_FPS, achieved_fps))
    if achieved_fps and abs(achieved_fps - RECORD_FPS) / RECORD_FPS > 0.15:
        print("[INFO] 평균 처리 FPS 가 녹화 FPS 와 15% 이상 차이납니다. 이번 실행의 카메라/조명/부하가"
              " calibration 때와 달랐을 수 있습니다. 다시 실행해서 재보정하면 개선될 수 있습니다.")
else:
    print("처리된 프레임이 없습니다. 카메라/오버레이 설정을 확인하세요.")

print()
for label, path in [("mp4", OUTPUT_MP4_PATH), ("npy", OUTPUT_NPY_PATH)]:
    if os.path.isfile(path):
        size_mb = os.path.getsize(path) / 1e6
        print("%-4s : %s (%.2f MB)" % (label, path, size_mb))

# ============================================================
# 15. 저장 결과 미리보기 (정상 동작 확인 + 끊김 여부 눈으로 확인용)
# ============================================================
# 터미널 실행이라 화면에 띄울 수 없으므로, 처음/중간/마지막 프레임을 나란히 붙인
# JPG 파일 하나로 저장한다. 촬영 중간에 프레임이 크게 밀리거나 멈춰있던 구간이
# 없는지 이 파일을 열어서 눈으로 대략 확인할 수 있다.
if os.path.isfile(OUTPUT_NPY_PATH):
    check = np.load(OUTPUT_NPY_PATH, mmap_mode="r")
    print("NPY shape :", check.shape, check.dtype)

    n = check.shape[0]
    if n > 0:
        idxs = sorted(set([0, n // 2, n - 1]))
        # npy 는 RGB 로 저장되어 있으므로 jpg 로 쓰기 전에 BGR 로 되돌린다.
        frames_bgr = [cv2.cvtColor(np.asarray(check[idx]), cv2.COLOR_RGB2BGR) for idx in idxs]
        summary_path = os.path.join(OUTPUT_DIR, "cropresize_640_summary.jpg")
        cv2.imwrite(summary_path, np.hstack(frames_bgr))
        print("요약 이미지 (frame %s) 저장 : %s" % (idxs, summary_path))
    else:
        print("저장된 프레임이 없습니다.")
else:
    print("npy 저장이 꺼져 있거나(SAVE_NPY=False) 저장된 프레임이 없습니다.")
