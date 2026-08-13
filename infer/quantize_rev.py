# [Cell 1] 라이브러리 임포트 및 모델/데이터 로드

import sys
import glob
import subprocess
import torch
import numpy as np
from pytorch_nndct.apis import torch_quantizer
from models.experimental import attempt_load

# 1. 모델 로드 (에러가 나면 소스코드 수정 단계나 경로 문제임)
weights_path = "best.pt"
model = attempt_load(weights_path, device='cpu')

# 메모리에 올라온 모델 내부의 모든 SiLU를 LeakyReLU로 강제 교체
def replace_silu(module):
    for name, child in module.named_children():
        if isinstance(child, torch.nn.SiLU):
            setattr(module, name, torch.nn.LeakyReLU(0.1, inplace=True))
        else:
            replace_silu(child)
            
replace_silu(model)
print("All SiLU activations replaced with LeakyReLU.")

# =========================================================
# 👇 [기존 m.export = True 처리하던 for문 전체를 지우고 이 코드로 교체]
def custom_detect_forward(self, x):
    for i in range(self.nl):
        x[i] = self.m[i](x[i])
    return x

for m in model.modules():
    if type(m).__name__ == "Detect":
        m.forward = custom_detect_forward.__get__(m, type(m))
        print("Successfully patched Detect.forward to Raw Conv mode.")
        
#for m in model.modules():
#    if type(m).__name__ == "Detect":
#        m.export = True  # Sigmoid 및 Grid 계산을 건너뛰고 Raw Conv 텐서만 return하게 함 >> 최신 업데이트
# =========================================================

model.eval()
print("Model loaded successfully.")

# 2. 캘리브레이션 데이터 로드
# src 폴더 내의 npy 파일 목록 수집 (extracted_frame_*.npy)
npy_files = sorted(glob.glob("src/extracted_frame_*.npy"))
if not npy_files:
    # 만약 이름이 다를 경우 src/ 안의 모든 npy 탐색
    npy_files = sorted(glob.glob("src/*.npy"))
    
# 방어 로직 1: 파일이 없으면 즉시 안전 종료
if not npy_files:
    print("[Error] No .npy files found in 'src/' directory. Exiting.")
    sys.exit(1)

print(f"Found {len(npy_files)} npy files in src/ directory.")

print("\n--- [검증 2: 데이터 개수 확인] ---")
if len(npy_files) < 100:
    print(f"[Warning] 캘리브레이션 이미지가 {len(npy_files)}장밖에 없습니다. (권장: 100~200장 이상)")
    print("[Warning] 데이터 다양성 부족으로 인한 양자화 가중치 파괴(Clipping)가 발생할 확률이 매우 높습니다.")
else:
    print(f"[Pass] 캘리브레이션 이미지 개수 충분: {len(npy_files)}장")
print("------------------------------------\n")

calib_tensors = []
for f_path in npy_files:
    arr = np.load(f_path)
    
    # 1. 3차원 (H, W, C) 데이터일 경우 Batch 차원 추가 -> (1, H, W, C)
    if arr.ndim == 3:
        arr = np.expand_dims(arr, axis=0)
        
    # 2. NHWC (1, 640, 640, 3) 규격일 경우 -> PyTorch 규격 NCHW (1, 3, 640, 640)로 자동 Transpose
    if arr.shape[-1] == 3:
        arr = np.transpose(arr, (0, 3, 1, 2))
        
    # 3. 픽셀 값이 0~255 범위일 경우 -> 0.0~1.0 정규화
    if arr.max() > 1.0:
        arr = arr / 255.0
        
    tensor_img = torch.from_numpy(arr).float()
    calib_tensors.append(tensor_img)
    
print("\n--- [검증 1: 전처리 스케일 확인] ---")
sample_tensor = calib_tensors[0]
print(f"Tensor Shape: {sample_tensor.shape} (기대값: 1, 3, 640, 640)")
print(f"Tensor Min: {sample_tensor.min().item():.4f}, Max: {sample_tensor.max().item():.4f}")
if sample_tensor.max().item() > 1.0 or sample_tensor.min().item() < 0.0:
    print("[Error] 텐서 스케일이 0~1 범위를 벗어났습니다. 양자화 Fix Point가 어그러집니다.")
else:
    print("[Pass] 텐서 스케일 정규화(0~1) 정상 처리됨.")
print("------------------------------------\n")

# 방어 로직 2: 하드코딩 제거하고 실제 로드된 데이터의 shape을 따라감
dynamic_input_shape = calib_tensors[0].shape
print(f"Processed input tensor shape: {dynamic_input_shape}")

dummy_input = torch.randn(dynamic_input_shape)

# [Cell 2] 양자화(Calibration) 실행 (Min/Max 스케일 추출)

print("--- Starting Quantization (Calibration Mode) ---")

# quantizer 초기화 (calib 모드)
quantizer_calib = torch_quantizer(
    quant_mode='calib',
    module=model,
    input_args=(dummy_input,),
    device=torch.device('cpu')
)
quant_model_calib = quantizer_calib.quant_model

# Forward Pass (데이터를 흘려보내어 분포 측정)
with torch.no_grad():
    for i, input_tensor in enumerate(calib_tensors):
        quant_model_calib(input_tensor)
        print(f"Calibrating frame {i+1}/{len(calib_tensors)} ({npy_files[i]})")

# Fast Finetuning
def eval_fn(q_model, tensors):
    q_model.eval()
    with torch.no_grad():
        for t in tensors:
            q_model(t)
            
#print("--- Running Fast Finetuning (AdaQuant) ---")
#quantizer_calib.fast_finetune(eval_fn, (quant_model_calib, calib_tensors))

# 스케일 및 조정된 가중치 정보 저장
quantizer_calib.export_quant_config()
print("Calibration & Fast Finetuning complete. Config saved.")

# [Cell 3] XIR 모델 추출 (Export)

print("--- Exporting Quantized Model (Test Mode) ---")

# quantizer 초기화 (test 모드)
quantizer_test = torch_quantizer(
    quant_mode='test',
    module=model,
    input_args=(dummy_input,),
    device=torch.device('cpu')
)
quant_model_test = quantizer_test.quant_model

# [추가된 핵심 부분] Fast Finetuning으로 교정된 파라미터 덮어쓰기
# quantizer_test.load_ft_param()

# 테스트 모드에서는 전체 데이터를 돌릴 필요 없이 1번만 Forward Pass를 수행하여 그래프를 추적합니다.
with torch.no_grad():
    # quant_model_test(calib_tensors[0])
    out = quant_model_test(calib_tensors[0])
    
    print("\n--- [검증 3: YOLO Head 출력 분포 확인] ---")
    if isinstance(out, (list, tuple)):
        for idx, o in enumerate(out):
            print(f"Head {idx} (Shape: {o.shape}) - Min: {o.min().item():.2f}, Max: {o.max().item():.2f}")
            if o.max().item() > 20 or o.min().item() < -20:
                print(f"  [Warning] Head {idx}의 값이 너무 큽니다. INT8 변환 시 정밀도 손실(음수 좌표 폭주)의 주범입니다!")
    else:
        print(f"Output (Shape: {out.shape}) - Min: {out.min().item():.2f}, Max: {out.max().item():.2f}")
    print("------------------------------------------\n")

# 컴파일용 파일 추출
quantizer_test.export_xmodel(deploy_check=False, output_dir='quantize_result')
print("Export complete. Check the 'quantize_result' folder.")

# [Cell 4] 터미널에서 B2304 DPU용 컴파일 (.xmodel 생성)

print("--- Compiling XIR Model for DPU ---")
cmd = [
    "vai_c_xir",
    "-x", "quantize_result/DetectionModel_int.xmodel",
    "-a", "./arch_kv260_b2304.json", #2304로 바꿔줘야 함 최종적으로.
    "-n", "yolov5n"
]

print("Executing...")

result = subprocess.run(cmd)

if result.returncode == 0:
    print("Compilation successful. 'yolov5n.xmodel' is ready.")
else:
    print("Compilation failed with return code.")
