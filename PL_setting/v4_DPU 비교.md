좋아. 이제 **B4096 실패 정도까지 정확하게 확보됐어.** 결과는 다음이야.

| DPU       |           WNS |           TNS | Setup 실패 endpoint |       WHS | THS | 결과       |
| --------- | ------------: | ------------: | ----------------: | --------: | --: | -------- |
| B2304     |     +0.003 ns |             0 |                 0 | +0.009 ns |   0 | PASS     |
| B3136     |     +0.002 ns |             0 |                 0 | +0.006 ns |   0 | PASS     |
| **B4096** | **-0.046 ns** | **-0.666 ns** |            **74** | +0.006 ns |   0 | **FAIL** |

즉 B4096은 **hold는 문제없고 setup timing에서 실패**한 거야.

```text
WNS = -0.046 ns = -46 ps
TNS = -0.666 ns
Failing endpoints = 74
```

`WNS=-0.046 ns`라는 것은 가장 나쁜 경로가 요구시간보다 **46 ps 늦었다**는 뜻이야.

### 이 결과에서 중요한 점

B2304와 B3136은 정말 아슬아슬하게 성공했어.

```text
B2304 : +3 ps
B3136 : +2 ps
B4096 : -46 ps
```

DPU 규모를 키우면서 timing 상황이:

```text
B2304       B3136        B4096
 +3 ps  →    +2 ps   →    -46 ps
 PASS        PASS         FAIL
```

로 악화된 흐름이 명확해.

그리고 B4096은 단순히 경로 하나가 약간 실패한 것도 아니야.

```text
74 failing endpoints
TNS = -0.666 ns
```

이 있기 때문에 **현재 동일 implementation 조건에서는 timing closure가 안 된 설계**라고 기록하는 게 맞아.

### 보고서에서는 이렇게 해석하면 돼

> DPU 병렬도를 B2304에서 B3136 및 B4096으로 증가시키며 동일한 PL 전처리 IP와 구현 조건에서 타이밍을 비교하였다. B2304와 B3136은 각각 WNS +0.003 ns와 +0.002 ns로 timing closure를 만족한 반면, B4096은 WNS -0.046 ns, TNS -0.666 ns 및 74개의 setup violating endpoints가 발생하여 timing constraint를 만족하지 못하였다.

여기서 중요한 표현은 **“B4096은 KV260에서 사용할 수 없다”가 아니라**, 더 정확하게:

> **현재의 KV260 플랫폼, 300/600 MHz DPU clock, PL 전처리 IP 및 동일 implementation strategy 조건에서는 B4096이 timing closure를 달성하지 못했다.**

라고 해야 해.

---

## 그러면 B2304 선택 이유가 완성됐나?

**아직 절반 정도야.**

현재 hardware implementation 측면에서는:

```text
B4096
→ 탈락 가능

B2304
→ 구현 가능

B3136
→ 구현 가능
```

이니까 이제 진짜 최종 경쟁은:

```text
B2304 vs B3136
```

이야.

B3136도 정상적으로 timing을 통과했기 때문에 단순히:

> B2304가 timing 때문에 선택됐다.

라고 하면 안 돼.

이제 B2304와 B3136을 보드에서 비교해서:

1. **DPU latency**
2. **전체 processing latency**
3. **SOM power**
4. **FPS/W**
5. **자원 증가량**

을 봐야 해.

예를 들어 결과가:

```text
             B2304        B3136
DPU          17.5 ms       15.5 ms
전체          34.5 ms       32.5 ms
카메라 FPS    15 FPS        15 FPS
전력          낮음          증가
자원          낮음          높음
```

이라면 B3136이 DPU에서는 빨라도 **실제 시스템은 어차피 카메라 15 FPS에 제한**되고 자원/전력은 더 많이 쓰니까 B2304 선택 근거가 아주 좋아져.

반대로 B3136이 전력도 거의 안 증가하고 DPU latency가 크게 떨어지면 **B3136을 최종 선택하는 것이 더 논리적**이고.

### 지금 다음으로 해야 할 일

B4096은 여기서 일단 멈춰도 돼. `Performance_EarlyBlockPlacement` 외의 strategy를 여러 개 시험해서 살릴 수도 있지만, **지금 프로젝트의 architecture 비교 목적에는 우선순위가 낮아.**

현재 결과를 보존하고:

```text
B4096
WNS = -0.046 ns
TNS = -0.666 ns
Setup failing endpoints = 74
WHS = +0.006 ns
THS = 0
Timing FAIL
```

로 기록해.

그다음 **B3136을 실제 KV260에 올려서 B2304와 DPU 성능을 비교하는 게 다음 작업**이야. 이 비교까지 나오면 왜 B2304를 쓰는지, 아니면 B3136으로 올라가는 게 맞는지를 데이터로 결정할 수 있어.
