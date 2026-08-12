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

============================================
 IDLE POWER
============================================
samples     : 15
idle avg    : 4.893 W
idle std    : 0.009 W
idle min    : 4.880 W
idle max    : 4.910 W

============================================
 CPU E2E POWER TEST
============================================

Cooldown 10 seconds...

============================================
 PL E2E POWER TEST
============================================


============================================
 FINAL IDLE POWER
============================================
samples             : 15
average             : 4.893 W
std                 : 0.009 W
min                 : 4.880 W
max                 : 4.910 W

============================================
 FINAL CPU E2E + POWER
============================================
processed frames    : 1174
measurement time    : 60.028 s

CPU preprocess      : 24.779 ms
  crop              : 0.018 ms
  resize            : 4.981 ms
  BGR->RGB          : 0.444 ms
  quant             : 19.335 ms
DPU                 : 17.361 ms
decode              : 8.863 ms
logic               : 0.036 ms
E2E                 : 51.108 ms
processing FPS      : 19.56

power samples       : 30
SOM power avg       : 6.101 W
SOM power std       : 0.621 W
SOM power min       : 5.120 W
SOM power max       : 7.370 W
dynamic power       : 1.208 W
FPS/W               : 3.206
energy/frame        : 311.950 mJ
dynamic energy/frame: 61.749 mJ

============================================
 FINAL PL E2E + POWER
============================================
processed frames    : 1901
measurement time    : 60.027 s

PL preprocess       : 5.290 ms
  packing           : 0.650 ms
  H2D               : 0.028 ms
  HLS               : 3.710 ms
  D2H               : 0.088 ms
  memcpy            : 0.521 ms
DPU                 : 17.301 ms
decode              : 8.859 ms
logic               : 0.034 ms
E2E                 : 31.551 ms
processing FPS      : 31.67

power samples       : 30
SOM power avg       : 6.264 W
SOM power std       : 0.763 W
SOM power min       : 5.120 W
SOM power max       : 7.290 W
dynamic power       : 1.371 W
FPS/W               : 5.055
energy/frame        : 197.805 mJ
dynamic energy/frame: 43.291 mJ

============================================
 FINAL CPU vs PL POWER COMPARISON
============================================
Idle SOM power      : 4.893 W

CPU preprocess      : 24.779 ms
PL preprocess       : 5.290 ms
Preprocess speedup  : 4.684 x
Preprocess reduction: 78.65 %

CPU E2E             : 51.108 ms
PL E2E              : 31.551 ms
E2E speedup         : 1.620 x
E2E latency reduction: 38.27 %

CPU processing FPS  : 19.56
PL processing FPS   : 31.67

CPU SOM power       : 6.101 W
PL SOM power        : 6.264 W
PL power difference : +2.68 %

CPU dynamic power   : 1.208 W
PL dynamic power    : 1.371 W

CPU FPS/W           : 3.206
PL FPS/W            : 5.055
FPS/W improvement   : 1.577 x

CPU energy/frame    : 311.950 mJ
PL energy/frame     : 197.805 mJ
Energy reduction    : 36.59 %

CPU dynamic E/frame : 61.749 mJ
PL dynamic E/frame  : 43.291 mJ
Dynamic E reduction : 29.89 %

