{%if settings.clock_period and design.rtl.clock_port-%} create_clock -period {{ "%.3f"|format(settings.clock_period) }} -name clock [get_ports {{design.rtl.clock_port}}] {%-endif%}

derive_pll_clocks
derive_clock_uncertainty