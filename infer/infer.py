import numpy as np
import cv2
import time
import signal
from pynq_dpu import DpuOverlay
from yolo_utils import decode_yolo_output, nms, build_results, DEFAULT_ANCHORS, DEFAULT_STRIDES

# 협의 필요한 사항
CLASS_NAMES = ['person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket', 'bottle',
'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch', 'potted plant', 'bed',
'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone', 'microwave', 'oven',
'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush']
CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45
INPUT_SIZE = 640
XMODEL_PATH = "yolov5n.xmodel"
TEST_IMAGE = "images/sample.jpg"

def letterbox(img, new_size = 640, color = (114, 114, 114)):
    h, w = img.shape[:2]
    scale = min(new_size / h, new_size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(img, (nw, nh))
    pad_x = (new_size - nw) / 2
    pad_y = (new_size - nh) / 2 
    top, bottom = int(round(pad_y - 0.1)), int(round(pad_y + 0.1))
    left, right = int(round(pad_x - 0.1)), int(round(pad_x + 0.1))
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    
    return padded, scale, (left, top)
  
def quantize_input(img_uint8, fix_point = None):
    img_float = img_uint8.astype(np.float32) / 255.0
    if fix_point is None:
    	print(" fix_point 미확정 - 임시 스케일(2**0) 사용, 실제 값 아님 주의")
    	scale = 1
    else:
    	scale = 2 ** fix_point
    
    return np.round(img_float * scale).astype(np.int8)
    
def run_on_board(img_letterboxed, overlay):
    import vart
    import xir
    
    # overlay 객체 내부를 뒤져서 xir 그래프 속성을 가진 진짜 DPU 칩셋 주소를 강제로 찾아냅니다.
    dpu_target = None
    if hasattr(overlay, 'subgraph'): dpu_target = overlay.subgraph
    elif hasattr(overlay, 'subgraphs'): dpu_target = overlay.subgraphs
    
    # 만약 리스트나 딕셔너리 형태로 묶여있다면 0번째 알맹이만 쏙 빼내기
    if isinstance(dpu_target, list) or isinstance(dpu_target, tuple): dpu_target = dpu_target[0]
    elif isinstance(dpu_target, dict): dpu_target = list(dpu_target.values())[0]

    print("Runner 생성 시작")
    runner = vart.Runner.create_runner(dpu_target, "run")
    print("Runner 생성 완료")
    
    input_tensors = runner.get_input_tensors()
    output_tensors = runner.get_output_tensors()
    
    fix_point = None
    if input_tensors[0].has_attr("fix_point"):
    	fix_point = input_tensors[0].get_attr("fix_point")
    # input_data = quantize_input(img_letterboxed, fix_point)
    # input_data = np.expand_dims(input_data, axis = 0) << letterbox, 전처리 한다면 필요없는 구간 
    #NCHW 상정하고 있는데, NHWC로 제대로 받으면 삭제해야.
    
    input_buffers = [input_data]
    output_buffers = [np.empty(t.dims, dtype = np.int8, order = "C") for t in output_tensors]
    
    output_fix_points = []
    for t in output_tensors:
        fp = t.get_attr("fix_point") if t.has_attr("fix_point") else 0
        output_fix_points.append(fp)
    
    print(f"입력 shape: {input_data.shape}, 출력 헤드 개수: {len(output_buffers)}")
    for i, t in enumerate(output_tensors):
    	print(f" 출력[{i}] shape: {t.dims}, fix_point: {output_fix_points[i]}")
    	
    start = time.time()
    job_id = runner.execute_async(input_buffers, output_buffers)
    runner.wait(job_id)
    print(f"DPU 추론 시간: {(time.time()-start)*1000:.2f} ms")
    
    del runner
    return output_buffers, output_fix_points
    
def run_dummy():
    print("DPU 미가용 환경 - 더미 텐서로 로직만 검증")
    nc = len(CLASS_NAMES)
    return [
    	np.random.randn(1, 3, 80, 80, 5 + nc).astype(np.float32) * 0.1,
    	np.random.randn(1, 3, 40, 40, 5 + nc).astype(np.float32) * 0.1,
    	np.random.randn(1, 3, 20, 20, 5 + nc).astype(np.float32) * 0.1,
    ]
    
def dequantize_output(raw_int8, fix_point):
    return raw_int8.astype(np.float32) / (2 ** fix_point)
    
def main():
   # 함수 시작하자마자 하드웨어 회로부터 먼저 로드
    print("FPGA 보드에 DPU 하드웨어 회로 주입 중...")
    try:
        overlay = DpuOverlay("dpu.bit")
        # 💡 [필수 추가]: 오버레이가 내부 서브그래프(overlay.subgraphs)를 자동으로 잡도록 컴파일된 모델을 등록.
        overlay.load_model(XMODEL_PATH) 
        print("DPU 하드웨어 및 가속 모델 로드 완료!")
    except Exception as e:
        print(f"DPU 하드웨어 로드 실패: {e}")
        overlay = None # 실패 시 에러 방지용 처리, 실패해도 일단 넘어가서 try-except로 더미 돌리니까...

    #img = cv2.imread(TEST_IMAGE)
    #if img is None:
    #    print(f" {TEST_IMAGE} 없음 - 검은 더미 이미지로 대체")
    #    img = np.zeros((480, 480, 3), dtype = np.uint8)
    	
    #padded, scale, pad = letterbox(img, INPUT_SIZE)
    #print(f"letterbox 완료: scale = {scale:.3f}, pad = {pad}")
    
    import glob
    npy_list = sorted(glob.glob("./src/*.npy")) #오름차순으로 긁어오기

    if not npy_list:
        print("Error: ./src/ 폴더 안에 .npy 파일이 없습니다!")
        return

    print(f"총 {len(npy_list)}개의 전처리 완료 NumPy 데이터 연속 가속 추론 시작...")

    for i, npy_path in enumerate(npy_list):
        print(f"\n [{i+1}/{len(npy_list)}] DPU 가속 및 후처리 디코딩 작동: {npy_path}")
        input_data = np.load(npy_path)

        CROP_SIZE = 480
        INPUT_SIZE = 640

        scale = INPUT_SIZE / CROP_SIZE
        pad = (0, 0)
    
        try:
            raw_outputs, output_fix_points = run_on_board(input_data, overlay) #원래 padded
        except Exception as e:
            print(f"보드 추론 실패/불가 ({type(e).__name__}): {e}")
            raw_outputs = run_dummy()
            output_fix_points = [0] * len(raw_outputs)
    	
        raw_outputs = [dequantize_output(o, fp) for o, fp in zip(raw_outputs, output_fix_points)]
        boxes, scores, class_ids = decode_yolo_output(raw_outputs, DEFAULT_ANCHORS, DEFAULT_STRIDES)
        print(f"격자 디코딩 완료: {boxes.shape[0]}개 후보 생성")
    
        conf_mask = scores > CONF_THRESHOLD
        boxes, scores, class_ids = boxes[conf_mask], scores[conf_mask], class_ids[conf_mask]

        keep_idx = nms(boxes, scores, IOU_THRESHOLD)
        print(f"NMS 완료: {len(keep_idx)}개 생존")
    
        results = build_results(
            boxes[keep_idx], scores[keep_idx], class_ids[keep_idx],
            CLASS_NAMES, CONF_THRESHOLD,
            letterbox_scale = scale, letterbox_pad = pad
        )
    
        interested = ['person', 'backpack', 'handbag', 'suitcase', 'bottle', 'cup', 'chair', 'laptop', 'cellphone', 'book']
        final_results = [r for r in results if r['class'] in interested]
    
        print(f"\n최종 결과 ({len(final_results)}개):")
        for r in final_results:
            print(" ", r)
    
    print("\n 모든 .npy 파일의 연속 가속 추론이 완료되었습니다") 	
    return final_results
    
if __name__ == "__main__":
    main()
