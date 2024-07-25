#!/usr/bin/env python

import datetime
import logging
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

from . import onpath, server, mock_input, mock_nvidia_smi

import fsl.installer.fslinstaller as inst


def test_str2bool():
    assert inst.str2bool('true')  is True
    assert inst.str2bool('TRUe')  is True
    assert inst.str2bool('false') is False
    assert inst.str2bool(True)    is True
    assert inst.str2bool(False)   is False


def test_identify_plaform():
    tests = [
        [('linux',  'x86_64'), 'linux-64'],
        [('darwin', 'x86_64'), 'macos-64'],
        [('darwin', 'arm64'),  'macos-M1'],
    ]

    for info, expected in tests:
        sys, cpu = info
        with mock.patch('platform.system', return_value=sys), \
             mock.patch('platform.machine', return_value=cpu):
            assert inst.identify_platform() == expected


def test_Version():
    assert inst.Version('1')       == inst.Version('1')
    assert inst.Version('1.2')     == inst.Version('1.2')
    assert inst.Version('1.2.3')   == inst.Version('1.2.3')
    assert inst.Version('1.2.3')   <  inst.Version('1.2.4')
    assert inst.Version('1.2.3')   >  inst.Version('1.2.2')
    assert inst.Version('1.2.3')   >  inst.Version('1.2')
    assert inst.Version('1.2.3')   <  inst.Version('1.2.3.0')
    assert inst.Version('1.2.3.0') >  inst.Version('1.2.3')


def test_get_admin_password():
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
            assert inst.get_admin_password() == 'password'

        # wrong, then right
        returnvals = ['wrong', 'password']
        def getpass(*a):
            return returnvals.pop(0)
        with mock.patch.dict(os.environ, PATH=path), \
             mock.patch('getpass.getpass', getpass):
            assert inst.get_admin_password() == 'password'

        # wrong wrong wrong
        returnvals = ['wrong', 'bad', 'no']
        def getpass(*a):
            return returnvals.pop(0)
        with mock.patch.dict(os.environ, PATH=path), \
             mock.patch('getpass.getpass', getpass):
            with pytest.raises(Exception):
                inst.get_admin_password()


def test_download_file():

    with inst.tempdir() as cwd:
        with open('file', 'wt') as f:
            f.write('hello\n')
        with server(cwd) as srv:

            url = '{}/file'.format(srv.url)

            inst.download_file(url, 'copy')

            with open('copy', 'rt') as f:
                 assert f.read() == 'hello\n'

        # download_file should also work
        # with a path to a local file
        os.remove('copy')
        inst.download_file('file', 'copy')

        with open('copy', 'rt') as f:
            assert f.read() == 'hello\n'


def test_download_file_skip_ssl_verify():

    with inst.tempdir() as cwd:
        inst.download_file(inst.FSL_RELEASE_MANIFEST, 'manifest1.json',
                           ssl_verify=True)
        inst.download_file(inst.FSL_RELEASE_MANIFEST, 'manifest2.json',
                           ssl_verify=False)


def test_patch_file():

    content = tw.dedent("""
    line1
    line2
    line3
    line4
    """).strip()

    with inst.tempdir():

        with open('file', 'wt') as f:
            f.write(content)
        inst.patch_file('file', 'line2', 1, 'newline2')
        expect = content.replace('line2', 'newline2')
        with open('file', 'rt') as f:
            assert f.read().strip() == expect

        with open('file', 'wt') as f:
            f.write(content)
        inst.patch_file('file', 'line2', 2, 'newline2')
        expect = content.replace('line2\nline3', 'newline2')
        with open('file', 'rt') as f:
            assert f.read().strip() == expect

        with open('file', 'wt') as f:
            f.write(content)
        inst.patch_file('file', 'noline', 1, 'newline')
        expect = content + '\n\nnewline'
        with open('file', 'rt') as f:
            assert f.read().strip() == expect


def test_configure_shell():

    template = tw.dedent("""
    # FSL Setup
    FSLDIR={}
    PATH=${{FSLDIR}}/share/fsl/bin:${{PATH}}
    export FSLDIR PATH
    . ${{FSLDIR}}/etc/fslconf/fsl.sh
    """).strip()

    with inst.tempdir() as homedir:

        # no profile file exists
        inst.configure_shell('bash', homedir, '/fsl')
        with open('.bash_profile', 'rt') as f:
            assert f.read().strip() == template.format('/fsl')

        # existing profile with FSL config already present
        inst.configure_shell('bash', homedir, '/fsl_new')
        with open('.bash_profile', 'rt') as f:
            assert f.read().strip() == template.format('/fsl_new')

        # existing profile without FSL config
        config = tw.dedent("""
        line1
        line2
        line3
        """).strip()
        with open('.bash_profile', 'wt') as f:
            f.write(config)
        inst.configure_shell('bash', homedir, '/fsl')

        expect = config + '\n\n' + template.format('/fsl')
        with open('.bash_profile', 'rt') as f:
            assert f.read().strip() == expect


def test_configure_matlab():

    template = tw.dedent("""
    % FSL Setup
    setenv( 'FSLDIR', '{}' );
    setenv('FSLOUTPUTTYPE', 'NIFTI_GZ');
    fsldir = getenv('FSLDIR');
    fsldirmpath = sprintf('%s/etc/matlab',fsldir);
    path(path, fsldirmpath);
    clear fsldir fsldirmpath;
    """).strip()

    with inst.tempdir() as homedir:

        os.makedirs(op.join('Documents', 'MATLAB'))
        startupm = op.join('Documents', 'MATLAB', 'startup.m')

        # no startup.m exists
        inst.configure_matlab(homedir, '/fsl')
        with open(startupm, 'rt') as f:
            assert f.read().strip() == template.format('/fsl')

        # existing startup.m with FSL config already present
        inst.configure_matlab(homedir, '/fsl_new')
        with open(startupm, 'rt') as f:
            assert f.read().strip() == template.format('/fsl_new')

        # existing startup.m without FSL config
        config = tw.dedent("""
        line1
        line2
        line3
        """).strip()
        with open(startupm, 'wt') as f:
            f.write(config)
        inst.configure_matlab(homedir, '/fsl')

        expect = config + '\n\n' + template.format('/fsl')
        with open(startupm, 'rt') as f:
            assert f.read().strip() == expect


def test_list_available_versions():
    manifest = {'versions' : {'latest' : '6.1.0',
                              '6.1.0' : [{'platform'    : 'linux-64',
                                          'environment' : 'http://env.yml'},
                                         {'platform'    : 'macos-64',
                                          'environment' : 'http://env.yml'},
                                         {'platform'    : 'linux-64',
                                          'cuda'        : '10.2',
                                          'environment' : 'http://env.yml'}],
                              '6.2.0' : [{'platform'    : 'linux-64',
                                          'environment' : 'http://env.yml'},
                                         {'platform'    : 'macos-64',
                                          'environment' : 'http://env.yml'},
                                         {'platform'    : 'linux-64',
                                          'cuda'        : '10.2',
                                          'environment' : 'http://env.yml'}]}}
    inst.list_available_versions(manifest)


def test_read_write_environment_file():
    envyml = tw.dedent("""
    name: env
    channels:
      - a
      - b
      - c
    dependencies:
      - d 1
      - e 2.* build*
      - f
    """).strip()
    exp_channels = ['a',   'b',   'c']
    exp_packages = {'d' : '1', 'e' : '2.* build*', 'f' : None}
    with inst.tempdir():
        with open('env.yml', 'wt') as f:
            f.write(envyml)

        name, got_channels, got_packages = inst.read_environment_file('env.yml')
        assert name         == 'env'
        assert got_channels == exp_channels
        assert got_packages == exp_packages

        inst.write_environment_file('env2.yml', 'some-env', exp_channels, exp_packages)
        name, got_channels, got_packages = inst.read_environment_file('env2.yml')
        assert name         == 'some-env'
        assert got_channels == exp_channels
        assert got_packages == exp_packages

        inst.write_environment_file('env3.yml', 'some-env', [], exp_packages)
        name, got_channels, got_packages = inst.read_environment_file('env3.yml')
        assert name         == 'some-env'
        assert got_channels == []
        assert got_packages == exp_packages

        inst.write_environment_file('env4.yml', 'some-env', exp_channels, {})
        name, got_channels, got_packages = inst.read_environment_file('env4.yml')
        assert name         == 'some-env'
        assert got_channels == exp_channels
        assert got_packages == {}

        inst.write_environment_file('env5.yml', None, exp_channels, exp_packages)
        name, got_channels, got_packages = inst.read_environment_file('env5.yml')
        assert name         == None
        assert got_channels == exp_channels
        assert got_packages == exp_packages


def test_download_install_miniconda():
    class MockObject(object):
        pass

    installer = tw.dedent("""
    #!/usr/bin/env bash
    # is run like <miniconda.sh> -b -p <prefix>
    mkdir -p $3
    touch $3/installed
    """)

    def gen_manifest(platform, port, sha256, pyver=None):

        if pyver is not None:
            # new manifest format with separate miniconda installer
            # for each pyver
            return {
                'miniconda' : { platform : { pyver : {
                    'url'    : 'http://localhost:{}/remote.sh'.format(port),
                    'sha256' : sha256,
                }}}}
        else:
            # old manifest format with single miniconda installer
            return {
                'miniconda' : { platform : {
                    'url'    : 'http://localhost:{}/remote.sh'.format(port),
                    'sha256' : sha256,
                }}}


    with inst.tempdir() as cwd:
        os.mkdir('remote')
        with open(op.join('remote', 'remote.sh'), 'wt') as f:
            f.write(installer)
        sha256 = inst.sha256(op.join('remote', 'remote.sh'))

        with server('remote') as srv:

            manifest = gen_manifest('linux', srv.port, sha256, '3.11')

            destdir                  = op.join(cwd, 'miniconda')
            ctx                      = MockObject()
            ctx.args                 = MockObject()
            ctx.destdir              = destdir
            ctx.basedir              = destdir
            ctx.need_admin           = False
            ctx.admin_password       = None
            ctx.args.no_checksum     = False
            ctx.args.skip_ssl_verify = False
            ctx.args.miniconda       = None
            ctx.args.progress_file   = None
            ctx.use_existing_base    = False
            ctx.platform             = 'linux'
            ctx.manifest             = manifest
            ctx.miniconda_metadata   = manifest['miniconda']['linux']['3.11']
            ctx.environment_channels = []
            ctx.run                  = lambda f, *a, **kwa: f(*a, **kwa)

            inst.download_miniconda(ctx)
            inst.install_miniconda(ctx)

            assert op.exists(destdir)
            assert op.exists(op.join(destdir, 'installed'))
            shutil.rmtree(destdir)

            # error on bad checksum
            manifest               = gen_manifest('linux', srv.port, 'bad', '3.11')
            ctx.manifest           = manifest
            ctx.miniconda_metadata = manifest['miniconda']['linux']['3.11']
            with pytest.raises(Exception):
                inst.download_miniconda(ctx)

            # skip checksum
            ctx.args.no_checksum = True
            inst.download_miniconda(ctx)
            inst.install_miniconda(ctx)

            assert op.exists(destdir)
            assert op.exists(op.join(destdir, 'installed'))
            shutil.rmtree(destdir)

            # old manifest format with single miniconda installer
            manifest               = gen_manifest('linux', srv.port, sha256)
            ctx.manifest           = manifest
            ctx.miniconda_metadata = manifest['miniconda']['linux']

            inst.download_miniconda(ctx)
            inst.install_miniconda(ctx)

            assert op.exists(destdir)
            assert op.exists(op.join(destdir, 'installed'))
            shutil.rmtree(destdir)


def test_self_update():

    ver    = inst.__version__
    newver = '{}.0.0'.format(int(ver.split('.')[0]) + 1)
    oldver = '{}.0.0'.format(int(ver.split('.')[0]) - 1)

    new_installer = tw.dedent("""
    #!/usr/bin/env python
    from __future__ import print_function
    print("new version")
    """).strip()

    script_template = tw.dedent("""
    #!/usr/bin/env python
    from __future__ import print_function

    manifest = {{
        'installer' : {{
            'version' : '{ver}',
            'url'     : 'http://localhost:{port}/new_installer.py',
            'sha256'  : '{checksum}'
        }}
    }}

    import fslinstaller as inst
    inst.self_update(manifest, '.', {check_checksum})
    print('old version')
    """).strip()

    with inst.tempdir() as cwd:
        with server() as srv:

            shutil.copyfile(inst.__absfile__, 'fslinstaller.py')
            with open('new_installer.py', 'wt') as f:
                f.write(new_installer)
            checksum = inst.sha256('new_installer.py')

            # new version available
            with open('script.py', 'wt') as f:
                f.write(script_template.format(ver=newver,
                                               port=srv.port,
                                               checksum=checksum,
                                               check_checksum=True))
            got = sp.check_output([sys.executable, 'script.py'])
            assert got.decode('utf-8').strip() == 'new version'

            # new version available, bad checksum
            with open('script.py', 'wt') as f:
                f.write(script_template.format(ver=newver,
                                               port=srv.port,
                                               checksum='bad',
                                               check_checksum=True))
            got = sp.check_output([sys.executable, 'script.py'])
            # drop warning messages
            got = got.decode('utf-8').strip().split('\n')[-1]
            assert got == 'old version'

            # new version available, bad checksum, but skip checksum
            with open('script.py', 'wt') as f:
                f.write(script_template.format(ver=newver,
                                               port=srv.port,
                                               checksum='bad',
                                               check_checksum=False))
            got = sp.check_output([sys.executable, 'script.py'])
            got = got.decode('utf-8').strip().split('\n')[-1]
            assert got == 'new version'

            # same version available
            with open('script.py', 'wt') as f:
                f.write(script_template.format(ver=ver,
                                               port=srv.port,
                                               checksum=checksum,
                                               check_checksum=True))
            got = sp.check_output([sys.executable, 'script.py'])
            assert got.decode('utf-8').strip() == 'old version'

            # old version available
            with open('script.py', 'wt') as f:
                f.write(script_template.format(ver=oldver,
                                               port=srv.port,
                                               checksum=checksum,
                                               check_checksum=True))
            got = sp.check_output([sys.executable, 'script.py'])
            assert got.decode('utf-8').strip() == 'old version'


def test_post_request(tmp_path):
    csrf_token = 'ABCDEF123456'
    with open(tmp_path / 'form.html', 'w') as temp_form:
        temp_form.write(
            '''<html><header></header><body>
            <input name='csrfmiddlewaretoken' value='{0}'>
            </input>
            </body></html>
            '''.format(csrf_token))

    with server(tmp_path) as srv:
        inst.post_request(
            "/".join((srv.url, 'form.html')),
            {'key' : 'value'})
    assert srv.posts == [{
        'key' : 'value',
        'csrfmiddlewaretoken' : csrf_token,
        'emailaddress' : ''}]


def test_register_installation():

    class MockObject(object):
        pass

    ctx                        = MockObject()
    ctx.args                   = MockObject()
    ctx.args.skip_registration = False
    ctx.build                  = {'version' : '6.7.0', 'platform' : 'linux-64'}
    ctx.registration_url       = 'http://localhost:12348'

    # should fail silently if
    # registration url is down
    inst.register_installation(ctx)


    # user asked to skip_regisistration
    # expect zero HTTP posts sent to the
    # registration url
    ctx.args.skip_registration = True
    with server() as srv:
        ctx.registration_url = srv.url
        inst.register_installation(ctx)
    assert len(srv.posts) == 0

    # normal usage - expect one HTTP post
    # sent to the registration url
    ctx.args.skip_registration = False
    with server() as srv:
        ctx.registration_url = srv.url
        inst.register_installation(ctx)

    assert len(srv.posts) == 1
    got = srv.posts[0]

    assert 'architecture'   in got
    assert 'os'             in got
    assert 'os_info'        in got
    assert 'uname'          in got
    assert 'python_version' in got
    assert 'python_info'    in got
    assert got['fsl_version']  == '6.7.0'
    assert got['fsl_platform'] == 'linux-64'
    assert 'locale'         in got
    assert 'emailaddress'   == ''
    assert 'csrfmiddlewaretoken' in got


def test_agree_to_license():
    class MockContext(object):
        pass

    # test agree_to_license when there is and
    # isn't a license_url in the manifest

    ctx             = MockContext()
    ctx.license_url = None
    inst.agree_to_license(ctx)

    ctx.license_url = 'http://abcdefg'
    inst.agree_to_license(ctx)


def test_retry_on_error():

    def func():
        raise RuntimeError('always fail')

    with pytest.raises(Exception):
        inst.retry_on_error(func, 3)

    ncalls = [0]

    def func():
        ncalls[0] += 1
        if ncalls[0] < 3:
            raise RuntimeError('pass on third call')
        return 'passed'

    with pytest.raises(Exception):
        inst.retry_on_error(func, 2)

    assert inst.retry_on_error(func, 3) == 'passed'


def test_LogRecordingHandler():

    log = logging.getLogger(__name__)
    log.setLevel(logging.DEBUG)

    patterns = ['pattern1', 'pattern2', 'pattern3']

    with inst.LogRecordingHandler(patterns, log) as hd:
        log.debug('message with pattern1')
        log.debug('message with pattern2')
        log.debug('message with pattern4')
        records = hd.records()
        assert records == ['message with pattern1',
                           'message with pattern2']
        hd.clear()
        assert len(hd.records()) == 0

        log.debug('message with pattern2')
        log.debug('message with pattern3')
        log.debug('message with pattern5')
        records = hd.records()
        assert records == ['message with pattern2',
                           'message with pattern3']
        hd.clear()
        assert len(hd.records()) == 0


def test_funccache():

    ncalled = [0]

    @inst.funccache
    def func(arg):
        ncalled[0] += 1
        return arg * 2

    assert func(1)    == 2
    assert func(1)    == 2
    assert ncalled[0] == 1
    assert func(2)    == 4
    assert func(2)    == 4
    assert ncalled[0] == 2
    func.reset()
    assert func(1)    == 2
    assert ncalled[0] == 3
    assert func(2)    == 4
    assert ncalled[0] == 4
    assert func(1)    == 2
    assert func(2)    == 4
    assert ncalled[0] == 4


def test_getlocale():
    with mock.patch('fsl.installer.fslinstaller.locale.getlocale') as mock_gl:
        with mock.patch('fsl.installer.fslinstaller.locale.setlocale') as mock_sl:

            mock_gl.return_value = (None, None)
            mock_sl.return_value = 'C.UTF-8'
            assert inst.getlocale() == 'en_US.UTF-8'
            mock_sl.return_value = 'en_GB.UTF-8'
            assert inst.getlocale() == 'en_GB.UTF-8'
            mock_gl.return_value = ('fr_FR', 'UTF-8')
            assert inst.getlocale() == 'fr_FR.UTF-8'
            mock_gl.return_value = ('fr_FR', None)
            assert inst.getlocale() == 'en_US.UTF-8'


def test_identify_cuda():

    nvidia_smi = tw.dedent("""
    #!/usr/bin/env bash

    echo "CUDA Version: {}"
    exit {}
    """).strip()

    # CUDA ver, exit code, expected
    tests = [('10.0',   0, (10, 0)),
             ('10.0',   1, None),
             ('11.4',   0, (11, 4)),
             ('ASDFGJ', 0, None),
             ('ASDFGJ', 1, None)]

    inst.identify_cuda.reset()

    with mock_nvidia_smi() as nvsmi:
        for cudaver, exitcode, expected in tests:
            nvsmi(cudaver, exitcode)
            try:
                assert inst.identify_cuda() == expected
            finally:
                inst.identify_cuda.reset()


def test_add_cuda_packages():
    class Mock(object):
        pass

    ctx                       = Mock()
    ctx.args                  = Mock()
    ctx.args.cuda             = None
    ctx.build                 = {}
    ctx.build['cuda_enabled'] = True

    # (system CUDA, requested CUDA, expected)
    tests = [
        (None,    None, None),
        ((10, 2), None, ('>=10.2,<11', '10.2')),
        ((11, 8), None, ('>=11.8,<12', '11.8')),
        ((11, 0), None, ('>=11.0,<12', '11.0')),
        ((11, 2), None, ('>=11.2,<12', '11.2')),
        ((12, 4), None, ('>=12.4,<13', '12.4')),

        # --cuda=none - no CUDA
        ((12, 4), 'none',   None),

        # --cuda=X.Y - if provided, the system cuda is ignored
        (None,    (10, 2), ('>=10.2,<11', '10.2')),
        (None,    (11, 2), ('>=11.2,<12', '11.2')),
        ((12, 5), (11, 2), ('>=11.2,<12', '11.2')),
        ((11, 2), (12, 4), ('>=12.4,<13', '12.4'))
    ]

    for syscuda, usrcuda, expect in tests:

        if expect is None:
            exppkgs, expcuda = {}, None
        else:
            exppkgs = {'cuda-version' : expect[0]}
            expcuda = expect[1]

        def mock_identify_cuda():
            if syscuda is None:
                return None
            return (syscuda[0], syscuda[1])

        with mock.patch('fsl.installer.fslinstaller.identify_cuda',
                        mock_identify_cuda):

            ctx.args.cuda = usrcuda
            result        = inst.add_cuda_packages(ctx)
            assert result == (exppkgs, expcuda)
