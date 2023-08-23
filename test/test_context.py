#!/usr/bin/env python


import os.path  as op
import             os
import textwrap as tw

try:  from unittest import mock
except ImportError: import mock

import pytest

import fsl.installer.fslinstaller as inst


@pytest.mark.noroottest
def test_Context_admin_password():
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

        with mock.patch.dict(os.environ, PATH=path), \
             mock.patch('getpass.getpass', return_value='password'):

            os.mkdir('needs_admin')
            os.mkdir('does_not_need_admin')
            os.chmod('needs_admin',         438) # 0o666
            os.chmod('does_not_need_admin', 511) # 0o777

            ctx = inst.Context(None, op.join('needs_admin', 'fsl'))
            assert ctx.admin_password == 'password'

            ctx = inst.Context(None, op.join('does_not_need_admin', 'fsl'))
            assert ctx.admin_password == None
