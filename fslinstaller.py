#!/usr/bin/env python
#
# FSL installer script.
#


from __future__ import print_function, division


import functools      as ft
import os.path        as op
import subprocess     as sp
import                   os
import                   sys
import                   argparse
import                   contextlib
import                   getpass
import                   json
import                   logging
import                   platform
import                   shlex
import                   shutil
import                   tempfile

# TODO check py2/3
import                   urllib
import urllib.parse   as urlparse
import urllib.request as urlrequest


log = logging.getLogger(__name__)


# List of modifiers which can be used to change how
# a message is printed by the printmsg function.
INFO      = 1
IMPORTANT = 2
QUESTION  = 3
PROMPT    = 4
WARNING   = 5
ERROR     = 6
EMPHASIS  = 7
UNDERLINE = 8
RESET     = 9
ANSICODES = {
    INFO      : '\033[37m',
    IMPORTANT : '\033[92m',
    QUESTION  : '\033[36m\033[4m',
    PROMPT    : '\033[36m\033[1m',
    WARNING   : '\033[93m',
    ERROR     : '\033[91m',
    EMPHASIS  : '\033[1m',
    UNDERLINE : '\033[4m',
    RESET     : '\033[0m',
}


__version__ = '0.0.0'
"""Installer version number. This is automatically updated in release versions
whenever a new version is released.
"""


DEFAULT_INSTALLATION_DIRECTORY = '/usr/local/fsl'
"""Default FSL installation directory. """


FSL_DOWNLOAD_URL = 'http://18.133.213.73/installer/'
"""URL to download FSL conda environment files from. """


def printmsg(msg, *msgtypes, **kwargs):
    """Prints msg according to the ANSI codes provided in msgtypes.
    All other keyword arguments are passed through to the print function.
    """
    msgcodes = [ANSICODES[t] for t in msgtypes]
    msgcodes = ''.join(msgcodes)
    print('{}{}{}'.format(msgcodes, msg, ANSICODES[RESET]), **kwargs)


def prompt(prompt, *msgtypes, **kwargs):
    """Prompts the user for some input. msgtypes and kwargs are passed
    through to the printmsg function.
    """
    printmsg(prompt + ' ', *msgtypes, end='', **kwargs)
    return input().strip()


@contextlib.contextmanager
def tempdir():
    """Returns a context manager which creates and returns a temporary
    directory, and then deletes it on exit.
    """

    testdir = tempfile.mkdtemp()
    prevdir = os.getcwd()

    try:
        os.chdir(testdir)
        yield testdir

    finally:
        os.chdir(prevdir)
        shutil.rmtree(testdir)


def memoize(f):
    """Decorator to memoize a function. """

    cache = f.cache = {}
    def g(*args, **kwargs):
        key = (f, tuple(args), frozenset(kwargs.items()))
        if key not in cache:
            cache[key] = f(*args, **kwargs)
        return cache[key]
    return g


@memoize
def download_installer_manifest():
    """Downloads the installer manifest file, which contains information about
    available FSL vesrions, and the most recent version number of the installer
    (this script).

    The manifest file is a JSON file with the following structure:

        {
          'fslinstaller' : {
            'version' : '1.2.3',         # Latest version of installer script
            'url'     : 'http://abc.com' # URL to download installer script
          }
          'versions' : {
            # TODO
          }
        }
    """

    url = urlparse.urljoin(FSL_DOWNLOAD_URL, 'manifest.json')

    log.debug('Downloading FSL installer manifest from %s', url)

    with tempdir():
        download_file(url, 'manifest.json')

        with open('manifest.json') as f:
            manifest = f.read()

    return json.loads(manifest)


def self_update():
    """Checks to see if a newer version of the installer (this script) is
    available and if so, downloads it, replaces this script file in-place,
    and re-runs the new installer script.
    """

    @ft.total_ordering
    class Version(object):
        """Class to hold and compare FSL installer version strings.  Version
        strings must be of the form X.Y.Z, where X, Y, and Z are all integers.
        """
        def __init__(self, verstr):
            major, minor, patch = verstr.split('.')[:3]
            self.verstr         = verstr
            self.major          = int(major)
            self.minor          = int(minor)
            self.patch          = int(patch)

        def __str__(self):
            return self.verstr

        def __eq__(self, other):
            return all((self.major == other.major,
                        self.minor == other.minor,
                        self.patch == other.patch))

        def __lt__(self, other):
            for p1, p2 in zip((self.major,  self.minor,  self.patch),
                              (other.major, other.minor, other.patch)):
                if p1 < p2: return True
                if p1 > p2: return False
            return False

    manifest  = download_installer_manifest()
    thisver   = Version(__version__)
    latestver = Version(manifest['fslinstaller']['version'])

    if latestver <= thisver:
        log.debug('Installer is up to date (this vesrion: %s, '
                  'latest version: %s)', thisver, latestver)
        return

    log.debug('New version of installer is available (%s) - self-updating')
    with tempdir():
        download_file(manifest['fslinstaller']['url'], 'fslinstaller.py')
        # TODO checksum
        shutil.copyfile('fslinstaller.py', __file__)

    cmd = [sys.executable, __file__] + sys.argv[1:]
    log.debug('Running new installer: %s', cmd)
    os.execl(*cmd)


def need_admin(dirname):
    """Returns True if dirname needs administrator privileges to write to,
    False otherwise.
    """
    # TODO os.supports_effective_ids added in python 3.3
    return not os.access(dirname, os.W_OK | os.X_OK)


class InvalidPassword(Exception):
    """Exception raised by get_admin_password if the user gives an incorrect
    password.
    """


@memoize
def get_admin_password():
    """Prompt the user for their administrator password."""

    def validate_admin_password(password):
        printmsg("Checking sudo password", INFO)
        cmd = sp.Popen(shlex.split('sudo -S true'),
                       stdin=PIPE,
                       stdout=DEVNULL,
                       stderr=DEVNULL)
        cmd.stdin.write(sudo_pwd + '\n')
        cmd.stdin.flush()
        cmd.communicate()
        return cmd.returncode == 0

    printmsg('We need your administrator password to install FSL: ',
             IMPORTANT, end='', flush=True)

    for _ in range(3):
        password = getpass.getpass('')
        valid    = validate_admin_password(password)

        if valid: break
        else:     printmsg("Incorrect password", WARNING)

    if not valid:
        raise InvalidPassword()

    return password


def run(cmd, admin=False, display_output=False):
    """Runs the given command, as administrator if requested. """
    admin = admin and os.getuid() != 0
    cmd   = shlex.split(cmd)

    if admin:
        password = get_admin_password()
        cmd      = ['sudo', '-S'] + cmd
        proc     = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)

        proc.stdin.write(password + '\n')
        proc.stdin.flush()
    else:
        proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)

    (output, error) = proc.communicate()


class UnsupportedPlatform(Exception):
    """Exception raised by the identify_platform function if FSL is not
    available on this platform.
    """


def identify_platform():
    """Figures out what platform we are running on. Returns a platform
    identifier string - one of:

      - linux-64 (Linux, x86_64)
      - macos-64 (macOS, x86_64)
    """

    platforms = {
        ('linux',  'x86_64') : 'linux-64',
        ('darwin', 'x86_64') : 'linux-64',
        ('darwin', 'arm64')  : 'macos-64',
    }

    system = platform.system().lower()
    cpu    = platform.machine()
    key    = (system, cpu)

    if key not in platforms:
        raise UnsupportedPlatform()

    return platforms[key]


@memoize
def identify_cuda():
    """Identifies the CUDA version supported on the platform. Returns a
    string containing the 'X.Y' CUDA version, or None if CUDA is not supported.
    """

    try:
        output = sp.check_output('nvidia-smi')
    except (sp.CalledProcessError, FileNotFoundError):
        return None

    cudaver = '9.2'  # todo
    cudaver = float(output)
    match   = None

    # Return the most suitable CUDA
    # version that we have a build for
    supported_cudas = [9.2, 10.2, 11.1]
    for supported in reversed(supported_cudas):
        if cudaver <= supported:
            match = supported
            break

    return match


def list_available_versions():
    """Lists available FSL versions. """



class DownloadFailed(Exception):
    """Exception type raised by the download_file function if a
    download fails for some reason.
    """


def download_file(url, destination, blocksize=1048576):
    """Download a file from url, saving it to destination. """

    def report_progress(downloaded, total):
        downloaded = downloaded / 1048576
        total      = total      / 1048576
        if total is not None:
            msg = '{:.1f} / {:.1f}MB ...'.format(downloaded, total)
        else:
            msg = '{:.1f}MB ...'.format(downloaded)
        printmsg(msg, end='\r')

    printmsg('Downloading {} ...'.format(url))

    try:
        with urlrequest.urlopen(url) as req, \
             open(destination, 'wb') as outf:

            try:             total = int(req.headers['content-length'])
            except KeyError: total = None

            downloaded = 0

            while True:
                block = req.read(blocksize)
                if len(block) == 0:
                    break
                downloaded += len(block)
                outf.write(block)
                report_progress(downloaded, total)

    except urllib.error.HTTPError as e:
        raise DownloadFailed(f'A network error has occurred while '
                             f'trying to download {destname}') from e


def install_miniforge(platform, destdir, **kwargs):
    """Downloads the miniforge installer, and installs it to destdir.
    Keyword arguments are passed through to the run function.
    """

    url_base = 'https://github.com/conda-forge/miniforge/' \
               'releases/latest/download/'
    urls     = {
        'linux-64' : url_base + 'Miniforge3-Linux-x86_64.sh',
        'macos-64' : url_base + 'Miniforge3-MacOSX-x86_64.sh',
    }

    download_file(urls[platform], 'miniforge.sh')

    run('sh miniforge.sh -b -p {}'.format(destdir), **kwargs)


def install_fsl(destdir, fslversion, platform, cudaver, **kwargs):
    """Install FSL into destdir (which is assumed to be a miniforge
    installation.

    Keyword arguments are passed through to the run function.
    """
    base = 'http://18.133.213.73/fslinstaller/'

    if cudaver is not None:
        filename = 'fsl-{}-{}-cuda-{}.yml'.format(fslversion,
                                                  platform,
                                                  cudaver)
    else:
        filename = 'fsl-{}-{}.yml'.format(fslversion, platform)

    download_file(base + filename, 'environment.yml')

    conda = op.join(destdir, 'bin', 'conda')

    run(conda + ' env update -n base -f environment.yml', **kwargs)


def parse_args(argv=None):
    """Parse command-line arguments, returns an argparse.Namespace object. """

    helps = {
        'dest' :                'Install FSL into this folder (default: '
                                '{})'.format(DEFAULT_INSTALLATION_DIRECTORY),
        'version'             : 'Print installer version number and exit',
        'debug'               : 'Print debugging messages',
        'disable_self_update' : 'Do not automaticall update the installer '
                                'script',
        'listversions'        : 'List available versions of FSL',
        'fslversion'          : 'Download this specific version of FSL',
        'cuda'                : 'Install FSL for this CUDA version (default: '
                                'automatically detected)',
    }

    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--version', action='version',
                        version=__version__, help=helps['version'])
    parser.add_argument('-D', '--debug', action='store_true',
                        help=helps['debug'])
    parser.add_argument('-u', '--disable_self_update', action='store_true',
                        help=helps['disable_self_update'])
    parser.add_argument('-d', '--dest', metavar='DESTDIR',
                        help=helps['dest'])
    parser.add_argument('-l', '--listversions', action='store_true',
                        help=helps['listversions'])
    parser.add_argument('-V', '--fslversion', default='latest',
                        help=helps['version'])
    parser.add_argument('-c', '--cuda', default='latest',
                        help=helps['cuda'])

    args = parser.parse_args(argv)

    logging.basicConfig()
    if args.debug:
        logging.getLogger('fslinstaller').setLevel(logging.DEBUG)
    else:
        logging.getLogger('fslinstaller').setLevel(logging.WARNING)

    return args


def main(argv=None):

    args = parse_args(argv)

    printmsg('FSL installer version: ', EMPHASIS, end='')
    printmsg(__version__ + '\n')

    if not args.disable_self_update:
        self_update()

    if args.listversions:
        list_available_versions()
        sys.exit(0)

    if args.dest is None:
        printmsg('Where do you want to install FSL?', IMPORTANT, EMPHASIS)
        printmsg('Press enter to install to the default '
                 'location [{}]'.format(DEFAULT_INSTALLATION_DIRECTORY), INFO)
        args.dest = prompt('FSL installation directory:', QUESTION)

    platform = identify_platform()
    cudaver  = identify_cuda()
    admin    = need_admin(args.dest)

    printmsg('FSL installation directory: ', EMPHASIS, end='')
    printmsg(args.dest)
    printmsg('Platform:                   ', EMPHASIS, end='')
    printmsg(platform)
    printmsg('CUDA:                       ', EMPHASIS, end='')
    printmsg(cudaver or 'not detected')
    printmsg('Admin password required:    ', EMPHASIS, end='')
    printmsg(admin)

    get_admin_password()

    with tempdir():
        install_miniforge(platform, args.dest, admin)
        install_fsl(args.dest, args.version, platform, cudaver, admin)


if __name__ == '__main__':
    sys.exit(main())
