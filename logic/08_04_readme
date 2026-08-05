# 오늘 진행 업무 및 문제 해결 과정

## 1. 오늘 작업의 전체 목표

오늘의 목표는 KV260 보드에서 다음 전체 파이프라인을 실제로 연결하고 동작을 확인하는 것이었다.

```text
DDR에 저장된 640×480 영상
    ↓
PL의 ROI crop HLS 커널
    ↓
480×480 좌석 ROI 영상 생성
    ↓
PS에서 YOLO 입력 크기로 전처리
    ↓
DPU에서 YOLO 객체 탐지
    ↓
person / bag 검출 결과 생성
    ↓
좌석 상태머신에 전달
```

기존에는 ROI crop 커널과 DPU가 각각 별도로 동작하는 상태였고, 오늘은 두 기능이 포함된 플랫폼 비트스트림을 보드에 올린 뒤 실제 ROI 결과를 YOLO 모델에 입력하는 통합 테스트를 진행하였다.

---

# 2. ROI crop과 DPU가 포함된 플랫폼 비트스트림 구성

## 2.1 플랫폼 구성 목적

기존 KV260 DPU 플랫폼에 직접 작성한 ROI crop HLS 커널을 추가하여 하나의 `xclbin` 안에 다음 두 커널이 포함되도록 구성하였다.

```text
roi_crop_accel_1
DPUCZDX8G_1
```

ROI crop 커널은 메모리 매핑 방식으로 구성하였다.

```text
입력:
640×480×3 영상 데이터

처리:
좌우 80픽셀 제거
중앙 480×480 영역 crop

출력:
480×480×3 ROI 데이터
```

DPU는 기존 KV260용 B4096 구성을 사용하였다.

---

## 2.2 V++ 빌드 환경 구성

빠른 PC에서 KV260 플랫폼을 사용하기 위해 플랫폼 파일을 복사하고 다음 플랫폼이 정상적으로 인식되는지 확인하였다.

```text
kv260_ispMipiRx_vcu_DP.xpfm
```

사용한 도구 버전은 다음과 같다.

```text
Vivado 2022.2
Vitis 2022.2
Vitis HLS 2022.2
Vitis AI 2.5 계열 runtime
```

`platforminfo` 명령을 통해 플랫폼이 정상적으로 열리고, 다음 자원이 제공되는 것을 확인하였다.

```text
300 MHz clock
600 MHz clock
100 MHz clock

HP1
HP3
HPC1
LPD memory interface
```

즉 V++ link에 사용할 플랫폼 경로와 클럭, 메모리 인터페이스가 정상적으로 준비되었다.

---

## 2.3 ROI crop HLS 커널 추가

기존 DPU benchmark 예제에 직접 작성한 `roi_crop_accel.xo`를 추가하였다.

ROI crop 커널의 주요 설정은 다음과 같다.

```text
입력 해상도  : 640×480
입력 데이터  : RGB/BGR 3채널, 총 921,600 byte
crop 시작점  : x=80
crop 폭       : 480
출력 높이     : 480
출력 크기     : 480×480×3, 총 691,200 byte
```

커널 인터페이스는 메모리 매핑 방식으로 구성하였다.

```cpp
extern "C" void roi_crop_accel(
    const ap_uint<8>* src,
    ap_uint<8>* dst
);
```

```text
src → M_AXI gmem0
dst → M_AXI gmem1
control → AXI-Lite
```

HLS 커널 자체는 V++ compile을 정상적으로 완료하여 `.xo` 파일을 생성하였다.

---

## 2.4 V++ link와 비트스트림 생성

기존 DPU kernel과 ROI crop kernel을 함께 link하기 위해 Makefile과 connectivity 설정을 수정하였다.

최종적으로 하나의 `xclbin` 안에 다음 두 커널이 포함되도록 구성하였다.

```text
DPUCZDX8G
roi_crop_accel
```

V++ link가 정상 완료되었고, KV260에서 사용할 수 있는 비트스트림과 관련 파일을 생성하였다.

---

# 3. KV260에 새 플랫폼 설치 및 활성화

생성한 파일을 KV260 보드로 복사한 뒤 새로운 애플리케이션 패키지를 설치하였다.

사용한 앱 이름은 다음과 같다.

```text
kv260-dpu-roi
```

설치 후 `xmutil`을 통해 해당 앱을 활성화하고, DPU와 ROI crop kernel이 포함된 새로운 비트스트림을 보드에 로드하였다.

## 확인한 사항

```text
FPGA manager load 성공
DPU kernel 인식
ROI crop kernel 인식
XRT runtime 정상
VART runner 생성 가능
```

즉 플랫폼 비트스트림 자체는 정상적으로 보드에 올라갔다.

---

# 4. ROI crop 하드웨어 단독 검증

## 4.1 테스트 데이터

ROI crop 검증을 위해 640×480 영상 프레임을 사용하였다.

```text
입력 shape:
480×640×3

출력 예상 shape:
480×480×3
```

입력 프레임의 중앙 영역을 다음 범위로 crop하도록 설정하였다.

```text
x = 80 ~ 559
y = 0 ~ 479
```

---

## 4.2 하드웨어 ROI 결과와 소프트웨어 결과 비교

하드웨어 ROI 결과를 raw 파일로 저장하고, NumPy를 이용한 소프트웨어 crop 결과와 비교하였다.

소프트웨어 기준 crop은 다음과 같다.

```python
software_roi = frame[:, 80:560, :]
```

비교 결과 하드웨어 결과와 소프트웨어 결과가 동일하게 나왔다.

```text
입력 크기  : 640×480
ROI 크기   : 480×480
crop 위치  : 정상
pixel 비교 : 일치
```

따라서 다음 항목은 정상으로 확인되었다.

```text
ROI HLS 알고리즘
ROI kernel 메모리 접근
입출력 buffer 크기
crop 좌표
xclbin 내부 ROI kernel
```

---

# 5. ROI 결과를 YOLOv5n DPU 모델에 연결

## 5.1 새 YOLOv5n 모델 확인

새로 전달받은 `yolov5n.xmodel`을 KV260에서 로드하였다.

모델 입력은 다음과 같았다.

```text
shape     : (1, 640, 640, 3)
dtype     : INT8
fix_point : 4
```

모델 출력은 다음 세 개의 YOLO raw head였다.

```text
(1, 80, 80, 255)
(1, 40, 40, 255)
(1, 20, 20, 255)
```

출력 채널 255는 다음 의미이다.

```text
3 anchors × (4 box + 1 objectness + 80 classes)
= 3 × 85
= 255
```

따라서 모델 shape만 보면 COCO 80 class YOLOv5 구조와 일치하였다.

또한 모델의 DPU target 정보는 다음과 같았다.

```text
DPUCZDX8G_ISA1_B4096
```

현재 KV260에서 사용하는 DPU도 B4096이므로 아키텍처 이름 자체는 일치하였다.

---

## 5.2 ROI 영상 전처리

ROI hardware output은 480×480이지만 YOLOv5n 입력은 640×640이므로 다음 전처리를 적용하였다.

```text
480×480 ROI
    ↓
640×640 resize
    ↓
0~255 픽셀값을 0~1로 정규화
    ↓
input fix_point=4 기준 ×16
    ↓
INT8 입력 생성
```

수식으로는 다음과 같다.

```text
INT8 입력값
= round(pixel / 255 × 2^4)
```

따라서 입력 범위는 다음과 같이 생성되었다.

```text
0 ~ 16
```

실제 로그에서도 다음을 확인하였다.

```text
shape : (1, 640, 640, 3)
dtype : int8
range : 0 ~ 16
```

---

# 6. 오늘 발생한 첫 번째 오류: 결과 이미지 색상이 파란색으로 표시됨

## 6.1 증상

DPU 테스트 결과 이미지를 저장했을 때 사람의 피부색이 파란색으로 표시되었다.

## 6.2 원인

하드웨어 ROI raw 파일은 실제로 OpenCV 형식인 BGR 순서였으나, 코드에서 RGB 영상으로 해석하였다.

즉 다음 채널 순서가 뒤바뀐 상태였다.

```text
실제 데이터 : B, G, R
코드 해석   : R, G, B
```

따라서 빨간색 계열인 피부색이 파란색으로 표시되었다.

## 6.3 해결 방법

DPU 입력 전에 BGR에서 RGB로 변환하였다.

```python
roi_rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB)
```

결과 이미지를 OpenCV로 저장할 때는 BGR 영상을 그대로 사용하였다.

```python
result_bgr = roi_bgr.copy()
```

## 6.4 해결 결과

```text
피부색 정상 표시
ROI 영상 방향 정상
영상 데이터 자체 정상
```

색상 문제는 해결되었지만 person 검출은 여전히 되지 않았다.

---

# 7. 오늘 발생한 두 번째 문제: person 검출 결과가 계속 False

## 7.1 초기 증상

YOLOv5n 추론은 정상적으로 종료되었지만 결과는 다음과 같았다.

```text
detection count : 0
person_present  : False
bag_present     : False
```

처음에는 score threshold가 너무 높아서 검출 결과가 제거되는 것으로 의심하였다.

---

## 7.2 Score threshold 변경 시도

기존 threshold 값을 낮추려고 하였다.

```text
0.35
→ 0.10
→ 0.05
```

하지만 threshold를 바꾸어도 검출 결과는 계속 0개였다.

중간에 파일 내 `score_thresh` 값이 원하는 대로 변경되지 않는 문제도 있었다.

### 원인

수정하려는 문자열과 실제 코드 형식이 달랐거나, 수정한 파일과 실제 실행한 파일이 서로 달랐을 가능성이 있었다.

예를 들어 다음 차이로 인해 단순 `sed` 명령이 매칭되지 않을 수 있었다.

```python
score_thresh=0.35
score_thresh = 0.35
```

### 해결

Python 정규식을 사용하여 실제 `score_thresh` 값을 변경하고, `grep` 명령으로 실행 파일의 값을 직접 확인하였다.

그러나 threshold를 정상적으로 낮춘 이후에도 detection은 발생하지 않았다.

---

# 8. DPU 입력 크기 점검

person이 검출되지 않아 ROI의 480×480 영상이 그대로 모델에 들어가는 것이 아닌지 확인하였다.

실제 모델 입력 로그는 다음과 같았다.

```text
input shape:
(1, 640, 640, 3)
```

전처리 후 입력도 다음과 같았다.

```text
(1, 640, 640, 3)
```

따라서 실제 처리 흐름은 정상적으로 다음과 같이 구성되어 있었다.

```text
480×480 ROI
    ↓ resize
640×640
    ↓ batch 추가
1×640×640×3
```

즉 검출 실패 원인은 입력 해상도가 480×480으로 잘못 전달된 문제가 아니었다.

---

# 9. YOLOv5 후처리 코드 검증

## 9.1 Anchor와 stride 확인

YOLOv5 decoder에 사용되는 anchor와 stride를 확인하였다.

```text
stride 8:
[10,13], [16,30], [33,23]

stride 16:
[30,61], [62,45], [59,119]

stride 32:
[116,90], [156,198], [373,326]
```

이는 일반적인 YOLOv5 COCO anchor 값과 일치하였다.

---

## 9.2 YOLOv5 decode 수식 확인

`_decode_head()` 내부를 확인하였다.

```python
box_xy = (sigmoid(txy) * 2.0 - 0.5 + grid) * stride
box_wh = (sigmoid(twh) * 2.0) ** 2 * anchors
```

confidence 계산은 다음과 같았다.

```python
scores = sigmoid(objectness) * sigmoid(class_probability)
```

따라서 다음 항목은 정상으로 확인하였다.

```text
YOLOv5 좌표 decode 방식
objectness 계산
class probability 계산
score 계산
anchor와 stride 적용
```

---

## 9.3 DPU 출력 reshape 확인

DPU raw output은 다음 형태였다.

```text
(1, H, W, 255)
```

이를 decoder 형식으로 다음과 같이 변환하였다.

```text
(1,H,W,255)
→ (1,H,W,3,85)
→ (1,3,H,W,85)
```

실제 코드는 다음과 같았다.

```python
f = f.reshape(1, H, W, 3, 85)
f = f.transpose(0, 3, 1, 2, 4)
```

따라서 anchor 채널이 뒤섞이는 reshape 문제도 아니었다.

---

# 10. Threshold 적용 전 score 직접 확인

threshold가 원인인지 정확하게 확인하기 위해 threshold 적용 전 score를 출력하도록 decoder에 디버그 코드를 추가하였다.

## 결과

```text
person max score     : 약 0.000145
global max score     : 약 0.000164
global max class     : 7
```

person 후보 개수는 다음과 같았다.

```text
person score >= 0.1   : 0개
person score >= 0.05  : 0개
person score >= 0.01  : 0개
person score >= 0.001 : 0개
```

## 판단

threshold가 0.35여서 정상 후보가 제거된 것이 아니었다.

모델의 최대 score 자체가 0.0001 수준이므로 threshold를 0.05나 0.01로 낮춰도 detection이 생성되지 않는 것이 정상이다.

즉 문제가 다음과 같이 바뀌었다.

```text
기존 의심:
후처리 threshold가 너무 높음

실제 문제:
DPU 출력 자체에 의미 있는 objectness/class score가 없음
```

---

# 11. 오늘의 핵심 디버깅: 실제 이미지와 zero 입력 비교

## 11.1 비교 목적

실제 ROI 입력이 DPU에 정상적으로 전달되고 있는지 확인하기 위해 두 가지 입력을 비교하였다.

```text
1. 모든 값이 0인 입력
2. 실제 ROI 이미지 입력
```

실제 ROI 입력 배열은 정상적으로 데이터가 존재하였다.

```text
range      : 0 ~ 16
mean       : 약 4.03
std        : 약 4.63
nonzero    : 약 1,044,390개
contiguous : True
```

즉 실제 입력 배열이 우연히 모두 0으로 만들어진 것은 아니었다.

---

## 11.2 비교 결과

두 입력을 각각 DPU에 넣은 결과, 세 출력 tensor가 완전히 동일하였다.

```text
Output[0]
different : 0

Output[1]
different : 0

Output[2]
different : 0
```

전체 출력 원소 약 214만 개가 전부 동일하였다.

```text
실제 ROI 입력 출력
=
zero 입력 출력
```

이 결과를 통해 검출 실패 원인이 threshold나 NMS 이후 단계가 아니라, DPU 모델 출력 단계 이전에 있다는 사실을 확인하였다.

---

# 12. 여러 패턴 입력으로 YOLOv5n 반응성 테스트

실제 영상 전처리만 잘못된 것인지, 모델이 어떤 입력에도 반응하지 않는 것인지 확인하기 위해 다양한 인위적 입력을 생성하였다.

## 테스트 입력

### 모든 값이 0인 입력

```text
모든 픽셀, 모든 채널 = 0
```

검은색에 가까운 기준 입력이다.

### 모든 값이 16인 입력

```text
모든 픽셀, 모든 채널 = 16
```

현재 정상 양자화 범위 0~16에서 최대값에 해당한다.

### Checker pattern 입력

```text
16  0 16  0
 0 16  0 16
16  0 16  0
```

0과 16이 번갈아 반복되는 강한 경계 패턴이다.

### Random 입력

```text
각 픽셀 값이 0~16 사이 무작위
```

공간적으로 복잡한 입력을 생성하기 위한 테스트이다.

### 모든 값이 -128인 입력

```text
INT8 최솟값
```

정상 영상 범위를 벗어난 극단적인 스트레스 입력이다.

### 모든 값이 127인 입력

```text
INT8 최댓값
```

이 역시 모델 입력 반응을 강제로 확인하기 위한 극단 입력이다.

---

## 테스트 결과

모든 입력에서 출력이 완전히 동일하였다.

```text
zero vs full16
total different = 0

zero vs checker
total different = 0

zero vs random
total different = 0

-128 vs 0
total different = 0

0 vs 127
total different = 0
```

즉 다음 입력들이 모두 동일한 DPU 출력을 만들었다.

```text
zero
full16
checker
random
-128
127
```

이는 단순히 실제 사진을 인식하지 못하는 문제가 아니라, 현재 YOLOv5n xmodel 출력이 입력 데이터에 전혀 의존하지 않는 상태임을 의미한다.

---

# 13. 보드와 VART 코드 문제를 제외하기 위한 YOLOv8 비교

## 13.1 비교 목적

다음 가능성을 확인할 필요가 있었다.

```text
VART Python 코드가 입력을 제대로 전달하지 못하는가?
현재 DPU 비트스트림이 잘못되었는가?
출력 버퍼를 이전 값으로 계속 읽는가?
```

이를 확인하기 위해 같은 보드, 같은 비트스트림, 같은 VART 코드로 기존 YOLOv8 xmodel을 테스트하였다.

---

## 13.2 YOLOv8 비교 결과

YOLOv8은 입력에 따라 출력이 정상적으로 변화하였다.

```text
zero vs full
약 114,116개 출력값 변화

zero vs checker
약 140,465개 출력값 변화

zero vs random
약 139,943개 출력값 변화
```

따라서 다음 항목은 정상으로 확인되었다.

```text
KV260 DPU 하드웨어
새 플랫폼 비트스트림의 DPU 동작
VART runner
Python input buffer 전달
execute_async
runner.wait
output buffer 읽기
테스트 코드
```

즉 YOLOv5n에서만 입력에 대한 반응이 없다는 사실이 확인되었다.

---

# 14. XMODEL subgraph 구조 확인

YOLOv5n의 XIR subgraph 구조도 확인하였다.

```text
USER subgraph
    ↓
(1,640,640,3) input_0_fix
    ↓
DPU subgraph
    ↓
80×80×255
40×40×255
20×20×255
    ↓
CPU reshape subgraph
```

처음에는 root input tensor가 0개이고 USER subgraph에 input이 없는 점을 문제로 의심하였다.

그러나 정상적으로 입력에 반응하는 YOLOv8도 동일한 형태였다.

```text
YOLOv8:
USER subgraph input 없음
USER output → DPU input
```

따라서 이러한 XIR 구조는 외부 입력을 나타내는 일반적인 표현이며, 이것만으로 YOLOv5n 입력 연결이 끊겼다고 판단할 수는 없었다.

이 부분에 대해서는 초기 판단을 수정하였다.

---

# 15. 오늘 최종적으로 확인된 문제 원인

## 정상 확인된 부분

```text
KV260 플랫폼 비트스트림 로드
DPUCZDX8G B4096 실행
ROI crop HLS kernel
ROI 640×480 → 480×480 결과
ROI 메모리 입출력
480×480 → 640×640 resize
INT8 입력 buffer 생성
BGR → RGB 처리
VART runner 실행
DPU output buffer 생성
YOLOv5 output reshape
YOLOv5 anchor와 stride
YOLOv5 decode 공식
NMS 이전 score 확인
```

## 제외된 원인

```text
ROI crop 오류
입력 크기 오류
RGB/BGR 오류
threshold 오류
NMS 오류
person class remap 오류
anchor 오류
decoder reshape 오류
VART 입력 전달 오류
현재 KV260 DPU 하드웨어 오류
새 플랫폼 bitstream 전체 오류
```

## 최종적으로 남은 문제

새로 받은 `yolov5n.xmodel`은 어떤 입력을 넣어도 DPU 출력이 완전히 동일하다.

```text
실제 이미지
zero
full16
checker
random
-128
127
```

모두 동일한 출력 tensor를 생성하였다.

반면 같은 환경에서 YOLOv8은 정상적으로 입력에 반응하였다.

따라서 현재 가장 유력한 문제 위치는 다음과 같다.

```text
YOLOv5n 양자화 결과 오류
YOLOv5n 컴파일 결과 오류
weight 또는 activation scale 오류
잘못된 xmodel 파일 전달
모델 생성 과정의 입력 또는 graph 처리 오류
```

---

# 16. 모델 담당자에게 전달한 내용

모델 담당자에게는 단순히 “사람이 검출되지 않는다”고 전달하는 것이 아니라 다음과 같이 설명해야 한다.

```text
현재 YOLOv5n 모델은 confidence가 낮은 문제가 아니다.

서로 완전히 다른 입력을 넣어도 3개 출력 tensor의
모든 값이 비트 단위로 완전히 동일하다.

같은 KV260, 같은 DPU bitstream, 같은 VART 코드에서
기존 YOLOv8 모델은 입력에 따라 출력이 정상적으로 달라진다.

따라서 보드나 실행 코드 문제가 아니라
YOLOv5n xmodel의 양자화 또는 컴파일 결과 문제로 판단된다.
```

추가로 모델 담당자에게 다음 자료를 요청하였다.

```text
동일 xmodel의 SHA256
사용한 Vitis AI 버전
사용한 arch.json
DPU target
양자화 스크립트
calibration 전처리 코드
vai_c_xir 명령
컴파일 로그
실제 이미지 검출 결과
zero 입력과 실제 입력의 output tensor 비교
```

---

# 17. 오늘 작업의 최종 결과

오늘 전체 파이프라인을 완전히 성공시킨 것은 아니지만, 시스템을 단계별로 분리하여 문제 위치를 명확하게 좁혔다.

```text
플랫폼 비트스트림 생성 및 보드 로드
                     성공

ROI crop 하드웨어 동작
                     성공

ROI 결과 검증
                     성공

DPU 하드웨어 및 VART 실행
                     성공

기존 YOLOv8 입력 반응
                     성공

새 YOLOv5n person 검출
                     실패

YOLOv5n 실패 원인 위치 분리
                     성공
```

최종적으로 오늘 확인한 핵심 결론은 다음과 같다.

> ROI crop과 KV260 DPU 실행 환경은 정상적으로 동작한다. 현재 통합 검출이 되지 않는 원인은 새로 전달받은 YOLOv5n xmodel이 입력 변화에 반응하지 않고 항상 동일한 출력 tensor를 생성하는 문제이며, 모델의 양자화 또는 컴파일 과정을 모델 담당자가 다시 확인해야 한다.
