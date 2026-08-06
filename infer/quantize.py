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
    import numpy as np

        # 1. 8개의 실제 npy 파일 경로 리스트 생성
    npy_dir = "./src"
    npy_files = [os.path.join(npy_dir, f"extracted_frame_{i}.npy") for i in range(8)]
    
        # 2. 첫 번째 데이터를 읽어 inputs로 지정
    inputs = torch.from_numpy(np.load(npy_files[0])).float() / 255.0
    
        # 만약 앞단 팀원이 준 npy에 배치 차원(1)이 없다면 추가 (3D -> 4D)
    if len(inputs.shape) == 3:
        inputs = inputs.unsqueeze(0)
        
        # 💡 [핵심 수리 구간 1]: [1, 640, 640, 3] 구조를 [1, 3, 640, 640] 구조로 재배치!
    inputs = inputs.permute(0, 3, 1, 2)
    
        # 3. 진짜 데이터 규격(inputs)을 넣어 Xilinx 양자화 엔진을 초기화
    quantizer = torch_quantizer('calib', model, (inputs,), output_dir="quantize_result")
    quant_model = quantizer.quant_model
    print("[QUANT MODEL CHECK] 양자화 모델 타입:", type(quant_model))
    print("[QUANT MODEL CHECK] 가중치 샘플 값:", [p.max().item() for p in list(quant_model.parameters())[:2]])
    
        # 4. 이제 루프를 돌며 0번부터 7번까지 순차적으로 피딩 진행
    print("📸 실제 도서관/카페 npy 데이터 8장 순회 피딩 중...")
    for npy_path in npy_files:
        raw_npy = np.load(npy_path)
        img_tensor = torch.from_numpy(raw_npy).float() / 255.0
        
        if len(img_tensor.shape) == 3:
            img_tensor = img_tensor.unsqueeze(0)
            
        img_tensor = img_tensor.permute(0, 3, 1, 2)
            
        _ = quant_model(img_tensor)

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
    
    #print("\n🛠️ [4/4] Kria KV260 DPU 하드웨어 가속 컴파일러 가동...") 
    ## 터미널에 치던 명령어를 문자열 그대로 변수에 담습니다. PYNQ-DPU 실물 전용 하드웨어 규격 코드를 직접 박아줍니다!
    #cmd = "vai_c_xir -x quantize_result/DetectionModel_int.xmodel -a /opt/vitis_ai/compiler/arch/DPUCZDX8G/KV260/arch.json -o . -n yolov5n"
    ## cmd = r"""vai_c_xir -x quantize_result/DetectionModel_int.xmodel -a '{"fingerprint":"0x101000016010407"}' -o . -n yolov5n"""
    ## 파이썬이 리눅스 터미널에 이 문자열을 그대로 던져서 실행합니다.
    #os.system(cmd)
    
    #print("🏆 [대성공] YOLOv5 양자화 및 KV260 DPU 컴파일 통합 마감 완료!:'yolov5n.xmodel' 및 'meta.json' 생성 완료!")

    print("\n🛠️ [4/4] Kria KV260 DPU 하드웨어 가속 컴파일러 가동...") 
    import json

    # 1. 교수님이 확인해주신 보드 요구 고유 핑거프린트 도장 정보 세팅
    custom_arch_path = "kv260_custom_arch.json"
    arch_config = {
        "target": "DPUCZDX8G_ISA1_B4096",
        "fingerprint": "0x101000016010407"
    }
    
    # 2. 파이썬이 실행 중에 해당 폴더에 진짜 실물 보드용 규격 파일로 구워버립니다.
    with open(custom_arch_path, 'w') as f:
        json.dump(arch_config, f)
        
    print(f"📄 실물 보드 요구 낙인 각인용 규격 파일 작성 완료 ({custom_arch_path})")

    # 3. 컴파일러에게 문자열이 아닌, 방금 만든 '물리 파일 경로'를 -a 옵션으로 확실하게 던집니다.
    # 이렇게 하면 문법 에러 없이 핑거프린트가 기계어 단에 완벽하게 각인됩니다.
    cmd = f"vai_c_xir -x quantize_result/DetectionModel_int.xmodel -a {custom_arch_path} -o . -n yolov5n"
    
    # 4. 컴파일러 실행
    os.system(cmd)
    
    # 5. 작업이 끝난 후 생성했던 임시 규격 파일은 깔끔하게 자동 삭제 청소
    if os.path.exists(custom_arch_path):
        os.remove(custom_arch_path)
    
    print("🏆 [대성공] YOLOv5 양자화 및 KV260 DPU 컴파일 통합 마감 완료!:'yolov5n.xmodel' 및 'meta.json' 생성 완료!")


