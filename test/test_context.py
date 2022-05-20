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
