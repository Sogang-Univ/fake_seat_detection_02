import os
import sys
import time
import glob
import numpy as np
from pynq_dpu import DpuOverlay
from yolo_utils import decode_yolo_output, nms, build_results, DEFAULT_ANCHORS, DEFAULT_STRIDES

# ==========================================
# [시스템 환경 설정 정보]
# ==========================================
XMODEL_PATH = "yolov5n.xmodel"
BIT_PATH = "dpu.bit"
CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45
CLASS_NAMES = ['person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket', 'bottle',
'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch', 'potted plant', 'bed',
'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone', 'microwave', 'oven',
'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush']
# 가짜 점유 탐지에서 모니터링할 핵심 타겟 오브젝트
INTERESTED_CLASSES = ['person', 'backpack', 'handbag', 'suitcase', 'bottle', 'cup', 'chair', 'laptop', 'cell phone', 'book']

class DPUModel:
    def __init__(self, bit_path=BIT_PATH, model_path=XMODEL_PATH):
        print("⚙️ [1/3] FPGA 비트스트림 주입 및 DPU 가속 드라이버 부팅...")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"⚠️ '{model_path}' 파일이 보드 내에 없습니다. 경로를 확인하세요.")
            
        self.overlay = DpuOverlay(bit_path)
        self.overlay.load_model(model_path)
        
        # 💡 [subgraph invalid 해결책]: 드라이버 단에서 자동 정렬된 러너 인스턴스를 즉시 바인딩
        self.runner = self.overlay.runner
        print("🏆 하드웨어 드라이버 수준 가속 러너 결착 완료!")
        
        # 출력 헤드의 차원 및 역양자화용 fix_point 메타데이터 자동 추출
        self.out_meta = []
        for t in self.runner.get_output_tensors():
            self.out_meta.append({
                "dims": tuple(int(x) for x in t.dims),
                "fix": int(t.get_attr("fix_point")) if t.has_attr("fix_point") else 0
            })

        print("가속기 내장 텐서 정밀 조회")
        in_t = self.runner.get_input_tensors()[0]
        out_t = self.runner.get_output_tensors()[0]
        print(f"  L [INPUT] 이름: {in_t.name}, Shape: {in_t.dims}, fix_point 유무: {in_t.has_attr('fix_point')}")
        if in_t.has_attr('fix_point'): print(f"  L 실제 인풋 fix_point 값: {in_t.get_attr('fix_point')}")
        print(f"   ↳ [OUTPUT 0] 이름: {out_t.name}, Shape: {out_t.dims}, fix_point 존재유무: {out_t.has_attr('fix_point')}")
        if out_t.has_attr('fix_point'): print(f"      ↳ 실제 아웃풋 fix_point 값: {out_t.get_attr('fix_point')}")
            
    def predict(self, input_npy: np.ndarray):
        """앞 단 팀원에게 받은 [Batch=1, H=640, W=640, Ch=3] INT8 데이터를 가속기에 태우는 함수"""
        # 4차원 배치 형태(1, 640, 640, 3)가 아니라면 차원 확장 안전장치
        if input_npy.ndim == 3:
            input_npy = np.expand_dims(input_npy, axis=0)
        
        input_data = input_npy
        # 모델 출력 사양(80x80, 40x40, 20x20 헤드 구조)에 맞춰 출력 버퍼 동적 생성
        output_buffers = [np.empty(m["dims"], dtype=np.int8, order="C") for m in self.out_meta]
        
        print(f"   [POINTER CHECK] input_data 메모리 주소: {input_data.__array_interface__['data'][0]}, 연속성 플래그: {input_data.flags['C_CONTIGUOUS']}")
        for b_idx, buf in enumerate(output_buffers):
            print(f"   [POINTER CHECK] output_buffers[{b_idx}] 할당 주소: {buf.__array_interface__['data'][0]}")

        # 비동기 하드웨어 연산 스트림 개시 및 프로세스 대기
        # start_time = time.time()
        job_id = self.runner.execute_async([input_npy], output_buffers)
        self.runner.wait(job_id)
        print(f"   ⚙️ [하드웨어 직출력 검증] output_buffers 배열 개수: {len(output_buffers)}")
        for b_idx, buf in enumerate(output_buffers):
            print(f"      ↳ 버퍼[{b_idx}] 실제 타입: {buf.dtype}, 최대: {np.max(buf)}, 최소: {np.min(buf)}")
        # print(f"⚡ [DPU pure compute]: {(time.time() - start_time)*1000:.2f} ms")
        
        # 💡 [역양자화 수리 완료]: int8 정수 배열을 float32 확률 스케일로 정교하게 복원
        dequantized_outputs = []
        for output_data, meta in zip(output_buffers, self.out_meta):
            fp = meta["fix"]
            float_feat = output_data.astype(np.float32) / (2 ** fp)
            dequantized_outputs.append(float_feat)
            
        return dequantized_outputs

def main():
    # 파이프라인 초기화 및 DPU 예열
    try:
        model = DPUModel()
    except Exception as e:
        print(f"❌ 가속 시스템 초기화 단계에서 치명적 에러 발생: {e}")
        return

    # 앞 사람이 차곡차곡 쌓아줄 수신 폴더 스캔
    src_dir = "./src"
    npy_list = sorted(glob.glob(os.path.join(src_dir, "*.npy")))
    
    if not npy_list:
        print(f"⚠️ '{src_dir}' 폴더 내에 처리할 데이터(npy)가 존재하지 않습니다.")
        return
        
    print(f"\n🚀 총 {len(npy_list)}개의 프레임 데이터 연속 탐지 가속 파이프라인 가동...")
    
    for idx, npy_path in enumerate(npy_list):
        print(f"\n📂 [{idx+1}/{len(npy_list)}] 처리 중: {os.path.basename(npy_path)}")
        
        # 앞 사람이 던져준 정제 완료된 npy 데이터 로드 (NHWC, INT8 상태)
        raw_data = np.load(npy_path)
        
        print(f"\n [HARDWARE ALIVE TEST] 가속기 하드웨어 실시간 연산 반응 검증")
        if idx == 0:
            raw_data = np.zeros_like(raw_data) # 1번 프레임: 검은 스크린
        elif idx == 1:
            raw_data = np.full_like(raw_data, 127) # 2번 프레임: 흰 스크린

        img_float = raw_data.astype(np.float32) / 255.0 # 정규화
        in_fix = 6  # input_fixpoint
        input_data = np.ascontiguousarray(np.clip(np.round(img_float * (2 ** in_fix)), -128, 127).astype(np.int8)) # v5 fix spec

        # 1단계: DPU 가속 추론 및 역양자화 통과
        raw_outputs = model.predict(input_data)
        
        print(f"\n --- [{idx+1}번 프레임] 데이터 흐름 내부 정밀 검증 시작 ---")
        print(f"1. [가속기 출력 검증] raw_outputs 헤드 개수: {len(raw_outputs)}")
        for h_idx, out in enumerate(raw_outputs):
            print(f"   L 헤드[{h_idx}] 실제 데이터 크기(size): {out.size}, 데이터 타입: {out.dtype}")
            print(f"   L 헤드[{h_idx}] 값 -> 최대: {np.max(out):.4f}, 최소: {np.min(out):.4f}, 평균: {np.mean(out):.4f}")

        # 2단계: YOLOv5 전용 출력 헤드 격자 디코딩 (yolo_utils 내장 함수 호출)
        # 80x80, 40x40, 20x20 결과물들이 1개의 일렬 텐서로 모여 boxes, scores, class_ids로 쪼개짐
        # 💡 이미지 속 상단 [RAW CHANNELS MONITORING] 단락 4줄을 이 독립 스캔 코드로 교체합니다.
        print(f"\n[TOTAL CHANNELS SCAN] 255개 채널 내 진짜 확률 성분 안전 추적")
        # .copy()를 사용하여 가속기 원본 버퍼 메모리를 완벽하게 보호하고 독립된 복사본으로 스캔합니다.
        raw_scan = raw_outputs[0].copy().reshape(1, 80, 80, 255)

        # 1. 85개씩 똑바르게 분리되어 순서대로 박혔을 때의 확률 (후보 1)
        print(f"   L [후보 1 (85분리)] 앵커0 확률: {np.max(raw_scan[..., 4]):.4f}, 앵커1: {np.max(raw_scan[..., 89]):.4f}, 앵커2: {np.max(raw_scan[..., 174]):.4f}")

        # 2. 앞쪽에 5개 좌표/확률 정보가 한꺼번에 몰려있을 때의 확률 (후보 2)
        print(f"   L [후보 2 (앞단conf)] 앵커0 확률: {np.max(raw_scan[..., 4]):.4f}, 앵커1: {np.max(raw_scan[..., 5]):.4f}, 앵커2: {np.max(raw_scan[..., 6]):.4f}")

        # 3. 맨 뒷구역에 5개 좌표/확률 정보가 한꺼번에 몰려있을 때의 확률 (후보 3)
        print(f"   L [후보 3 (뒷단conf)] 앵커0 확률: {np.max(raw_scan[..., 251]):.4f}, 앵커1: {np.max(raw_scan[..., 252]):.4f}, 앵커2: {np.max(raw_scan[..., 253]):.4f}")

        print(f"\n [HARDWARE SHAPE DIAGNOSIS] DPU가 뱉은 헤드별 진짜 물리 차원 분석")
        for h_idx, buf in enumerate(model.out_meta):
            INPUT_RESOLUTION = 640
            current_stride = [8, 16, 32][h_idx]
            current_grid = INPUT_RESOLUTION // current_stride
            real_no = buf["dims"][-1] if buf["dims"][-1] != current_grid else buf["dims"][1]
            print(f"  L헤드[{h_idx}] 격자 크기: {current_grid}x{current_grid}, 진짜 1개 상자당 채널수(no): {real_no}개 (원래 예상: 85)")

        boxes, scores, class_ids = decode_yolo_output(raw_outputs, DEFAULT_ANCHORS, DEFAULT_STRIDES)
        
        print(f"2. [격자 디코딩 직후 검증] 총 후보 개수: {boxes.shape[0]}개 생성")
        if boxes.shape[0] > 0:
            print(f"  L 디코딩된 score 범위 -> 최대: {np.max(scores):.4f}, 최소: {np.min(scores):.4f}")
            print(f"  L 디코딩된 boxes 좌표 샘플 (앞 5개):\n{boxes[:5]}")
            print(f"  L 디코딩된 scores 점수 샘플 (앞 5개): {scores[:5]}")

        # 3단계: 임계값(Confidence) 1차 컷오프 필터링
        conf_mask = scores > CONF_THRESHOLD
        print(f"3. [임계값 필터링 검증] CONF_THRESHOLD ({CONF_THRESHOLD}) 문턱 통과 개수: {np.sum(conf_mask)}개")

        boxes = boxes[conf_mask]
        scores = scores[conf_mask]
        class_ids = class_ids[conf_mask]
        
        if len(boxes) == 0:
            print("📭 해당 프레임에 탐지된 객체가 아무도 없습니다.")
            continue
            
        # 4단계: 질문자님 파트의 마감 임무인 NMS(비최대 억제) 실행
        keep_indices = nms(boxes, scores, IOU_THRESHOLD)
        
        # 5단계: 생존한 박스 정보들만 축적하여 정형 구조화
        final_boxes = boxes[keep_indices]
        final_scores = scores[keep_indices]
        final_classes = class_ids[keep_indices]
        
        # 앞 사람의 크롭 스케일(640/480)에 대입하여 원래 좌표계로 매핑 복원
        CROP_SIZE, INPUT_SIZE = 480, 640
        current_scale = INPUT_SIZE / CROP_SIZE
        
        results = build_results(
            final_boxes, final_scores, final_classes,
            CLASS_NAMES, CONF_THRESHOLD,
            letterbox_scale=current_scale, letterbox_pad=(0, 0)
        )
        
        # 6단계: 자리 가짜 점유 판별에 필요한 관심 객체만 필터링하여 마감 구조화
        # ➡️ 뒷 단 팀원에게 고스란히 이 배열 형식을 토스해주면 질문자님의 임무는 퍼펙트하게 끝납니다.
        final_serialized_output = [r for r in results if r['class'] in INTERESTED_CLASSES]
        
        print(f"🎯 탐지 마감 완료 (생존 객체: {len(final_serialized_output)}개)")
        for item in final_serialized_output:
            print(f"   ↳ {item}")
            
    print("\n🏁 모든 npy 데이터 스트림의 하드웨어 가속 추론 및 NMS 후처리가 마감되었습니다.")

if __name__ == "__main__":
    main()

