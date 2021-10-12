#!/usr/bin/env python

import os
import os.path as op
import shutil
import subprocess as sp
import sys
import textwrap as tw

# py3
try:
    from unittest import mock
# py2
except ImportError:
    import mock

import pytest

from . import onpath, server

import fslinstaller as inst



def test_Context_identify_plaform():
    tests = [
        [('linux',  'x86_64'), 'linux-64'],
        [('darwin', 'x86_64'), 'macos-64'],
        [('darwin', 'arm64'),  'macos-64'],
    ]

    for info, expected in tests:
        sys, cpu = info
        with mock.patch('platform.system', return_value=sys), \
             mock.patch('platform.machine', return_value=cpu):
            assert inst.Context.identify_platform() == expected


def test_Context_identify_cuda():
    with inst.tempdir() as cwd:
        with onpath(cwd):

            nvidia_smi = tw.dedent("""
            #!/usr/bin/env bash
            echo "{stdout}"
            exit {retcode}
            """).strip()

            # test when nvidia-smi doesn't exist
            # (assuming that it won't be present
            # in any of the mock paths)
            path = op.pathsep.join(('/usr/sbin', '/usr/bin', '/sbin', '/bin'))
            with mock.patch.dict(os.environ, PATH=path):
                assert inst.Context.identify_cuda() is None
                if hasattr(inst.Context.identify_cuda, 'no_cuda'):
                    delattr(inst.Context.identify_cuda, 'no_cuda')

            with open('nvidia-smi', 'wt') as f:
                f.write(nvidia_smi.format(stdout='CUDA Version: 10.1', retcode=0))
            os.chmod('nvidia-smi', 0o755)
            assert  inst.Context.identify_cuda() == 10.1
            if hasattr(inst.Context.identify_cuda, 'no_cuda'):
                delattr(inst.Context.identify_cuda, 'no_cuda')

            with open('nvidia-smi', 'wt') as f:
                f.write(nvidia_smi.format(stdout='CUDA Version: 11.2', retcode=0))
            os.chmod('nvidia-smi', 0o755)
            assert  inst.Context.identify_cuda() == 11.2
            if hasattr(inst.Context.identify_cuda, 'no_cuda'):
                delattr(inst.Context.identify_cuda, 'no_cuda')

            with open('nvidia-smi', 'wt') as f:
                f.write(nvidia_smi.format(stdout='CUDA Version: 11.2', retcode=1))
            os.chmod('nvidia-smi', 0o755)
            assert  inst.Context.identify_cuda() is None
            if hasattr(inst.Context.identify_cuda, 'no_cuda'):
                delattr(inst.Context.identify_cuda, 'no_cuda')


def test_Context_get_admin_password():
    sudo = tw.dedent("""
    #!/usr/bin/env bash
    echo -n "Password: "
    read -e password
    if [ "$password" = "password" ]; then exit 0
    else exit 1
    fi
    """).strip()

    with inst.tempdir() as cwd:

        path = op.pathsep.join((cwd, os.environ['PATH']))

        with open('sudo', 'wt') as f:
            f.write(sudo)
        os.chmod('sudo', 0o755)

        # right password first time
        with mock.patch.dict(os.environ, PATH=path), \
             mock.patch('getpass.getpass', return_value='password'):
            assert inst.Context.get_admin_password() == 'password'

        # wrong, then right
        returnvals = ['wrong', 'password']
        def getpass(*a):
            return returnvals.pop(0)
        with mock.patch.dict(os.environ, PATH=path), \
             mock.patch('getpass.getpass', getpass):
            assert inst.Context.get_admin_password() == 'password'

        # wrong wrong wrong
        returnvals = ['wrong', 'bad', 'no']
        def getpass(*a):
            return returnvals.pop(0)
        with mock.patch.dict(os.environ, PATH=path), \
             mock.patch('getpass.getpass', getpass):
            with pytest.raises(Exception):
                inst.Context.get_admin_password()
