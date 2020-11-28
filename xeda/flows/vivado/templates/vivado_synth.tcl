# These settings are set by XEDA
set design_name           {{design.name}}
set vhdl_std              {{design.language.vhdl.standard}}
set debug                 {{debug}}
set nthreads              {{nthreads}}

set fail_critical_warning {{flow.fail_critical_warning}}
set fail_timing           {{flow.fail_timing}}
set bitstream             false

set reports_dir           {{reports_dir}}
set results_dir           {{results_dir}}
set checkpoints_dir       {{checkpoints_dir}}

{% include 'util.tcl' %}

# TODO move all strategy-based decisions to Python side
puts "Using \"{{flow.strategy}}\" synthesis strategy"

set_param general.maxThreads ${nthreads}

file mkdir ${results_dir}
file mkdir ${reports_dir}
file mkdir [file join ${reports_dir} post_synth]
file mkdir [file join ${reports_dir} post_place]
file mkdir [file join ${reports_dir} post_route]
file mkdir ${checkpoints_dir}

# suppress some warning messages
# warning partial connection
set_msg_config -id "\[Synth 8-350\]" -suppress
# info do synthesis
set_msg_config -id "\[Synth 8-256\]" -suppress
set_msg_config -id "\[Synth 8-638\]" -suppress
# BRAM mapped to LUT due to optimization
set_msg_config -id "\[Synth 8-3969\]" -suppress
# BRAM with no output register
set_msg_config -id "\[Synth 8-4480\]" -suppress
# DSP without input pipelining
set_msg_config -id "\[Drc 23-20\]" -suppress
# Update IP version
set_msg_config -id "\[Netlist 29-345\]" -suppress   

set parts [get_parts]

puts "\n================================( Read Design Files and Constraints )================================"

if {[lsearch -exact $parts {{flow.fpga_part}}] < 0} {
    puts "ERROR: device {{flow.fpga_part}} is not supported!"
    puts "Supported devices: $parts"
    quit
}

puts "Targeting device: {{flow.fpga_part}}"

# DO NOT use per file vhdl version as not supported universally (even though our data structures support it)
set vhdl_std_opt [expr {$vhdl_std == "08" ?  "-vhdl2008": ""}];

{% for src in design.rtl.sources %}
{%- if src.type == 'verilog' %}
{%- if src.variant == 'systemverilog' %}
puts "Reading SystemVerilog file {{src.file}}"
if { [catch {eval read_verilog -sv {{src.file}} } myError]} {
    errorExit $myError
}
{% else %}
puts "Reading Verilog file {{src.file}}"
if { [catch {eval read_verilog {{src.file}} } myError]} {
    errorExit $myError
}
{%- endif %}
{%- endif %}
{% if src.type == 'vhdl' %}
puts "Reading VHDL file {{src.file}} ${vhdl_std_opt}"
if { [catch {eval read_vhdl ${vhdl_std_opt} {{src.file}} } myError]} {
    errorExit $myError
}
{%- endif %}
{%- endfor %}

# TODO: Skip saving some artifects in case timing not met or synthesis failed for any reason

{% for xdc_file in xdc_files %}
read_xdc {{xdc_file}}
{% endfor %}

puts "\n===========================( RTL Synthesize and Map )==========================="
## eval synth_design -rtl -rtl_skip_ip -top {{design.rtl.top}} {{options.synth}} {{generics_options}}
## write_verilog -force ${results_dir}/synth_rtl.v

eval synth_design -part {{flow.fpga_part}} -top {{design.rtl.top}} {{options.synth}} {{generics_options}}
{% if flow.strategy == "Debug" %}
set_property KEEP_HIERARCHY true [get_cells -hier * ]
set_property DONT_TOUCH true [get_cells -hier * ]
{% endif %}
showWarningsAndErrors


{% if flow.strategy != "Debug" and flow.strategy != "Runtime" %}
puts "\n==============================( Optimize Design )================================"
eval opt_design {{options.opt}}
{% endif %}


puts "==== Synthesis and Mapping Steps Complemeted ====\n"
write_checkpoint -force ${checkpoints_dir}/post_synth
report_timing_summary -file ${reports_dir}/post_synth/timing_summary.rpt
report_utilization -file ${reports_dir}/post_synth/utilization.rpt
report_utilization -file ${reports_dir}/post_synth/utilization.xml -format xml
reportCriticalPaths ${reports_dir}/post_synth/critpath_report.csv
report_methodology  -file ${reports_dir}/post_synth/methodology.rpt

## TODO FIXME
{% if True or flow.strategy == "Power" %}
puts "\n===============================( Post-synth Power Optimization )================================"
# this is more effective than Post-placement Power Optimization but can hurt timing
eval power_opt_design
report_power_opt -file ${reports_dir}/post_synth/power_optimization.rpt
showWarningsAndErrors
{% endif %}

puts "\n================================( Place Design )================================="
eval place_design {{options.place}}
showWarningsAndErrors


{% if False and flow.strategy != "Power" and flow.optimize_power %}
puts "\n===============================( Post-placement Power Optimization )================================"
eval power_opt_design
report_power_opt -file ${reports_dir}/post_synth/post_place_power_optimization.rpt
showWarningsAndErrors
{% endif %}

{% if flow.strategy != "Debug" and flow.strategy != "Runtime" %}
puts "\n==============================( Post-place optimization )================================"
eval opt_design {{options.place_opt}}
{% endif %}


{% if flow.strategy != "Debug" and flow.strategy != "Runtime" %}
puts "\n========================( Physical Optimization )=========================="
eval phys_opt_design {{options.phys_opt}}
{% endif %}


write_checkpoint -force ${checkpoints_dir}/post_place
report_timing_summary -max_paths 10 -file ${reports_dir}/post_place/timing_summary.rpt

puts "\n================================( Route Design )================================="
eval route_design {{options.route}}
showWarningsAndErrors

## {% if flow.strategy != "Debug" and flow.strategy != "Runtime" %}
## puts "\n=========================( Physically Optimize Design 2)=========================="
## eval phys_opt_design {{options.phys_opt}}
## showWarningsAndErrors
## {% endif %}

puts "\n=============================( Writing Checkpoint )=============================="
write_checkpoint -force ${checkpoints_dir}/post_route

puts "\n==============================( Writing Reports )================================"
report_timing_summary -max_paths 10                             -file ${reports_dir}/post_route/timing_summary.rpt
report_timing  -sort_by group -max_paths 100 -path_type summary -file ${reports_dir}/post_route/timing.rpt
reportCriticalPaths ${reports_dir}/post_route/critpath_report.csv
## report_clock_utilization                                        -force -file ${reports_dir}/post_route/clock_utilization.rpt
report_utilization                                              -force -file ${reports_dir}/post_route/utilization.rpt
## report_utilization                                              -force -file ${reports_dir}/post_route/utilization.xml -format xml
report_utilization -hierarchical                                -force -file ${reports_dir}/post_route/hierarchical_utilization.rpt
## report_utilization -hierarchical                                -force -file ${reports_dir}/post_route/hierarchical_utilization.xml -format xml
report_power                                                    -file ${reports_dir}/post_route/power.rpt
report_drc                                                      -file ${reports_dir}/post_route/drc.rpt
## report_ram_utilization                                          -file ${reports_dir}/post_route/ram_utilization.rpt -append
report_methodology                                              -file ${reports_dir}/post_route/methodology.rpt

set timing_slack [get_property SLACK [get_timing_paths]]
puts "Final timing slack: $timing_slack ns"

if {$timing_slack < 0} {
    puts "\n===========================( *ENABLE ECHO* )==========================="
    puts "ERROR: Failed to meet timing by $timing_slack, see [file join ${reports_dir} post_route timing_summary.rpt] for details"
    if {$fail_timing} {
        exit 1
    }
    puts "\n===========================( *DISABLE ECHO* )==========================="
} else {
    puts "\n==========================( Writing Netlist and SDF )============================="
    write_sdf -mode timesim -process_corner slow -force -file ${results_dir}/impl_timesim.sdf
    # should match sdf
    write_verilog -mode timesim -sdf_anno false -force -file ${results_dir}/impl_timesim.v
##    write_verilog -mode timesim -sdf_anno false -include_xilinx_libs -write_all_overrides -force -file ${results_dir}/impl_timesim_inlined.v
##    write_verilog -mode funcsim -force ${results_dir}/impl_funcsim_noxlib.v
##    write_vhdl    -mode funcsim -include_xilinx_libs -write_all_overrides -force -file ${results_dir}/impl_funcsim.vhd
    write_xdc -no_fixed_only -force ${results_dir}/impl.xdc

    if {${bitstream}} {
        puts "\n==============================( Writing Bitstream )==============================="
        write_bitstream -force ${results_dir}/bitstream.bit
    }
    showWarningsAndErrors
}
