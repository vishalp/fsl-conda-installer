#!/usr/bin/env python

import os
import os.path  as op
import contextlib
import shutil
import json

import fsl.installer.fslinstaller as inst

try:
    from unittest import mock
except ImportError:
    import mock

import pytest

from . import (server,
               CaptureStdout,
               indir,
               mock_input,
               strip_ansi_escape_sequences)


# mock miniconda installer which creates
# a mock $FSLDIR/bin/conda command
mock_miniconda_sh = """
#!/usr/bin/env bash

#called like <script> -b -p <prefix>
prefix=$3

mkdir -p $prefix/bin/
mkdir -p $prefix/etc/
mkdir -p $prefix/pkgs/

prefix=$(cd $prefix && pwd)

# called like
#  - conda env update -n base -f <envfile>
#  - conda clean -y --all
echo "#!/usr/bin/env bash"  >> $3/bin/conda
echo 'if   [ "$1" = "clean" ]; then '      >> $3/bin/conda
echo "    touch $prefix/cleaned"           >> $3/bin/conda
echo 'elif [ "$1" = "env" ]; then '        >> $3/bin/conda
echo "    cp "'$6'" $prefix/"              >> $3/bin/conda
echo "fi"                                  >> $3/bin/conda
chmod a+x $prefix/bin/conda
""".strip()


mock_manifest = """
{{
    "installer" : {{
        "version"          : "{version}",
        "url"              : "na",
        "sha256"           : "na",
        "registration_url" : "http://registrationurl",
        "license_url"      : "http://licenseurl"

    }},
    "miniconda" : {{
        "{platform}" : {{
            "url"    : "{url}/miniconda.sh",
            "sha256" : "{conda_sha256}"
        }}
    }},
    "versions" : {{
        "latest" : "6.2.0",
        "6.2.0"  : [
            {{
                "platform"      : "{platform}",
                "environment"   : "{url}/env-6.2.0.yml",
                "sha256"        : "{env620_sha256}",
                "base_packages" : ["fsl-base", "libopenblas"],
                "output"        : {{
                    "install"   : {{ "version" : "2", "value" : "100" }}
                }}

            }}
        ],
        "6.1.0"  : [
            {{
                "platform"      : "{platform}",
                "environment"   : "{url}/env-6.1.0.yml",
                "sha256"        : "{env610_sha256}",
                "base_packages" : ["fsl-base", "libopenblas"],
                "output"        : {{
                    "install"   : "100"
                }}
            }}
        ]
    }}
}}
""".strip()
# Format vars: version platform url conda_sha256 env610_sha256 env620_sha256


mock_env_yml_template = """
{version}
packages:
 - fsl-base 1234.0
""".strip()


def patch_manifest(src, dest, latest, *parts):
    with open(src, 'rt') as f:
        manifest = json.loads(f.read())

    if latest is not None:
        prev                           = manifest['versions']['latest']
        manifest['versions']['latest'] = latest
        manifest['versions'][latest]   = manifest['versions'][prev]

    for part in parts:
        parents = part[:-2]
        key     = part[-2]
        val     = part[-1]
        destd   = manifest

        for p in parents:
            destd = destd[p]

        destd[key] = val

    with open(dest, 'wt') as f:
        f.write(json.dumps(manifest))


@contextlib.contextmanager
def installer_server(cwd=None):
    if cwd is None:
        cwd = '.'
    cwd = op.abspath(cwd)

    with indir(cwd), server(cwd) as srv:
        with open('miniconda.sh', 'wt') as f:
            f.write(mock_miniconda_sh)
        with open('env-6.1.0.yml', 'wt') as f:
            f.write(mock_env_yml_template.format(version='6.1.0'))
        with open('env-6.2.0.yml', 'wt') as f:
            f.write(mock_env_yml_template.format(version='6.2.0'))

        conda_sha256  = inst.sha256('miniconda.sh')
        env610_sha256 = inst.sha256('env-6.1.0.yml')
        env620_sha256 = inst.sha256('env-6.2.0.yml')

        manifest = mock_manifest.format(
            version=inst.__version__,
            platform=inst.identify_platform(),
            url=srv.url,
            conda_sha256=conda_sha256,
            env610_sha256=env610_sha256,
            env620_sha256=env620_sha256)

        with open('manifest.json', 'wt') as f:
            f.write(manifest)

        yield srv


def check_install(homedir, destdir, version,
                  envver=None,
                  postinst=True,
                  finalise=True):
    # the devrelease test patches the manifest
    # file with devrelease versions, but leaves
    # the env files untouched, and referring to
    # the hard- coded versions in the temlates
    # above. So the "version" argument specifies
    # the actual version (which should be written
    # to $FSLDIR/etc/fslversion), and the
    # "envver" argument gives the version that
    # the yml file should refer to.

    if envver is None:
        envver = version

    destdir = op.abspath(destdir)
    etc     = op.join(destdir, 'etc')
    shell   = os.environ.get('SHELL', 'sh')
    profile = inst.configure_shell.shell_profiles.get(shell, None)

    with indir(destdir):
        # added by our mock conda env creeate call
        with open(op.join(destdir, 'env-{}.yml'.format(envver)), 'rt') as f:
            exp = mock_env_yml_template.format(version=envver)
            assert f.read().strip() == exp

        # added by our mock conda clean call
        if postinst:
            assert op.exists(op.join(destdir, 'cleaned'))

        assert op.exists(op.join(homedir, 'Documents', 'MATLAB'))

        # added by the fslinstaller
        if finalise:
            with open(op.join(etc, 'fslversion'), 'rt') as f:
                assert f.read().strip() == version
            assert op.exists(op.join(etc, 'env-{}.yml'.format(envver)))

        if profile is not None:
            assert any([op.exists(op.join(homedir, p)) for p in profile])


def test_installer_normal_interactive_usage():
    with inst.tempdir():
        with installer_server() as srv:
            with mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                            '{}/manifest.json'.format(srv.url)):
                # accept rel/abs paths
                for i in range(3):
                    with inst.tempdir() as cwd:
                        dests = ['fsl',
                                 op.join('.', 'fsl'),
                                 op.abspath('fsl')]
                        dest  = dests[i]
                        with mock_input(dest):
                            inst.main(['--homedir', cwd,
                                       '--root_env'])
                        check_install(cwd, dest, '6.2.0')
                        shutil.rmtree(dest)


def test_installer_list_versions():
    platform = inst.identify_platform()
    with inst.tempdir():
        with installer_server() as srv:
            with mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                            '{}/manifest.json'.format(srv.url)):
                with inst.tempdir() as cwd:
                    with CaptureStdout() as cap:
                        with pytest.raises(SystemExit) as e:
                            inst.main(['--listversions'])
                        assert e.value.code == 0

                    out   = strip_ansi_escape_sequences(cap.stdout)
                    lines = out.split('\n')

                    assert '6.1.0' in lines
                    assert '6.2.0' in lines
                    assert '  {} {}/env-6.1.0.yml'.format(platform, srv.url) in lines
                    assert '  {} {}/env-6.2.0.yml'.format(platform, srv.url) in lines


def test_installer_normal_cli_usage():



    with inst.tempdir():
        with installer_server() as srv:
            with mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                            '{}/manifest.json'.format(srv.url)):

                # accept rel/abs paths
                for i in range(3):
                    with inst.tempdir() as cwd:
                        dests = ['fsl', op.join('.', 'fsl'), op.abspath('fsl')]
                        dest  = dests[i]
                        inst.main(['--homedir', cwd,
                                   '--dest', dest,
                                   '--root_env'])
                        check_install(cwd, dest, '6.2.0')
                        shutil.rmtree(dest)

                # install specific version
                with inst.tempdir() as cwd:
                    inst.main(['--homedir', cwd,
                               '--dest', 'fsl',
                               '--fslversion', '6.1.0',
                               '--root_env'])
                    check_install(cwd, 'fsl', '6.1.0')
                    shutil.rmtree('fsl')


def test_installer_fsldir_already_set():
    with inst.tempdir():
        existing_fsldir = op.abspath(op.join('.', 'usr', 'local', 'fsl'))
        os.makedirs(existing_fsldir)
        with installer_server() as srv, \
             mock.patch.dict(os.environ, FSLDIR=existing_fsldir):
            with mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                            '{}/manifest.json'.format(srv.url)):

                with inst.tempdir() as cwd:
                    # hit enter to accept default installation
                    # directory, then 'y' to confirm overwrite
                    with mock_input('', 'y'):
                        inst.main(['--homedir',
                                   cwd, '--root_env'])
                    check_install(cwd, existing_fsldir, '6.2.0')


def test_installer_devrelease():
    with inst.tempdir():
        with installer_server() as srv:
            with mock.patch('fsl.installer.fslinstaller.FSL_DEV_RELEASES',
                            '{}/devreleases.txt'.format(srv.url)):
                patch_manifest('manifest.json',
                               'manifest-6.1.0.20220518.abcdefg.master.json',
                               '6.1.0.20220518')
                patch_manifest('manifest.json',
                               'manifest-6.1.0.20220519.asdjeia.master.json',
                               '6.1.0.20220519')
                patch_manifest('manifest.json',
                               'manifest-6.1.0.20220520.rkjlvis.master.json',
                               '6.1.0.20220520')

                # the installer should order
                # entries by date, newest first
                with open('devreleases.txt', 'wt') as f:
                    f.write('{}/manifest-6.1.0.20220518.abcdefg.master.json\n'.format(srv.url))
                    f.write('{}/manifest-6.1.0.20220520.rkjlvis.master.json\n'.format(srv.url))
                    f.write('{}/manifest-6.1.0.20220519.asdjeia.master.json\n'.format(srv.url))

                with inst.tempdir() as cwd:
                    dest = 'fsl'
                    with mock_input('2', dest):
                        inst.main(['--homedir', cwd, '--devrelease', '--root_env'])
                    check_install(cwd, dest, '6.1.0.20220519', '6.2.0')
                    shutil.rmtree(dest)
                # default option is newest devrelease
                with inst.tempdir() as cwd:
                    dest = 'fsl'
                    with mock_input('', dest):
                        inst.main(['--homedir', cwd, '--devrelease', '--root_env'])
                    check_install(cwd, dest, '6.1.0.20220520', '6.2.0')
                    shutil.rmtree(dest)

                with inst.tempdir() as cwd:
                    dest = 'fsl'
                    with mock_input(dest):
                        inst.main(['--homedir', cwd, '--devlatest', '--root_env'])
                    check_install(cwd, dest, '6.1.0.20220520', '6.2.0')
                    shutil.rmtree(dest)


# finalise_installation or post_install_cleanup failures
# should not result in installation failure
def test_installer_finalise_or_post_cleanup_failure():

    # make the clean step fail
    @inst.warn_on_error('Warning')
    def failing_finalise_installation(*a, **kwa):
        raise RuntimeError()

    @inst.warn_on_error('Warning')
    def failing_post_install_cleanup(*a, **kwa):
        raise RuntimeError()

    with inst.tempdir(), \
         installer_server() as srv, \
         mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                    '{}/manifest.json'.format(srv.url)), \
         inst.tempdir() as cwd, \
         mock.patch('fsl.installer.fslinstaller.finalise_installation',
                    failing_finalise_installation):

        inst.main(['--homedir', cwd,
                   '--dest', 'fsl',
                   '--root_env'])
        check_install(cwd, 'fsl', '6.2.0', finalise=False)

    with inst.tempdir(), \
         installer_server() as srv, \
         mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                    '{}/manifest.json'.format(srv.url)), \
         inst.tempdir() as cwd, \
         mock.patch('fsl.installer.fslinstaller.post_install_cleanup',
                    failing_post_install_cleanup):

        inst.main(['--homedir', cwd,
                   '--dest', 'fsl',
                   '--root_env'])
        check_install(cwd, 'fsl', '6.2.0', postinst=False)


def test_installer_skip_registration():

    # normal usage - registration info should be posted
    with inst.tempdir() as srvdir, \
         installer_server() as srv, \
         mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                    '{}/manifest.json'.format(srv.url)), \
         inst.tempdir() as cwd:

        manifest = '{}/manifest.json'.format(srvdir)
        patch_manifest(manifest, manifest, None,
                       ('installer', 'registration_url', srv.url))

        inst.main(['--homedir', cwd,
                   '--dest', 'fsl',
                   '--root_env'])
        check_install(cwd, 'fsl', '6.2.0')

        assert len(srv.posts) == 1

    # --skip_registration - registration info should *not* be posted
    with inst.tempdir() as srvdir, \
         installer_server() as srv, \
         mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                    '{}/manifest.json'.format(srv.url)), \
         inst.tempdir() as cwd:

        manifest = '{}/manifest.json'.format(srvdir)
        patch_manifest(manifest, manifest, None,
                       ('installer', 'registration_url', srv.url))

        inst.main(['--homedir', cwd,
                   '--dest', 'fsl',
                   '--root_env',
                   '--skip_registration'])
        check_install(cwd, 'fsl', '6.2.0')
        assert len(srv.posts) == 0

    # bad registration url in manifest - install should still succeed
    with inst.tempdir() as srvdir, \
         installer_server() as srv, \
         mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                    '{}/manifest.json'.format(srv.url)), \
         inst.tempdir() as cwd:
        manifest = '{}/manifest.json'.format(srvdir)
        patch_manifest(manifest, manifest, None,
                       ('installer', 'registration_url', 'badurl'))

        inst.main(['--homedir', cwd,
                   '--dest', 'fsl',
                   '--root_env'])
        check_install(cwd, 'fsl', '6.2.0')

        assert len(srv.posts) == 0

    # no registration url in manifest - install should still succeed
    with inst.tempdir() as srvdir, \
         installer_server() as srv, \
         mock.patch('fsl.installer.fslinstaller.FSL_RELEASE_MANIFEST',
                    '{}/manifest.json'.format(srv.url)), \
         inst.tempdir() as cwd:

        manifest = '{}/manifest.json'.format(srvdir)
        with open(manifest, 'rt') as f:
            installer = json.load(f)['installer']
        installer.pop('registration_url')
        patch_manifest(manifest, manifest, None, ('installer', installer))

        inst.main(['--homedir', cwd,
                   '--dest', 'fsl',
                   '--root_env'])
        check_install(cwd, 'fsl', '6.2.0')

        assert len(srv.posts) == 0
