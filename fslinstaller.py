#!/usr/bin/env python
#
# FSL installer script.
#
"""This is the FSL installation script. It can be used to install FSL, or
to update an existing FSL installation.  This script can be executed with
Python 2.7 or newer.
"""


from __future__ import print_function, division, unicode_literals

import functools      as ft
import os.path        as op
import subprocess     as sp
import textwrap       as tw
import                   argparse
import                   contextlib
import                   fnmatch
import                   getpass
import                   hashlib
import                   json
import                   logging
import                   os
import                   platform
import                   re
import                   readline
import                   shlex
import                   shutil
import                   ssl
import                   sys
import                   tempfile
import                   threading
import                   traceback

try:                import urllib.request as urlrequest
except ImportError: import urllib         as urlrequest


try:                import urllib.parse as urlparse
except ImportError: import                 urlparse

try:                import queue
except ImportError: import Queue as queue


PYVER = sys.version_info[:2]


log = logging.getLogger(__name__)


# this sometimes gets set to fslinstaller.pyc, so rstrip c
__absfile__ = op.abspath(__file__).rstrip('c')


__version__ = '1.9.0'
"""Installer script version number. This must be updated
whenever a new version of the installer script is released.
"""


DEFAULT_INSTALLATION_DIRECTORY = op.join(op.expanduser('~'), 'fsl')
"""Default FSL installation directory. """


FSL_RELEASE_MANIFEST = 'https://fsl.fmrib.ox.ac.uk/fsldownloads/' \
                       'fslconda/releases/manifest.json'
"""URL to download the FSL installer manifest file from. The installer
manifest file is a JSON file which contains information about available FSL
versions.

See the Context.download_manifest function, and an example manifest file
in test/data/manifest.json, for more details.

A custom manifest URL can be specified with the -a/--manifest command-line
option.
"""


FSL_DEV_RELEASES = 'https://fsl.fmrib.ox.ac.uk/fsldownloads/' \
                   'fslconda/releases/devreleases.txt'
"""URL to the devreleases.txt file, which contains a list of available
internal/development FSL releases.
"""


FIRST_FSL_CONDA_RELEASE = '6.0.6'
"""Oldest conda-based FSL version that can be updated in-place by this
installer script. Versions older than this will need to be overwritten.
"""


@ft.total_ordering
class Version(object):
    """Class to represent and compare version strings.  Accepted version
    strings are of the form W.X.Y.Z, where W, X, Y, and Z are all integers.
    """
    def __init__(self, verstr):
        # Version identifiers for official FSL
        # releases will have up to four
        # components (X.Y.Z.W), but We accept
        # any number of (integer) components,
        # as internal releases may have more.
        components = []

        for comp in verstr.split('.'):
            try:              components.append(int(comp))
            except Exception: break

        self.components = components
        self.verstr     = verstr

    def __str__(self):
        return self.verstr

    def __eq__(self, other):
        for sn, on in zip(self.components, other.components):
            if sn != on:
                 return False
        return len(self.components) == len(other.components)

    def __lt__(self, other):
        for p1, p2 in zip(self.components, other.components):
            if p1 < p2: return True
            if p1 > p2: return False
        return len(self.components) < len(other.components)


class Context(object):
    """Bag of information and settings created in the main function, and passed
    around this script.

    Several settings are lazily evaluated on first access, but once evaluated,
    their values are immutable.
    """

    def __init__(self, args):
        """Create the context with the argparse.Namespace object containing
        parsed command-line arguments.
        """

        self.args  = args
        self.shell = op.basename(os.environ.get('SHELL', 'sh')).lower()

        # These attributes are updated on-demand via
        # the property accessors defined below, or all
        # all updated via the finalise-settings method.
        self.__platform       = None
        self.__manifest       = None
        self.__devmanifest    = None
        self.__build          = None
        self.__destdir        = None
        self.__need_admin     = None
        self.__admin_password = None

        # These attributes are set by main - exists is
        # a flag denoting whether the dest dir already
        # exists, and update is the version string of
        # the existing FSL installation if the user
        # has selected to update it, or None otherwise.
        self.exists = False
        self.update = None

        # If the destination directory already exists,
        # and the user chooses to overwrite it, it is
        # moved so that, if the installation fails, it
        # can be restored. The new path is stored
        # here - refer to overwrite_destdir.
        self.old_destdir = None

        # The download_fsl_environment function stores
        # the path to the FSL conda environment file,
        # list of conda channels, and versions of a
        # small set of "base" packages here.
        self.environment_file     = None
        self.environment_channels = None
        self.fsl_base_packages    = None

        # The config_logging function stores the path
        # to the fslinstaller log file here.
        self.logfile = None


    def finalise_settings(self):
        """Finalise values for all information and settings in the Context.
        """
        self.manifest
        self.platform
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
    def build(self):
        """Returns a suitable FSL build (a dictionary entry from the FSL
        installer manifest) for the target platform.

        The returned dictionary has the following elements:
          - 'version'      FSL version.
          - 'platform':    Platform identifier (e.g. 'linux-64')
          - 'environment': Environment file to download
          - 'sha256':      Checksum of environment file
          - 'output':      Number of lines of expected output, for reporting
                           progress
        """

        if self.__build is not None:
            return self.__build

        # defaults to "latest" if
        # not specified by the user
        fslversion = self.args.fslversion

        if fslversion not in self.manifest['versions']:
            available = ', '.join(self.manifest['versions'].keys())
            raise Exception(
                'FSL version "{}" is not available - available '
                'versions: {}'.format(fslversion, available))

        if fslversion == 'latest':
            fslversion = self.manifest['versions']['latest']

        # Find refs to a suitable build for this
        # platform. We assume that there is only
        # one default build for each platform.
        # in the list of builds for a given FSL
        # version.
        build = None

        for candidate in self.manifest['versions'][fslversion]:
            if candidate['platform'] == self.platform:
                build = candidate
                break

        if build is None:
            raise Exception(
                'Cannot find a version of FSL matching '
                'platform {}'.format(self.platform))

        printmsg('FSL {} selected for installation'.format(build['version']))

        self.__build = build
        return build


    @property
    def destdir(self):
        """Installation directory. If not specified at the command line, the
        user is prompted to enter a directory.
        """

        if self.__destdir is not None:
            return self.__destdir

        # The loop below validates the destination directory
        # both when specified at commmand line or
        # interactively.  In either case, if invalid, the
        # user is re-prompted to enter a new destination.
        destdir = None
        if self.args.dest is not None: response = self.args.dest
        else:                          response = None

        while destdir is None:

            if response is None:
                printmsg('\nWhere do you want to install FSL?',
                         IMPORTANT, EMPHASIS)
                printmsg('Press enter to install to the default location '
                         '[{}]\n'.format(DEFAULT_INSTALLATION_DIRECTORY), INFO)
                response = prompt('FSL installation directory [{}]:'.format(
                    DEFAULT_INSTALLATION_DIRECTORY), QUESTION, EMPHASIS)
                response = response.rstrip(op.sep)

                if response == '':
                    response = DEFAULT_INSTALLATION_DIRECTORY

            response  = op.expanduser(op.expandvars(response))
            response  = op.abspath(response)
            parentdir = op.dirname(response)
            if op.exists(parentdir):
                destdir = response
            else:
                printmsg('Destination directory {} does not '
                         'exist!'.format(parentdir), ERROR)
                response = None

        self.__destdir = destdir
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
        self.__admin_password = Context.get_admin_password()


    @property
    def manifest(self):
        """Returns the FSL installer manifest as a dictionary. """
        if self.__manifest is None:
            if self.devmanifest is not None:
                self.args.manifest = self.devmanifest

            self.__manifest = Context.download_manifest(self.args.manifest,
                                                        self.args.workdir)
        return self.__manifest


    @property
    def devmanifest(self):
        """Returns a URL to a development manifest to use for installation.
        This will only return a value if the --devrelease or --devlatest
        options are active.

        If this is the case, the FSL_DEV_RELEASES file is downloaded - this
        file contains a list of available development manifest URLS. The
        user is then prompted to choose which development manifest to use
        for the installation, unless --devlatest is active, in which case
        the newest manifest is selected.
        """
        if not self.args.devrelease:
            return None
        if self.__devmanifest == 'na':
            return None
        elif self.__devmanifest is not None:
            return self.__devmanifest

        # parse a dev manifest file name, returning
        # a sequence containing the tage, date, commit
        # hash, and branch name. Dev manifest files
        # are named like so:
        #
        #   manifest-<tag>.<date>.<commit>.<branch>.json
        #
        # where <tag> is the tag of the most recent
        # public FSL release, and everything else is
        # self-explanatory.
        def parse_devrelease_name(url):
            name = urlparse.urlparse(url).path
            name = op.basename(name)
            name = name.lstrip('manifest-').rstrip('.json')
            # Awkward - the tag may have periods in it
            name = name.rsplit('.', maxsplit=3)
            return name

        # list of (url, tag, date, commit, branch),
        # sorted by date
        devreleases = []

        with tempdir(self.args.workdir):
            download_file(FSL_DEV_RELEASES, 'devreleases.txt')

            with open('devreleases.txt', 'rt') as f:
                urls = f.readlines()
                urls = [l.strip() for l in urls]

            for url in urls:
                devreleases.append([url] + parse_devrelease_name(url))

        devreleases = sorted(devreleases, key=lambda r: r[2])

        if len(devreleases) == 0:
            self.__devmanifest = 'na'
            return None

        # automatically choose latest dev manifest?
        if self.args.devlatest:
            devrelease = devreleases[-1][0]
        # show the user a list, ask them which one they want
        else:
            printmsg('Available development releases:', EMPHASIS)
            for i, (url, tag, date, commit, branch) in enumerate(devreleases):
                printmsg('  [{}]: {} [{} commit {}]'.format(
                    i + 1, date, branch, commit), IMPORTANT)
            while True:
                selection = prompt('Which release would you like to '
                                   'install? [1]: ', PROMPT)
                if selection == '':
                    selection = '1'
                try:
                    selection = int(selection) - 1
                except Exception:
                    continue
                if selection >= 0 and selection < len(devreleases):
                    break
            devrelease = devreleases[selection][0]

        self.__devmanifest = devrelease
        return self.__devmanifest


    @staticmethod
    def identify_platform():
        """Figures out what platform we are running on. Returns a platform
        identifier string - one of:

          - "linux-64" (Linux, x86_64)
          - "macos-64" (macOS, x86_64)
        """

        platforms = {
            ('linux',  'x86_64') : 'linux-64',
            ('darwin', 'x86_64') : 'macos-64',

            # M1 builds (and possbily ARM for Linux)
            # will be added in the future
            ('darwin', 'arm64')  : 'macos-64',
        }

        system = platform.system().lower()
        cpu    = platform.machine()
        key    = (system, cpu)

        if key not in platforms:
            supported = ', '.join(['[{}, {}]' for s, c in platforms])
            raise Exception('This platform [{}, {}] is unrecognised or '
                            'unsupported! Supported platforms: {}'.format(
                                system, cpu, supported))

        return platforms[key]


    @staticmethod
    def check_need_admin(dirname):
        """Returns True if dirname needs administrator privileges to write to,
        False otherwise.
        """
        # os.supports_effective_ids added in
        # python 3.3, so can't be used here
        return not os.access(dirname, os.W_OK | os.X_OK)


    @staticmethod
    def get_admin_password():
        """Prompt the user for their administrator password."""

        def validate_admin_password(password):
            proc = Process.sudo_popen(['true'], password, stdin=sp.PIPE)
            proc.communicate()
            return proc.returncode == 0

        for attempt in range(3):
            if attempt == 0:
                msg = 'Your administrator password is needed to ' \
                      'install FSL: '
            else:
                msg = 'Your administrator password is needed to ' \
                      'install FSL [attempt {} of 3]:'.format(attempt + 1)
            printmsg(msg, IMPORTANT, end='')
            password = getpass.getpass('')
            valid    = validate_admin_password(password)

            if valid:
                printmsg('Password accepted', INFO)
                break
            else:
                printmsg('Incorrect password', WARNING)

        if not valid:
            raise Exception('Incorrect password')

        return password


    @staticmethod
    def download_manifest(url, workdir=None):
        """Downloads the installer manifest file, which contains information
        about available FSL versions, and the most recent version number of the
        installer (this script).

        The manifest file is a JSON file. Lines beginning
        with a double-forward-slash are ignored. See test/data/manifes.json
        for an example.

        This function modifies the manifest structure by adding a 'version'
        attribute to all FSL build entries.
        """

        log.debug('Downloading FSL installer manifest from %s', url)

        with tempdir(workdir):
            download_file(url, 'manifest.json')
            with open('manifest.json') as f:
                lines = f.readlines()

        # Drop comments
        lines = [l for l in lines if not l.lstrip().startswith('//')]

        manifest = json.loads('\n'.join(lines))

        # Add "version" to every build
        for version, builds in manifest['versions'].items():
            if version == 'latest':
                continue
            for build in builds:
                build['version'] = version

        return manifest


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


def printmsg(msg='', *msgtypes, **kwargs):
    """Prints msg according to the ANSI codes provided in msgtypes.
    All other keyword arguments are passed through to the print function.

    :arg msgtypes: Message types to control formatting
    :arg log:      If True (default), the message is logged.

    All other keyword arguments are passed to the built-in print function.
    """
    logmsg   = kwargs.pop('log', msg != '')
    msgcodes = [ANSICODES[t] for t in msgtypes]
    msgcodes = ''.join(msgcodes)
    if logmsg:
        log.debug(msg)
    print('{}{}{}'.format(msgcodes, msg, ANSICODES[RESET]), **kwargs)
    sys.stdout.flush()


def prompt(prompt, *msgtypes, **kwargs):
    """Prompts the user for some input. msgtypes and kwargs are passed
    through to the printmsg function.
    """
    printmsg(prompt, *msgtypes, end='', log=False, **kwargs)

    if PYVER[0] == 2: response = raw_input(' ').strip()
    else:             response = input(    ' ').strip()

    log.debug('%s: %s', prompt, response)

    return response


class Progress(object):
    """Simple progress reporter. Displays one of the following:

       - If both a value and total are provided, a progress bar is shown
       - If only a value is provided, a cumulative count is shown
       - If nothing is provided, a spinner is shown.

    Use as a context manager, and call the update method to report progress,
    e,g:

        with Progress('%') as p:
            for i in range(100):
                p.update(i + 1, 100)
    """

    def __init__(self,
                 label='',
                 transform=None,
                 fmt='{:.1f}',
                 total=None,
                 width=None):
        """Create a Progress reporter.

        :arg label:     Units (e.g. "MB", "%",)

        :arg transform: Function to transform values (see e.g.
                        Progress.bytes_to_mb)

        :arg fmt:       Template string used to format value / total.

        :arg total:     Maximum value - overrides the total value passed to
                        the update method.

        :arg width:     Maximum width, if a progress bar is displayed. Default
                        is to automatically infer the terminal width (see
                        Progress.get_terminal_width).
        """

        if transform is None:
            transform = Progress.default_transform

        self.width     = width
        self.fmt       = fmt.format
        self.total     = total
        self.label     = label
        self.transform = transform

        # used by the spin function
        self.__last_spin = None

    @staticmethod
    def default_transform(val, total):
        return val, total

    @staticmethod
    def bytes_to_mb(val, total):
        if val   is not None: val   = val   / 1048576
        if total is not None: total = total / 1048576
        return val, total

    @staticmethod
    def percent(val, total):
        if val is None or total is None:
            return val, total
        return 100 * (val / total), 100

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        printmsg(log=False)

    def update(self, value=None, total=None):

        if total is None:
            total = self.total

        value, total = self.transform(value, total)

        if value is None and total is None:
            self.spin()
        elif value is not None and total is None:
            self.count(value)
        elif value is not None and total is not None:
            self.progress(value, total)

    def spin(self):

        symbols = ['|', '/', '-',  '\\']

        if self.__last_spin is not None: last = self.__last_spin
        else:                            last = symbols[-1]

        idx  = symbols.index(last)
        idx  = (idx + 1) % len(symbols)
        this = symbols[idx]

        printmsg(this, end='\r', log=False)
        self.__last_spin = this

    def count(self, value):

        value = self.fmt(value)

        if self.label is None: line = '{} ...'.format(value)
        else:                  line = '{}{} ...'.format(value, self.label)

        printmsg(line, end='\r', log=False)

    def progress(self, value, total):

        value = min(value, total)

        # arbitrary fallback of 50 columns if
        # terminal width cannot be determined
        if self.width is None: width = Progress.get_terminal_width(50)
        else:                  width = self.width

        fvalue = self.fmt(value)
        ftotal = self.fmt(total)
        suffix = '{} / {} {}'.format(fvalue, ftotal, self.label).rstrip()

        # +5: - square brackets around bar
        #     - space between bar and tally
        #     - space+spin at the end
        width     = width - (len(suffix) + 5)
        completed = int(round(width * (value  / total)))
        remaining = width - completed
        progress  = '[{}{}] {}'.format('#' * completed,
                                       ' ' * remaining,
                                       suffix)

        printmsg(progress, end='', log=False)
        printmsg(' ', end='', log=False)
        self.spin()
        printmsg(end='\r', log=False)


    @staticmethod
    def get_terminal_width(fallback=None):
        """Return the number of columns in the current terminal, or fallback
        if it cannot be determined.
        """
        # os.get_terminal_size added in python
        # 3.3, so we try it but fall back to
        # COLUMNS, or tput as a last resort.
        try:
            return os.get_terminal_size()[0]
        except Exception:
            pass

        try:
            return int(os.environ['COLUMNS'])
        except Exception:
            pass

        try:
            result = Process.check_output('tput cols')
            return int(result.strip())
        except Exception:
            return fallback


def isstr(s):
    """Returns True if s is a string, False otherwise, Works on python 2.7
    and >=3.3.
    """
    try:              return isinstance(s, basestring)
    except Exception: return isinstance(s, str)


def match_any(s, patterns):
    """Test if the string s matches any of the fnmatch-style patterns.
    Returns the matched pattern, or None.
    """
    for pat in patterns:
        if fnmatch.fnmatch(s, pat):
            return pat
    return None


@contextlib.contextmanager
def tempdir(override_dir=None):
    """Returns a context manager which creates, changes into, and returns a
    temporary directory, and then deletes it on exit.

    If override_dir is not None, instead of creating and changing into a
    temporary directory, this function just changes into override_dir.
    """

    if override_dir is None: tmpdir = tempfile.mkdtemp()
    else:                    tmpdir = override_dir

    prevdir = os.getcwd()

    try:
        os.chdir(tmpdir)
        yield tmpdir

    finally:
        os.chdir(prevdir)
        if override_dir is None:
            shutil.rmtree(tmpdir)


@contextlib.contextmanager
def tempfilename(permissions=None, delete=True):
    """Returns a context manager which creates a temporary file, yields its
    name, then deletes the file on exit.
    """

    fname = None

    try:
        tmpf  = tempfile.NamedTemporaryFile(delete=False)
        fname = tmpf.name

        tmpf.close()

        if permissions:
            os.chmod(fname, permissions)

        yield fname

    finally:
        if delete and fname and op.exists(fname):
            os.remove(fname)


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
            raise Exception('File {} does not match expected checksum '
                            '({})'.format(filename, check_against))

    return checksum


def clean_environ():
    """Return a dict containing a set of sanitised environment variables.

    All FSL and conda related variables are removed.
    """
    env = os.environ.copy()
    for v in list(env.keys()):
        if any(('FSL' in v, 'CONDA' in v)):
            env.pop(v)
    return env


def download_file(url,
                  destination,
                  progress=None,
                  blocksize=131072,
                  ssl_verify=True):
    """Download a file from url, saving it to destination. """

    def default_progress(downloaded, total):
        pass

    if progress is None:
        progress = default_progress

    log.debug('Downloading %s ...', url)

    # Path to local file
    if op.exists(url):
        url = 'file:' + urlrequest.pathname2url(op.abspath(url))

    # We create and use an unconfigured SSL
    # context to disable SSL verification.
    # Otherwise pass None causes urlopen to
    # use default behaviour. The context
    # argument is not available in py3.3
    kwargs = {}
    if (not ssl_verify) and (PYVER != (3, 3)):
        printmsg('Skipping SSL verification - this '
                 'is not recommended!', WARNING)
        kwargs['context'] = ssl.SSLContext(ssl.PROTOCOL_TLS)

    req = None

    try:
        # py2: urlopen result cannot be
        # used as a context manager
        req = urlrequest.urlopen(url, **kwargs)
        with open(destination, 'wb') as outf:

            try:             total = int(req.headers['content-length'])
            except KeyError: total = None

            downloaded = 0

            progress(downloaded, total)
            while True:
                block = req.read(blocksize)
                if len(block) == 0:
                    break
                downloaded += len(block)
                outf.write(block)
                progress(downloaded, total)

    finally:
        if req:
            req.close()


class Process(object):
    """Container for a subprocess.Popen object, allowing non-blocking
    line-based access to its standard output and error streams via separate
    queues, while logging all outputs.

    Don't create a Process directly - use one of the following static methods:
     - Process.check_output
     - Process.check_call
     - Process.monitor_progress
    """


    def __init__(self,
                 cmd,
                 admin=False,
                 ctx=None,
                 log_output=True,
                 append_env=None,
                 **kwargs):
        """Run the specified command. Starts threads to capture stdout and
        stderr.

        :arg cmd:        Command to run - passed directly to subprocess.Popen

        :arg admin:      Run the command with administrative privileges

        :arg ctx:        The installer Context. Only used for admin password -
                         can be None if admin is False.

        :arg log_output: If True, the command and all of its stdout/stderr are
                         logged.

        :arg append_env: Dictionary of additional environment to be set when
                         the command is run.

        :arg kwargs:     Passed to subprocess.Popen
        """

        self.ctx        = ctx
        self.cmd        = cmd
        self.admin      = admin
        self.log_output = log_output
        self.stdoutq    = queue.Queue()
        self.stderrq    = queue.Queue()

        if log_output:
            log.debug('Running %s [as admin: %s]', cmd, admin)

        self.popen = Process.popen(
            self.cmd, self.admin, self.ctx,
            append_env=append_env, **kwargs)

        # threads for consuming stdout/stderr
        self.stdout_thread = threading.Thread(
            target=Process.forward_stream,
            args=(self.popen.stdout, self.stdoutq, cmd, 'stdout', log_output))
        self.stderr_thread = threading.Thread(
            target=Process.forward_stream,
            args=(self.popen.stderr, self.stderrq, cmd, 'stderr', log_output))

        self.stdout_thread.daemon = True
        self.stderr_thread.daemon = True
        self.stdout_thread.start()
        self.stderr_thread.start()


    def wait(self):
        """Waits for the process to terminate, then waits for the stdout
        and stderr consumer threads to finish.
        """
        self.popen.wait()
        self.stdout_thread.join()
        self.stderr_thread.join()


    @property
    def returncode(self):
        """Process return code. Returns None until the process has terminated,
        and the stdout/stderr consumer threads have finished.
        """
        if self.popen.returncode is None: return None
        if self.stdout_thread.is_alive(): return None
        if self.stderr_thread.is_alive(): return None
        return self.popen.returncode


    @staticmethod
    def check_output(cmd, *args, **kwargs):
        """Behaves like subprocess.check_output. Runs the given command, then
        waits until it finishes, and return its standard output. An error
        is raised if the process returns a non-zero exit code.

        :arg cmd: The command to run, as a string
        """

        proc = Process(cmd, *args, **kwargs)
        proc.wait()

        if proc.returncode != 0:
            raise RuntimeError('This command returned an error: ' + cmd)

        stdout = ''
        while True:
            try:
                stdout += proc.stdoutq.get_nowait()
            except queue.Empty:
                break

        return stdout


    @staticmethod
    def check_call(cmd, *args, **kwargs):
        """Behaves like subprocess.check_call. Runs the given command, then
        waits until it finishes. An error is raised if the process returns a
        non-zero exit code.

        :arg cmd: The command to run, as a string
        """
        proc = Process(cmd, *args, **kwargs)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError('This command returned an error: ' + cmd)


    @staticmethod
    def monitor_progress(cmd, total=None, *args, **kwargs):
        """Runs the given command(s), and shows a progress bar under the
        assumption that cmd will produce "total" number of lines of output.

        :arg cmd:   The commmand to run as a string, or a sequence of
                    multiple commands.
        :arg total: Total number of lines of standard output to expect.
        """
        if total is None: label = None
        else:             label = '%'

        if isstr(cmd): cmds = [cmd]
        else:          cmds =  cmd

        with Progress(label=label,
                      fmt='{:.0f}',
                      transform=Progress.percent) as prog:

            nlines = 0 if total else None

            for cmd in cmds:

                proc = Process(cmd, *args, **kwargs)
                prog.update(nlines, total)

                while proc.returncode is None:
                    try:
                        line    = proc.stdoutq.get(timeout=0.5)
                        nlines  = (nlines + 1) if total else None

                    except queue.Empty:
                        pass

                    prog.update(nlines, total)
                    proc.popen.poll()

                # force progress bar to 100% when finished
                if proc.returncode == 0:
                    prog.update(total, total)
                else:
                    raise RuntimeError('This command returned '
                                       'an error: ' + cmd)


    @staticmethod
    def forward_stream(stream, queue, cmd, streamname, log_output):
        """Reads lines from stream and pushes them onto queue until popen
        is finished. Logs every line.

        :arg stream:     stream to forward
        :arg queue:      queue.Queue to push lines onto
        :arg cmd:        string - the command that is running
        :arg streamname: string - 'stdout' or 'stderr'
        :arg log_output: If True, log all stdout/stderr.
        """

        while True:
            line = stream.readline().decode('utf-8')
            if line == '':
                break
            queue.put(line)
            if log_output:
                log.debug(' [%s]: %s', streamname, line.rstrip())


    @staticmethod
    def popen(cmd, admin=False, ctx=None, append_env=None, **kwargs):
        """Runs the given command via subprocess.Popen, as administrator if
        requested.

        :arg cmd:        The command to run, as a string

        :arg admin:      Whether to run with administrative privileges

        :arg ctx:        The installer Context object. Only required if admin is
                         True.

        :arg append_env: Dictionary of additional environment to be set when
                         the command is run.

        :arg kwargs:     Passed to subprocess.Popen. stdin, stdout, and stderr
                         will be silently clobbered

        :returns:        The subprocess.Popen object.
        """

        admin = admin and os.getuid() != 0

        if admin: password = ctx.admin_password
        else:     password = None

        cmd              = shlex.split(cmd)
        kwargs['stdin']  = sp.PIPE
        kwargs['stdout'] = sp.PIPE
        kwargs['stderr'] = sp.PIPE

        if admin:
            proc = Process.sudo_popen(cmd, password, append_env, **kwargs)
        else:
            # if append_env has been specified,
            # add it to the normal env option.
            if append_env is not None:
                env = kwargs.get('env', os.environ.copy())
                env.update(append_env)
                kwargs['env'] = env

            proc = sp.Popen(cmd, **kwargs)

        return proc


    @staticmethod
    def sudo_popen(cmd, password, append_env=None, **kwargs):
        """Runs "sudo cmd" using subprocess.Popen. Used by Process.popen.
        Assumes that kwargs contains stdin=sp.PIPE
        """

        # sudo will not necessarily propagate environment
        # variables, and there is no guarantee that the
        # sudo -E option will work. So here we create a
        # wrapper shell script with "export VAR=VALUE"
        # statements for all environment variables that
        # are set.
        if append_env is None:
            append_env = {}

        # Make the wrapper script delete itself
        # after the command has been executed.
        with tempfilename(0o755, delete=False) as wrapper:
            with open(wrapper, 'wt') as f:
                f.write('#!/usr/bin/env sh\n')
                f.write('set -e\n')
                f.write('thisfile=$0\n')
                f.write('thisdir=$(cd $(dirname $0) && pwd)\n')
                for k, v in append_env.items():
                    f.write('export {}="{}"\n'.format(k, v))
                # shlex.join not available in py27
                f.write(' '.join(cmd) + '\n')
                f.write('cd ${thisdir} && rm ${thisfile}\n')

        cmd  = ['sudo', '-S', '-k', wrapper]
        proc = sp.Popen(cmd, **kwargs)
        proc.stdin.write('{}\n'.format(password).encode())
        proc.stdin.flush()
        return proc


def list_available_versions(manifest):
    """Lists available FSL versions. """
    printmsg('Available FSL versions:', EMPHASIS)
    for version in manifest['versions']:
        if version == 'latest':
            continue
        printmsg(version, IMPORTANT, EMPHASIS)
        for build in manifest['versions'][version]:
            printmsg('  {}'.format(build['platform']), EMPHASIS, end=' ')
            printmsg(build['environment'], INFO)


def download_fsl_environment(ctx):
    """Downloads the environment specification file for the selected FSL
    version.

    Internal/development FSL versions may source packages from the internal
    FSL conda channel, which requires a username+password to authenticate.

    These are referred to in the environment file as ${FSLCONDA_USERNAME}
    and ${FSLCONDA_PASSWORD}.

    If the user has not provided a username+password on the command-line, they
    are prompted for them.

    The downloaded environment file may be modified - if the user has requested
    a specific CUDA version, or no CUDA packages (--cuda or --no_cuda), all
    CUDA packages are removed from the environment file.
    """

    build        = ctx.build
    url          = build['environment']
    checksum     = build.get('sha256',        None)
    basepkgnames = build.get('base_packages', [])

    printmsg('Downloading FSL environment specification '
             'from {}...'.format(url))
    fname = url.split('/')[-1]
    download_file(url, fname)
    ctx.environment_file = op.abspath(fname)
    if (checksum is not None) and (not ctx.args.no_checksum):
        sha256(fname, checksum)

    # Environment files for internal/dev FSL versions
    # will list the internal FSL conda channel with
    # ${FSLCONDA_USERNAME} and ${FSLCONDA_PASSWORD}
    # as placeholders for the username/password.
    with open(fname, 'rt') as f:
        need_auth = '${FSLCONDA_USERNAME}' in f.read()

    # We need a username/password to access the internal
    # FSL conda channel. Prompt the user if they haven't
    # provided credentials.
    if need_auth and (ctx.args.username is None):
        printmsg('A username and password are required to install '
                 'this version of FSL.', WARNING, EMPHASIS)
        ctx.args.username = prompt('Username:').strip()
        ctx.args.password = getpass.getpass('Password: ').strip()

    # Conda expands environment variables within a
    # .condarc file, but *not* within an environment.yml
    # file. So to authenticate to our internal channel
    # without storing credentials anywhere in plain text,
    # we *move* the channel list from the environment.yml
    # file into $FSLDIR/.condarc.
    #
    # Here we extract the channels from the environment
    # file, and save them to ctx.environment_channels.
    # The install_miniconda function will then add the
    # channels to $FSLDIR/.condarc.
    #
    # A collection of "base" packages are installed
    # before any other packages. So we also extract the
    # version numbers of these base packages from the
    # environment file, and store them in the context.
    # Sort base package names from longest to shortest,
    # to avoid name conflicts (e.g. 'fsl-sub', and
    # 'fsl-sub_plugin_sge')
    basepkgnames = sorted(basepkgnames, key=len, reverse=True)
    copy         = '.' + op.basename(ctx.environment_file)
    channels     = []
    basepkgs     = {}

    shutil.move(ctx.environment_file, copy)
    with open(copy,                 'rt') as inf, \
         open(ctx.environment_file, 'wt') as outf:

        in_channels_section = False

        for line in inf:

            # start of channels list
            if line.strip() == 'channels:':
                in_channels_section = True
                continue

            if in_channels_section:
                # end of channels list
                if not line.strip().startswith('-'):
                    in_channels_section = False
                else:
                    channels.append(line.split()[-1])
                    continue

            # Save base package versions, as we
            # install them separately. Package
            # specs in the yml file are of the
            # form:
            #
            #   - <package> <version> [<build_variant>]
            #
            # From this we create a dict of the form:
            #
            #   - <package> : <version>[=<build_variant>]
            for pkg in basepkgnames:
                if line.strip().startswith('- {} '.format(pkg)):
                    pkgver        = line.strip().split(' ', 2)[2]
                    basepkgs[pkg] = pkgver.replace(' ', '=')

            # Include/exclude packages upon user request
            pkgname = line.strip(' -').split()[0]
            exclude = match_any(pkgname, ctx.args.exclude_package)
            include = match_any(pkgname, ctx.args.include_package)
            if exclude and not include:
                log.debug('Excluding package %s (matched '
                          '--exclude_package %s)', line, exclude)
            else:
                outf.write(line)

    ctx.environment_channels = channels
    ctx.fsl_base_packages    = basepkgs


def download_miniconda(ctx):
    """Downloads the miniconda/miniforge installer and saves it as
    "miniconda.sh".

    This function assumes that it is run within a temporary/scratch directory.
    """

    metadata = ctx.manifest['miniconda'][ctx.platform]
    url      = metadata['url']
    checksum = metadata['sha256']
    output   = metadata.get('output', '').strip()

    if output == '': output = None
    else:            output = int(output)

    # Download
    printmsg('Downloading miniconda from {}...'.format(url))
    with Progress('MB', transform=Progress.bytes_to_mb) as prog:
        download_file(url, 'miniconda.sh', prog.update)
    if not ctx.args.no_checksum:
        sha256('miniconda.sh', checksum)


def install_miniconda(ctx):
    """Downloads the miniconda/miniforge installer, and installs it to the
    destination directory.

    This function assumes that it is run within a temporary/scratch directory.
    """

    metadata = ctx.manifest['miniconda'][ctx.platform]
    url      = metadata['url']
    checksum = metadata['sha256']
    output   = metadata.get('output', '').strip()

    if output == '': output = None
    else:            output = int(output)

    # Install
    printmsg('Installing miniconda at {}...'.format(ctx.destdir))
    env = clean_environ()
    cmd = 'sh miniconda.sh -b -p {}'.format(ctx.destdir)
    Process.monitor_progress(cmd, output, ctx.need_admin, ctx, env=env)

    # Avoid WSL filesystem issue
    # https://github.com/conda/conda/issues/9948
    cmd = 'find {} -type f -exec touch {{}} +'.format(ctx.destdir)
    Process.check_call(cmd, ctx.need_admin, ctx)

    # Create .condarc config file
    condarc = tw.dedent("""
    # Try and make package downloads more robust
    remote_read_timeout_secs:    240
    remote_connect_timeout_secs: 20
    remote_max_retries:          10
    remote_backoff_factor:       5
    safety_checks:               warn

    # Disable caching of remote channel repodata.
    # This is a hack which is combined with the
    # WSL1 filesystem hack in the fslinstaller
    # script - because we have modified file
    # timestamps, conda will assume that its
    # channel repodata cache is up to date, and
    # will not bother refreshing it in the
    # commands that we run in the install_fsl
    # function. When we remove the WSL1 hack from
    # the fslinstaller, we can remove this config
    # setting.
    # https://github.com/conda/conda/issues/9948
    local_repodata_ttl: 0

    # Channel priority is important. In older versions
    # of FSL we placed the FSL conda channel at the
    # bottom (lowest priority) for legacy reasons (to
    # ensure that conda-forge versions of e.g. VTK were
    # preferred over legacy FSL conda versions).
    #
    # Use final/top/bottom marks to prevent the channel
    # priority order being modified by user ~/.condarc
    # configuration files.
    #
    # https://conda.io/projects/conda/en/latest/user-guide/configuration/use-condarc.html
    # https://www.anaconda.com/blog/conda-configuration-engine-power-users
    # https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-channels.html
    channel_priority: strict #!final
    """)

    if ctx.args.skip_ssl_verify:
        printmsg('Configuring conda to skip SSL verification '
                 '- this is not recommended!', WARNING)
        condarc += tw.dedent("""
        # Disable SSL verification when accessing
        # conda channels over https:// (the
        # fslinstaller script was called with
        # --skip_ssl_verify). NOT RECOMMENDED.
        ssl_verify: false
        """)

    # Set up the channel list
    channels = list(ctx.environment_channels)
    if len(channels) > 0:
        channels[0]  += ' #!top'
        channels[-1] += ' #!bottom'
    condarc      += '\nchannels: #!final\n'
    for channel in channels:
        condarc += ' - {}\n'.format(channel)

    with open('.condarc', 'wt') as f:
        f.write(condarc)

    Process.check_call('cp -f .condarc {}'.format(ctx.destdir),
                       ctx.need_admin, ctx)


def install_fsl(ctx):
    """Install FSL into ctx.destdir (which is assumed to be a miniconda
    installation.

    This function assumes that it is run within a temporary/scratch directory.
    """

    # expected number of output lines for new
    # install or upgrade, used for progress
    # reporting. If manifest does not contain
    # expected #lines, we fall back to a spinner.
    if ctx.update is None:
        output = ctx.build.get('output', {}).get('install', None)
    else:
        output = ctx.build.get('output', {}).get(ctx.update, None)

    if output in ('', None): output = None
    else:                    output = int(output)

    conda = op.join(ctx.destdir, 'bin', 'conda')

    # We install FSL in two steps:
    #
    #   1. Install base packages. This is installed first, as
    #      FSL packages require fsl-base to be present during
    #      installation (in their post-link.sh scripts), and
    #      this is not guaranteed if everything is installed
    #      simultaneously. Also done for efficiency, so e.g.
    #      libopenblas variants don't get swapped back and
    #      forth.
    #   2. Install everything else.
    #
    # The download_fsl_environment function extracts the
    # appropriate base package versions to install.
    commands = []
    if ctx.fsl_base_packages is not None and len(ctx.fsl_base_packages) > 0:
        basepkgs = ctx.fsl_base_packages
        basepkgs = ['{}=={}'.format(pkg, ver) for pkg, ver in basepkgs.items()]
        basepkgs = ' '.join(basepkgs)
        commands.append(conda + ' install -y -n base ' + basepkgs)
    commands.append(conda + ' env update -n base -f ' + ctx.environment_file)

    printmsg('Installing FSL into {}...'.format(ctx.destdir))

    # Clear any environment variables that refer
    # to existing FSL or conda installations.
    # See Process.sudo_popen regarding append_env
    env        = clean_environ()
    append_env = {}

    # post-link scripts call $FSLDIR/share/fsl/sbin/createFSLWrapper
    # (part of fsl/base), which will only do its thing if the following
    # env vars are set
    append_env['FSL_CREATE_WRAPPER_SCRIPTS'] = '1'
    append_env['FSLDIR']                     = ctx.destdir

    # Make sure HTTP proxy variables, if set,
    # are available to the conda env command
    for v in ['http_proxy', 'https_proxy',
              'HTTP_PROXY', 'HTTPS_PROXY']:
        if v in os.environ:
            append_env[v] = os.environ[v]

    # FSL environments which source packages from the internal
    # FSL conda channel will refer to the channel as:
    #
    # http://${FSLCONDA_USERNAME}:${FSLCONDA_PASSWORD}/abc.com/
    #
    # so we need to set those variables
    if ctx.args.username: env['FSLCONDA_USERNAME'] = ctx.args.username
    if ctx.args.password: env['FSLCONDA_PASSWORD'] = ctx.args.password

    Process.monitor_progress(commands, output, ctx.need_admin, ctx,
                             append_env=append_env, env=env)


def finalise_installation(ctx):
    """Performs some finalisation tasks. Includes:
      - Saving the installed version to $FSLDIR/etc/fslversion
      - Saving this installer script and the environment file to
        $FSLDIR/etc/
    """
    with open('fslversion', 'wt') as f:
        f.write(ctx.build['version'])

    call    = ft.partial(Process.check_call, admin=ctx.need_admin, ctx=ctx)
    etcdir  = op.join(ctx.destdir, 'etc')

    call('cp fslversion {}'.format(etcdir))
    call('cp {} {}'        .format(ctx.environment_file, etcdir))
    call('cp {} {}'        .format(__absfile__,          etcdir))


def post_install_cleanup(ctx):
    """Cleans up the FSL directory after installation. """

    conda = op.join(ctx.destdir, 'bin', 'conda')
    cmd   = conda + ' clean -y --all'

    Process.check_call(cmd, ctx.need_admin, ctx)


def patch_file(filename, searchline, numlines, content):
    """Used by configure_shell and configure_matlab. Adds to, modifies,
    or creates the specified file.

    If a line matching searchline is found in the file, numlines (starting
    from searchline) are replaced with content.

    Otherwise, content is appended to the end of the file.
    """

    content = content.split('\n')

    if op.isfile(filename):
        with open(filename) as f:
            lines = [l.strip() for l in f.readlines()]
    else:
        lines = []

    # replace block
    try:
        idx   = lines.index(searchline)
        lines = lines[:idx] + content + lines[idx + numlines:]

    # append to end
    except ValueError:
        lines = lines + [''] + content

    with open(filename, 'wt') as f:
        f.write('\n'.join(lines))


def configure_shell(shell, homedir, fsldir):
    """Configures the user's shell environment (e.g. ~/.bash_profile).

    :arg shell:   User's shell (taken from the $SHELL environment variable
    :arg homedir: User's home directory, presumed to contain shell profile
                  file(s).
    :arg fsldir:  FSL installation directory
    """

    bourne_shells  = ['sh', 'bash', 'zsh', 'dash']
    csh_shells     = ['csh', 'tcsh']

    # we edit the first file that exists in
    # the list of candidate profile files.
    # They are attached as an attribute of
    # this function just for testing purposes
    # (see after function definition)
    shell_profiles = configure_shell.shell_profiles

    # DO NOT CHANGE the format of these configurations -
    # they are kept exactly as-is for compatibility with
    # legacy FSL installations, i.e. so we can modify
    # profiles with an existing configuration from older
    # FSL versions
    bourne_cfg = tw.dedent("""
    # FSL Setup
    FSLDIR={fsldir}
    PATH=${{FSLDIR}}/share/fsl/bin:${{PATH}}
    export FSLDIR PATH
    . ${{FSLDIR}}/etc/fslconf/fsl.sh
    """).format(fsldir=fsldir).strip()

    csh_cfg = tw.dedent("""
    # FSL Setup
    setenv FSLDIR {fsldir}
    setenv PATH ${{FSLDIR}}/share/fsl/bin:${{PATH}}
    source ${{FSLDIR}}/etc/fslconf/fsl.csh
    """).format(fsldir=fsldir).strip()

    if shell not in bourne_shells + csh_shells:
        printmsg('Shell {} not recognised - skipping environment '
                 'setup'.format(shell), WARNING, EMPHASIS)
        return

    if shell in bourne_shells: cfg = bourne_cfg
    else:                      cfg = csh_cfg

    # find the profile file to edit
    profile    = None
    candidates = [op.join(homedir, p)
                  for p in shell_profiles[shell]]
    for candidate in candidates:
        if op.isfile(candidate):
            profile = candidate
            break

    # if no candidate profile files
    # exist, fall back to the first one
    if profile is None:
        profile = candidates[0]

    printmsg('Adding FSL configuration to {}'.format(profile))

    patch_file(profile, '# FSL Setup', len(cfg.split('\n')), cfg)
configure_shell.shell_profiles = {'sh'   : ['.profile'],
                                  'bash' : ['.bash_profile', '.profile'],
                                  'dash' : ['.bash_profile', '.profile'],
                                  'zsh'  : ['.zprofile'],
                                  'csh'  : ['.cshrc'],
                                  'tcsh' : ['.tcshrc']}


def configure_matlab(homedir, fsldir):
    """Creates/appends FSL configuration code to ~/Documents/MATLAB/startup.m.
    """

    # DO NOT CHANGE the format of this configuration -
    # see in-line comments in configure_shell.
    cfg = tw.dedent("""
    % FSL Setup
    setenv( 'FSLDIR', '{fsldir}' );
    setenv('FSLOUTPUTTYPE', 'NIFTI_GZ');
    fsldir = getenv('FSLDIR');
    fsldirmpath = sprintf('%s/etc/matlab',fsldir);
    path(path, fsldirmpath);
    clear fsldir fsldirmpath;
    """).format(fsldir=fsldir).strip()

    matlab_dir = op.expanduser(op.join(homedir, 'Documents', 'MATLAB'))
    startup_m  = op.join(matlab_dir, 'startup.m')

    if not op.exists(matlab_dir):
        os.makedirs(matlab_dir)

    printmsg('Adding FSL configuration to {}'.format(startup_m))

    patch_file(startup_m, '% FSL Setup', len(cfg.split('\n')), cfg)


def self_update(manifest, workdir, checksum):
    """Checks to see if a newer version of the installer (this script) is
    available and if so, downloads it to a temporary file, and runs it in
    place of this script.
    """

    thisver   = Version(__version__)
    latestver = Version(manifest['installer']['version'])

    if latestver <= thisver:
        log.debug('Installer is up to date (this version: %s, '
                  'latest version: %s)', thisver, latestver)
        return

    log.debug('New version of installer is available '
              '(%s) - self-updating', latestver)

    tmpf = tempfile.NamedTemporaryFile(
        prefix='new_fslinstaller', delete=False, dir=workdir)
    tmpf.close()
    tmpf = tmpf.name

    download_file(manifest['installer']['url'], tmpf)

    if checksum:
        try:
            sha256(tmpf, manifest['installer']['sha256'])
        except Exception as e:
            printmsg('New installer file does not match expected '
                     'checksum! Skipping update.', WARNING)
            return

    # Don't try and update again - if for some
    # reason the online manifest reports a newer
    # version than what is available, we would
    # otherwise enter into an infinite loop.
    cmd = [sys.executable, tmpf] + sys.argv[1:] + ['--no_self_update']
    log.debug('Running new installer: %s', cmd)
    os.execv(sys.executable, cmd)


def read_fslversion(destdir):
    """Reads the FSL version from an existing FSL installation. Returns the
    version string, or None if it can't be read.
    """
    fslversion = op.join(destdir, 'etc', 'fslversion')
    if not op.exists(fslversion):
        return None
    try:
        with open(fslversion, 'rt') as f:
            fslversion = f.readline().split(':')[0]
    except:
        return None
    return fslversion


def update_destdir(ctx):
    """Called by main. Checks if the destination directory is an FSL
    installation, and determines / asks the user whether they want to update
    it.

    Returns the old FSL version string if the existing FSL installation
    should be updated, or None if it should be overwritten.

    Note: This functionality is not currently supported - the --update
    command-line option is hidden for the time being.
    """

    installed = read_fslversion(ctx.destdir)

    # Cannot detect a FSL installation
    if installed is None:
        return None

    printmsg()
    printmsg('Existing FSL installation [version {}] detected '
             'at {}'.format(installed, ctx.destdir), INFO)

    installed  = Version(installed)
    requested  = Version(ctx.build['version'])
    updateable = Version(FIRST_FSL_CONDA_RELEASE)

    # Too old (pre-conda)
    if installed < updateable:
        printmsg('FSL version {} is too old to update - you will need '
                 'to overwrite/re-install FSL'.format(installed), INFO)
        return None

    # Existing install is equal to
    # or newer than requested
    if installed >= requested:
        if installed == requested:
            msg       = '\nFSL version {installed} is already installed!'
            promptmsg = 'Do you want to re-install FSL {installed} [y/N]?'
        else:
            msg       = '\nInstalled version [{installed}] is newer than ' \
                        'the requested version [{requested}]!'
            promptmsg = 'Do you want to replace your existing version ' \
                        '[{installed}] with an older version [{requested}] ' \
                        '[y/N]?'

        msg       = msg      .format(installed=installed, requested=requested)
        promptmsg = promptmsg.format(installed=installed, requested=requested)

        printmsg(msg, WARNING, EMPHASIS)
        response = prompt(promptmsg, QUESTION, EMPHASIS)

        # Overwrite/re-install - don't ask user
        # again if they want to overwrite destdir
        if response.lower() in ('y', 'yes'):
            ctx.args.overwrite = True
            return None
        else:
            printmsg('Aborting installation', ERROR, EMPHASIS)
            sys.exit(1)

    # User specified --update -> don't prompt
    if ctx.args.update:
        return str(installed)

    printmsg('Would you like to upgrade your existing FSL installation from '
             'version {} to version {}, or replace your installation?'.format(
                 installed, requested), IMPORTANT, EMPHASIS)
    printmsg('Upgrading an existing FSL installation is experimental '
             'and might fail - replacing your installation will take '
             'longer, but is usually a safer option\n', INFO)
    response = prompt('Upgrade (u), replace (r), or cancel? [u/r/C]:',
                      QUESTION, EMPHASIS)

    if response.lower() in ('u'):
        return str(installed)
    # main routine will go on to ask
    # if they want to overwrite
    elif response.lower() in ('r'):
        ctx.args.overwrite = True
        return None
    else:
        printmsg('Aborting installation', ERROR, EMPHASIS)
        sys.exit(1)


def overwrite_destdir(ctx):
    """Called by main if the destination directory already exists. Asks the
    user if they want to overwrite it. If they do, or if the --overwrite
    option was specified, the directory is moved, and then deleted after
    the installation succeeds.

    This function assumes that it is run within a temporary/scratch directory.
    """

    if not ctx.args.overwrite:
        printmsg()
        printmsg('Destination directory [{}] already exists!'
                 .format(ctx.destdir), WARNING, EMPHASIS)
        response = prompt('Do you want to overwrite it [y/N]?',
                          QUESTION, EMPHASIS)
        if response.lower() not in ('y', 'yes'):
            printmsg('Aborting installation', ERROR, EMPHASIS)
            sys.exit(1)

    # generate a unique name for the old
    # destination directory (to avoid
    # collisions if using the same workdir
    # repeatedly)
    i = 0
    while True:
        ctx.old_destdir = op.abspath('old_destdir{}'.format(i))
        i              += 1
        if not op.exists(ctx.old_destdir):
            break

    printmsg('Deleting directory {}'.format(ctx.destdir), IMPORTANT)
    Process.check_call('mv {} {}'.format(ctx.destdir, ctx.old_destdir),
                       ctx.need_admin, ctx)


def parse_args(argv=None):
    """Parse command-line arguments, returns an argparse.Namespace object. """

    helps = {

        'version'      : 'Print installer version number and exit',
        'listversions' : 'List available FSL versions and exit',
        'dest'         : 'Install FSL into this folder (default: '
                         '{})'.format(DEFAULT_INSTALLATION_DIRECTORY),
        'overwrite'    : 'Delete existing destination directory if it exists, '
                         'without asking',
        'no_env'       : 'Do not modify your shell or MATLAB configuration '
                         'implies --no_shell and --no_matlab)',
        'no_shell'     : 'Do not modify your shell configuration',
        'no_matlab'    : 'Do not modify your MATLAB configuration',
        'fslversion'   : 'Install this specific version of FSL',
        'cuda'         : 'Install FSL packages for this CUDA version only '
                         '(default: install packages for all CUDA versions)',
        'no_cuda'      : 'Do not install any FSL CUDA packages',

        # Update existing FSL installation if
        # possible, without asking.  This
        # option is hidden/unsupported at the
        # moment, but may be added in the future.
        'update'          : argparse.SUPPRESS,

        # Username / password for accessing
        # internal FSL conda channel, if an
        # internal/development release is being
        # installed. If not set, will be read from
        # FSLCONDA_USERNAME/FSLCONDA_PASSWORD
        # environment variables.
        'username'        : argparse.SUPPRESS,
        'password'        : argparse.SUPPRESS,

        # Do not automatically update the installer script,
        'no_self_update'  : argparse.SUPPRESS,

        # Install a development release. This
        # option will cause the installer to
        # download the devrelreases.txt file,
        # which contains a list of available
        # internal/development manifests. The
        # user will be prompted to choose one,
        # which will be propagated on to the
        # --manifest option. If --devlatest
        # is used, the most recent developmet
        # release is automatically selected.
        'devrelease'      : argparse.SUPPRESS,
        'devlatest'       : argparse.SUPPRESS,

        # Path to alternative FSL release manifest.
        'manifest'        : argparse.SUPPRESS,

        # Print debugging messages
        'debug'           : argparse.SUPPRESS,

        # Disable SHA256 checksum validation of downloaded files
        'no_checksum'     : argparse.SUPPRESS,

        # Store temp files in this directory
        # rather than in a temporary directory
        'workdir'         : argparse.SUPPRESS,

        # Treat this directory as user's home directory,
        # for the purposes of shell configuration. Must
        # already exist.
        'homedir'         : argparse.SUPPRESS,

        # Configure conda to skip SSL verification.
        # Not recommended.
        'skip_ssl_verify' : argparse.SUPPRESS,

        # Do not install packages matching this
        # fnmatch-style wildcard pattern. Can
        # be used multiple times.
        'exclude_package' : argparse.SUPPRESS,
    }

    parser = argparse.ArgumentParser()

    # regular options
    parser.add_argument('-v', '--version', action='version',
                        version=__version__, help=helps['version'])
    parser.add_argument('-d', '--dest', metavar='DESTDIR',
                        help=helps['dest'])
    parser.add_argument('-u', '--update', action='store_true',
                        help=helps['update'])
    parser.add_argument('-o', '--overwrite', action='store_true',
                        help=helps['overwrite'])
    parser.add_argument('-l', '--listversions', action='store_true',
                        help=helps['listversions'])
    parser.add_argument('-n', '--no_env', action='store_true',
                        help=helps['no_env'])
    parser.add_argument('-s', '--no_shell', action='store_true',
                        help=helps['no_shell'])
    parser.add_argument('-m', '--no_matlab', action='store_true',
                        help=helps['no_matlab'])
    parser.add_argument('-V', '--fslversion', default='latest',
                        help=helps['version'])

    # CUDA packages are currently
    # only built for linux-64
    if Context.identify_platform() == 'linux-64':
        parser.add_argument('-c', '--cuda',     help=helps['cuda'],
                            type=float, metavar='X.Y')
        parser.add_argument('-nc', '--no_cuda', help=helps['no_cuda'],
                            action='store_true')

    # hidden options
    parser.add_argument('--username', help=helps['username'])
    parser.add_argument('--password', help=helps['password'])
    parser.add_argument('--no_checksum', action='store_true',
                        help=helps['no_checksum'])
    parser.add_argument('--skip_ssl_verify', action='store_true',
                        help=helps['skip_ssl_verify'])
    parser.add_argument('--workdir', help=helps['workdir'])
    parser.add_argument('--homedir', help=helps['homedir'],
                        default=op.expanduser('~'))
    parser.add_argument('--devrelease', help=helps['devrelease'],
                        action='store_true')
    parser.add_argument('--devlatest', help=helps['devlatest'],
                        action='store_true')
    parser.add_argument('--manifest', default=FSL_RELEASE_MANIFEST,
                        help=helps['manifest'])
    parser.add_argument('--no_self_update', action='store_true',
                        help=helps['no_self_update'])
    parser.add_argument('--exclude_package', action='append',
                        help=helps['exclude_package'])

    args = parser.parse_args(argv)

    args.homedir = op.abspath(args.homedir)
    if not op.isdir(args.homedir):
        printmsg('Home directory {} does not exist!'.format(args.homedir),
                 ERROR, EMPHASIS)
        sys.exit(1)

    if os.getuid() == 0:
        printmsg('Running the installer script as root user is discouraged! '
                 'You should run this script as a regular user - you will be '
                 'asked for your administrator password if required.',
                 WARNING, EMPHASIS)

    if args.username is None:
        args.username = os.environ.get('FSLCONDA_USERNAME', None)
    if args.password is None:
        args.password = os.environ.get('FSLCONDA_PASSWORD', None)

    if args.no_env:
        args.no_shell  = True
        args.no_matlab = True

    if args.workdir is not None:
        args.workdir = op.abspath(args.workdir)
        if not op.exists(args.workdir):
            os.mkdir(args.workdir)

    if args.devlatest:
        args.devrelease = True

    if args.exclude_package is None:
        args.exclude_package = []

    # The download_fsl_environment function also checks
    # package names against this "include_package" list,
    # although it is not exposed on the command
    # line. This is used to override any patterns in
    # exclude_package, and is currently used to select
    # packages for a specific CUDA version.
    #
    # All FSL cuda packages have a name ending with
    # "-cuda-X.Y".
    args.include_package = []

    if args.cuda is not None:
        args.include_package.append('fsl-*-cuda-{:0.1f}'.format(args.cuda))
    if args.no_cuda or (args.cuda is not None):
        args.exclude_package.append('fsl-*-cuda-*')

    # accept local path for manifest and environment
    if args.manifest is not None and op.exists(args.manifest):
        args.manifest = op.abspath(args.manifest)

    return args


def config_logging(ctx):
    """Configures logging. Log messages are directed to
    $TMPDIR/fslinstaller_<unique_token>.log, or
    workdir/fslinstaller_<unique_token>.log
    """
    if ctx.args.workdir is not None: logdir = ctx.args.workdir
    else:                            logdir = tempfile.gettempdir()

    # Use a unique name for the log file
    # (important for multi-user systems)
    logfilef, logfile = tempfile.mkstemp(prefix='fslinstaller_',
                                         suffix='.log',
                                         dir=logdir)
    os.close(logfilef)

    ctx.logfile = logfile
    handler     = logging.FileHandler(logfile)
    formatter   = logging.Formatter(
        '%(asctime)s %(filename)s:%(lineno)4d: %(message)s', '%H:%M:%S')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)


@contextlib.contextmanager
def handle_error(ctx):
    """Used by main as a context manager around the main installation steps.
    If an error occurs, prints some messages, performs some clean-up/
    restoration tasks, and exits.
    """

    try:
        yield

    except Exception as e:
        printmsg('\nERROR occurred during installation!', ERROR, EMPHASIS)
        printmsg('    {}\n'.format(e), INFO)

        # send traceback to log file
        tb = traceback.format_tb(sys.exc_info()[2])
        log.debug(''.join(tb))

        # Don't remove a failed update, despite
        # it potentially being corrupt (because
        # it might also be fine)
        if ctx.update:
            printmsg('Update failed - your FSL installation '
                     'might be corrupt!', WARNING, EMPHASIS)

        elif op.exists(ctx.destdir):
            printmsg('Removing failed installation directory '
                     '{}'.format(ctx.destdir), WARNING)
            Process.check_call('rm -r ' + ctx.destdir, ctx.need_admin, ctx)

        # overwrite_destdir moves the existing
        # destdir to a temp location, so we can
        # restore it if the installation fails
        if not op.exists(ctx.destdir) and (ctx.old_destdir is not None):
            printmsg('Restoring contents of {}'.format(ctx.destdir),
                     WARNING)
            Process.check_call('mv {} {}'.format(ctx.old_destdir, ctx.destdir),
                               ctx.need_admin, ctx)

        printmsg('\nFSL installation failed!', ERROR, EMPHASIS)
        printmsg('The log file may contain some more information to help '
                 'you diagnose the problem: {}'.format(ctx.logfile), ERROR)
        sys.exit(1)


def main(argv=None):
    """Installer entry point. Downloads and installs miniconda and FSL, and
    configures the user's environment.
    """

    args = parse_args(argv)
    ctx  = Context(args)

    config_logging(ctx)

    log.debug(' '.join(sys.argv))

    if not args.no_self_update:
        self_update(ctx.manifest, args.workdir, not args.no_checksum)

    printmsg('FSL installer version:', EMPHASIS, UNDERLINE, end='')
    printmsg(' {}'.format(__version__))
    printmsg('Press CTRL+C at any time to cancel installation', INFO)
    printmsg('Installation log file: {}\n'.format(ctx.logfile), INFO)

    if args.listversions:
        list_available_versions(ctx.manifest)
        sys.exit(0)

    ctx.finalise_settings()

    with tempdir(args.workdir):

        # Ask the user if they want to update or
        # overwrite an existing installation
        ctx.update = None
        ctx.exists = op.exists(ctx.destdir)

        if ctx.exists:
            # The update facility is currently disabled.
            # ctx.update = update_destdir(ctx)
            if not ctx.update:
                overwrite_destdir(ctx)

        download_fsl_environment(ctx)

        if ctx.update: action = 'Updating'
        else:          action = 'Installing'
        printmsg('\n{} FSL in {}\n'.format(action, ctx.destdir), EMPHASIS)

        with handle_error(ctx):
            if not ctx.update:
                download_miniconda(ctx)
                install_miniconda(ctx)
            install_fsl(ctx)
            finalise_installation(ctx)
            post_install_cleanup(ctx)

    if not args.no_shell:
        configure_shell(ctx.shell, args.homedir, ctx.destdir)
    if not args.no_matlab:
        configure_matlab(args.homedir, ctx.destdir)

    printmsg('\nFSL successfully installed\n', IMPORTANT)
    if not args.no_shell:
        printmsg('Open a new terminal, or log out and log back in, '
                 'for the environment changes to take effect.', INFO)


if __name__ == '__main__':
    sys.exit(main())
