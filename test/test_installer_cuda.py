#!/usr/bin/env python

import contextlib
import copy
import json
import os.path as op
import textwrap as tw

import fsl.installer.fslinstaller as fi

from . import (indir,
               server,
               mock_miniconda_installer,
               mock_nvidia_smi)

try:                from unittest import mock
except ImportError: import mock


PLATFORM = fi.identify_platform()


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

    'miniconda' : { PLATFORM : { 'python3.11' : {
        'url'    : None,  # populated below
        'sha256' : None
    }}},
    'versions' : { 'latest' : '6.1.0', '6.1.0'  : [ {
        'platform'     : PLATFORM,
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


@contextlib.contextmanager
def mock_server(cwd=None, patches=None, extras=None):
    if cwd     is None: cwd     = '.'
    if extras  is None: extras  = {}
    if patches is None: patches = []
    cwd = op.abspath(cwd)
    with indir(cwd), server(cwd) as srv:

        mock_miniconda_installer('miniconda.sh', pyver='3.11')

        with open('env.yml', 'wt') as f:
            f.write(mock_env_yml)
        for envname, yml in extras.items():
            with open('{}.yml'.format(envname), 'wt') as f:
                f.write(yml)

        manifest            = copy.deepcopy(mock_manifest)
        miniconda           = manifest['miniconda'][PLATFORM]['python3.11']
        env                 = manifest['versions']['6.1.0'][0]
        miniconda['url']    = '{}/miniconda.sh'.format(srv.url)
        miniconda['sha256'] = fi.sha256('miniconda.sh')
        env['environment']  = '{}/env.yml'.format(srv.url)
        env['sha256']       = fi.sha256('env.yml')
        env['extras']       = {}

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


def check_install(fsldir, cudavers=None, extras=None):
    # Check cuda-version has been added to each env file

    if extras is None:
        extras = {}

    expect = {'default' : mock_env_yml}
    expect.update(extras)

    if cudavers is None or isinstance(cudavers, str):
        cudavers = {env : cudavers for env in expect.keys()}

    for envname, expect_yml in expect.items():
        cudaver = cudavers[envname]

        if cudaver is not None:
            major, minor = cudaver.split('.')
            major        = int(major)
            minor        = int(minor)
            pin          = '>={}.{},<{}'.format(major, minor, major + 1)
            expect_yml   = expect_yml + '\n - cuda-version {}'.format(pin)

        if envname == 'default':
            envfile = op.join(fsldir, 'env.yml')
        else:
            envfile = op.join(fsldir, '{}.yml'.format(envname))

        assert open(envfile, 'rt').read().strip() == expect_yml


@reset_caches
def test_installer_cuda_local_gpu():
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

    with fi.tempdir()                     as td,  \
         mock_server(td, patches=[patch]) as srv, \
         fi.tempdir()                     as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir))

        check_install(destdir, None)



@reset_caches
def test_installer_cuda_in_extra_env():
    """GPU available, CUDA packages should be installed only in an extra
    environment, and not in the main environment.
    """

    mock_extra_env_yml = tw.dedent("""
    name: extra
    dependencies:
     - fsl-base
     - python 3.11.*
    """).strip()

    # CUDA should only be added to extra env
    patches = [
        ['versions', '6.1.0', 0, 'cuda_enabled', False],
        ['versions', '6.1.0', 0, 'extras', 'extra', {
            'cuda_enabled' : True
        }]
    ]

    skwargs = {'patches' : patches,
               'extras'  : {'extra' : mock_extra_env_yml}}

    with fi.tempdir()               as td,  \
         mock_server(td, **skwargs) as srv, \
         fi.tempdir()               as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir,
                 '--extra',   'extra'))

        check_install(
            destdir,
            {'default' : None, 'extra' : '11.2'},
            {'extra' : mock_extra_env_yml})


@reset_caches
def test_installer_cuda_in_main_env():
    """GPU available, CUDA packages should be installed only in the main
    environment, and not in an extra environment.
    """

    mock_extra_env_yml = tw.dedent("""
    name: extra
    dependencies:
     - fsl-base
     - python 3.11.*
    """).strip()

    # CUDA should only be added to main env
    patches = [
        ['versions', '6.1.0', 0, 'cuda_enabled', True],
        ['versions', '6.1.0', 0, 'extras', 'extra', {
            'cuda_enabled' : False
        }]
    ]

    skwargs = {'patches' : patches,
               'extras'  : {'extra' : mock_extra_env_yml}}

    with fi.tempdir()               as td,  \
         mock_server(td, **skwargs) as srv, \
         fi.tempdir()               as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir,
                 '--extra',   'extra'))

        check_install(
            destdir,
            {'default' : '11.2', 'extra' : None},
            {'extra' : mock_extra_env_yml})


@reset_caches
def test_installer_cuda_in_main_and_extra_env():
    """GPU available, CUDA packages should be installed in both the main
    environment, and in an extra environment.
    """

    mock_extra_env_yml = tw.dedent("""
    name: extra
    dependencies:
     - fsl-base
     - python 3.11.*
    """).strip()

    # CUDA should be added to both main and extra env
    patches = [
        ['versions', '6.1.0', 0, 'cuda_enabled', True],
        ['versions', '6.1.0', 0, 'extras', 'extra', {
            'cuda_enabled' : True
        }]
    ]

    skwargs = {'patches' : patches,
               'extras'  : {'extra' : mock_extra_env_yml}}

    with fi.tempdir()               as td,  \
         mock_server(td, **skwargs) as srv, \
         fi.tempdir()               as cwd, \
         mock_nvidia_smi('11.2'):

        destdir = 'fsl'

        fi.main(('--root_env',
                 '--homedir', cwd,
                 '--dest',    destdir,
                 '--extra',   'extra'))

        check_install(
            destdir,
            {'default' : '11.2', 'extra' : '11.2'},
            {'extra' : mock_extra_env_yml})
