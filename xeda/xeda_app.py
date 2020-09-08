# © 2020 [Kamyar Mohajerani](mailto:kamyar@ieee.org)

import sys
import argparse
from xeda.flow_runner import DefaultFlowRunner, LwcFmaxRunner, LwcVariantsRunner

from .utils import load_class

import coloredlogs
import logging

import pkg_resources


try:
    __version__ = pkg_resources.get_distribution(__package__).version
except pkg_resources.DistributionNotFound:
    __version__ = '(N/A - Local package)'



class XedaApp:
    def __init__(self):
        self.parser = argparse.ArgumentParser(
            prog=__package__,
            description=f'{__package__}: Simulate And Synthesize Hardware! Version {__version__}')
        self.args = None
        self.logger = logging.getLogger(__package__)

    # TODO
    def check_settings(self):
        if "design" in self.settings:
            ds = self.settings["design"]
            assert "generics" not in ds or isinstance(ds["generics"], dict), "design.generics must be a dict"
            assert "tbgenerics" not in ds or isinstance(
                ds["tb_generics"], dict), "design.tb_generics must be a dict"

    def main(self):
        args = self.args = self.parse_args()

        coloredlogs.install(level='DEBUG' if args.debug else 'INFO',
                            fmt='%(asctime)s %(levelname)s %(message)s', logger=self.logger)

        # FIXME this should be dynamically setup during runner registeration
        registered_runner_cmds = {
            'run': DefaultFlowRunner,
            'run_variants': LwcVariantsRunner,
            'run_fmax': LwcFmaxRunner
        }
        runner_cls = registered_runner_cmds.get(args.command)
        if runner_cls:
            runner = runner_cls(self.args)
        else:
            sys.exit(f"Ruuner for {args.command} is not implemented")

        runner.launch()


    #TODO FIXME
    def register_plugin_parsers(self):
        #TODO FIXME
        for runner_plugin in [LwcVariantsRunner, LwcFmaxRunner]:
            runner_plugin.register_subparser(self.subparsers)
        

    def parse_args(self, args=None):
        parser = self.parser
        parser.add_argument(
            '--debug',
            action='store_true',
            help='Print debug info'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Be verbose. Print everything to stdout'
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help="Be as quiet as possible. Never print out output from command executions"
        )
        parser.add_argument(
            '--force-run-dir',
            # help='Force set run directory where the tools are run.',
            # default=None
        )
        parser.add_argument(
            '--all-runs-dir',
            # help='Change top directory where the all the runs of a flow is run from `<FLOW_NAME>_run` ',
            # default=None
        )

        subparsers = parser.add_subparsers(dest='command', help='Commands Help')
        subparsers.required = True
        self.subparsers = subparsers

        # TODO FIXME add as validator!
        registered_flows = []
        ### FIXME FIXME FIXME


        ############################
        run_parser = subparsers.add_parser('run', help='Run a flow')
        run_parser.add_argument('flow', metavar='FLOW_NAME',
                                help=f'Flow name. Supported flows are: {registered_flows}')
        run_parser.add_argument(
            '--design-json',
            help='Path to design JSON file.'
        )

        self.register_plugin_parsers()
        
        return parser.parse_args(args)
