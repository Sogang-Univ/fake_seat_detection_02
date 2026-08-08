원인은 거의 확실히 **출력 단계의 `memcpy + 포인터 강제 캐스팅`** 쪽이었습니다.

기존 코드와 수정 코드를 비교하면, crop/resize 계산 자체는 거의 그대로이고 **실제로 바뀐 핵심은 `out_line`의 내용을 DDR의 `dst`로 쓰는 방식**입니다.

## 핵심 결론

기존 코드는 마지막에 이렇게 썼습니다.

```cpp
memcpy(
    dst + oy * DST_SIZE,
    (pixel_t*)out_line,
    DST_SIZE * sizeof(pixel_t)
);
```

여기서:

```cpp
word_t  = ap_uint<128>
pixel_t = ap_uint<32>
```

입니다.

즉 `out_line`은 실제로:

```text
128-bit word 배열
```

인데, 이것을 강제로:

```text
32-bit pixel 배열처럼 보이게 cast
```

한 뒤 `memcpy()`를 시킨 겁니다.

CPU C/C++에서는 이런 방식이 메모리 바이트 배열 관점에서 동작할 수 있지만, **Vitis HLS에서는 `ap_uint<128>*`와 `ap_uint<32>*`를 단순한 일반 포인터처럼 reinterpret해서 처리하는 것이 안전하지 않습니다.**

반면 수정된 코드는:

```cpp
word_t out_word = out_line[w];

pixel_t p0 = out_word.range(31, 0);
pixel_t p1 = out_word.range(63, 32);
pixel_t p2 = out_word.range(95, 64);
pixel_t p3 = out_word.range(127, 96);

dst[base + 0] = p0;
dst[base + 1] = p1;
dst[base + 2] = p2;
dst[base + 3] = p3;
```

처럼 **128bit → 4개의 32bit 픽셀이라는 관계를 HLS에게 명시적으로 알려줬습니다.**

그래서 실제 하드웨어가 원하는 write transaction을 정확하게 생성할 수 있게 된 것입니다.

---

## 1. 기존 코드 내부에서는 어디까지 정상적이었나

기존 구조를 따라가면:

```text
DDR src
 ↓
128-bit AXI read
 ↓
load_row()
 ↓
line0 / line1
 ↓
get_pix()
 ↓
blend4()
 ↓
pixel_t
 ↓
out_line에 4픽셀씩 packing
 ↓
?????????
 ↓
DDR dst
```

입니다.

여기서 기존 코드도 `out_line`까지는 꽤 명확했습니다.

예를 들어:

```cpp
int widx = ox >> 2;
int pidx = ox & 3;

word_t cur = out_line[widx];

cur.range(
    pidx * 32 + 31,
    pidx * 32
) = pix;

out_line[widx] = cur;
```

이면:

```text
out_line[0]

bit 127                   bit 0
 ┌────────┬────────┬────────┬────────┐
 │ pixel3 │ pixel2 │ pixel1 │ pixel0 │
 └────────┴────────┴────────┴────────┘
   32bit    32bit    32bit    32bit
```

로 구성됩니다.

여기까지는 의도가 명확합니다.

문제는 이걸 DDR에 쓰는 마지막 부분이었습니다.

---

# 2. 기존 코드의 가장 큰 문제

기존:

```cpp
memcpy(
    dst + oy * DST_SIZE,
    (pixel_t*)out_line,
    DST_SIZE * sizeof(pixel_t)
);
```

이 한 줄에는 사실 세 종류의 타입이 섞입니다.

```text
out_line
    ↓
word_t*
= ap_uint<128>*

강제 cast
    ↓
pixel_t*
= ap_uint<32>*

memcpy
    ↓
dst
= ap_uint<32>*
```

C언어 관점에서는 개발자가:

> 128bit 하나 안에 32bit가 4개 있으니까 그냥 32bit pointer로 보면 되겠지

라고 생각할 수 있습니다.

하지만 HLS 입장에서는 이게 단순한 소프트웨어 메모리 복사가 아닙니다.

HLS가 이 코드를 보고 실제로 만들어야 하는 것은:

```text
BRAM read
→ bit slicing
→ AXI write address 생성
→ WDATA 생성
→ burst 제어
```

입니다.

그런데 `ap_uint<128>*`를 `ap_uint<32>*`로 cast해서 `memcpy()`를 호출하면 HLS가:

```text
out_line[w]의 어느 32bit가
dst의 어느 주소로 가는가?
```

를 정상적인 배열 접근 형태로 직접 보지 못합니다.

이게 핵심입니다.

---

# 3. 왜 `memcpy` 자체보다는 "reinterpret cast + memcpy"가 문제인가

`memcpy()` 자체가 무조건 나쁜 것은 아닙니다.

예를 들어:

```cpp
pixel_t src_array[640];
pixel_t dst_array[640];

memcpy(
    dst_array,
    src_array,
    640 * sizeof(pixel_t)
);
```

라면 source와 destination의 element type이 동일합니다.

```text
32bit → 32bit
```

이기 때문에 HLS가 이해하기 쉽습니다.

하지만 기존은:

```cpp
word_t out_line[...];      // 128 bit
```

를

```cpp
(pixel_t*)out_line         // 32 bit pointer로 강제 변환
```

했습니다.

즉:

```text
128-bit storage
   ↓
reinterpret
   ↓
32-bit storage인 것처럼 사용
```

했습니다.

이게 가장 위험한 부분입니다.

---

# 4. 수정 코드에서는 무엇이 달라졌나

수정 버전은 HLS에게 관계를 하나하나 명시했습니다.

```cpp
word_t out_word =
    out_line[w];
```

먼저 BRAM에서 128bit를 읽고,

```cpp
pixel_t p0 =
    out_word.range(
        31,
        0
    );

pixel_t p1 =
    out_word.range(
        63,
        32
    );

pixel_t p2 =
    out_word.range(
        95,
        64
    );

pixel_t p3 =
    out_word.range(
        127,
        96
    );
```

128bit를 정확히 네 조각으로 자릅니다.

그리고:

```cpp
int base =
    oy * DST_SIZE
    +
    w * 4;
```

로 DDR address를 명확하게 계산합니다.

마지막으로:

```cpp
dst[base + 0] = p0;
dst[base + 1] = p1;
dst[base + 2] = p2;
dst[base + 3] = p3;
```

를 써서 실제 메모리 mapping을 명확하게 했습니다.

즉 HLS 관점에서는 이제:

```text
BRAM 128-bit read
        ↓
    bit slicing
        ↓
p0 p1 p2 p3
        ↓
32bit AXI write × 4
```

가 명백합니다.

---

# 5. 실제 하드웨어 실험 결과가 이것을 어떻게 뒷받침하나

이전에 디버깅용으로 아주 단순한 HLS를 만들어서:

```cpp
word_t first_word = src[0];

pixel_t first_pixel =
    first_word.range(
        31,
        0
    );

dst[0] = first_pixel;

for (int i = 1;
     i < DST_SIZE * DST_SIZE;
     i++)
{
    dst[i] =
        (pixel_t)0x00123456;
}
```

처럼 `dst[]`에 직접 써봤을 때는 정상적으로 DDR에 기록됐습니다.

즉 그 테스트로 이미:

```text
PYNQ allocate
      ↓
physical address
      ↓
AXI-Lite pointer register
      ↓
gmem0
      ↓
HLS
      ↓
gmem1
      ↓
SmartConnect
      ↓
PS DDR
```

경로 자체는 정상이라는 것을 확인했습니다.

그러므로 당시 문제가:

```text
DDR 연결 문제
SmartConnect 문제
PYNQ address 문제
cache 문제
AXI-Lite 문제
```

일 가능성이 크게 제거됐습니다.

그리고 최종적으로 **출력 write 코드만 명시적으로 바꾼 뒤 실제 영상이 정상적으로 나왔습니다.**

그래서 현재 증거를 종합하면 가장 강한 원인은:

> `word_t*` → `pixel_t*` 강제 캐스팅을 포함한 `memcpy()`가 HLS 합성에서 기대한 DDR write 구조를 만들지 못한 것

이라고 판단할 수 있습니다.

---

# 6. `out_line` BRAM도 바뀌었다

기존에는:

```cpp
#pragma HLS BIND_STORAGE \
variable=out_line \
type=RAM_1P \
impl=BRAM
```

이었고 수정본에서는:

```cpp
#pragma HLS BIND_STORAGE \
variable=out_line \
type=RAM_2P \
impl=BRAM
```

로 바뀌었습니다.

이것도 차이점입니다.

다만 **정상 동작 여부에 가장 직접적인 영향을 준 변경은 이 부분보다는 출력 write 방식**이라고 보는 것이 타당합니다.

RAM_2P로 바꾼 효과는 주로:

```text
동시에 발생하는 read/write access
pipeline scheduling
memory port conflict
II 달성
```

같은 HLS scheduling 측면입니다.

즉:

```text
RAM_1P → RAM_2P
```

는 성능/스케줄링 안정성 개선이고,

```text
memcpy + cast
→ explicit range extraction + dst[]
```

가 기능적 오류를 해결한 핵심 변경이라고 보는 게 좋습니다.

---

# 7. `get_pix()`도 조금 더 명시적으로 바뀌었다

기존:

```cpp
return (pixel_t)(
    lbuf[w]
    >>
    (pidx * 32)
);
```

수정:

```cpp
word_t current_word =
    lbuf[w];

pixel_t result =
    current_word.range(
        pidx * 32 + 31,
        pidx * 32
    );

return result;
```

이 두 코드는 논리적으로 거의 같은 동작을 합니다.

예를 들어 `pidx = 2`라면 기존은:

```cpp
lbuf[w] >> 64
```

한 뒤 하위 32bit만 `pixel_t`에 넣습니다.

수정은 바로:

```cpp
range(95,64)
```

를 가져옵니다.

따라서 이것도 **가독성과 HLS에 대한 명시성이 좋아진 변경**입니다.

하지만 이것만으로 이전의 “출력 DDR가 갱신되지 않는 문제”가 해결됐다고 보기는 어렵습니다.

---

# 8. 바뀌지 않은 부분도 중요하다

오히려 원인을 판단할 때는 **무엇이 안 바뀌었는지**가 중요합니다.

다음 부분은 사실상 동일합니다.

```text
ROI 좌표 계산
x0 alignment
line buffer 구조
DDR src read
row caching
scaled_w / scaled_h
pad_x / pad_y
x_step / y_step
fixed-point bilinear interpolation
blend4()
4 pixel → 128-bit out_line packing
```

즉 이전 코드가 실패했고 수정 코드가 성공했는데, 위 계산들은 그대로입니다.

따라서:

```text
crop 알고리즘이 잘못됐다
bilinear 계산이 잘못됐다
line buffer에서 input을 못 읽었다
ROI 좌표가 잘못됐다
```

가 주요 원인이었을 가능성은 낮습니다.

---

# 9. 가장 중요한 before / after만 뽑으면

### 기존 구조

```cpp
word_t out_line[MAX_DST / 4];

...

word_t cur =
    out_line[widx];

cur.range(
    pidx * 32 + 31,
    pidx * 32
) = pix;

out_line[widx] =
    cur;

...

memcpy(
    dst + oy * DST_SIZE,
    (pixel_t*)out_line,
    DST_SIZE * sizeof(pixel_t)
);
```

논리적으로는:

```text
out_line
128-bit BRAM
    ↓
C pointer cast
    ↓
32-bit 배열이라고 가정
    ↓
memcpy
    ↓
DDR
```

였습니다.

### 수정 구조

```cpp
word_t out_word =
    out_line[w];

pixel_t p0 =
    out_word.range(31, 0);

pixel_t p1 =
    out_word.range(63, 32);

pixel_t p2 =
    out_word.range(95, 64);

pixel_t p3 =
    out_word.range(127, 96);

int base =
    oy * DST_SIZE
    + w * 4;

dst[base + 0] = p0;
dst[base + 1] = p1;
dst[base + 2] = p2;
dst[base + 3] = p3;
```

논리적으로:

```text
out_line
128-bit BRAM
    ↓
명시적 bit slicing
    ↓
4개의 32-bit pixel
    ↓
명시적 dst address
    ↓
DDR write
```

입니다.

**두 번째 방식이 HLS에 훨씬 명확합니다.**

---

# 10. 왜 기존에는 HLS가 `ap_done`까지 떴는데 화면은 안 나왔는가

이 부분도 설명이 됩니다.

당시:

```text
CTRL = 0xE
```

가 나왔으므로 HLS kernel 자체는 끝까지 실행되었습니다.

그런데 output buffer marker가 그대로 남아 있었습니다.

즉:

```text
HLS start
   ↓
계산 수행
   ↓
ap_done = 1
```

까지는 됐지만,

```text
계산 결과
   ↓
DDR output
```

이 제대로 반영되지 않았던 겁니다.

`ap_done`은:

> 함수 제어 흐름이 끝났다

는 뜻이지,

> 우리가 의도한 데이터가 반드시 DDR에 정확히 써졌다

를 보증하는 신호는 아닙니다.

그래서 당시 증상:

```text
HLS elapsed ≈ 정상
CTRL = 0xE
output = marker 그대로
```

와 이번 원인이 잘 맞습니다.

---

# 11. 이번 수정으로 성능이 약간 느려진 이유도 설명된다

수정본에서는:

```cpp
#pragma HLS PIPELINE II=4
```

로:

```cpp
dst[base + 0] = p0;
dst[base + 1] = p1;
dst[base + 2] = p2;
dst[base + 3] = p3;
```

네 번의 32bit write를 수행합니다.

기존 `memcpy()`는 HLS가 이상적으로 해석했다면 burst transfer로 더 효율적인 구조를 만들 여지가 있었습니다.

하지만 지금은:

```text
correctness 우선
```

으로 직접 32bit write를 명시했습니다.

그래서 실제 측정이 약:

```text
24.37 ms/frame
≈ 41 FPS
```

정도였던 것도 자연스럽습니다.

즉 이번 수정은:

```text
더 명확한 hardware behavior
      ↑
기능 안정성

대신

4 × 32bit explicit write
      ↓
일부 throughput 손실 가능
```

이라는 trade-off가 있습니다.

---

# 12. 보고서에는 이렇게 정리하면 가장 정확하다

프로젝트 보고서에서는 원인을 다음 정도로 표현하면 좋습니다.

> 초기 HLS 구현에서는 128-bit 내부 출력 버퍼(`ap_uint<128>`)를 32-bit 출력 포인터(`ap_uint<32>*`)로 강제 형변환한 뒤 `memcpy()`를 사용하여 DDR로 전송하였다. 해당 구조는 C/C++ 수준에서는 메모리 재해석으로 표현 가능하지만, HLS 합성 과정에서는 서로 다른 arbitrary-precision 데이터 타입 간의 포인터 재해석 및 메모리 전송 구조가 명확하지 않아 예상한 AXI 출력 write 동작이 생성되지 않았다. 이를 해결하기 위해 128-bit 출력 워드를 4개의 32-bit 픽셀로 명시적으로 분리하고 각 픽셀을 `dst[]`에 직접 기록하도록 수정하였다. 수정 후 DDR 출력 데이터가 정상적으로 갱신되었으며 실제 영상에 대해 ROI crop 및 resize 동작이 확인되었다.

그리고 한 문장으로 핵심만 쓰면:

> **문제의 핵심은 resize 연산이 아니라 `128-bit 내부 버퍼 → 32-bit AXI 출력` 사이의 데이터 폭 변환 및 DDR write 구현 방식이었다.**

이 표현이 현재 실험 결과와 가장 잘 맞습니다.

# 13. 성능

=== Kernel-only test ===

=== Transfer + Kernel test ===

====================================
 ROI + Resize Performance
====================================
Resolution : 640x480 -> 640x640
ROI        : 480x480
Iterations : 1000

[Kernel only]
Total time : 12.7542 sec
Avg latency: 12.7542 ms
FPS        : 78.4053

[Transfer + Kernel]
Total time : 12.7614 sec
Avg latency: 12.7614 ms
FPS        : 78.361
====================================



