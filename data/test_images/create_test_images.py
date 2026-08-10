import os
import time
import cv2
import numpy as np

print("=== 3단계 밝기 사진 촬영 & 개별 NPY 저장 프로그램 (640x640) ===")

# ============================================================
# 0. 저장할 폴더 및 해상도 설정
# ============================================================
SAVE_DIR = "test_image"
os.makedirs(SAVE_DIR, exist_ok=True)
print(f"\n[준비] '{SAVE_DIR}' 폴더에 파일들이 각각 따로 저장됩니다.")

# 수정된 부분: 최종 NPY 배열의 크기를 640x640으로 확정합니다.
TARGET_SIZE = 640
NPY_SHAPE = (TARGET_SIZE, TARGET_SIZE, 3) 
FRAME_COUNT = 1 

# 안전한 NPY 저장 함수
def finalize_npy(temp_path, final_path, shape_per_frame, count):
    if count > 0:
        temp_data = np.load(temp_path, mmap_mode="r")
        final_data = np.lib.format.open_memmap(
            final_path,
            mode="w+",
            dtype=np.uint8,
            shape=(count,) + shape_per_frame
        )
        final_data[:] = temp_data[:count]
        final_data.flush()

        del final_data
        del temp_data

    if os.path.exists(temp_path):
        os.remove(temp_path)

# ============================================================
# 1. 카메라 촬영 준비
# ============================================================
print("\n카메라를 수동 모드로 변경합니다...")
os.system("v4l2-ctl -d /dev/video0 -c auto_exposure=1")
time.sleep(1)

# ============================================================
# 2. [1/3] 어두운 버전 (Dark) 개별 처리
# ============================================================
print("\n[1/3] 어두운 사진을 촬영하고 640x640 크기로 npy에 저장합니다...")
path_dark_jpg = os.path.join(SAVE_DIR, "1_dark.jpg")
path_dark_tmp = os.path.join(SAVE_DIR, "1_dark.tmp.npy")
path_dark_npy = os.path.join(SAVE_DIR, "1_dark.npy")

npy_temp_dark = np.lib.format.open_memmap(path_dark_tmp, mode="w+", dtype=np.uint8, shape=(FRAME_COUNT,) + NPY_SHAPE)

os.system("v4l2-ctl -d /dev/video0 -c exposure_time_absolute=30")
os.system("v4l2-ctl -d /dev/video0 -c brightness=30")
time.sleep(1)
# 카메라는 기본 비율(640x480)로 촬영합니다.
os.system(f"fswebcam -d /dev/video0 -r 640x640 --no-banner {path_dark_jpg}")

# 수정된 부분: 파이썬이 이미지를 640x640 정사각형으로 강제 변환(Resize)합니다.
img_dark = cv2.imread(path_dark_jpg)
img_dark_resized = cv2.resize(img_dark, (TARGET_SIZE, TARGET_SIZE), interpolation=cv2.INTER_LINEAR)
npy_temp_dark[0] = cv2.cvtColor(img_dark_resized, cv2.COLOR_BGR2RGB) 

npy_temp_dark.flush()
del npy_temp_dark
finalize_npy(path_dark_tmp, path_dark_npy, NPY_SHAPE, FRAME_COUNT)


# ============================================================
# 3. [2/3] 중간 버전 (Medium) 개별 처리
# ============================================================
print("\n[2/3] 중간 밝기 사진을 촬영하고 640x640 크기로 npy에 저장합니다...")
path_medium_jpg = os.path.join(SAVE_DIR, "2_medium.jpg")
path_medium_tmp = os.path.join(SAVE_DIR, "2_medium.tmp.npy")
path_medium_npy = os.path.join(SAVE_DIR, "2_medium.npy")

npy_temp_medium = np.lib.format.open_memmap(path_medium_tmp, mode="w+", dtype=np.uint8, shape=(FRAME_COUNT,) + NPY_SHAPE)

os.system("v4l2-ctl -d /dev/video0 -c exposure_time_absolute=156")
os.system("v4l2-ctl -d /dev/video0 -c brightness=128")
time.sleep(1)
os.system(f"fswebcam -d /dev/video0 -r 640x640 --no-banner {path_medium_jpg}")

# 640x640으로 리사이즈
img_medium = cv2.imread(path_medium_jpg)
img_medium_resized = cv2.resize(img_medium, (TARGET_SIZE, TARGET_SIZE), interpolation=cv2.INTER_LINEAR)
npy_temp_medium[0] = cv2.cvtColor(img_medium_resized, cv2.COLOR_BGR2RGB)

npy_temp_medium.flush()
del npy_temp_medium
finalize_npy(path_medium_tmp, path_medium_npy, NPY_SHAPE, FRAME_COUNT)


# ============================================================
# 4. [3/3] 밝은 버전 (Bright) 개별 처리
# ============================================================
print("\n[3/3] 밝은 사진을 촬영하고 640x640 크기로 npy에 저장합니다...")
path_bright_jpg = os.path.join(SAVE_DIR, "3_bright.jpg")
path_bright_tmp = os.path.join(SAVE_DIR, "3_bright.tmp.npy")
path_bright_npy = os.path.join(SAVE_DIR, "3_bright.npy")

npy_temp_bright = np.lib.format.open_memmap(path_bright_tmp, mode="w+", dtype=np.uint8, shape=(FRAME_COUNT,) + NPY_SHAPE)

os.system("v4l2-ctl -d /dev/video0 -c exposure_time_absolute=450")
os.system("v4l2-ctl -d /dev/video0 -c brightness=200")
time.sleep(1)
os.system(f"fswebcam -d /dev/video0 -r 640x640 --no-banner {path_bright_jpg}")

# 640x640으로 리사이즈
img_bright = cv2.imread(path_bright_jpg)
img_bright_resized = cv2.resize(img_bright, (TARGET_SIZE, TARGET_SIZE), interpolation=cv2.INTER_LINEAR)
npy_temp_bright[0] = cv2.cvtColor(img_bright_resized, cv2.COLOR_BGR2RGB)

npy_temp_bright.flush()
del npy_temp_bright
finalize_npy(path_bright_tmp, path_bright_npy, NPY_SHAPE, FRAME_COUNT)

print("\n=== 프로그램 종료 ===")
print(f"'{SAVE_DIR}' 폴더 안에 jpg 파일 3장과 완벽한 640x640 크기의 npy 파일 3장이 저장되었습니다!")
