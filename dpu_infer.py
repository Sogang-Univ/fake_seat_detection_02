import os
import cv2
import numpy as np
import xir
import vart

def main():
    print("==================================================")
    print(" Kria KV260 보드 단독 가동: On-Device YOLO 추론 시동")
    print("==================================================")

    # 1. 내가 호스트 PC에서 컴파일해서 보드로 넘긴 xmodel 파일 경로 지정
    model_path = "./yolov5n.xmodel"
    if not os.path.exists(model_path):
        print(f"❌ 에러: {model_path} 파일이 보드에 존재하지 않습니다. scp로 전송하세요.")
        return

    # 2. Xilinx 가속기 엔진(XIR)을 통해 xmodel 구조 로드
    graph = xir.Graph.deserialize(model_path)
    root_subgraph = graph.get_root_subgraph()
    
    # 1. 전체 그래프에서 디바이스 속성이 'DPU'인 서브그래프들을 탐색합니다.
    all_subgraphs = graph.get_root_subgraph().get_children()
    dpu_subgraphs = [s for s in all_subgraphs if s.has_attr("device") and s.get_attr("device").upper() == "DPU"]

    # 2. VART API 규격에 맞춰, 리스트가 아닌 '단 하나의 최상위 대표 서브그래프 객체'만 추출합니다.
    if not dpu_subgraphs:
        print("❌ 에러: 모델 내에서 DPU 가속 서브그래프를 찾을 수 없습니다.")
        return
        
    main_dpu_subgraph = dpu_subgraphs[0] # 대표 서브그래프 지정

    # 3. 단일 서브그래프 객체를 주입하여 DPU Runner 가동
    dpu_runner = vart.Runner.create_runner(main_dpu_subgraph, "run")

    # 4. DPU의 입력/출력 텐서 버퍼 구조(Shape) 자동으로 읽어오기
    input_tensors = dpu_runner.get_input_tensors()
    output_tensors = dpu_runner.get_output_tensors()
    
    input_shape = input_tensors[0].dims # 예: [1, 640, 640, 3]
    print(f"🎯 DPU 가속기 입력 요구 규격(Shape): {input_shape}")

    # 5. [치트키] 앞 팀 자료가 없으므로, 아까 만들어둔 더미 이미지 1장을 로드
    dummy_img_path = "./data/calib/dummy_0.jpg"
    if os.path.exists(dummy_img_path):
        print(f"📷 앞 팀 전처리 부재로 인해 더미 이미지({dummy_img_path})로 대치 구동합니다.")
        raw_image = cv2.imread(dummy_img_path)
    else:
        print("💡 더미 이미지 파일도 없으므로 메모리 상에 즉석 가짜 640x640 이미지를 생성합니다.")
        raw_image = np.zeros((640, 640, 3), dtype=np.uint8)

    # 6. 전처리 규격 동기화 (YOLOv5 규칙: BGR -> RGB 스왑 및 차원 확장)
    image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_BGR2RGB)
    image_resized = cv2.resize(image_rgb, (input_shape[1], input_shape[2]))
    input_data = np.expand_dims(image_resized, axis=0).astype(np.int8) # DPU 호환 INT8 정수형 캐스팅

    # 7. DPU 가속 메모리 공간(Buffer) 할당 및 매핑
    input_buffers = [np.empty(input_shape, dtype=np.int8, order="C")]
    input_buffers[0][0] = input_data[0] # 버퍼에 내 더미 데이터 탑재

    output_buffers = [np.empty(output.dims, dtype=np.int8, order="C") for output in output_tensors]

    print("🚀 DPU 하드웨어 척수반사 고속 추론 연산 시작...")
    # 8. 실전 가속 추론 가동 (비동기 연산 호출 및 완료 대기)
    job_id = dpu_runner.execute_async(input_buffers, output_buffers)
    dpu_runner.wait(job_id)
    print("🎉 DPU 가속 연산 완료!")

    # 9. 결과 확인: meta.json에서 확인했던 3개 멀티 헤드(P3, P4, P5) 출력 확인
    print("\n==================================================")
    print("       보드 DPU 가속기 최종 출력 텐서 결과 수령       ")
    print("==================================================")
    for i, out_buf in enumerate(output_buffers):
        print(f" 채널 [{i}] 출력 데이터 구조(Shape): {out_buf.shape}")
        # 이 output_buffers의 원본 데이터 주소들이 우리가 짠 Custom NMS 가속기 IP로 연계됩니다.
    print("==================================================")

    # 10. DPU 엔진 안전 종료
    del dpu_runner

if __name__ == "__main__":
    main()