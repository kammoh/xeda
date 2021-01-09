import copy
import multiprocessing
from typing import Mapping
from pebble.common import ProcessExpired
from pebble.pool.process import ProcessPool
import random
import sys
import re
import inspect
import logging
from concurrent.futures import CancelledError, TimeoutError
import time
import pkg_resources
from pathlib import Path
import json
import traceback
# heavy, but will probably become handy down the road
import numpy
# import psutil
from math import ceil, floor


from ..flows.settings import Settings
from ..flows.flow import DesignSource, FileResource, Flow, FlowFatalException, NonZeroExit, SynthFlow, my_print
from ..utils import camelcase_to_snakecase, load_class, dict_merge, try_convert

logger = logging.getLogger()


def merge_overrides(overrides, settings):
    if overrides:
        if isinstance(overrides, str):
            overrides = [overrides]
        if len(overrides) == 1:
            overrides = re.split(r'\s*,\s*', overrides[0])
        for override in overrides:
            key, val = override.split('=')
            hier = key.split('.')
            patch_dict = dict()
            for field in hier[:-1]:
                new_dict = dict()
                patch_dict[field] = new_dict
                patch_dict = new_dict
            patch_dict[hier[-1]] = try_convert(val, convert_lists=True)
            settings = dict_merge(settings, patch_dict, True)
    return settings



def print_results(results, title, subset):
    data_width = 32
    name_width = 80 - data_width
    hline = "-"*(name_width + data_width)

    my_print("\n" + hline)
    my_print(f"{title:^{name_width + data_width}s}")
    my_print(hline)
    for k, v in results.items():
        if not k.startswith('_') and (not subset or k in subset):
            if isinstance(v, float):
                my_print(f'{k:{name_width}}{v:{data_width}.6f}')
            elif isinstance(v, bool):
                my_print(f'{k:{name_width}}{"True" if v else "False":>{data_width}}')
            elif isinstance(v, int):
                my_print(f'{k:{name_width}}{v:>{data_width}}')
            elif isinstance(v, list):
                my_print(f'{k:{name_width}}{" ".join(v):<{data_width}}')
            else:
                my_print(f'{k:{name_width}}{str(v):>{data_width}s}')
    my_print(hline + "\n")


def run_flow(f: Flow):
    try:
        f.run()
        return f.results
    except FlowFatalException as e:
        logger.exception(f'[Run Thread] Fatal exception during flow run in {f.flow_run_dir}: {e}')
    except KeyboardInterrupt as e:
        logger.exception(f'[Run Thread] Received KeyboardInterrupt during flow run in {f.flow_run_dir}: {e}')
    except KeyboardInterrupt as e:
        logger.exception(f'[Run Thread] Received KeyboardInterrupt during flow run in {f.flow_run_dir}: {e}')
    return {}

def run_flow_fmax(arg):
    idx, flow = arg
    try:
        flow.run_flow()
        flow.parse_reports()
        flow.results['timestamp'] = flow.timestamp
        flow.results['design.name'] = flow.settings.design['name']
        flow.results['flow.name'] = flow.name
        flow.results['flow.run_hash'] = flow.design_run_hash

        return idx, flow.results, flow.settings, flow.flow_run_dir

    except FlowFatalException as e:
        logger.warning(f'[Run Thread] Fatal exception during flow run in {flow.flow_run_dir}: {e}')
        traceback.print_exc()
        logger.warning(f'[Run Thread] Continuing')
    except KeyboardInterrupt as e:
        logger.exception(f'[Run Thread] KeyboardInterrupt received during flow run in {flow.flow_run_dir}')
        raise e
    except NonZeroExit as e:
        logger.warning(f'[Run Thread] {e}')
    except Exception as e:
        logger.warning(f"Exception: {e}")

    return None, None, flow.settings, flow.flow_run_dir


class FlowRunner():
    def __init__(self, args, xeda_project_settings, timestamp) -> None:
        self.args = args
        self.timestamp = timestamp
        self.xeda_project_settings = xeda_project_settings
        # in case super().add_common_args(plug_parser) was not called in a subclass
        if not hasattr(args, 'override_settings'):
            self.args.override_settings = None

        self.parallel_run = None

    def get_default_settings(self):
        defaults_data = pkg_resources.resource_string('xeda', "defaults.json")
        try:
            return json.loads(defaults_data)
        except json.decoder.JSONDecodeError as e:
            self.fatal(f"Failed to parse defaults settings file (defaults.json): {' '.join(e.args)}", e)

    def fatal(self, msg=None, exception=None):
        if msg:
            logger.critical(msg)
        if exception:
            raise exception
        else:
            raise Exception(msg)

    def validate_settings(self, settings):
        assert 'design' in settings
        # design = settings['design']
        # assert 'sources' in design
        # assert 'vhdl_std' in design
        # if design['vhdl_std'] == 8:
        #     design['vhdl_std'] = "08"
        # elif design['vhdl_std'] == 2:
        #     design['vhdl_std'] = "02"

        return settings

    def get_design_settings(self):
        

        settings = self.get_default_settings()

        def get_design(d):
            if not isinstance(d, list):
                return d
            if len(d) == 1:
                return d[0]
            dname = self.args.design
            if dname:
                if isinstance(dname, list):
                    dname = dname[0]  # TODO FIXME match dname !!!!
                for x in d:
                    if x['name'] == dname:
                        return x
                logger.critical(f'Design "{dname}" not found in the current project.')
            else:
                logger.critical(
                    f'{len(d)} designs are availables in the current project. Please specify target design using --design')
            logger.critical(f'Available designs: {", ".join([x["name"] for x in d])}')
            sys.exit(1)

        design_settings = dict(design=get_design(
            self.xeda_project_settings['design']), flows=self.xeda_project_settings.get('flows', {}))

        settings = dict_merge(settings, design_settings)

        settings = merge_overrides(self.args.override_settings, settings)
        flow_settings = settings['flows'].get(self.args.flow, dict())
        settings['flows'][self.args.flow] = merge_overrides(self.args.override_flow_settings, flow_settings)

        return self.validate_settings(settings)

    # should not override
    def post_run(self, flow: Flow, print_failed=True):
        # Run post-run hooks
        for hook in flow.post_run_hooks:
            logger.info(f"Running post-run hook from from {hook.__class__.__name__}")
            hook(flow)

        flow.reports_dir = flow.flow_run_dir / flow.reports_subdir_name
        if not flow.reports_dir.exists():
            flow.reports_dir.mkdir(parents=True)

        flow.parse_reports()
        flow.results['timestamp'] = flow.timestamp
        flow.results['design.name'] = flow.settings.design['name']
        flow.results['flow.name'] = flow.name
        flow.results['flow.run_hash'] = flow.design_run_hash

        if print_failed or flow.results.get('success'):
            flow.print_results()
        flow.dump_results()

        # Run post-results hooks
        for hook in flow.post_results_hooks:
            logger.info(f"Running post-results hook from {hook.__class__.__name__}")
            hook(flow)

    def load_flow_class(self, flow_name_or_class):
        if inspect.isclass(flow_name_or_class) and issubclass(flow_name_or_class, Flow):
            return flow_name_or_class
        try:
            return load_class(flow_name_or_class, ".flows")
        except AttributeError as e:
            self.fatal(
                f"Could not find Flow class corresponding to {flow_name_or_class}. Make sure it's typed correctly.", e)

    def setup_flow(self, settings, flow_name_or_class, max_threads=None):
        if not max_threads:
            max_threads = multiprocessing.cpu_count()
        # settings is a ref to a dict and its data can change, take a snapshot
        settings = copy.deepcopy(settings)

        flow_cls = self.load_flow_class(flow_name_or_class)

        flow_name = flow_name_or_class if isinstance(flow_name_or_class, str) else flow_name_or_class.name

        flow_settings = Settings()

        # flow defaults
        flow_settings.flow.update(**flow_cls.default_settings)

        # override sections
        flow_settings.design.update(settings['design'])

        if flow_cls.depends_on:
            for dep,subsettings in flow_cls.depends_on.items():
                flow_settings.flow_depends[dep.name] = settings['flows'].get(dep.name, {})
                flow_settings.flow_depends[dep.name].update(subsettings)
                
        # override entire section if available in settings
        if flow_name in settings['flows']:
            flow_settings.flow.update(settings['flows'][flow_name])
            logger.info(f"Using {flow_name} settings")
        else:
            logger.warning(f"No settings found for {flow_name}")


                

        flow: Flow = flow_cls(flow_settings, self.args)

        flow.nthreads = int(max(1, max_threads))

        return flow

    def add_common_args(parser):
        pass


class DefaultRunner(FlowRunner):
    def launch(self):
        settings = self.get_design_settings()
        flow = self.setup_flow(settings, self.args.flow)
        if flow.depends_on:
            assert isinstance(
                flow.depends_on, Mapping), "flow.depends_on should be a mapping of DependentFlowClass -> settings"

            flow.set_run_dir()

            for fcls, sub_settings in flow.depends_on.items():
                gen_rtl_sources = sub_settings.get('rtl.sources') ## TODO FIXME more generic dependency system, covering settings hierarchy!!!
                if gen_rtl_sources:
                    run_required = False
                    for gen_src in gen_rtl_sources:
                        gen_src_path = flow.run_path / fcls.name / gen_src
                        if not gen_src_path.exists():
                            run_required = True
                            logger.warning(f'Need to run {fcls.__name__} to generate {gen_src_path}')
                            break

                    dependency_flow = self.setup_flow(settings, fcls)
                    dependency_flow.run_path = flow.run_path
                    dependency_flow.set_run_dir()
                    if run_required:
                        dependency_flow.run_flow()
                        self.post_run(dependency_flow)
                        assert dependency_flow.results['success']

                    flow.settings.design['rtl']['sources'] = [
                        DesignSource(dependency_flow.flow_run_dir / src) for src in gen_rtl_sources
                    ]

                    logger.info(
                        f"Setting {flow.name}.rtl.sources to {[ str(x) for x in flow.settings.design['rtl']['sources']]}")
        flow.run_flow()
        self.post_run(flow)


class Best:
    def __init__(self, freq, results, settings):
        self.freq = freq
        self.results = copy.deepcopy(results)
        self.settings = copy.deepcopy(settings)


def nukemall():
    def on_terminate(proc):
        logger.warning(f"Child process {proc.info['name']}[{proc}] terminated with exit code {proc.returncode}")

    try:
        pass
        # procs = psutil.Process().children(recursive=True)
        # print(f"killing {len(procs)} child processes")
        # for p in procs:
        #     p.terminate()
        # gone, alive = psutil.wait_procs(procs, timeout=3, callback=on_terminate)
        # for p in alive:
        #     p.kill()
        # on nix: negative number means the process group with that PGID
        # os.kill(-os.getpgid(0), signal.SIGINT)
    except:
        logger.exception('exception during killing')


def unique(lst):
    return list(dict.fromkeys(lst))

class FmaxRunner(FlowRunner):
    def launch(self):
        start_time = time.monotonic()

        args = self.args
        settings = self.get_design_settings()

        flow_name = args.flow

        flow_settings = settings['flows'].get(flow_name)

        # will try halfing max_no_improvements iterations if all runs have failed
        lo_freq = float(flow_settings.get('fmax_low_freq', 1.0))
        # can go higher
        hi_freq = float(flow_settings.get('fmax_high_freq', 600.0))
        assert lo_freq < hi_freq , "fmax_low_freq should be less than fmax_high_freq"
        resolution = 0.09
        max_no_improvements = 3
        delta_increment = resolution / 2

        ONE_THOUSAND = 1000.0

        nthreads = int(flow_settings.get('nthreads', 4))

        max_workers = max(2, args.max_cpus // nthreads)
        logger.info(f'nthreads={nthreads} num_workers={max_workers}')
        self.parallel_run = True
        args.quiet = True

        best = None
        rundirs = []
        all_results = []
        future = None
        num_iterations = 0
        pool = None
        no_improvements = 0

        previously_tried_frequencies=set()
        previously_tried_periods=set() # can be different due to rounding errors

        # TODO adaptive tweeking of timeout?
        proc_timeout_seconds = flow_settings.get('timeout', 3600)
        logger.info(f'[Fmax] Timeout set to: {proc_timeout_seconds} seconds.')

        def round_freq_to_ps(freq: float) -> float:
            period = round(ONE_THOUSAND / freq, 3)
            return ONE_THOUSAND / period
        try:
            with ProcessPool(max_workers=max_workers) as pool:
                while hi_freq - lo_freq >= resolution:

                    while True:
                        frequencies_to_try, freq_step = numpy.linspace(
                            lo_freq, hi_freq, num=max_workers, dtype=float, retstep=True)

                        frequencies_to_try = unique([round_freq_to_ps(f) for f in frequencies_to_try if f not in previously_tried_frequencies])
                        
                        clock_periods_to_try = []
                        frequencies = []
                        for freq in frequencies_to_try:
                            clock_period = round(ONE_THOUSAND / freq, 3)
                            if clock_period not in previously_tried_periods:
                                clock_periods_to_try.append(clock_period)
                                frequencies.append(freq)
                        frequencies_to_try = frequencies

                        if len(frequencies_to_try) > 0 and (max_workers - len(frequencies_to_try)) <= max(2, max_workers / 4):
                            break
                        hi_freq += random.random() * delta_increment
                        lo_freq += 0.1 * random.random() * delta_increment

                    logger.info(
                        f"[Fmax] Trying following frequencies (MHz): {[f'{freq:.2f}' for freq in frequencies_to_try]}")

                    # TODO Just keep clock_periods!
                    previously_tried_frequencies.update(frequencies_to_try)
                    previously_tried_periods.update(clock_periods_to_try)

                    flows_to_run = []
                    for clock_period in clock_periods_to_try:
                        flow_settings['clock_period'] = clock_period
                        flow = self.setup_flow(settings, flow_name, max_threads=nthreads)
                        flow.set_parallel_run()
                        flows_to_run.append(flow)

                    future = pool.map(run_flow_fmax, enumerate(flows_to_run), timeout=proc_timeout_seconds)
                    num_iterations += 1

                    improved_idx = None

                    try:
                        iterator = future.result()
                        if not iterator:
                            logger.error("iterator is None! Retrying")
                            continue #retry
                        while True:
                            try:
                                idx, results, fs, rundir = next(iterator)
                                if results:
                                    freq = frequencies_to_try[idx]
                                    rundirs.append(rundir)
                                    if results['success'] and (not best or freq > best.freq):
                                        all_results.append(results)
                                        best = Best(freq, results, fs)
                                        improved_idx = idx
                            except StopIteration:
                                break
                            except TimeoutError as e:
                                logger.critical(
                                    f"Flow run took longer than {e.args[1]} seconds. Cancelling remaining tasks.")
                                future.cancel()
                            except ProcessExpired as e:
                                logger.critical(f"{e}. Exit code: {e.exitcode}")
                    except CancelledError:
                        logger.warning("[Fmax] CancelledError")
                    except KeyboardInterrupt:
                        pool.stop()
                        pool.join()
                        raise

                    if freq_step < resolution * 0.5:
                        break

                    if not best or improved_idx is None:
                        no_improvements += 1
                        if no_improvements >= max_no_improvements:
                            logger.info(
                                f"Stopping as there were no improvements in {no_improvements} consecutive iterations.")
                            break
                        logger.info(f"No improvements during this iteration.")

                        shrink_factor = 0.7 + no_improvements
                        
                        if not best:
                            hi_freq = lo_freq + resolution
                            lo_freq /= shrink_factor
                        else:
                            hi_freq = (best.freq + hi_freq) / 2 + delta_increment
                            lo_freq = (lo_freq + best.freq) / 2 + delta_increment * random.random()
                    else:
                        lo_freq = best.freq + delta_increment + delta_increment * random.random()
                        no_improvements = 0
                        # last or one before last
                        if improved_idx >= len(frequencies_to_try) - 2 or frequencies_to_try[-1] - best.freq <= freq_step:
                            min_plausible_period =  (ONE_THOUSAND / best.freq) - best.results['wns'] - 0.001
                            lo_point_choice = frequencies_to_try[1] if len(
                                frequencies_to_try) > 4 else frequencies_to_try[0]
                            hi_freq = max(best.freq + min(max_workers * 1.0, best.freq - lo_point_choice),  ceil(ONE_THOUSAND / min_plausible_period))
                        hi_freq += 2.3 * resolution + freq_step + random.random() 
                    
                    hi_freq += random.random() * delta_increment

                    logger.info(f'[Fmax] End of iteration #{num_iterations}')
                    logger.info(f'[Fmax] Execution Time so far: {int(time.monotonic() - start_time) // 60} minute(s)')
                    if best and best.results:
                        print_results(best.results, title='Best so far', subset=['clock_period', 'clock_frequency', 'lut', 'ff', 'slice'])

        except KeyboardInterrupt:
            logger.exception('Received Keyboard Interrupt')
        except Exception as e:
            logger.exception(f'Received exception: {e}')
            traceback.print_exc()
        finally:
            if future and not future.cancelled():
                future.cancel()
            if pool:
                pool.close()
                pool.join()
            runtime_minutes = int(time.monotonic() - start_time) // 60
            if best:
                best.iterations = num_iterations
                best.runtime_minutes = runtime_minutes
                print_results(best.results, title='Best Results', subset=[
                    'clock_period', 'clock_frequency', 'lut', 'ff', 'slice'])
                best_json_path = Path(args.xeda_run_dir) / \
                    f'fmax_{settings["design"]["name"]}_{flow_name}_{self.timestamp}.json'
                logger.info(f"Writing best result to {best_json_path}")

                with open(best_json_path, 'w') as f:
                    json.dump(best, f, default=lambda x: x.__dict__ if hasattr(x, '__dict__') else str(x), indent=4)
            else:
                logger.warning("No successful results.")
            logger.info(f'[Fmax] Total Execution Time: {runtime_minutes} minute(s)')
            logger.info(f'[Fmax] Total Iterations: {num_iterations}')
