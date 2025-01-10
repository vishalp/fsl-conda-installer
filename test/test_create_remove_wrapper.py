#!/usr/bin/env python
#
# test_create_remove_wrapper.py - Test the createFSLWrapper.py and
# removeFSLWrapper.py scripts.
#
# Author: Paul McCarthy <pauldmccarthy@gmail.com>
#


import contextlib
import itertools as it
import os
import os.path as op
import shlex
import shutil
import subprocess as sp
import sys
import tempfile
import textwrap as tw
import time
from   unittest import mock

import fsl.installer.createFSLWrapper as createFSLWrapper
import fsl.installer.removeFSLWrapper as removeFSLWrapper


def createWrapper(*args, env=None):
    if env is None:
        env = os.environ.copy()
    with mock.patch('os.environ', env):
        try:
            return createFSLWrapper.main(args) == 0
        except Exception as e:
            print('createFSLWrapper raised error: ', e)
            return False

def removeWrapper(*args, env=None):
    if env is None:
        env = os.environ.copy()
    with mock.patch('os.environ', env):
        try:
            return removeFSLWrapper.main(args) == 0
        except Exception as e:
            print('removeFSLWrapper raised error: ', e)
            return False

def run(cmd, **kwargs):
    return sp.run(shlex.split(cmd), check=True, **kwargs)


@contextlib.contextmanager
def temp_fsldir(wrapperdir=None, prefix=None):

    if wrapperdir is None:
        wrapperdir = op.join('share', 'fsl', 'bin')

    testdir    = tempfile.mkdtemp()
    prevdir    = os.getcwd()
    fsldir     = op.join(testdir, 'fsl')
    wrapperdir = op.join(fsldir, wrapperdir)

    if prefix is None: prefix = fsldir
    else:              prefix = op.join(fsldir, prefix)

    try:

        os.chdir(testdir)
        os.mkdir(fsldir)

        with mock.patch.dict(os.environ, {
                'FSLDIR'                     : fsldir,
                'PREFIX'                     : prefix,
                'FSL_CREATE_WRAPPER_SCRIPTS' : '1'}):
            yield fsldir, wrapperdir

    finally:
        os.chdir(prevdir)
        shutil.rmtree(testdir)


def touch(path):
    dirname = op.dirname(path)
    if not op.exists(dirname):
        os.makedirs(dirname)
    with open(path, 'wt') as f:
        f.write('.')


def get_called_command(filename):
    """Returns the command that is being called by the given wrapper script.
    """

    with open(filename, 'rt') as f:
        line = f.readlines()[1]

    tokens = line.split()
    cmd    = op.basename(tokens[0])

    if cmd in ('python', 'pythonw'):
        cmd = tokens[2]

    return cmd


def test_env_vars_not_set():
    """Test that wrapper scripts are not created if the
    FSL_CREATE_WRAPPER_SCRIPTS, FSLDIR, or PREFIX environment variables
    are not set.
    """
    with temp_fsldir() as (fsldir, wrapperdir):
        touch(op.join(fsldir, 'bin', 'test_script'))

        env = os.environ.copy()
        env.pop('FSL_CREATE_WRAPPER_SCRIPTS')
        assert createWrapper('test_script', env=env)
        assert not op.exists(op.join(wrapperdir, 'test_script1'))

        env = os.environ.copy()
        env.pop('FSLDIR')
        assert createWrapper('test_script', env=env)
        assert not op.exists(op.join(wrapperdir, 'test_script1'))

        env = os.environ.copy()
        env.pop('PREFIX')
        assert createWrapper('test_script', env=env)
        assert not op.exists(op.join(wrapperdir, 'test_script1'))

        # FSLDIR invalid
        env = os.environ.copy()
        env['FSLDIR'] = '/some/non-existent/path'
        assert createWrapper('test_script', env=env)
        assert not op.exists(op.join(wrapperdir, 'test_script1'))

        # FSLDIR != PREFIX
        env = os.environ.copy()
        env['FSLDIR'] = op.join(env['PREFIX'], 'other_fsl')
        assert createWrapper('test_script', env=env)
        assert not op.exists(op.join(wrapperdir, 'test_script1'))


def test_create_python_wrapper():
    """Test creation of a wrapper script for a python executable"""

    hashbangs = [
        '#!/usr/bin/python3.10',
        '#!/usr/bin/python',
        '#!/usr/bin/env python',
        '#!/usr/bin/env fslpython',
        '#!/usr/bin/pythonw3.10',
        '#!/usr/bin/pythonw',
        '#!/usr/bin/env pythonw',
        '#!/usr/bin/env fslpythonw']

    with temp_fsldir() as (fsldir, wrapperdir):

        script_path  = op.join(fsldir, 'bin', 'test_script')
        wrapper_path = op.join(wrapperdir,    'test_script')

        for hb in hashbangs:

            touch(script_path)
            with open(script_path, 'wt') as f:
                f.write(f'{hb}\n')
                f.write('print("hello")\n')

            expect = tw.dedent(f"""
            #!/usr/bin/env bash
            {hb[2:]} -I {script_path} "$@"
            """).strip()

            if op.exists(wrapper_path):
                os.remove(wrapper_path)

            assert createWrapper('test_script')

            assert op.exists(wrapper_path)
            with open(wrapper_path, 'rt') as f:
                got = f.read().strip()

            assert got == expect


def test_create_other_wrapper():
    """Test creation of a wrapper script for a non-python executable."""
    with temp_fsldir() as (fsldir, wrapperdir):
        script_path  = op.join(fsldir, 'bin', 'test_script')
        wrapper_path = op.join(wrapperdir,    'test_script')

        touch(script_path)
        with open(op.join(fsldir, 'bin', 'test_script'), 'wt') as f:
            f.write('#!/usr/bin/env bash\n')
            f.write('echo "hello"\n')

        expect = tw.dedent(f"""
        #!/usr/bin/env bash
        {script_path} "$@"
        """).strip()

        assert createWrapper('test_script')

        assert op.exists(wrapper_path)
        with open(wrapper_path, 'rt') as f:
            got = f.read().strip()

        assert got == expect


def test_create_wrapper_dont_overwrite():
    """Make sure that an existing wrapper script is not overwritten."""
    with temp_fsldir() as (fsldir, wrapperdir):
        script_path  = op.join(fsldir, 'bin', 'test_script')
        wrapper_path = op.join(wrapperdir,    'test_script')

        touch(script_path)
        with open(op.join(fsldir, 'bin', 'test_script'), 'wt') as f:
            f.write('#!/usr/bin/env bash\n')
            f.write('echo "hello"\n')

        expect = tw.dedent(f"""
        #!/usr/bin/env bash
        {script_path} "$@"
        """).strip()

        assert createWrapper('test_script')
        mtime = op.getmtime(wrapper_path)

        time.sleep(2)
        assert createWrapper('test_script')
        assert op.getmtime(wrapper_path) == mtime


def test_permissions_preserved():
    """Test that wrapper script has same permissions as wrapped script."""
    with temp_fsldir() as (fsldir, wrapperdir):
        perms        = [0o777, 0o755, 0o644, 0o600, 0o755, 0o700]
        script_path  = op.join(fsldir, 'bin', 'test_script')
        wrapper_path = op.join(wrapperdir,    'test_script')
        touch(script_path)

        for perm in perms:
            os.chmod(script_path, perm)

            if op.exists(wrapper_path):
                os.remove(wrapper_path)

            assert createWrapper('test_script')

            assert op.exists(wrapper_path)
            stat = os.stat(wrapper_path)
            assert (stat.st_mode & 0o777) == perm


def test_create_remove_wrappers():
    """Tests normal usage. """
    with temp_fsldir() as (fsldir, wrapperdir):
        touch(op.join(fsldir, 'bin', 'test_script1'))
        touch(op.join(fsldir, 'bin', 'test_script2'))

        assert createWrapper('test_script1', 'test_script2')

        assert op.exists(op.join(wrapperdir, 'test_script1'))
        assert op.exists(op.join(wrapperdir, 'test_script2'))

        assert removeWrapper('test_script1', 'test_script2')

        assert not op.exists(op.join(wrapperdir, 'test_script1'))
        assert not op.exists(op.join(wrapperdir, 'test_script2'))


def test_create_remove_wrappers_child_env():
    """Tests creation of wrappers for executables in a child environment.
    """
    prefix = op.join('envs', 'childenv')
    with temp_fsldir(prefix=prefix) as (fsldir, wrapperdir):
        touch(op.join(fsldir, prefix, 'bin', 'test_script1'))
        touch(op.join(fsldir, prefix, 'bin', 'test_script2'))

        assert createWrapper('test_script1', 'test_script2')

        assert op.exists(op.join(wrapperdir, 'test_script1'))
        assert op.exists(op.join(wrapperdir, 'test_script2'))

        assert removeWrapper('test_script1', 'test_script2')

        assert not op.exists(op.join(wrapperdir, 'test_script1'))
        assert not op.exists(op.join(wrapperdir, 'test_script2'))


def test_create_gui_wrappers():
    """Tests creation of wrappers for FSL GUI commands, which are called
    "<Command>_gui" on macOS, and "<Command>" on linux, where "<command>"
    (note the case) may also exist. Post-link scripts should only pass the
    "<Command>_gui" variant.
    """


    for plat in 'darwin', 'linux':
        # Test outcome differs for different platforms.
        # Keys are passed to createFSLWrapper, values are
        # wrappers that should be created
        if plat == 'darwin':
            scripts = {'script'     : 'script',
                       'Script_gui' : 'Script_gui'}

        # linux
        else:
            scripts = {'script'     : 'script',
                       'Script'     : 'Script',
                       'Script_gui' : 'Script_gui'}

        with temp_fsldir() as (fsldir, wrapperdir):
            for target in scripts.values():
                touch(op.join(fsldir, 'bin', target))

            for wrappers in it.permutations(scripts.keys()):
                assert createWrapper(*wrappers, '-p', plat)

                for arg in wrappers:
                    target  = scripts[arg]
                    wrapper = op.join(wrapperdir, target)
                    assert op.exists(wrapper), wrapper
                    assert get_called_command(wrapper) == scripts[arg]

                assert removeWrapper(*wrappers)
                for arg in wrappers:
                    target  = scripts[arg]
                    wrapper = op.join(wrapperdir, target)
                    assert not op.exists(wrapper), wrapper

    # On Linux, make sure that if we have $FSLDIR/bin/Tool,
    # we get both Tool and Tool_gui wrapper scripts
    with temp_fsldir() as (fsldir, wrapperdir):
        touch(op.join(fsldir, 'bin', 'Tool'))

        assert createWrapper('Tool_gui', '-p', 'linux')

        tool     = op.join(wrapperdir, 'Tool')
        tool_gui = op.join(wrapperdir, 'Tool_gui')
        assert op.exists(tool)
        assert op.exists(tool_gui)
        assert get_called_command(tool)     == 'Tool'
        assert get_called_command(tool_gui) == 'Tool'

        assert removeWrapper('Tool_gui')
        assert not op.exists(tool)
        assert not op.exists(tool_gui)


def test_create_wrappers_rename():
    """Tests the renaming functionality in createFSLWrapper.  If
    $FSLDIR/bin/script exists, a wrapper with a different name
    (e.g. $FSLDIR/share/fsl/bin/renamed_script) can be created by passing
    "script=renamed_script".
    """

    # Keys are passed to createFSLWrapper, values
    # are wrappers that should be created
    scripts = {
        'script1=renamed_script1'         : 'renamed_script1',
        'script2=renamed_script2'         : 'renamed_script2',
        'script3_gui=renamed_script3_gui' : 'renamed_script3_gui',
        'script4_gui=renamed_script4'     : 'renamed_script4'
    }

    with temp_fsldir() as (fsldir, wrapperdir):
        for script in scripts.keys():
            target = script.split('=')[0]
            with open(target, 'wt') as f:
                touch(op.join(fsldir, 'bin', target))

        for wrappers in it.permutations(scripts.keys()):

            assert createWrapper(*wrappers)

            for arg in wrappers:
                target  = arg.split('=')[0]
                wrapper = op.join(wrapperdir, scripts[arg])

                assert op.exists(wrapper)
                assert get_called_command(wrapper) == target

            assert removeWrapper(*wrappers)
            for arg in wrappers:
                target  = scripts[arg]
                wrapper = op.join(wrapperdir, target)
                assert not op.exists(wrapper)


def test_create_wrappers_multiple_same():
    """Tests creating multiple wrapper scripts which call the same
    target command.
    """

    # Keys are passed to createFSLWrapper, values
    # are wrappers that should be created
    scripts = {
        'scripta'         : 'scripta',
        'scripta=script1' : 'script1',
        'scripta=script2' : 'script2',
        'scriptb'         : 'scriptb',
        'scriptc=script3' : 'script3',
        'scriptc=script4' : 'script4',
    }

    with temp_fsldir() as (fsldir, wrapperdir):
        for script in scripts.keys():
            target = script.split('=')[0]
            with open(target, 'wt') as f:
                touch(op.join(fsldir, 'bin', target))

        for wrappers in it.permutations(scripts.keys()):

            assert createWrapper(*wrappers)

            for arg in wrappers:
                target  = arg.split('=')[0]
                wrapper = op.join(wrapperdir, scripts[arg])

                assert op.exists(wrapper)
                assert get_called_command(wrapper) == target

            assert removeWrapper(*wrappers)

            for arg in wrappers:
                target  = scripts[arg]
                wrapper = op.join(wrapperdir, target)
                assert not op.exists(wrapper)


def test_create_wrappers_custom_destdir():

    with temp_fsldir(op.join('alt', 'wrapperdir')) as (fsldir, wrapperdir):
        script_path  = op.join(fsldir, 'bin', 'test_script')
        wrapper_path = op.join(wrapperdir,    'test_script')

        touch(script_path)
        with open(op.join(fsldir, 'bin', 'test_script'), 'wt') as f:
            f.write('#!/usr/bin/env bash\n')
            f.write('echo "hello"\n')

        expect = tw.dedent(f"""
        #!/usr/bin/env bash
        {script_path} "$@"
        """).strip()

        assert createWrapper('test_script', '-d', wrapperdir)

        assert op.exists(wrapper_path)
        with open(wrapper_path, 'rt') as f:
            got = f.read().strip()

        assert got == expect


def test_create_wrappers_custom_srcdir():

    with temp_fsldir() as (fsldir, wrapperdir):
        alt_srcdir   = op.join(fsldir, 'alt', 'bin')
        script_path  = op.join(alt_srcdir, 'test_script')
        wrapper_path = op.join(wrapperdir, 'test_script')

        os.makedirs(alt_srcdir)

        with open(script_path, 'wt') as f:
            f.write('#!/usr/bin/env bash\n')
            f.write('echo "hello"\n')

        expect = tw.dedent(f"""
        #!/usr/bin/env bash
        {script_path} "$@"
        """).strip()

        assert createWrapper('test_script', '-s', alt_srcdir)

        assert op.exists(wrapper_path)
        with open(wrapper_path, 'rt') as f:
            got = f.read().strip()

        assert got == expect


def test_create_wrappers_no_resolve():

    with temp_fsldir() as (fsldir, wrapperdir):
        script_path  = op.join(fsldir, 'bin', 'test_script')
        wrapper_path = op.join(wrapperdir, 'test_script')

        touch(script_path)
        with open(script_path, 'wt') as f:
            f.write('#!/usr/bin/env bash\n')
            f.write('echo "hello"\n')

        expect = tw.dedent("""
        #!/usr/bin/env bash
        ${FSLDIR}/bin/test_script "$@"
        """).strip()

        assert createWrapper('test_script', '-r')

        assert op.exists(wrapper_path)
        with open(wrapper_path, 'rt') as f:
            got = f.read().strip()

        assert got == expect


def test_create_wrappers_extra_args():

    with temp_fsldir() as (fsldir, wrapperdir):
        script_path  = op.join(fsldir, 'bin', 'test_script')
        wrapper_path = op.join(wrapperdir, 'test_script')

        touch(script_path)
        with open(script_path, 'wt') as f:
            f.write('#!/usr/bin/env bash\n')
            f.write('echo "hello"\n')

        expect = tw.dedent(f"""
        #!/usr/bin/env bash
        {script_path} --extra --thing -o 2 "$@"
        """).strip()

        assert createWrapper('test_script', '-a', ' --extra --thing -o 2')

        assert op.exists(wrapper_path)
        with open(wrapper_path, 'rt') as f:
            got = f.read().strip()

        assert got == expect, got
