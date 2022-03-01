# © 2020 [Kamyar Mohajerani](mailto:kamyar@ieee.org)

from typing import Literal
from pydantic.fields import Field
from ..flow import Flow, FpgaSynthFlow, SimFlow, SynthFlow
from ...utils import parse_csv


class Quartus(FpgaSynthFlow):
    class Settings(FpgaSynthFlow.Settings):
        optimization_mode: Literal[
            "BALANCED",
            "HIGH PERFORMANCE EFFORT",
            "AGGRESSIVE PERFORMANCE",
            "High Performance with Maximum Placement Effort",
            "Superior Performance",
            "Superior Performance with Maximum Placement Effort",
            "Aggressive Area",
            "High Placement Routability Effort",
            "High Packing Routability Effort",
            "Optimize Netlist for Routability",
            "High Power Effort",
        ] = Field("HIGH PERFORMANCE EFFORT", description="""
            see https://www.intel.com/content/www/us/en/programmable/documentation/zpr1513988353912.html
            https://www.intel.com/content/www/us/en/programmable/quartushelp/current/index.htm
        """)
        remove_redundant_logic: bool = True
        auto_resource_sharing: bool = True
        retiming: bool = True
        register_duplication: bool = True
        packed_registers: bool = False
        gated_clock_conversion: bool = True
        dsp_recognition: bool = True
        ram_recognition: bool = True
        rom_recognition: bool = True
        synthesis_effort: Literal[
            "auto",
            "fast"
        ] = "auto"
        fitter_effort: Literal[
            "STANDARD FIT",
            "AUTO FIT", "FAST_FIT"
        ] = "STANDARD FIT"
        optimization_technique: Literal["AREA", "SPEED", "BALANCED"] = "SPEED"
        placement_effort_multiplier: float = Field(2.0, description="""
        A logic option that controls how much time the Fitter spends in placement. 
        The default value is 1.0 and legal values must be greater than 0 and can be non-integer values.
        Values between 0 and 1 can reduce fitting time, but also can reduce placement quality and design performance.
        Values greater than 1 increase placement time and placement quality, but may reduce routing time for designs with routing congestion.
        For example, a value of 4 increases fitting time by approximately 2 to 4 times, but may improve quality."""
                                                   )
        router_timing_optimization_level: Literal["Normal",
                                                  "Maximum", "Minimum"] = "Maximum"
        final_placement_optimization: Literal["ALWAYS",
                                              "AUTOMATICALLY", "NEVER"] = "ALWAYS"

    def init(self):
        self.artifacts = {
            'reports': {
                'utilization': self.reports_dir / 'Fitter' / 'Resource_Section' / 'Fitter_Resource_Utilization_by_Entity.csv',
                'timing': self.reports_dir / 'Timing_Analyzer' / 'Multicorner_Timing_Analysis_Summary.csv',
            },
        }
        return super().init()

    def create_project(self, **kwargs):
        ss = self.settings

        project_settings = {

            "OPTIMIZATION_MODE": ss.optimization_mode,
            "REMOVE_REDUNDANT_LOGIC_CELLS": ss.remove_redundant_logic,
            "AUTO_RESOURCE_SHARING": ss.auto_resource_sharing,
            "ALLOW_REGISTER_RETIMING": ss.retiming,

            "SYNTH_GATED_CLOCK_CONVERSION": ss.gated_clock_conversion,


            # faster:
            "FITTER_EFFORT": ss.fitter_effort,

            # AREA, SPEED, BALANCED
            "STRATIX_OPTIMIZATION_TECHNIQUE": ss.optimization_technique,
            "CYCLONE_OPTIMIZATION_TECHNIQUE": ss.optimization_technique,

            # see https://www.intel.com/content/www/us/en/programmable/documentation/rbb1513988527943.html
            "PLACEMENT_EFFORT_MULTIPLIER": ss.placement_effort_multiplier,

            "ROUTER_TIMING_OPTIMIZATION_LEVEL": ss.router_timing_optimization_level,

            "FINAL_PLACEMENT_OPTIMIZATION": ss.final_placement_optimization,
            # "PHYSICAL_SYNTHESIS_COMBO_LOGIC_FOR_AREA": "ON",
            # ?
            # "ADV_NETLIST_OPT_SYNTH_GATE_RETIME": "ON",
            # ?
            # "ADV_NETLIST_OPT_SYNTH_WYSIWYG_REMAP": "ON",

            "AUTO_PACKED_REGISTERS_STRATIX": ss.packed_registers,
            "AUTO_PACKED_REGISTERS_CYCLONE": ss.packed_registers,
            "PHYSICAL_SYNTHESIS_COMBO_LOGIC": "ON",
            "PHYSICAL_SYNTHESIS_REGISTER_DUPLICATION": ss.register_duplication,
            "PHYSICAL_SYNTHESIS_REGISTER_RETIMING": ss.retiming,

            # "PHYSICAL_SYNTHESIS_EFFORT": "EXTRA",

            #NORMAL, OFF, EXTRA_EFFORT
            # "OPTIMIZE_POWER_DURING_SYNTHESIS": "NORMAL",
            # SYNTH_CRITICAL_CLOCK: ON, OFF : Speed Optimization Technique for Clock Domains}
            "AUTO_DSP_RECOGNITION": ss.dsp_recognition,
            "AUTO_RAM_RECOGNITION": ss.ram_recognition,
            "AUTO_ROM_RECOGNITION": ss.rom_recognition,

            "FLOW_ENABLE_POWER_ANALYZER": True
        }

        clock_sdc_path = self.copy_from_template(f'clock.sdc')
        script_path = self.copy_from_template(
            f'create_project.tcl',
            sdc_files=[clock_sdc_path],
            project_settings=project_settings,
            **kwargs
        )
        self.run_tool('quartus_sh', ['-t', script_path])

        # self.run_process('quartus_sh',
        #                  ['--dse', '-project', self.settings.design['name'], '-nogui', '-concurrent-compiles', '8', '-exploration-space',
        #                   "Extra Effort Space", '-optimization-goal', "Optimize for Speed", '-report-all-resource-usage', '-ignore-failed-base'],
        #                  stdout_logfile='dse_stdout.log'
        #                  )

    # def __init__(self, settings, args, logger):
    #     # def supported_quartus_generic(k, v, sim):
    #     #     if sim:
    #     #         return True
    #     #     if isinstance(v, int):
    #     #         return True
    #     #     if isinstance(v, bool):
    #     #         return True
    #     #     v = str(v)
    #     #     return (v.isnumeric() or (v.strip().lower() in {'true', 'false'}))

    #     # def quartus_gen_convert(k, x, sim):
    #     #     if sim:
    #     #         if isinstance(x, dict) and "file" in x:
    #     #             p = x["file"]
    #     #             assert isinstance(p, str), "value of `file` should be a relative or absolute path string"
    #     #             x = self.conv_to_relative_path(p.strip())
    #     #             self.logger.info(f'Converting generic `{k}` marked as `file`: {p} -> {x}')
    #     #     xl = str(x).strip().lower()
    #     #     if xl == 'false':
    #     #         return "1\\'b0"
    #     #     if xl == 'true':
    #     #         return "1\\'b1"
    #     #     return x

    #     # def quartus_generics(kvdict, sim):
    #     #     return ' '.join([f"-generic {k}={quartus_gen_convert(k, v, sim)}" for k, v in kvdict.items() if supported_quartus_generic(k, v, sim)])

    #     super().__init__(settings, args, logger)

    #     # self.settings.flow['generics_options'] = quartus_generics(self.settings.design["generics"], sim=False)
    #     # self.settings.flow['tb_generics_options'] = quartus_generics(self.settings.design["tb_generics"], sim=True)

    def run(self):
        self.create_project()
        script_path = self.copy_from_template(f'compile.tcl', reports_dir=self.reports_dir)
        self.run_tool('quartus_sh', ['-t', str(script_path)])
        # self.run_process('quartus_eda', [prj_name, '--simulation', '--functional', '--tool=modelsim_oem', '--format=verilog'],
        #                         stdout_logfile='eda_1_stdout.log'
        #                         )

    def parse_reports(self):
        failed = False
        reports = self.artifacts.get('reports')
        def try_int(s: str):
            s = s.strip()
            try:
                return int(s)
            except ValueError:
                return s

        resources = parse_csv(
            reports['utilization'],
            id_field='Compilation Hierarchy Node',
            field_parser=lambda s: try_int(s.split()[0]),
            id_parser=lambda s: s.strip()[1:],
            interesting_fields=['Logic Cells', 'Memory Bits', 'M9Ks', 'DSP Elements',
                                'LUT-Only LCs',	'Register-Only LCs', 'LUT/Register LCs']
        )

        top_resources = resources[self.design.rtl.top]
        top_resources['lut'] = top_resources['LUT-Only LCs'] + \
            top_resources['LUT/Register LCs']
        top_resources['ff'] = top_resources['Register-Only LCs'] + \
            top_resources['LUT/Register LCs']

        self.results.update(top_resources)

        # TODO is this the most reliable timing report?
        def try_float(s: str):
            s = s.strip()
            try:
                return float(s)
            except ValueError:
                return s
        slacks = parse_csv(
            reports['timing'],
            id_field='Clock',
            field_parser=try_float,
            id_parser=lambda s: s.strip(),
            interesting_fields=['Setup', 'Hold']
        )
        worst_slacks = slacks['Worst-case Slack']
        wns = worst_slacks['Setup']
        whs = worst_slacks['Hold']
        self.results['wns'] = wns
        self.results['whs'] = whs

        failed |= wns < 0 or whs < 0

        vcc = '1200mV'
        corner = 'Slow'
        for temp in ['85C', '0C']:
            fmax = parse_csv(
                self.reports_dir / 'Timing_Analyzer' /
                f'{corner}_{vcc}_{temp}_Model' /
                f'{corner}_{vcc}_{temp}_Model_Fmax_Summary.csv',
                id_field='Clock Name',
                field_parser=lambda s: s.strip().split(),
                id_parser=lambda s: s.strip(),
                interesting_fields=['Fmax']
            )
            self.results[f'fmax_{temp}'] = fmax['clock']['Fmax']

        temp = '85C'
        self.results['clock_frequency'] = self.results[f'fmax_{temp}']

        self.results['success'] = not failed


# class QuartusPower(QuartusSynth, SimFlow):
#     def run(self):
#         self.create_project(vcd=self.settings.flow.get('vcd'))
#         script_path = self.copy_from_template(f'compile.tcl')
#         self.run_process('quartus_sh',
#                          ['-t', str(script_path)],
#                          stdout_logfile='compile_stdout.log'
#                          )

#     def parse_reports(self):
#         failed = False

#         resources = parse_csv(
#             self.reports_dir / 'Fitter' / 'Resource_Section' / 'Fitter_Resource_Utilization_by_Entity.csv',
#             id_field='Compilation Hierarchy Node',
#             field_parser=lambda s: int(s.split()[0]),
#             id_parser=lambda s: s.strip()[1:],
#             interesting_fields=['Logic Cells', 'Memory Bits', 'M9Ks', 'DSP Elements',
#                                 'LUT-Only LCs',	'Register-Only LCs', 'LUT/Register LCs']
#         )

#         top_resources = resources[self.settings.design['top']]

#         top_resources['lut'] = top_resources['LUT-Only LCs'] + top_resources['LUT/Register LCs']
#         top_resources['ff'] = top_resources['Register-Only LCs'] + top_resources['LUT/Register LCs']

#         self.results.update(top_resources)

#         # TODO is this the most reliable timing report?
#         slacks = parse_csv(
#             self.reports_dir / 'Timing_Analyzer' / 'Multicorner_Timing_Analysis_Summary.csv',
#             id_field='Clock',
#             field_parser=lambda s: float(s.strip()),
#             id_parser=lambda s: s.strip(),
#             interesting_fields=['Setup', 'Hold']
#         )
#         worst_slacks = slacks['Worst-case Slack']
#         wns = worst_slacks['Setup']
#         whs = worst_slacks['Hold']
#         self.results['wns'] = wns
#         self.results['whs'] = whs

#         failed |= wns < 0 or whs < 0

#         for temp in ['85C', '0C']:
#             fmax = parse_csv(
#                 self.reports_dir / 'Timing_Analyzer' /
#                 f'Slow_1200mV_{temp}_Model' / f'Slow_1200mV_{temp}_Model_Fmax_Summary.csv',
#                 id_field='Clock Name',
#                 field_parser=lambda s: s.strip().split(),
#                 id_parser=lambda s: s.strip(),
#                 interesting_fields=['Fmax']
#             )
#             self.results[f'fmax_{temp}'] = fmax['clock']['Fmax']

#         self.results['success'] = not failed


# class QuartusDse(QuartusSynth, DseFlow):
#     def run(self):
#         self.create_project()
#         # 'explore': Exploration flow to use, if not specified in --config
#         #   configuration file. Valid flows: timing_aggressive,
#         #   all_optimization_modes, timing_high_effort, seed,
#         #   area_aggressive, power_high_effort, power_aggressive
#         # 'compile_flow':  'full_compile', 'fit_sta' and 'fit_sta_asm'.
#         # 'timeout': Limit the amount of time a compute node is allowed to run. Format: hh:mm:ss
#         if 'dse' not in self.settings.flow:
#             self.fatal('`flows.quartus.dse` settings are missing!')

#         dse = self.settings.flow['dse']
#         if 'nproc' not in dse or not dse['nproc']:
#             dse['nproc'] = self.nthreads

#         script_path = self.copy_from_template(f'settings.dse',
#                                               dse=dse
#                                               )
#         self.run_process('quartus_dse',
#                          ['--use-dse-file', script_path, self.settings.design['name']],
#                          stdout_logfile='dse_stdout.log',
#                          initial_step="Running Quartus DSE",
#                          )

#     def parse_reports(self):
#         'quartus_dse_report.json'
#         pass


# DES:

# Available exploration spaces for this family are:
# "Seed Sweep"
# "Extra Effort Space"
# "Extra Effort Space for Quartus Prime Integrated Synthesis Projects"
# "Area Optimization Space"
# "Signature: Placement Effort Multiplier"
# "Custom Space"

# Valid optimization-goal options are:
# "Optimize for Speed"
# "Optimize for Area"
# "Optimize for Power"
# "Optimize for Negative Slack and Failing Paths"
# "Optimize for Average Period"
# "Optimize for Quality of Fit"


# -run-power ?

#
