import numpy as np
import cv2
import time
from yolo_utils import decode_yolo_output, nms, build_results, DEFAULT_ANCHORS, DEFAULT_STRIDES

# 협의 필요한 사항
CLASS_NAMES = ['person', 'backpack', 'handbag', 'bottle', 'cup', 'chair', 'laptop', 'cell phone', 'book', 'clothes'] #TODO: 실제 클래스 리스트로 교체할 것
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
    padded = cv2.copyMakerBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    
    return padded, scale, (left, top)
  
def quantize_input(img_uint8, fix_point = None):
    img_float = img_uint8.astype(np.float32) / 255.0
    if fix_point is None:
    	print(" fix_point 미확정 - 임시 스케일(2**0) 사용, 실제 값 아님 주의")
    	scale = 1
    else:
    	scale = 2 ** fix_point
    
    return np.round(img_float * scale).astype(np.int8)
    
def run_on_board(img_letterboxed):
    import vart
    import xir
    
    graph = xir.Graph.deserialize(XMODEL_PATH)
    subgraphs = [s for s in graph.get_root_subgraph().get_children() if s.has_attr("device") and s.get_attr("device").upper() == "DPU"]
    runner = vart.Runner.create_runner(subgraphs[0], "run")
    
    input_tensors = runner.get_input_tensors()
    output_tensors = runner.get_output_tensors()
    
    fix_point = None
    if input_tensor[0].has_attr("fix_point"):
    	fix_point = input_tensors[0].get_attr("fix_point")
    input_data = quantize_input(img_letterboxed, fix_point)
    input_data = np.expand_dims(input_data, axis = 0)
    
    input_buffers = [input_data]
    output_buffers = [np.empty(t.dims, dtype = np.int8, order = "C") for t in output_tensors]
    
    print(f"입력 shape: {input_data.shape}, 출력 헤드 개수: {len(output_buffers)}")
    for i, t in enumerate(output_tensors):
    	print(f" 출력[{i}] shape: {t_dims}")
    	
    start = time.time()
    job_id = runner.execute_async(input_buffers, output_buffers)
    runner.wait(job_id)
    print(f"DPU 추론 시간: {(time.time()-start)*1000:.2f} ms")
    
    del runner
    return output_buffers
    
def run_dummy():
    print("DPU 미가용 환경 - 더미 텐서로 로직만 검증")
    nc = len(CLASS_NAMES)
    return [
    	np.random.randn(1, 3, 80, 80, 5 + nc).astype(np.float32) * 0.1,
    	np.random.randn(1, 3, 40, 40, 5 + nc).astype(np.float32) * 0.1,
    	np.random.randn(1, 3, 20, 20, 5 + nc).astype(np.float32) * 0.1,
    ]
    
def main():
    img = cv2.imread(TEST_IMAGE)
    if img is None:
    	print(f" {TEST_IMAGE} 없음 - 검은 더미 이미지로 대체")
    	img = np.zeros((480, 480, 3), dtype = np.uint8)
    	
    padded, scale, pad = letterbox(img, INPUT_SIZE)
    print(f"letterbox 완료: scale = {scale:.3f}, pad = {pad}")
    
    try:
    	raw_outputs = run_on_board(padded)
    except Exception as e:
    	print(f"보드 추론 실패/불가 ({type(e).__name__}): {e}")
    	raw_outputs = run_dummy()
    	
    raw_outputs = [o.astype(np.float32) for o in raw_outputs]
    
    boxes, scores, class_ids = decode_output(raw_outputs, DEFAULT_ANCHORS, DEFAULT_STRIDES)
    print(f"디코딩 완료: {boxes.shape[0]}개 후보")
    
    keep_idx = nms(boxes, scores, IOU_THRESHOLD)
    print(f"NMS 완료: {len(keep_idx)}개 생존")
    
    results = build_results(
    	boxes[keep_idx], scores[keep_idx], class_ids[keep_idx],
    	CLASS_NAMES, CONF_THRESHOLD,
    	letterbox_scale = scale, letterbox_pad = pad
    )
    print(f"\n최종 결과 ({len(results)}개):")
    for r in results:
    	print(" ", r)
    	
    return results
    
if __name__ == "__main__":
    main()
