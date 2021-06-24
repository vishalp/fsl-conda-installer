#!/usr/bin/env python


import sys
import argparse


def parseArgs(argv=None):

    helptext = {
        'dest'         : 'Install FSL into this folder (default: /usr/local/fsl)',
        'listversions' : 'List available versions of FSL',
        'version'      : 'Download this specific version of FSL',
    }

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--dest', help=helptext['dest'],
                        metavar='DESTDIR', default='/usr/local/fsl/')
    parser.add_argument('-l', '--listversions', help=helptext['listversions'],
                        action='store_true')
    parser.add_argument('-V', '--version', help=helptext['version'])

    return parser.parse_args(argv)


def main(argv=None):
    args = parseArgs(argv)


if __name__ == '__main__':
    sys.exit(main())
