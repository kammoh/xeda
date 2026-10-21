- Changing `quiet`, `print_commands` or `redirect_stdout` no longer runs a finished flow again.
  `quiet` no longer adds `-quiet` to `log_vcd` in `vivado_sim`, which made the command ignore its
  errors.
