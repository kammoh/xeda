# © 2020 [Kamyar Mohajerani](mailto:kamyar@ieee.org)

from collections import abc
import copy
import logging
import os
import math
from typing import Union
from ...utils import unique_list
from ..flow import SimFlow, Flow, SynthFlow, DebugLevel

logger = logging.getLogger()


def supported_vivado_generic(k, v, sim):
    if sim:
        return True
    if isinstance(v, int):
        return True
    if isinstance(v, bool):
        return True
    v = str(v)
    return (v.isnumeric() or (v.strip().lower() in {'true', 'false'}))


def vivado_gen_convert(k, x, sim):
    if sim:
        return x
    xl = str(x).strip().lower()
    if xl == 'false':
        return "1\\'b0"
    if xl == 'true':
        return "1\\'b1"
    return x


def vivado_generics(kvdict, sim):
    return ' '.join([f"-generic{'_top' if sim else ''} {k}={vivado_gen_convert(k, v, sim)}" for k, v in kvdict.items() if supported_vivado_generic(k, v, sim)])


class Vivado(Flow):
    reports_subdir_name = 'reports'

    def run_vivado(self, script_path):
        debug = self.args.debug
        vivado_args = ['-nojournal', '-mode', 'tcl' if debug >=
                       DebugLevel.HIGHEST else 'batch', '-source', str(script_path)]
        if not debug:
            vivado_args.append('-notrace')
        return self.run_process('vivado', vivado_args, initial_step='Starting vivado',
                                stdout_logfile=f'{self.name}_stdout.log')


class VivadoSynth(Vivado, SynthFlow):
    default_settings = {**SynthFlow.default_settings,
                        'fail_critical_warning': False, 'fail_timing': False}

    required_settings = {'clock_period': Union[str, int]}

    # see https://www.xilinx.com/support/documentation/sw_manuals/xilinx2020_1/ug904-vivado-implementation.pdf
    # and https://www.xilinx.com/support/documentation/sw_manuals/xilinx2020_1/ug901-vivado-synthesis.pdf
    strategy_options = {
        "Debug": {
            "synth": ["-assert", "-debug_log",
                      "-flatten_hierarchy none", "-no_timing_driven", "-keep_equivalent_registers",
                      "-no_lc", "-fsm_extraction off", "-directive RuntimeOptimized"],
            "opt": "-directive RuntimeOptimized",
            "place": "-directive RuntimeOptimized",
            "place_opt": [],
            "route": "-directive RuntimeOptimized",
            "phys_opt": "-directive RuntimeOptimized"
        },

        "Runtime": {
            "synth": ["-no_timing_driven", "-directive RuntimeOptimized"],
            "opt": "-directive RuntimeOptimized",
            "place": "-directive RuntimeOptimized",
            "place_opt": [],
            # with -ultrathreads results are not reproducible!
            # OR "-no_timing_driven -ultrathreads",
            "route": ["-directive RuntimeOptimized"],
            "phys_opt": "-directive RuntimeOptimized"
        },

        "Default": {
            "synth": ["-flatten_hierarchy rebuilt", "-directive Default"],
            "opt": ["-directive ExploreWithRemap"],
            "place": ["-directive Default"],
            "place_opt": [],
            "route": ["-directive Default"],
            "phys_opt": ["-directive Default"]
        },

        "Timing": {
            # or ExtraTimingOpt, ExtraPostPlacementOpt, Explore
            # very slow: AggressiveExplore
            # -mode: default, out_of_context
            # -flatten_hierarchy: rebuilt, full; equivalent in terms of QoR?
            # -no_lc: When checked, this option turns off LUT combining
            # -keep_equivalent_registers -no_lc
            "synth": ["-flatten_hierarchy full",
                      "-retiming",
                      "-directive PerformanceOptimized",
                      "-fsm_extraction one_hot",
                      "-resource_sharing off",
                      #   "-no_lc",
                      "-shreg_min_size 5",
                      #   "-keep_equivalent_registers "
                      ],
            "opt": ["-directive ExploreWithRemap"],
            # "place": "-directive ExtraTimingOpt",
            "place": ["-directive ExtraPostPlacementOpt"],
            "place_opt": ['-retarget', '-propconst', '-sweep', '-aggressive_remap', '-shift_register_opt',
                          '-dsp_register_opt', '-bram_power_opt'],
            # "route": "-directive NoTimingRelaxation",
            "route": ["-directive AggressiveExplore"],
            # if no directive: -placement_opt
            "phys_opt": ["-directive AggressiveExplore"]
        },
        "Timing2": {
            # or ExtraTimingOpt, ExtraPostPlacementOpt, Explore
            # very slow: AggressiveExplore
            # -mode: default, out_of_context
            # -flatten_hierarchy: rebuilt, full; equivalent in terms of QoR?
            # -no_lc: When checked, this option turns off LUT combining
            # -keep_equivalent_registers -no_lc
            "synth": ["-flatten_hierarchy rebuilt",
                      "-retiming",
                      "-directive PerformanceOptimized",
                      #   "-fsm_extraction one_hot",
                      #   "-resource_sharing off",
                      #   "-no_lc",
                      "-shreg_min_size 5",
                      "-keep_equivalent_registers ",
                      ],
            "opt": ["-directive ExploreWithRemap"],
            # "place": "-directive ExtraTimingOpt",
            "place": ["-directive ExtraPostPlacementOpt"],
            "place_opt": ['-retarget', '-propconst', '-sweep', '-aggressive_remap', '-shift_register_opt',
                          '-dsp_register_opt', '-bram_power_opt'],
            # "route": "-directive NoTimingRelaxation",
            "route": ["-directive AggressiveExplore"],
            # if no directive: -placement_opt
            "phys_opt": ["-directive AggressiveExplore"]
        },

        "Area": {
            "synth": ["-flatten_hierarchy full", "-directive AreaOptimized_high"],
            # if no directive: -resynth_seq_area
            "opt": "-directive ExploreArea",
            "place": "-directive Explore",
            "place_opt": ['-retarget', '-propconst', '-sweep', '-aggressive_remap', '-shift_register_opt',
                          '-dsp_register_opt', '-bram_power_opt', '-resynth_seq_area', '-merge_equivalent_drivers'],
            "route": "-directive Explore",
            # if no directive: -placement_opt
            "phys_opt": "-directive Explore"
        }
    }
    results_dir = 'results'
    checkpoints_dir = 'checkpoints'

    def run(self):
        rtl_settings = self.settings.design["rtl"]
        flow_settings = self.settings.flow
        generics_options = vivado_generics(
            rtl_settings.get("generics", {}), sim=False)

        input_delay = flow_settings.get('input_delay', 0)
        output_delay = flow_settings.get('output_delay', 0)

        clock_xdc_path = self.copy_from_template(f'clock.xdc',
                                                 input_delay=input_delay, output_delay=output_delay,
                                                 )

        strategy = flow_settings.get('strategy', 'Default')
        if isinstance(strategy, abc.Mapping):
            options = copy.deepcopy(strategy)
        else:
            logger.info(f'Using synthesis strategy: {strategy}')
            if strategy not in self.strategy_options.keys():
                self.fatal(f'Unknown strategy: {strategy}')
            options = copy.deepcopy(self.strategy_options[strategy])
        for k, v in options.items():
            if isinstance(v, str):
                options[k] = v.split()
        if not self.settings.flow.get('allow_brams', True):
            # -max_uram 0 for ultrascale+
            options['synth'].append('-max_bram 0')
        if not flow_settings.get('allow_dsps', True):
            options['synth'].append('-max_dsp 0')

        # to strings
        for k, v in options.items():
            options[k] = ' '.join(v)
        script_path = self.copy_from_template(f'{self.name}.tcl',
                                              xdc_files=[clock_xdc_path],
                                              options=options,
                                              generics_options=generics_options,
                                              results_dir=self.results_dir,
                                              checkpoints_dir=self.checkpoints_dir
                                              )
        return self.run_vivado(script_path)

    def parse_reports(self):
        reports_dir = self.reports_dir

        report_stage = 'post_route'
        reports_dir = reports_dir / report_stage

        fields = {'lut': 'Slice LUTs', 'ff': 'Register as Flip Flop',
                  'latch': 'Register as Latch'}
        hrule_pat = r'^\s*(?:\+\-+)+\+\s*$'
        slice_logic_pat = r'^\S*\d+\.\s*Slice Logic\s*\-+\s*' + \
            hrule_pat + r'.*' + hrule_pat + r'.*'
        for fname, fregex in fields.items():
            slice_logic_pat += r'^\s*\|\s*' + fregex + \
                r'\s*\|\s*' + f'(?P<{fname}>\\d+)' + r'\s*\|.*'

        slice_logic_pat += hrule_pat + r".*" + \
            r'^\S*\d+\.\s*Slice\s+Logic\s+Distribution\s*\-+\s*' + \
            hrule_pat + r'.*' + hrule_pat + r'.*'

        fields = {'slice': 'Slices?', 'lut_logic': 'LUT as Logic ',
                  'lut_mem': 'LUT as Memory'}
        for fname, fregex in fields.items():
            slice_logic_pat += r'^\s*\|\s*' + fregex + \
                r'\s*\|\s*' + f'(?P<{fname}>\\d+)' + r'\s*\|.*'

        slice_logic_pat += hrule_pat + r".*" + r'^\S*\d+\.\s*Memory\s*\-+\s*' + \
            hrule_pat + r'.*' + hrule_pat + r'.*'
        fields = {'bram_tile': 'Block RAM Tile',
                  'bram_RAMB36': 'RAMB36[^\|]+', 'bram_RAMB18': 'RAMB18'}
        for fname, fregex in fields.items():
            slice_logic_pat += r'^\s*\|\s*' + fregex + \
                r'\s*\|\s*' + f'(?P<{fname}>\\d+)' + r'\s*\|.*'
        slice_logic_pat += hrule_pat + r".*" + r'^\S*\d+\.\s*DSP\s*\-+\s*' + \
            hrule_pat + r'.*' + hrule_pat + r'.*'

        fname, fregex = ('dsp', 'DSPs')
        slice_logic_pat += r'^\s*\|\s*' + fregex + \
            r'\s*\|\s*' + f'(?P<{fname}>\\d+)' + r'\s*\|.*'
        self.parse_report(reports_dir / 'utilization.rpt', slice_logic_pat)

        self.parse_report(reports_dir / 'timing_summary.rpt',
                          r'Design\s+Timing\s+Summary[\s\|\-]+WNS\(ns\)\s+TNS\(ns\)\s+TNS Failing Endpoints\s+TNS Total Endpoints\s+WHS\(ns\)\s+THS\(ns\)\s+THS Failing Endpoints\s+THS Total Endpoints\s+WPWS\(ns\)\s+TPWS\(ns\)\s+TPWS Failing Endpoints\s+TPWS Total Endpoints\s*' +
                          r'\s*(?:\-+\s+)+' +
                          r'(?P<wns>\-?\d+(?:\.\d+)?)\s+(?P<_tns>\-?\d+(?:\.\d+)?)\s+(?P<_failing_endpoints>\-?\d+(?:\.\d+)?)\s+(?P<_tns_total_endpoints>\-?\d+(?:\.\d+)?)\s+'
                          r'(?P<whs>\-?\d+(?:\.\d+)?)\s+(?P<_ths>\-?\d+(?:\.\d+)?)\s+(?P<_ths_failing_endpoints>\-?\d+(?:\.\d+)?)\s+(?P<_ths_total_endpoints>\-?\d+(?:\.\d+)?)\s+',
                          r'Clock Summary[\s\|\-]+^\s*Clock\s+.*$[^\w]+(\w*)\s+(\{.*\})\s+(?P<clock_period>\d+(?:\.\d+)?)\s+(?P<clock_frequency>\d+(?:\.\d+)?)'
                          )

        self.parse_report(reports_dir / 'power.rpt',
                          r'^\s*\|\s*Total\s+On-Chip\s+Power\s+\(W\)\s*\|\s*(?P<power_total>[\-\.\w]+)\s*\|.*' +
                          r'^\s*\|\s*Dynamic\s*\(W\)\s*\|\s*(?P<power_dynamic> [\-\.\w]+)\s*\|.*' +
                          r'^\s*\|\s*Device\s+Static\s+\(W\)\s*\|\s*(?P<power_static>[\-\.\w]+)\s*\|.*' +
                          r'^\s*\|\s*Confidence\s+Level\s*\|\s*(?P<power_confidence_level>[\-\.\w]+)\s*\|.*' +
                          r'^\s*\|\s*Design\s+Nets\s+Matched\s*\|\s*(?P<power_nets_matched>[\-\.\w]+)\s*\|.*'
                          )

        failed = False
        forbidden_resources = ['latch', 'dsp', 'bram_tile']
        for res in forbidden_resources:
            if (self.results[res] != 0):
                logger.critical(
                    f'{report_stage} reports show {self.results[res]} use(s) of forbidden resource {res}.')
                failed = True

        # TODO better fail analysis for vivado
        failed = failed or (self.results['wns'] < 0) or (self.results['whs'] < 0) or (
            self.results['_failing_endpoints'] != 0)

        self.results['success'] = not failed


class VivadoSim(Vivado, SimFlow):
    def run(self):
        flow_settings = self.settings.flow
        tb_settings = self.settings.design["tb"]
        rtl_settings = self.settings.design["rtl"]
        generics_options = vivado_generics(
            tb_settings.get("generics", {}), sim=True)
        saif = flow_settings.get('saif')
        elab_flags = flow_settings.get('elab_flags')
        if not elab_flags:
            elab_flags = ['-nospecify',
                          '-notimingchecks', '-relax', '-maxdelay']

        elab_debug = flow_settings.get('elab_debug')
        if not elab_debug and (self.args.debug or saif or self.vcd):
            elab_debug = "typical"
        if elab_debug:
            elab_flags.append(f'-debug {elab_debug}')

        tb_uut = tb_settings.get('uut')
        sdf = flow_settings.get('sdf')
        if sdf:
            if not isinstance(sdf, list):
                sdf = [sdf]
            for s in sdf:
                if isinstance(s, str):
                    s = {"file": s}
                root = s.get("root", tb_uut)
                assert root, "neither SDF root nor tb.uut are provided"
                elab_flags.append(
                    f'-sdf{s.get("delay", "max")} {root}={s["file"]}')

        # for post-synthesis simulation:
        # other : -rangecheck

        libraries = flow_settings.get('libraries')
        if libraries:
            elab_flags.extend([f'-L {l}' for l in libraries])

        elab_optimize = flow_settings.get('elab_optimize', '-O2')
        if elab_optimize and elab_optimize not in elab_flags:
            elab_flags.append(elab_optimize)

        sim_tops = tb_settings['top']
        tb_top = sim_tops
        if isinstance(sim_tops, list):
            tb_top = sim_tops[0]
        else:
            sim_tops = [sim_tops]

        sim_sources = list(rtl_settings['sources'])
        for src in tb_settings['sources']:
            if src not in sim_sources:
                sim_sources.append(src)

        script_path = self.copy_from_template(f'vivado_sim.tcl',
                                              analyze_flags='-relax',
                                              elab_flags=' '.join(
                                                  unique_list(elab_flags)),
                                              generics_options=generics_options,
                                              sim_flags='',  # '-maxdeltaid 100000 -verbose'
                                              initialize_zeros=False,
                                              vcd=self.vcd,
                                              sim_tops=sim_tops,
                                              tb_top=tb_top,
                                              saif=saif,
                                              lib_name='work',
                                              prerun_time=tb_settings.get(
                                                  'prerun_time'),
                                              sim_sources=sim_sources,
                                              debug_traces=self.args.debug >= DebugLevel.HIGHEST or self.settings.flow.get(
                                                  'debug_traces')
                                              )
        return self.run_vivado(script_path)


class VivadoPostsynthSim(VivadoSim):
    depends_on = {VivadoSynth: {'rtl.sources': ['results/impl_timesim.v']}}

    def run(self):
        design_settings = self.settings.design
        tb_settings = design_settings['tb']
        flow_settings = self.settings.flow
        top = tb_settings['top']
        if isinstance(top, str):
            top = [top]
        if not 'glbl' in top:
            top.append('glbl')
        tb_settings['top'] = top

        if 'libraries' not in flow_settings:
            flow_settings['libraries'] = []
        if 'simprims_ver' not in flow_settings['libraries']:
            flow_settings['libraries'].append('simprims_ver')

        netlist_base = os.path.splitext(
            str(design_settings['rtl']['sources'][0]))[0]
        flow_settings['sdf'] = {'file': netlist_base + '.sdf'}

        clock_period_ps_generic = tb_settings.get('clock_period_ps_generic')
        if clock_period_ps_generic:
            tb_settings['generics'][clock_period_ps_generic] = math.floor(
                self.settings.flow_depends['vivado_synth']['clock_period'] * 1000)

        flow_settings['elab_flags'] = ['-relax', '-maxdelay', '-transport_int_delays',
                                       '-pulse_r 0', '-pulse_int_r 0', '-pulse_e 0', '-pulse_int_e 0']

        super().run()
