#!/usr/bin/env python3
"""
Deploy a new version of the fslinstaller script.  This script is run
every time a new tag is added to the fsl/conda/installer gitlab
repository.

This involves generating the standalone fslinstaller.py script and copying
it into the deployment directory, denoted by the
$FSLINSTALLER_DEPLOY_DIRECTORY environment variable.
"""

import sys

def read_attr(srcfile, attr):
    for line in open(srcfile, 'rt'):
        if line.startswith('{} = '.format(attr)):
            version = line.strip().split()[2]
            version = version.strip("'")
            return version
    raise RuntimeError(f'Could not find {attr} in {srcfile}')


def insert_templated_content(srcfile, destfile):

    template_id = read_attr(srcfile, 'TEMPLATE_IDENTIFIER')
    srclines    = open(srcfile, 'rt').readlines()
    destlines   = []

    for line in srclines:
        line = line.rstrip()
        if line.startswith(template_id):
            content_file = line.removeprefix(template_id).strip()
            contents     = open(content_file, 'rt').read().replace('\\', '\\\\')
            destlines.append(contents)
        else:
            destlines.append(line)

    with open(destfile, 'wt') as f:
        for line in destlines:
            f.write(f'{line}\n')

def main():
    if len(sys.argv) != 4:
        raise RuntimeError('Usage: new_release.py srcfile destfile tag')

    srcfile  = sys.argv[1]
    destfile = sys.argv[2]
    tag      = sys.argv[3]

    version  = read_attr(srcfile, '__version__')

    if version != tag:
        raise RuntimeError(f'Version in {srcfile} does not match tag! '
                           f'{version} != {tag}')

    insert_templated_content(srcfile, destfile)

if __name__ == '__main__':
    main()
