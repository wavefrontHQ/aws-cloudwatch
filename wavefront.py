#!/usr/bin/env python
import argparse
import glob
import importlib
import logging
import os
import sys

# List of available commands to run
installed_commands = {
    'aws-metrics': importlib.import_module('command-aws-metrics'),
}

logger = logging.getLogger(__name__)

def parse_args(installed_commands):
    """
    Parse user arguments and return as parser object.
    """

    parser = argparse.ArgumentParser(description = 'Wavefront command line tool')
    subparsers = parser.add_subparsers(dest = 'command',
                                       help = 'Available commands.  Use \'wavefront <command name> -h\' to get help on an individual command')

    for command_name, module in installed_commands.iteritems():
        c = getattr(module, get_class_name(command_name))()
        p = subparsers.add_parser(command_name, help = c.get_help_text())
        c.add_arguments(p)

    parser.add_argument('--verbose', action = 'store_true', default = False,
                        help = 'More output')
    return parser.parse_args()


def get_class_name(command_name):
    """
    Gets the name of the class for the given command.
    'command-name' => CommandNameCommand
    """

    return ''.join(x for x in command_name.title() if not x == '-') + 'Command'

args = None
def main():
    global args
    args = parse_args(installed_commands)

    m = installed_commands[args.command]
    c = getattr(m, get_class_name(args.command))()
    c.verbose = args.verbose
    c.execute(args)

if __name__ == '__main__':
    logging.basicConfig(format = '%(levelname)s: %(message)s',
                        level = logging.INFO)
    try:
        main()
    except Exception as e:
        if args is not None and args.verbose:
            raise
        print e.message
