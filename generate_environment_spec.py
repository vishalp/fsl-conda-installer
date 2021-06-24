#!/usr/bin/env python
"""Generate conda YAML environment specifications for specific platforms.

This script reads the fsl-environment-yml.template template file, and generates
a new file from it for a specific platform and, optionally, CUDA version.
"""


import os.path as op
import            re
import            sys


USAGE = """Usage: generate_environment_spec.py outfile platform [cudaver]

Generates a conda YAML environment specification file for a specific platform
(and, optionally, CUDA version).

Arguments:

  - outfile:  File to write generated specification to

  - platform: Platform to generate specification for (linux, macOS)

  - cudaver:  (Optional) CUDA version to generate specification for
              (9.2 10.2 11.1 11.2).
"""


CHANNELS = [
    'http://18.133.213.73/production/',
    'conda-forge',
    'defaults'
]


def parse_selector(selector):
    """Parses a selector specification. A selector specification is a
    sequence of key-value pairs which are appended to lines in the
    fsl-environment.yml template file. For example:

       platform:linux, cudaver:9.2

    Returns a dictionary containing the key-value pairs.
    """
    selector = selector.lower()
    kvps     = selector.split(',')
    kvps     = selector.split(',')
    kvps     = [kvp.strip().split(':')  for kvp in kvps]

    return dict((k.strip(), v.strip()) for k, v in kvps)


def filter_packages(packages, selectors):
    """Filters the given package list according to the given selectors. """

    pat     = r'^(.+) *# *\[(.+)\]$'
    include = []

    for pkg in packages:

        match = re.fullmatch(pat, pkg)

        if match is None:
            include.append(pkg)
            continue

        pkg          = match.group(1)
        pkg_selector = match.group(2)

        pkg_selector = parse_selector(pkg_selector)
        selected      = all(selectors.get(k, None) == v
                            for k, v in pkg_selector.items())

        if selected:
            include.append(pkg)

    return include


def load_packages(pkgfile):
    """Load the fsl-packages.txt file, returning a list of package entries. """

    with open(pkgfile) as f:
        packages = f.readlines()

    packages = [p.strip() for p in packages]
    packages = [p for p in packages if p != '' and not p.startswith('#')]

    return packages


def generate_environment_spec(outfile, channels, packages):
    """Writes a conda YAML environment speciifcation to the given file,
    containing the given channels and packages.
    """

    with open(outfile, 'wt') as f:

        f.write('channels:\n')
        for channel in channels:
            f.write(f'  - {channel}\n')

        f.write('dependencies:\n')
        for pkg in packages:
            f.write(f'  - {pkg}\n')


def main():
    """Generates a conda YAML environment specification file. """
    if len(sys.argv) not in (3, 4):
        print(USAGE)
        return 1

    thisdir = op.abspath(op.dirname(__file__))
    pkgfile = op.join(thisdir, 'fsl-packages.txt')
    outfile = sys.argv[1]

    selectors             = {}
    selectors['platform'] = sys.argv[2].lower()

    if len(sys.argv) == 4:
        selectors['cudaver'] = sys.argv[3].lower()

    packages = load_packages(pkgfile)
    packages = filter_packages(packages, selectors)

    generate_environment_spec(outfile, CHANNELS, packages)


if __name__ == '__main__':
    sys.exit(main())
