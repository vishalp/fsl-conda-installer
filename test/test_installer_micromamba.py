#!/usr/bin/env python

#!/usr/bin/env python

import contextlib
import copy
import json
import os
import os.path as op
import tarfile
import textwrap as tw

import fsl.installer.fslinstaller as fi

from . import (indir, server)

try:                from unittest import mock
except ImportError: import mock


mock_manifest = {
    'installer' : {
        'version'          : fi.__version__,
        'url'              : 'na',
        'sha256'           : 'na',
        'registration_url' : 'http://registrationurl',
        'license_url'      : 'http://licenseurl'
    },

    'miniconda' : { 'linux-64' : {
        'python3.11' : {
            'url'    : "invalid",
            'sha256' : "invalid"
        },
        'micromamba' : {
            'url'    : None,  # populated below
            'sha256' : None
        }
    }},
    'versions' : { 'latest' : '6.1.0', '6.1.0'  : [ {
        'platform'     : 'linux-64',
        'environment'  : None,  # populated below
        'sha256'       : None,
        'cuda_enabled' : True
    }]}
}


mock_env_yml = """
name: FSL
dependencies:
 - fsl-base
 - numpy
 - python 3.11.*
""".strip()


def mock_micromamba_installer(filename):
    mock_micromamba = tw.dedent("""
    #!/usr/bin/env bash
    # called like
    #  - micromamba env update -p <fsldir> -f <envfile>
    #  - micromamba env create -p <fsldir> -f <envfile>
    #  - micromamba clean -y --all

    prefix=$(cd $(dirname $0)/.. && pwd)

    echo "$@" >> "$prefix/allcommands"
    if   [ "$1" = "clean" ]; then
        touch $prefix/cleaned
    elif [ "$1" = "env" ]; then
        envprefix=$4
        mkdir -p $envprefix/bin/
        mkdir -p $envprefix/etc/
        mkdir -p $envprefix/pkgs/
        # copy env file into $prefix - so we
        # can check that this conda command
        # was called. The fslinstaller script
        # independently copies all env files
        # into $FSLDIR/etc/
        cp "$6" "$prefix"
        echo "$2" > $envprefix/env_command
    fi
    """).strip()

    filename = op.abspath(filename)

    with fi.tempdir() as td:
        os.mkdir('bin')
        with open('bin/micromamba', 'wt') as f:
            f.write(mock_micromamba)
        os.chmod('bin/micromamba', 0o755)

        with tarfile.TarFile(filename, 'w') as f:
            f.add('bin', arcname='bin')



@contextlib.contextmanager
def mock_server(cwd=None, patches=None, extras=None):
    if cwd     is None: cwd     = '.'
    if extras  is None: extras  = {}
    if patches is None: patches = []
    cwd = op.abspath(cwd)
    with indir(cwd), server(cwd) as srv:

        mock_micromamba_installer('micromamba.tar')

        with open('env.yml', 'wt') as f:
            f.write(mock_env_yml)
        for envname, yml in extras.items():
            with open('{}.yml'.format(envname), 'wt') as f:
                f.write(yml)

        manifest             = copy.deepcopy(mock_manifest)
        micromamba           = manifest['miniconda']['linux-64']['micromamba']
        env                  = manifest['versions']['6.1.0'][0]
        micromamba['url']    = '{}/micromamba.tar'.format(srv.url)
        micromamba['sha256'] = fi.sha256('micromamba.tar')
        env['environment']   = '{}/env.yml'.format(srv.url)
        env['sha256']        = fi.sha256('env.yml')
        env['extras']        = {}

        for patch in patches:
            keys  = patch[:-1]
            value = patch[-1]
            section = manifest
            for key in keys[:-1]:
                section = section[key]
            section[keys[-1]] = value

        for envname in extras.keys():
            exenv = {
                'environment': '{}/{}.yml'.format(srv.url, envname),
                'sha256'     : fi.sha256('{}.yml'.format(envname))
            }
            if envname not in env['extras']:
                env['extras'][envname] = {}
            env['extras'][envname].update(exenv)

        with open('manifest.json', 'wt') as f:
            f.write(json.dumps(manifest))

        with mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                        '{}/manifest.json'.format(srv.url)):
            yield srv


def test_installer_micromamba():
    with fi.tempdir()    as td,  \
         mock_server(td) as srv, \
         fi.tempdir()    as cwd:

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir))

        with indir(destdir):
            assert op.exists('bin/micromamba')
            assert op.exists('env.yml')
            assert op.exists('cleaned')
            assert op.exists('env_command')
            assert open('env_command', 'rt').read().strip() == 'update'
