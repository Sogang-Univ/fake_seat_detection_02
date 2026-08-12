# =============================================================
# run_hls.tcl  --  Vitis HLS 배치 빌드 (crop_and_resize)
#
#   기본 실행:  vitis_hls -f run_hls.tcl
#   단계 선택:  vitis_hls -f run_hls.tcl -tclargs csim
#               vitis_hls -f run_hls.tcl -tclargs synth
#               vitis_hls -f run_hls.tcl -tclargs cosim
#               vitis_hls -f run_hls.tcl -tclargs export
#               vitis_hls -f run_hls.tcl -tclargs all     (기본값)
# =============================================================
set PROJ    "crop_resize"
set SOL     "solution1"
set TOP     "crop_and_resize"
set PART    "xck26-sfvc784-2LV-c"
set PERIOD  10                    ;# 10ns = 100MHz

# ── step 인자 파싱 (roi_crop 스타일 그대로) ─────────────────
# 안전한 step 파싱: 옵션(-로 시작) 무시하고 마지막 non-option 인자를 step으로 사용
set VALID_STEPS {csim synth cosim export all}
set STEP "all"

# 필터링: argv에서 -로 시작하는 항목 제거
set filtered_args {}
foreach a $argv {
    if {![string match -* $a]} {
        lappend filtered_args $a
    }
}

if {[llength $filtered_args] > 0} {
    set LAST [lindex $filtered_args end]
    if {[lsearch -exact $VALID_STEPS $LAST] >= 0} {
        set STEP $LAST
    } else {
        puts "ERROR: unknown step '$LAST'"
        puts "  usage: vitis_hls -f run_hls.tcl -tclargs [csim|synth|cosim|export|all]"
        exit 1
    }
}
puts "=========================================="
puts " STEP = $STEP  (crop_and_resize)"
puts "=========================================="

# ── 프로젝트 셋업 (roi_crop 스타일: -reset 으로 매번 초기화) ─
open_project -reset $PROJ
set_top $TOP
add_files crop_resize.cpp
add_files crop_resize.hpp
add_files -tb crop_resize_tb.cpp
open_solution -reset $SOL -flow_target vivado
set_part $PART
create_clock -period $PERIOD -name default

# ── 단계 실행 (roi_crop 스타일 그대로) ──────────────────────
switch $STEP {
    csim   { csim_design -clean }
    synth  { csynth_design }
    cosim  { csynth_design
             cosim_design -O -rtl verilog }
    export { csynth_design
             export_design -format ip_catalog }
    all    { csim_design -clean
             csynth_design
             cosim_design -O -rtl verilog
             export_design -format ip_catalog }
}

puts "=========================================="
puts " DONE: step = $STEP"
puts "=========================================="
exit 0
