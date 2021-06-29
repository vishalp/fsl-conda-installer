#!/usr/bin/env python
#
# FSL installer script.
#


from __future__ import print_function, division, unicode_literals


import functools      as ft
import os.path        as op
import subprocess     as sp
import                   os
import                   sys
import                   argparse
import                   contextlib
import                   getpass
import                   hashlib
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


__version__ = '0.0.0'
"""Installer version number. This is automatically updated in release versions
whenever a new version is released.
"""


DEFAULT_INSTALLATION_DIRECTORY = '/usr/local/fsl'
"""Default FSL installation directory. """


FSL_INSTALLER_MANIFEST = 'http://18.133.213.73/installer/manifest,json'
"""URL to download the FSL installer manifest file from. The installer
manifest file is a JSON file which contains information about available FSL
versions.

See the Context.download_manifest function, and an example manifest file
in test/data/manifest.json, for more details.
"""


class InvalidPassword(Exception):
    """Exception raised by Context.get_admin_password if the user gives an
    incorrect password.
    """


class UnknownVersion(Exception):
    """Exception raised by Context.build if the user has requested a FSL
    version that does not exist.
    """


class BuildNotAvailable(Exception):
    """Exception raised by Context.build if there is no available FSL version
    that matches the target platform and/or requested CUDA version.
    """


class Context(object):
    """Bag of information and settings created in main, and passed around
    this script.

    Several settings are lazily evaluated on first access, but once evaluated,
    their values are immutable.
    """

    def __init__(self, args):

        self.args = args

        # These attributes are updated on-demand via
        # the property accessors defined below, or all
        # all updated via the finalise-settings method.
        self.__platform       = None
        self.__cuda           = None
        self.__manifest       = None
        self.__build          = None
        self.__destdir        = None
        self.__need_admin     = None
        self.__admin_password = None


    def finalise_settings(self):
        self.platform
        self.cuda
        self.manifest
        self.build
        self.destdir
        self.need_admin
        self.admin_password


    @property
    def platform(self):
        """The platform we are running on, e.g. "linux-64", "macos-64". """
        if self.__platform is None:
            self.__platform = Context.identify_platform()
        return self.__platform


    @property
    def cuda(self):
        """The available CUDA version, or a CUDA version requested by the user.
        """
        if self.__cuda is not None:
            return self.__cuda
        if self.args.cuda is not None:
            self.__cuda = self.args.cuda
        if self.__cuda is None:
            self.__cuda = Context.identify_cuda()
        return self.__cuda


    @property
    def build(self):
        """Returns a suitable FSL build (a dictionary entry from the FSL
        installer manifest) for the target platform and CUDA version.
        """

        fslversion = self.args.fslversion
        if fslversion is None:
            fslversion = 'latest'

        if fslversion not in self.manifest['versions']:
            raise UnknownVersion(
                'FSL version {} is not available'.format(args.fslversion))

        if fslversion == 'latest':
            fslversion = self.manifest['versions']['latest']

        match = None

        for build in self.manifest['versions'][fslversion]:
            if build['platform']       == self.platform and \
               build.get('cuda', None) == self.cuda:
                match = build
                break
        else:
            raise BuildNotAvailable(
                'Cannot find a version of FSL matching platform '
                '{} and CUDA {}'.format(self.platform, self.cuda))

        return match


    @property
    def destdir(self):
        """Installation directory. If not specified at the command line, the
        user is prompted to enter a directory.
        """
        if self.args.dest is not None:
            self.__destdir = op.abspath(self.args.dest)
        if self.__destdir is None:
            while True:
                printmsg('Where do you want to install FSL?',
                         IMPORTANT, EMPHASIS)
                printmsg('Press enter to install to the default location [{}]'
                         .format(DEFAULT_INSTALLATION_DIRECTORY), INFO)
                response = prompt('FSL installation directory:', QUESTION)
                response = response.rstrip(op.sep)
                if response == '':
                    response = DEFAULT_INSTALLATION_DIRECTORY
                    break
                parentdir = op.dirname(response)
                if not op.exists(parentdir):
                    printmsg('Destination directory {} does not '
                             'exist!'.format(parentdir), ERROR)
            self.__destdir = response
        return self.__destdir


    @property
    def need_admin(self):
        """Returns True if administrator privileges will be needed to install
        FSL.
        """
        if self.__need_admin is not None:
            return self.__need_admin
        parentdir = op.dirname(self.destdir)
        self.__need_admin = Context.check_need_admin(parentdir)
        return self.__need_admin


    @property
    def admin_password(self):
        """Returns the user's administrator password, prompting them if needed.
        """
        if self.__admin_password is not None:
            return self.__admin_password
        if self.__need_admin == False:
            return None
        if self.__destdir is None:
            raise RuntimeError('Destination directory has not been set')
        self.__admin_password = Context.get_admin_password()


    @property
    def manifest(self):
        """Returns the FSL installer manifest as a dictionary. """
        if self.__manifest is None:
            self.__manifest = Context.download_manifest(self.args.manifest)
        return self.__manifest


    @staticmethod
    def identify_platform():
        """Figures out what platform we are running on. Returns a platform
        identifier string - one of:

          - "linux-64" (Linux, x86_64)
          - "macos-64" (macOS, x86_64)
        """

        platforms = {
            ('linux',  'x86_64') : 'linux-64',
            ('darwin', 'x86_64') : 'linux-64',

            # M1 builds (and possbily ARM for Linux)
            # will be added in the future
            ('darwin', 'arm64')  : 'macos-64',
        }

        system = platform.system().lower()
        cpu    = platform.machine()
        key    = (system, cpu)

        if key not in platforms:
            raise UnsupportedPlatform()

        return platforms[key]


    @staticmethod
    def identify_cuda():
        """Identifies the CUDA version supported on the platform. Returns a
        string containing the 'X.Y' CUDA version, or None if CUDA is not
        supported.
        """

        try:
            output = sp.check_output('nvidia-smi')
        except (sp.CalledProcessError, FileNotFoundError):
            return None

        cudaver = '9.2'  # TODO
        match   = None

        # Return the most suitable CUDA
        # version that we have a build for
        available_cudas = ['9.2', '10.2', '11.1']
        for available in reversed(supported_cudas):
            if float(cudaver) <= float(available):
                match = available
                break

        return match


    @staticmethod
    def check_need_admin(dirname):
        """Returns True if dirname needs administrator privileges to write to,
        False otherwise.
        """
        # TODO os.supports_effective_ids added in python 3.3
        return not os.access(dirname, os.W_OK | os.X_OK)


    @staticmethod
    def get_admin_password():
        """Prompt the user for their administrator password."""

        def validate_admin_password(password):
            proc = sudo_popen(['true'], password)
            proc.communicate()
            return proc.returncode == 0

        for _ in range(3):
            printmsg('Your administrator password is needed to '
                     'install FSL: ', IMPORTANT, end='', flush=True)
            password = getpass.getpass('')
            valid    = validate_admin_password(password)

            if valid: break
            else:     printmsg('Incorrect password', WARNING)

        if not valid:
            raise InvalidPassword()

        return password


    @staticmethod
    def download_manifest(url):
        """Downloads the installer manifest file, which contains information
        about available FSL vesrions, and the most recent version number of the
        installer (this script).

        The manifest file is a JSON file with the following structure (lines
        beginning with two forward-slashes are ignored):

          {
              "installer" : {

                  // Latest version of installer script
                  "version" : "1.2.3",

                  // URL to download installer script
                  "url"     : "http://abc.com/fslinstaller.py"

                  // SHA256 checksum of installer script
                  "sha256"  : "ab238........."
              },
              "versions" : {

                  // Latest must be present, and must
                  // contain the version number of the
                  // latest release
                  "latest" : "6.1.0",
                  "6.1.0"  : {
                      'linux-64' : {
                          "environment" : "http;//abc.com/fsl-6.1.0-linux-64.yml",
                          "sha256"      : "ab23456...",
                      }
                      'macos-64' : {
                          "environment" : "http;//abc.com/fsl-6.1.0-macos-64.yml",
                          "sha256"      : "ab23456...",
                      }
                      'linux-64-cuda9.2' : {
                          "environment" : "http;//abc.com/fsl-6.1.0-linux-64-cuda9.2.yml",
                          "sha256"      : "ab23456...",
                      }
                      'linux-64-cuda10.2' : {
                          "environment" : "http;//abc.com/fsl-6.1.0-linux-64-cuda10.2.yml",
                          "sha256"      : "ab23456...",
                      }
                  }
                  "6.1.1" : {
                      ...
                  }
              }
          }
        """

        log.debug('Downloading FSL installer manifest from %s', url)

        with tempdir():
            download_file(url, 'manifest.json')
            with open('manifest.json') as f:
                lines = f.readlines()

        # Drop comments
        lines = [l for l in lines if not l.lstrip().startswith('//')]

        return json.loads('\n'.join(lines))


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
    INFO      : '\033[37m',         # Light grey
    IMPORTANT : '\033[92m',         # Green
    QUESTION  : '\033[36m\033[4m',  # Blue+underline
    PROMPT    : '\033[36m\033[1m',  # Bright blue+bold
    WARNING   : '\033[93m',         # Yellow
    ERROR     : '\033[91m',         # Red
    EMPHASIS  : '\033[1m',          # White+bold
    UNDERLINE : '\033[4m',          # Underline
    RESET     : '\033[0m',          # Used internally
}


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


class ChecksumError(Exception):
    """Exception raised by the sha256 function if a file checksume does
    not match the expected checksum.
    """


def sha256(filename, check_against=None, blocksize=1048576):
    """Calculate the SHA256 checksum of the given file. If check_against
    is provided, it is compared against the calculated checksum, and an
    error is raised if they are not the same.
    """

    hashobj = hashlib.sha256()

    with open(filename, 'rb') as f:
        while True:
            block = f.read(blocksize)
            if len(block) == 0:
                break
            hashobj.update(block)

    checksum = hashobj.hexdigest()

    if check_against is not None:
        if checksum != check_against:
            raise ChecksumError('File {} does not match expected checksum '
                                '({})'.format(filename, check_against))

    return checksum


class DownloadFailed(Exception):
    """Exception type raised by the download_file function if a
    download fails for some reason.
    """


def download_file(url, destination, blocksize=1048576, progress=None):
    """Download a file from url, saving it to destination. """

    def default_progress(downloaded, total):
        pass

    if progress is None:
        progress = default_progress

    # def report_progress(downloaded, total):
    #     downloaded = downloaded / 1048576
    #     total      = total      / 1048576
    #     if total is not None:
    #         msg = '{:.1f} / {:.1f}MB ...'.format(downloaded, total)
    #     else:
    #         msg = '{:.1f}MB ...'.format(downloaded)
    #     printmsg(msg, end='\r')

    log.debug('Downloading %s ...', url)

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
                progress(downloaded, total)

    except urllib.error.HTTPError as e:
        raise DownloadFailed(f'A network error has occurred while '
                             f'trying to download {destname}') from e


def sudo_popen(cmd, password, **kwargs):
    """Runs "sudo cmd" using subprocess.Popen. """

    cmd  = ['sudo', '-S', '-k'] + cmd
    proc = sp.Popen(
        cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE, **kwargs)
    proc.stdin.write('{}\n'.format(password).encode())
    return proc


def run(ctx, cmd, display_output=False, admin=False):
    """Runs the given command, as administrator if requested. """

    admin = admin and os.getuid() != 0

    log.debug('Running %s [as admin: %s]', cmd, admin)

    cmd = shlex.split(cmd)

    if admin:
        proc = sudo_popen(cmd, password)
    else:
        proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)

    (output, error) = proc.communicate()


class UnsupportedPlatform(Exception):
    """Exception raised by the identify_platform function if FSL is not
    available on this platform.
    """


def list_available_versions(ctx):
    """Lists available FSL versions. """
    printmsg('Available FSL versions:', EMPHASIS)
    for version in ctx.manifest['versions']:
        if version == 'latest':
            continue
        printmsg(version, IMPORTANT, EMPHASIS)
        for build in ctx.manifest['versions'][version]:
            if build.get('cuda', '').strip() != '':
                template = '  {platform} [CUDA {cuda}]'
            else:
                template = '  {platform}'
            printmsg(template.format(**build), EMPHASIS, end=' ')
            printmsg(build['environment'], INFO)


def install_miniconda(ctx):
    """Downloads the miniconda/miniforge installer, and installs it to the
    destination directory.
    """

    url      = ctx.manifest['installer']['miniconda'][ctx.platform]['url']
    checksum = ctx.manifest['installer']['miniconda'][ctx.platform]['sha256']

    printmsg('Downloading miniconda from {}...'.format(url))

    download_file(url, 'miniforge.sh')
    sha256('miniforge.sh', checksum)
    cmd = 'sh miniforge.sh -b -p {}'.format(ctx.destdir)
    run(ctx, cmd, admin=ctx.need_admin)
    # TODO create .condarc


def install_fsl(ctx):
    """Install FSL into ctx.destdir (which is assumed to be a miniforge
    installation.
    """

    builds = ctx.manifest['versions'][ctx.args.fslversion][ctx.platform]
    for build in builds:
        if ctx.cuda == build.get('cuda', None):
            break
    else:
        raise

    if cudaver is not None:
        filename = 'fsl-{}-{}-cuda-{}.yml'.format(fslversion,
                                                  platform,
                                                  cudaver)
    else:
        filename = 'fsl-{}-{}.yml'.format(fslversion, platform)

    download_file(base + filename, 'environment.yml')

    conda = op.join(destdir, 'bin', 'conda')

    run(ctx, conda + ' env update -n base -f environment.yml',
        admin=ctx.need_admin)


def configure_environment(ctx):
    """Configures the user's shell environment (e.g. ~/.bash_profile). """
    # TODO
    pass


def self_update(ctx):
    """Checks to see if a newer version of the installer (this script) is
    available and if so, downloads it to a temporary file, and runs it in
    place of this script.
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

    thisver   = Version(__version__)
    latestver = Version(ctx.manifest['installer']['version'])

    if latestver <= thisver:
        log.debug('Installer is up to date (this vesrion: %s, '
                  'latest version: %s)', thisver, latestver)
        return

    log.debug('New version of installer is available '
              '(%s) - self-updating', latestver)

    tmpf = tempfile.NamedTemporaryFile(delete=False)
    tmpf.close()
    tmpf = tmpf.name

    download_file(ctx.manifest['installer']['url'], tmpf)

    if not ctx.args.disable_checksum:
        sha256(tmpf, ctx.manifest['installer']['sha256'])

    cmd = [sys.executable, tmpf] + sys.argv[1:]
    log.debug('Running new installer: %s', cmd)
    os.execv(sys.executable, cmd)


def parse_args(argv=None):
    """Parse command-line arguments, returns an argparse.Namespace object. """

    helps = {
        'dest' :                'Install FSL into this folder (default: '
                                '{})'.format(DEFAULT_INSTALLATION_DIRECTORY),
        'version'             : 'Print installer version number and exit',
        'disable_self_update' : 'Do not automatically update the installer '
                                'script',
        'listversions'        : 'List available versions of FSL',
        'fslversion'          : 'Download this specific version of FSL',
        'cuda'                : 'Install FSL for this CUDA version (default: '
                                'automatically detected)',

        # Path to local installer manifest file
        'manifest'            : argparse.SUPPRESS,

        # Print debugging messages
        'debug'               : argparse.SUPPRESS,

        # Disable SHA256 checksum validation of downloaded files
        'disable_checksum'    : argparse.SUPPRESS,
    }

    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--version', action='version',
                        version=__version__, help=helps['version'])
    parser.add_argument('-D', '--debug', action='store_true',
                        help=helps['debug'])
    parser.add_argument('-m', '--manifest', default=FSL_INSTALLER_MANIFEST,
                        help=helps['manifest'])
    parser.add_argument('-u', '--disable_self_update', action='store_true',
                        help=helps['disable_self_update'])
    parser.add_argument('-d', '--dest', metavar='DESTDIR',
                        help=helps['dest'])
    parser.add_argument('-s', '--disable_checksum', action='store_true',
                        help=helps['disable_checksum'])
    parser.add_argument('-l', '--listversions', action='store_true',
                        help=helps['listversions'])
    parser.add_argument('-V', '--fslversion', default='latest',
                        help=helps['version'])
    parser.add_argument('-c', '--cuda', help=helps['cuda'])

    args = parser.parse_args(argv)

    logging.basicConfig()
    if args.debug: logging.getLogger().setLevel(logging.DEBUG)
    else:          logging.getLogger().setLevel(logging.WARNING)

    return args


def main(argv=None):

    args = parse_args(argv)
    ctx  = Context(args)

    if not args.disable_self_update:
        self_update(ctx)

    printmsg('FSL installer version:', EMPHASIS, UNDERLINE, end='')
    printmsg(' ' + __version__ + '\n')

    if args.listversions:
        list_available_versions(ctx)
        sys.exit(0)

    ctx.finalise_settings()

    printmsg('Installing FSL into {}'.format(ctx.destdir))

    with tempdir():
        install_miniconda(ctx)
        install_fsl(ctx)


if __name__ == '__main__':
    sys.exit(main())
