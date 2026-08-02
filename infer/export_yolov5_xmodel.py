import torch
import os
import sys

# YOLOv5 소스코드를 참조할 수 있도록 패스 추가
sys.path.append(os.getcwd())
from models.experimental import attempt_load

if __name__ == "__main__":
    print("🚀 [Vitis-AI] YOLOv5-Nano 하드웨어 가속 컴파일 파이프라인 구동...")
    
    # 1. 팀원들이 넘겨줄 커스텀 학습 완료 가중치 파일 로드
    # (파일이 오면 이름을 best.pt로 변경하여 이 폴더에 넣으시면 됩니다)
    model_path = "best.pt"
    if not os.path.exists(model_path):
        print(f"⚠️ '{model_path}' 파일이 아직 폴더에 없습니다. 팀원에게 받아서 이 위치에 넣어주세요.")
        sys.exit()
        
    model = attempt_load(model_path, device=torch.device('cpu'))
    model.eval()
    
    model.model[-1].export = True
    
    print("📂 [1/3] YOLOv5-Nano 모델 구조 및 가중치 파싱 완료!")

    # 2. Xilinx vai_q_pytorch 엔진 호출 및 Calibration 압축
    print("⚙️ [2/3] Xilinx 엔진 가동: 1차 Calibration 보정 데이터 축적 시작...")
    from pytorch_nndct.apis import torch_quantizer
    
    # YOLOv5 규격 입력 텐서 (Batch=1, Ch=3, H=640, W=640)
    # ⚠️ YOLOv5는 기본 입력 해상도가 640x640입니다! 앞단 팀원에게 640x640 크기 텐서로 요청해야 합니다.
    inputs = torch.randn(1, 3, 640, 640)
    
    # Calibration 모드로 가중치 오차 보정 진행
    quantizer = torch_quantizer('calib', model, (inputs,))
    quant_model = quantizer.quant_model
    _ = quant_model(inputs)
    quantizer.export_quant_config()
    print("🎉 하드웨어 가속 보정 데이터 축적 완료!")

    # 3. Test 모드로 기어를 바꾸어 실전 배포용 xmodel 중간 파일 덤프
    print("\n📦 [3/3] 컴파일용 중간 가속 파일(yolov5_int.xmodel) 배포 시작...")
    deploy_quantizer = torch_quantizer('test', model, (inputs,))
    _ = deploy_quantizer.quant_model(inputs)
    deploy_quantizer.export_xmodel(deploy_check=False) 
    
    print("\n🏆 [대성공] YOLOv5 양자화 통합 배포 팩 최종 마감 완료! 'quantize_result' 폴더를 확인하세요.")
