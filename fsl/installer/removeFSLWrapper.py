#!/usr/bin/env python
"""
Remove wrapper script/links in $FSLDIR/share/fsl/bin/ which invoke commands
that are installed in $FSLDIR/bin/. See createFSLWrapper for more
information.

This script is intended to be called by the pre-unlink.sh script of the
conda recipe for each FSL project that provides executable commands.

Note that we don't check the FSL_CREATE_WRAPPER_SCRIPTS environment variable
here. Wrapper scripts in $FSLDIR/share/fsl/bin/ will exist only if a
FSL conda packages was installed in an environment where thenb
FSL_CREATE_WRAPPER_SCRIPTS variable was set, so this script will simply
delete any wrapper scripts that exist.
"""


import os
import os.path as op
import sys


def main():
    # Names of all executables for which wrapper
    # scripts are to be removed are passed as
    # arguments
    targets = sys.argv[1:]
    fsldir  = os.environ.get('FSLDIR', None)
    prefix  = os.environ.get('PREFIX', None)

    if fsldir is not None: fsldir = op.abspath(fsldir)
    if prefix is not None: prefix = op.abspath(prefix)

    # Only remove wrappers if FSLDIR
    # exists and if PREFIX is equal to
    # or is within FSLDIR
    if (fsldir is None) or \
       (prefix is None) or \
       not prefix.startswith(fsldir):
        sys.exit(0)

    for target in targets:

        # A wrapper script with a different
        # name to the target can be created
        # by passing "targetName=wrapperName"
        target = target.split('=')

        if len(target) == 2: target, wrapper = target
        else:                target, wrapper = target[0], target[0]

        wrapper = op.join(fsldir, 'share', 'fsl', 'bin', wrapper)

        # On Linux there may be two wrapper scripts
        # for GUI tools - "<Tool>" and "<Tool>_gui".
        # We delete them both.
        linux = sys.platform.lower().startswith('linux')
        gui   = linux and wrapper.endswith('_gui')

        if gui:
            wrapper  = wrapper.removesuffix('_gui')
            wrappers = [wrapper, wrapper + '_gui']
        else:
            wrappers = [wrapper]

        for wrapper in wrappers:
            if op.exists(wrapper):
                os.remove(wrapper)


if __name__ == '__main__':
    main()
