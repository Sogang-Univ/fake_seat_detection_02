# YOLOv5 DPU 파이프라인 개발 현황 및 요약

## 1. 진행한 작업 (What We Did)
- **DPU 추론 파이프라인 구축**: Xilinx Vitis AI DPU 상에서 YOLOv5n 모델 구동, `.npy` 프레임 데이터 입력 및 Raw 텐서 출력 수집 파이프라인 완성.
- **후처리 및 NMS 연동**: DPU 출력 텐서를 디코딩하고 NMS(Non-Maximum Suppression)를 거쳐 최종 Bounding Box 및 Score를 추출하는 흐름 검증 완료.

## 2. 해결한 문제 (Fixed Issues)
- **엉뚱한 클래스 폭발 현상 해결**: 초기에 넥타이(Class 27), 연(Class 38) 등 관련 없는 사물이 높은 신뢰도(0.85 이상)로 수십 개씩 도배되던 문제 해결.
  - **조치**: NMS 호출 직전에 관심 클래스(사람 등 10개)만 1차 추출하도록 필터링 로직 반영 및 Class-aware NMS 적용.

## 3. 남은 문제 (Remaining Issues)
- **낮은 신뢰도 (Score 0.2~0.3대)**: 사람을 잡더라도 Score가 0.27~0.35 수준으로 매우 낮음.
- **허위/착시 검출 (Ghost Detection)**: 사람이 없는 빈 프레임에서도 모니터나 의자 같은 검은 영역을 사람(Class 0)으로 오인.
- **색상 채널(RGB/BGR) 가설 기각**: BGR ↔ RGB 반전 테스트 진행 결과 유의미한 점수 상승이 없어 색상 문제는 아닌 것으로 판명.

## 4. 향후 시도할 과제 (Next Steps)
1. **입력 정규화 (`/ 255.0`) 검증**: `.npy` 파일의 픽셀 값이 0~255 범위일 경우, `arr.astype(np.float32) / 255.0` 적용 후 추론 결과 확인.
2. **앵커 박스(Anchor Box) 점검**: 디코딩 코드 내 하드코딩된 앵커 좌표가 공식 YOLOv5n v6.2 규격과 일치하는지 확인.
3. **공식 모델 재양자화 (Quantization)**: 전처리/앵커 문제가 아닐 경우, Ultralytics 공식 `yolov5n.pt`(v6.2)를 받아 Vitis AI Quantizer부터 재진행.
