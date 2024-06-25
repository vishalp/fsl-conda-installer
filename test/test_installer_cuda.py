#!/usr/bin/env python

import contextlib
import copy
import json
import os.path as op

import test.test_installer        as ti
import fsl.installer.fslinstaller as fi

from . import (indir,
               server,
               mock_miniconda_installer,
               mock_nvidia_smi)

try:                from unittest import mock
except ImportError: import mock


def reset_caches(func):
    def decorator(*args, **kwargs):
        try:
            fi.identify_cuda.reset()
            return func(*args, **kwargs)
        finally:
            fi.identify_cuda.reset()
    return decorator


mock_manifest = {
    'installer' : {
        'version'          : fi.__version__,
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
 - python 3.11.*
""".strip()


@contextlib.contextmanager
def mock_server(cwd=None, *patches):
    if cwd is None:
        cwd = '.'
    cwd = op.abspath(cwd)
    with indir(cwd), server(cwd) as srv:

        mock_miniconda_installer('miniconda.sh', pyver='3.11')

        with open('env.yml', 'wt') as f:
            f.write(mock_env_yml)

        manifest                 = copy.deepcopy(mock_manifest)
        miniconda                = manifest['miniconda']['linux-64']['python3.11']
        env                      = manifest['versions']['6.1.0'][0]
        miniconda['url']         = '{}/miniconda.sh'.format(srv.url)
        miniconda['sha256']      = fi.sha256('miniconda.sh')
        env['environment']       = '{}/env.yml'.format(srv.url)
        env['sha256']            = fi.sha256('env.yml')

        for patch in patches:
            keys  = patch[:-1]
            value = patch[-1]
            section = manifest
            for key in keys[:-1]:
                section = section[key]
            section[keys[-1]] = value

        with open('manifest.json', 'wt') as f:
            f.write(json.dumps(manifest))

        with mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                        '{}/manifest.json'.format(srv.url)):
            yield srv


def check_install(fsldir, cudaver=None):
    # Check cuda-version has been added

    expect = mock_env_yml

    if cudaver is not None:
        major, minor = cudaver.split('.')
        major        = int(major)
        minor        = int(minor)
        pin          = '>={}.{},<{}'.format(major, minor, major + 1)
        expect       = expect + '\n - cuda-version {}'.format(pin)

    assert open(op.join(fsldir, 'env.yml'), 'rt').read().strip() == expect


@reset_caches
def test_installer_cuda_local_gou():
    """Local GPU available - installer should add "cuda-version X.Y" to package
    list.
    """
    with fi.tempdir()    as td,  \
         mock_server(td) as srv, \
         fi.tempdir()    as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir))

        check_install(destdir, '11.2')


@reset_caches
def test_installer_cuda_local_gpu_different_cuda_requested():
    """Local GPU available, but user has requested different CUDA version.
    """
    with fi.tempdir()    as td,  \
         mock_server(td) as srv, \
         fi.tempdir()    as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir,
                 '--cuda',    '12.0'))

        check_install(destdir, '12.0')


@reset_caches
def test_installer_cuda_local_gpu_requested_none():
    """Local GPU available, but user has requested non-GPU installation. """
    with fi.tempdir()    as td,  \
         mock_server(td) as srv, \
         fi.tempdir()    as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir,
                 '--cuda',    'none'))

        check_install(destdir)


@reset_caches
def test_installer_cuda_no_gpu_requested_cuda():
    """No GPU available, but user has requested a GPU installation. """
    with fi.tempdir()    as td,  \
         mock_server(td) as srv, \
         fi.tempdir()    as cwd, \
         mock_nvidia_smi(exitcode=1):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir,
                 '--cuda',    '12.0'))

        check_install(destdir, '12.0')



@reset_caches
def test_installer_cuda_disabled_for_build():
    """GPU available/user requested, but the specific FSL version does
    not have CUDA-capable packages.
    """

    patch = ['versions', '6.1.0', 0, 'cuda_enabled', False]

    with fi.tempdir()           as td,  \
         mock_server(td, patch) as srv, \
         fi.tempdir()           as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir))

        check_install(destdir, None)
