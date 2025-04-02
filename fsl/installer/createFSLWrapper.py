#!/usr/bin/env python
#
# IMPORTANT: Do not use triple-double-quotes anywhere in this file!
#
# Create wrapper scripts in $FSLDIR/share/fsl/bin/ which invoke commands that
# are installed in $FSLDIR/bin/. Calling this script like:
#
#   createFSLWrapper command1 command2 command3
#
# will cause wrapper scripts to be created in $FSLDIR/share/fsl/bin/, which
# call the commands of the same name in $FSLDIR/bin/, i.e.:
#
#    $FSLDIR/share/fsl/bin/command1 calls $FSLDIR/bin/command1
#    $FSLDIR/share/fsl/bin/command2 calls $FSLDIR/bin/command2
#
# This script is used to create isolated versions of all executables provided
# by FSL projects, so they can be added to the user $PATH without any other
# executables that are installed into the FSL conda environment (for example,
# python, pip, tcl, etc).
#
# This script is intended to be called by the post-link.sh script of the conda
# recipe for each FSL project that provides executable commands.  This script
# should only be invoked when FSL is being installed via the fslinstaller
# script - it is not intended to be used when individual FSL projects are
# explicitly installed into a custom conda environment.
#
# The fslinstaller script should ensure that the FSLDIR and
# FSL_CREATE_WRAPPER_SCRIPTS variables are set appropriately before creating
# the FSL conda environment.
#
# Wrapper scripts will only be created if the following conditions are met:
#
#  - The $FSLDIR and $PREFIX environment variables are set, and
#    $PREFIX is equal to, or contained within, $FSLDIR.
#  - The $FSL_CREATE_WRAPPER_SCRIPTS environment variable is set and is not
#    empty.
#
# Wrapper scripts, and not sym-links, are used to avoid a couple of potential
# problems:
#
#  - We need python executables to exclusively use the libraries installed in
#    the FSL conda environment. Users may have other Python environments
#    activated, and/or libraries installed into a local site-packages
#    directory. So we need to invoke the python interpreter in isolated mode,
#    with the -I flag:
#
#        https://docs.python.org/3/using/cmdline.html#id2
#
#  - There is no guarantee that a shell supports shebang lines longer than 127
#    characters. Depending on where FSL is installed, it may not be possible
#    to have a shebang line pointing to $FSLDIR/bin/python which does not
#    exceed 127 characters.
#
# Wrapper scripts are created for *all* FSL commands, including FSL TCL GUI
# commands (e.g. "fsl", "Flirt", "Flirt_gui", etc).  FSL TCL GUIs are called
# (e.g.) "<Command>" om Linux, but "<Command>_gui" on macOS, because macOS
# file systems are usually case-sensitive.
#
# To work around this, and to not accidentally create a link called <Command>
# to <command>, the FSL package post link scripts must only specify
# "<Command>_gui", and *not* "<Command>".  This script will create a wrapper
# script for the appropriate variant ("<Command>_gui" on macOS, or "<Command>"
# on Linux).
#
# Wrapper scripts with a different name to the target command can be created
# by passing "<command>=<wrapper-name>" to this script. For example, the
# FSL cluster command is called "fsl-cluster" to avoid naming conflicts with
# third-party packages (graphviz). A wrapper script called "cluster", which
# invokes "fsl-cluster", can be created like so:
#
#   createFSLWrapper fsl-cluster=cluster


import argparse
import os
import os.path as op
import sys
import textwrap as tw


def parse_args(argv=None):

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser()
    parser.add_argument('target', nargs='*')

    parser.add_argument('-f', '--force',
                        action='store_true',
                        help='Create wrappers even if the wrapper script '
                             'already exists, the target executable does not '
                             'exist, and/or FSL_CREATE_WRAPPER_SCRIPTS is not '
                             'set')
    parser.add_argument('-a', '--args',
                        help='Additional arguments to pass to '
                             'target within wrapper script')
    parser.add_argument('-s', '--srcdir',
                        help='Source directory containing target '
                             'executables (default: $FSLDIR/bin/')
    parser.add_argument('-d', '--destdir',
                        help='Destination directory (default: '
                             '$FSLDIR/share/fsl/bin)')
    parser.add_argument('-r', '--no-resolve',
                        action='store_true',
                        help='Do not resolve call to target executable in '
                             'wrapper script, i.e. use "${FSLDIR}/bin/target"'
                             'rather than "/full/path/to/fsl/bin/target"')

    # overrides sys.platform
    parser.add_argument('-p', '--platform', default=sys.platform,
                        help=argparse.SUPPRESS)

    return parser.parse_args(argv)


def get_python_interpreter(target):
    '''Attempts to determine whether the given target appears to be a
    Python executable. If it is, returns the path to the Python interpreter
    in the she-bang line. Otherwise returns None.
    '''

    with open(target, 'rb') as f:
        header = f.read(2048).split(b'\n')

    # Python entry points created by pip have two forms, and are
    # generated with distlib:
    #
    # https://github.com/pypa/pip/blob/ffbf6f0ce61170d6437ad5ff3a90086200ba9e2a/\
    # src/pip/_vendor/distlib/scripts.py#L147
    #
    #  - "Simple shebang": a python script of the form:
    #
    #        #!/path/to/python
    #        ...
    if len(header) >= 1:
        h0 = header[0].strip()
        if h0.startswith(b'#!') and (b'python' in h0):
            return h0[2:].decode('utf-8')

    #  - "Contrived shebang": A script which can be executed with either
    #    python or sh, of the form:
    #
    #        #!/bin/sh
    #        '''exec' /path/to/python "$0" "$@"
    #        ' '''
    #        ...
    if len(header) >= 2:
        h0 = header[0].strip()
        h1 = header[1].strip()
        if (h0 == b'#!/bin/sh')        and \
           h1.startswith(b"'''exec' ") and \
           (b'python' in h1):
            return h1.split()[1].decode('utf-8')

    return None


def generate_wrapper(target, fsldir, extra_args, resolve):
    '''Generate the contents of a wrapper script for the given target.'''

    # Python executable - run it via the
    # specified python interpreter in
    # isolated mode (strip leading '#!')
    PYTHON_TEMPLATE = tw.dedent('''
    #!/usr/bin/env bash
    {interp} -I {target}{args} "$@"
    ''').strip()

    # Non-python executable - use
    # a pass-through script
    OTHER_TEMPLATE = tw.dedent('''
    #!/usr/bin/env bash
    {target}{args} "$@"
    ''').strip()

    if extra_args is None: extra_args = ''
    else:                  extra_args = ' ' + extra_args.strip()

    interp   = None
    template = OTHER_TEMPLATE

    # Check if this the target is a python script.
    # If the target doesn't exist (--force was used),
    # we assume that it is a non-python executable
    if op.exists(target):
        interp = get_python_interpreter(target)
        if interp is not None:
            template = PYTHON_TEMPLATE

    wrapper = template.format(interp=interp,
                              target=target,
                              args=extra_args)

    if not resolve:
        wrapper = wrapper.replace(fsldir, '${FSLDIR}')

    return wrapper


def create_wrapper(target, srcdir, destdir, fsldir,
                   platform, extra_args, resolve, force):

    # A wrapper script with a different
    # name to the target can be created
    # by passing "targetName=wrapperName"
    target = target.split('=')
    if len(target) == 2: target, wrapper = target
    else:                target, wrapper = target[0], target[0]

    target  = op.join(srcdir,  target)
    wrapper = op.join(destdir, wrapper)

    # Historically, FSL GUIs are named "Tool" on linux, and
    # "Tool_gui" on macOS.. In FSL ~6.0.7.5, we started naming them
    # "Tool_gui" on linux for consistency across the platforms (but
    # also still creating commands called "Tool" as well for to
    # minimise disruption). During the transition period some linux
    # tools may have both "Tool" and "Tool_gui" variants, but others
    # may only have the "Tool" variant. But here we create "Tool"
    # and "Tool_gui" wrappers in $FSLDIR/share/fsl/bin/, regardless
    # of whether we only have "$FSLDIR/bin/Tool" or both
    # "$FSLDIR/bin/Tool" and "$FSLDIR/bin/Tool_gui"

    # So for <Tool>_gui targets:
    #   - on macOS we create one wrapper called  "<Tool>_gui"
    #   - on Linux we create two wrappers - "<Tool>" and "<Tool>_gui".
    #     The target may either be called "<Tool>" or "<Tool>_gui".

    linux = platform.lower().startswith('linux')
    gui   = linux and wrapper.endswith('_gui')

    # macOS or non-gui - the wrapper simply
    # has the same name as the target
    if not gui:
        targets  = [target]
        wrappers = [wrapper]

    # GUI scripts on linux - we create wrappers
    # for both "<Tool>" and "<Tool>_gui"
    else:
        target1  = target .removesuffix('_gui')
        wrapper1 = wrapper.removesuffix('_gui')
        target2  = target1  + '_gui'
        wrapper2 = wrapper1 + '_gui'

        # if $FSLDIR/bin/Tool_gui doesn't exist
        # make the Tool_gui wrapper point to
        # $FSLDIR/bin/Tool instead.
        if not op.exists(target2):
            target2 = target1

        targets  = [target1,  target2]
        wrappers = [wrapper1, wrapper2]

    for target, wrapper in zip(targets, wrappers):

        # Don't create a wrapper script if the
        # target executable does not exist.
        # Don't create a wrapper script if it
        # already exists.
        if (not force) and (not op.exists(target)):  continue
        if (not force) and (    op.exists(wrapper)): continue

        contents = generate_wrapper(target, fsldir, extra_args, resolve)

        with open(wrapper, 'wt') as f:
            f.write(contents)

        # copy permissions from target file
        if op.exists(target): perms = os.stat(target).st_mode & 0o777
        else:                 perms = 0o755

        os.chmod(wrapper, perms)


def main(argv=None):

    args   = parse_args(argv)
    fsldir = os.environ.get('FSLDIR', None)
    prefix = os.environ.get('PREFIX', None)

    if fsldir is not None: fsldir = op.realpath(op.abspath(fsldir))
    if prefix is not None: prefix = op.realpath(op.abspath(prefix))

    # Only create wrappers if the FSL_CREATE_WRAPPER_SCRIPTS
    # environment variable is set
    if not args.force:
        if 'FSL_CREATE_WRAPPER_SCRIPTS' not in os.environ:
            return 0

    # Only create wrappers if FSLDIR
    # exists and if PREFIX is equal to
    # or is within FSLDIR
    if fsldir is None                or \
       prefix is None                or \
       not op.exists(fsldir)         or \
       not prefix.startswith(fsldir):
        return 0

    # Names of all executables for which wrapper
    # scripts are to be created are passed as
    # arguments. The caller may also optionally
    # override the source directory (default
    # $FSLDIR/bin/) where the target executables
    # are located, and the destination directory
    # (default $FSLDIR/share/fsl/bin/) where the
    # wrapper script is to be created.
    targets = args.target
    srcdir  = args.srcdir
    destdir = args.destdir

    if destdir is None: destdir = op.join(fsldir, 'share', 'fsl', 'bin')
    if srcdir  is None: srcdir  = op.join(prefix, 'bin')

    # Source and destination directories
    # must be located inside $FSLDIR
    if not (destdir.startswith(fsldir) and srcdir.startswith(fsldir)):
        return 1

    os.makedirs(destdir, exist_ok=True)

    for target in targets:
        create_wrapper(target, srcdir, destdir, fsldir, args.platform,
                       args.args, not args.no_resolve, args.force)

    return 0


if __name__ == '__main__':
    sys.exit(main())
