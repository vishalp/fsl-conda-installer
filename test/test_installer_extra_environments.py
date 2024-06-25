#!/usr/bin/env python


import contextlib
import copy
import json
import os.path as op
import shutil

try:                from unittest import mock
except ImportError: import mock

import fsl.installer.fslinstaller as inst

from . import (server,
               indir,
               mock_miniconda_installer)


mock_manifest = {
    'installer' : {
        'version'          : inst.__version__,
        'url'              : 'na',
        'sha256'           : 'na',
        'registration_url' : 'http://registrationurl',
        'license_url'      : 'http://licenseurl'
    },

    'miniconda' : { 'linux-64' : { 'python3.11' : {
        'url'    : None,  # populated below
        'sha256' : None
    }}},
    'versions' : { 'latest' : '6.1.0', '6.1.0'  : [ {
        'platform'    : 'linux-64',
        'environment' : None,  # populated below
        'sha256'      : None,
        'extras'      : {
            'extra1' : {
                'environment' : None,  # populated below
                'sha256'      : None
            },
            'extra2' : {
                'environment' : None,  # populated below
                'sha256'      : None
            }
        }
    }]}
}

mock_env_yml = """
name: FSL
dependencies:
 - fsl-base
 - python 3.11.*
""".strip()

mock_env_yml_extra1 = """
name: extra
dependencies:
 - numpy
 - python 3.11.*
""".strip()

mock_env_yml_extra2 = """
name: extra
dependencies:
 - python 3.11.*
 - scipy
""".strip()


@contextlib.contextmanager
def mock_server(cwd=None):
    if cwd is None:
        cwd = '.'
    cwd = op.abspath(cwd)
    with indir(cwd), server(cwd) as srv:

        mock_miniconda_installer('miniconda.sh')

        with open('env.yml',        'wt') as f: f.write(mock_env_yml)
        with open('env_extra1.yml', 'wt') as f: f.write(mock_env_yml_extra1)
        with open('env_extra2.yml', 'wt') as f: f.write(mock_env_yml_extra2)

        manifest                 = copy.deepcopy(mock_manifest)
        miniconda                = manifest['miniconda']['linux-64']['python3.11']
        env                      = manifest['versions']['6.1.0'][0]
        extra1env                = env['extras']['extra1']
        extra2env                = env['extras']['extra2']
        miniconda['url']         = '{}/miniconda.sh'.format(srv.url)
        miniconda['sha256']      = inst.sha256('miniconda.sh')
        env['environment']       = '{}/env.yml'.format(srv.url)
        env['sha256']            = inst.sha256('env.yml')
        extra1env['environment'] = '{}/env_extra1.yml'.format(srv.url)
        extra1env['sha256']      = inst.sha256('env_extra1.yml')
        extra2env['environment'] = '{}/env_extra2.yml'.format(srv.url)
        extra2env['sha256']      = inst.sha256('env_extra2.yml')

        with open('manifest.json', 'wt') as f:
            f.write(json.dumps(manifest))

        with mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                        '{}/manifest.json'.format(srv.url)):
            yield srv


def check_install(fsldir, extras=None):
    if extras is None:
        extras = []

    envfile = op.join(fsldir, 'env.yml')
    assert open(envfile, 'rt').read().strip() == mock_env_yml

    for extra in ['extra1', 'extra2']:
        envfile  = op.join(fsldir, 'env_{}.yml'.format(extra))

        assert op.exists(envfile) == (extra in extras)

        if extra in extras:
            if extra == 'extra1': expect = mock_env_yml_extra1
            else:                 expect = mock_env_yml_extra2
            assert open(envfile, 'rt').read().strip() == expect


def test_install_extra_environment():
    with inst.tempdir():
        with mock_server() as srv:
            with inst.tempdir() as homedir:
                destdir = op.abspath('./fsl')
                inst.main(('--root_env',
                           '--dest', destdir,
                           '--homedir', homedir))
                check_install(destdir)
                shutil.rmtree(destdir)

                inst.main(('--root_env',
                           '--dest', destdir,
                           '--homedir', homedir,
                           '--extra', 'extra1'))
                check_install(destdir, ['extra1'])
                shutil.rmtree(destdir)

                inst.main(('--root_env',
                           '--dest', destdir,
                           '--homedir', homedir,
                           '--extra', 'extra2'))
                check_install(destdir, ['extra2'])
                shutil.rmtree(destdir)

                inst.main(('--root_env',
                           '--dest', destdir,
                           '--homedir', homedir,
                           '--extra', 'extra1',
                           '--extra', 'extra2'))
                check_install(destdir, ['extra1', 'extra2'])
                shutil.rmtree(destdir)
