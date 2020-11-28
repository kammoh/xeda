puts "\n================================( Opening routed design from checkpoint )================================="
open_checkpoint {{checkpoint}}

{% for rc in run_configs %}
puts "\n================================( Reporting power from {{rc.saif}} )================================="
reset_switching_activity -all
eval read_saif -verbose {{rc.saif}}
report_power -hier all -format xml -verbose -file {{rc.report}}

{% endfor %}