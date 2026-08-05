import torch
import torch.nn as nn
import os
import sys
# 교차 컴파일 및 호스트 개발환경 단계

# YOLOv5 소스코드를 참조할 수 있도록 패스 추가
sys.path.append(os.getcwd())
from models.experimental import attempt_load

def replace_silu(module):
    for name, child in module.named_children():
    	if isinstance(child, nn.SiLU):
    	    setattr(module, name, nn.ReLU(inplace = True))
    	else:
    	    replace_silu(child)

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
    replace_silu(model)
    model.model[-1].export = True
    
    print("📂 [1/4] YOLOv5-Nano 모델 구조 및 가중치 파싱 완료!")

    # 2. Xilinx vai_q_pytorch 엔진 호출 및 Calibration 압축
    print("⚙️ [2/4] Xilinx 엔진 가동: 1차 Calibration 보정 데이터 축적 시작...")
    from pytorch_nndct.apis import torch_quantizer
    
    # YOLOv5 규격 입력 텐서 (Batch=1, Ch=3, H=640, W=640)
    # ⚠️ YOLOv5는 기본 입력 해상도가 640x640입니다! 앞단 팀원에게 640x640 크기 텐서로 요청해야 합니다.
    inputs = torch.randn(1, 3, 640, 640)
    
    # Calibration 모드로 가중치 오차 보정 진행
    quantizer = torch_quantizer('calib', model, (inputs,), output_dir="quantize_result")
    quant_model = quantizer.quant_model
    _ = quant_model(inputs)
    quantizer.export_quant_config()
    print("🎉 하드웨어 가속 보정 데이터 축적 완료!")

    # 3. Test 모드로 기어를 바꾸어 실전 배포용 xmodel 중간 파일 덤프
    print("\n📦 [3/4] 컴파일용 중간 가속 파일(yolov5_int.xmodel) 배포 시작...")    
    
    # 💡 [핵심 수리 구간]: 2단계 연산으로 인해 오염된 model 객체를 완전히 버리고,
    # 3단계 배포용으로 쓰기 위해 순정 가중치 파일로부터 모델을 '깨끗하게 새로 로드'합니다.
    # 이렇게 해야 2단계에서 저장된 정밀도 보정 파일과 레이어 구조가 100% 자석처럼 딱 맞물립니다.
    deploy_model = attempt_load(model_path, device=torch.device('cpu'))
    deploy_model.eval()
    replace_silu(deploy_model)
    deploy_model.model[-1].export = True
    
    # 깨끗하게 새로 태어난 deploy_model 객체를 배포 가속 엔진에 주입합니다.
    deploy_quantizer = torch_quantizer('test', deploy_model, (inputs,), output_dir="quantize_result")
    
    # 배포용 가속 모델 객체를 최종 활성화 연산합니다.
    deploy_quant_model = deploy_quantizer.quant_model
    _ = deploy_quant_model(inputs)
    
    deploy_quantizer.export_xmodel(deploy_check=True) 
    print("\n🏆 [대성공] YOLOv5 양자화 통합 배포 팩 최종 마감 완료! 'quantize_result' 폴더를 확인하세요.")
    
    print("\n🛠️ [4/4] Kria KV260 DPU 하드웨어 가속 컴파일러 가동...") 
    # 터미널에 치던 명령어를 문자열 그대로 변수에 담습니다. PYNQ-DPU 실물 전용 하드웨어 규격 코드를 직접 박아줍니다!
    cmd = "vai_c_xir -x quantize_result/DetectionModel_int.xmodel -a '{\"fingerprint\":\"0x101000016010407\"}' -o . -n yolov5n"

    
    # 파이썬이 리눅스 터미널에 이 문자열을 그대로 던져서 실행합니다.
    os.system(cmd)
    
    print("🏆 [대성공] YOLOv5 양자화 및 KV260 DPU 컴파일 통합 마감 완료!:'yolov5n.xmodel' 및 'meta.json' 생성 완료!")

