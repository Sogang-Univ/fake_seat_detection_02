========================================
 FINAL CPU PERFORMANCE
========================================
CPU processed frames : 300
CPU preprocess       : 25.012 ms
  crop               : 0.019 ms
  resize             : 5.022 ms
  BGR->RGB           : 0.447 ms
  quant              : 19.524 ms
DPU                  : 17.379 ms
decode               : 8.867 ms
logic                : 0.034 ms
E2E                  : 51.366 ms
E2E std              : 1.414 ms
E2E min              : 49.830 ms
E2E max              : 60.702 ms
processing FPS       : 19.47
300-frame total      : 15.413 s

========================================
 FINAL PL PERFORMANCE
========================================
PL processed frames  : 300
PL preprocess        : 5.336 ms
  packing            : 0.647 ms
  H2D                : 0.028 ms
  HLS                : 3.713 ms
  D2H                : 0.087 ms
  memcpy             : 0.550 ms
DPU                  : 17.342 ms
decode               : 8.862 ms
logic                : 0.034 ms
E2E                  : 31.643 ms
E2E std              : 0.276 ms
E2E min              : 31.395 ms
E2E max              : 35.553 ms
processing FPS       : 31.60
300-frame total      : 9.497 s

========================================
 FINAL CPU vs PL COMPARISON
========================================
Compared frames      : 300
Camera acquired FPS  : 29.13

CPU preprocess       : 25.012 ms
PL preprocess        : 5.336 ms
Preprocess speedup   : 4.687 x
Preprocess reduction : 78.66 %

CPU DPU              : 17.379 ms
PL DPU               : 17.342 ms
CPU decode           : 8.867 ms
PL decode            : 8.862 ms

CPU E2E              : 51.366 ms
PL E2E               : 31.643 ms
E2E speedup          : 1.623 x
E2E latency reduction: 38.40 %

CPU processing FPS   : 19.47
PL processing FPS    : 31.60
FPS improvement      : 62.33 %

CPU final state      : EMPTY
PL final state       : EMPTY
