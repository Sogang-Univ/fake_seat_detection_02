# =============================================================
# run_hls_letterbox.tcl  --  Vitis HLS 배치 빌드 (letterbox_resize)
#
#   vitis_hls -f run_hls_letterbox.tcl -tclargs csim
#   vitis_hls -f run_hls_letterbox.tcl -tclargs all
# =============================================================

set PROJ    "letterbox_prj"
set SOL     "sol1"
set TOP     "letterbox_resize"
set PART    "xck26-sfvc784-2LV-c"
set PERIOD  5

# vitis_hls 2022.2 는 argv 에 "-f <tcl> <step>" 전체를 넘기므로 마지막 원소를 읽는다
set VALID_STEPS {csim synth cosim export all}
set STEP "all"
if {$argc > 0} {
    set LAST [lindex $argv end]
    if {[lsearch -exact $VALID_STEPS $LAST] >= 0} {
        set STEP $LAST
    } else {
        puts "ERROR: unknown step '$LAST'"
        puts "  usage: vitis_hls -f run_hls_letterbox.tcl -tclargs \[csim|synth|cosim|export|all\]"
        exit 1
    }
}

puts "=========================================="
puts " STEP = $STEP  (letterbox_resize)"
puts "=========================================="

open_project -reset $PROJ
set_top $TOP

add_files letterbox.cpp
add_files -tb letterbox_tb.cpp

open_solution -reset $SOL -flow_target vivado
set_part $PART
create_clock -period $PERIOD -name default

switch $STEP {
    csim   { csim_design }
    synth  { csynth_design }
    cosim  { csynth_design ; cosim_design }
    export { csynth_design ; export_design -format ip_catalog }
    all    {
        csim_design
        csynth_design
        cosim_design
        export_design -format ip_catalog
    }
}

puts "=========================================="
puts " DONE: step = $STEP"
puts "=========================================="

exit
