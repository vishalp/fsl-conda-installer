#!/usr/bin/env python
#
# FSL installer script.
#


from __future__ import print_function, division, unicode_literals

import functools      as ft
import os.path        as op
import subprocess     as sp
import textwrap       as tw
import                   argparse
import                   contextlib
import                   getpass
import                   hashlib
import                   json
import                   logging
import                   os
import                   platform
import                   re
import                   shlex
import                   shutil
import                   sys
import                   tempfile
import                   threading
import                   time

# TODO check py2/3
try:
    import                   urllib
    import urllib.parse   as urlparse
    import urllib.request as urlrequest
except ImportError:
    import urllib2 as urllib
    import urllib2 as urlparse
    import urllib2 as urlrequest

try:                import queue
except ImportError: import Queue as queue


PY2 = sys.version[0] == '2'


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


SUPPORTED_CUDAS = ['9.2', '10.2', '11.1']
"""Versions of CUDA that CUDA-capable FSL packages are built for. Used
by Context.identify_cuda. Must be in increasing order.
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


class UnsupportedPlatform(Exception):
    """Exception raised by the identify_platform function if FSL is not
    available on this platform.
    """


class Context(object):
    """Bag of information and settings created in main, and passed around
    this script.

    Several settings are lazily evaluated on first access, but once evaluated,
    their values are immutable.
    """

    def __init__(self, args):
        """Create the context with the argparse.Namespace object containing
        parsed command-line arguments.
        """

        self.args  = args
        self.shell = op.basename(os.environ['SHELL'])

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
        """Finalise values for all information and settings in the Context.
        """
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
        installer manifest) for the target platform and requested FSL/CUDA
        versions.
        """

        fslversion = self.args.fslversion

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

        if self.__destdir is not None:
            return self.__destdir

        # The loop below validates the destination directory
        # both when specified at commmand line or
        # interactively.  In either case, if invalid, the
        # user is re-prompted to enter a new destination.
        destdir = None
        if self.args.dest is not None:
            response = self.args.dest
        else:
            response = None

        while destdir is None:

            if response is None:
                printmsg('Where do you want to install FSL?',
                         IMPORTANT, EMPHASIS)
                printmsg('Press enter to install to the default location [{}]'
                         .format(DEFAULT_INSTALLATION_DIRECTORY), INFO)
                response = prompt('FSL installation directory:', QUESTION)
                response = response.rstrip(op.sep)

                if response == '':
                    response = DEFAULT_INSTALLATION_DIRECTORY

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
        if self.__destdir is None:
            raise RuntimeError('Destination directory has not been set')
        self.__admin_password = Context.get_admin_password()


    @property
    def manifest(self):
        """Returns the FSL installer manifest as a dictionary. """
        if self.__manifest is None:
            self.__manifest = Context.download_manifest(self.args.manifest,
                                                        self.args.workdir)
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
            output = Process.check_output('nvidia-smi')
        except Exception:
            return None

        pat   = r'CUDA Version: (\S+)'
        lines = output.split('\n')
        for line in lines:
            match = re.search(pat, line)
            if match:
                cudaver = match.group(1)
                break
        else:
            return None

        # Return the most suitable CUDA
        # version that we have a build for
        for supported in reversed(SUPPORTED_CUDAS):
            if float(cudaver) >= float(supported):
                return supported

        return None


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

        for attempt in range(3):
            if attempt == 0:
                msg = 'Your administrator password is needed to ' \
                      'install FSL: '
            else:
                msg = 'Your administrator password is needed to ' \
                      'install FSL [attempt {} of 3]:'.format(attempt + 1)
            printmsg(msg, IMPORTANT, end='', flush=True)
            password = getpass.getpass('')
            valid    = validate_admin_password(password)

            if valid:
                printmsg('Password accepted', INFO)
                break
            else:
                printmsg('Incorrect password', WARNING)

        if not valid:
            raise InvalidPassword()

        return password


    @staticmethod
    def download_manifest(url, workdir=None):
        """Downloads the installer manifest file, which contains information
        about available FSL vesrions, and the most recent version number of the
        installer (this script).

        The manifest file is a JSON file. Lines beginning
        with a double-forward-slash are ignored. See test/data/manifes.json
        for an example.
        """

        log.debug('Downloading FSL installer manifest from %s', url)

        with tempdir(workdir):
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


def printmsg(msg='', *msgtypes, **kwargs):
    """Prints msg according to the ANSI codes provided in msgtypes.
    All other keyword arguments are passed through to the print function.
    """
    msgcodes = [ANSICODES[t] for t in msgtypes]
    msgcodes = ''.join(msgcodes)
    print('{}{}{}'.format(msgcodes, msg, ANSICODES[RESET]), **kwargs)
    sys.stdout.flush()


def prompt(prompt, *msgtypes, **kwargs):
    """Prompts the user for some input. msgtypes and kwargs are passed
    through to the printmsg function.
    """
    printmsg(prompt, *msgtypes, end='', **kwargs)

    if PY2: return raw_input(' ').strip()
    else:   return input(    ' ').strip()


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
        printmsg()

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

        printmsg(this, end='\r')
        self.__last_spin = this

    def count(self, value):
        value = self.fmt(value)
        line  = '{}{} ...'.format(value, self.label)
        printmsg(line, end='\r')

    def progress(self, value, total):

        overflow = value > total
        value    = min(value, total)

        # arbitrary fallback of 50 columns if
        # terminal width cannot be determined
        if self.width is None: width = Progress.get_terminal_width(50)
        else:                  width = self.width

        fvalue = self.fmt(value)
        ftotal = self.fmt(total)
        suffix = '{} / {} {}'.format(fvalue, ftotal, self.label).rstrip()

        # +5: - square brackets around bar
        #     - space between bar and tally
        #     - space+spin in case of overflow
        width     = width - (len(suffix) + 5)
        completed = int(round(width * (value  / total)))
        remaining = width - completed
        progress  = '[{}{}] {}'.format('#' * completed,
                                       ' ' * remaining,
                                       suffix)

        printmsg(progress, end='')
        if overflow:
            printmsg(' ', end='')
            self.spin()
        printmsg(end='\r')


    @staticmethod
    def get_terminal_width(fallback=None):
        """Return the number of columns in the current terminal, or fallback
        if it cannot be determined.
        """
        # os.get_terminal_size added in python
        # 3.3, so we try and call tput instead
        try:
            result = Process.check_output('tput cols')
            return int(result.strip())
        except Exception:
            return fallback


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


def download_file(url, destination, progress=None, blocksize=1048576):
    """Download a file from url, saving it to destination. """

    def default_progress(downloaded, total):
        pass

    if progress is None:
        progress = default_progress

    log.debug('Downloading %s ...', url)

    req = None
    try:
        # py2: urlopen result cannot be
        # used as a context manager
        req = urlrequest.urlopen(url)
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

    except Exception:
        raise DownloadFailed('A network error has occurred while '
                             'trying to download {}'.format(url))
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


    def __init__(self, ctx, cmd, admin, **kwargs):
        """Run the specified command. Starts threads to capture stdout and
        stderr.

        :arg ctx:    The installer Context. Only used for admin password - can
                     be None if admin is False.
        :arg cmd:    Command to run - passed directly to subprocess.Popen
        :arg admin:  Run the command with administrative privileges
        :arg kwargs: Passed to subprocess.Popen
        """

        self.ctx     = ctx
        self.cmd     = cmd
        self.admin   = admin
        self.stdoutq = queue.Queue()
        self.stderrq = queue.Queue()
        self.popen   = Process.popen(self.cmd, self.admin, self.ctx)

        # threads for gathering stdout/stderr
        self.stdout_thread = threading.Thread(
            target=Process.forward_stream,
            args=(self.popen, self.stdoutq, cmd, 'stdout'))
        self.stderr_thread = threading.Thread(
            target=Process.forward_stream,
            args=(self.popen, self.stderrq, cmd, 'stderr'))

        self.stdout_thread.daemon = True
        self.stderr_thread.daemon = True
        self.stdout_thread.start()
        self.stderr_thread.start()


    @staticmethod
    def check_output(cmd, admin=False, ctx=None):
        """Behaves like subprocess.check_output. Runs the given command, then
        waits until it finishes, and return its standard output. An error
        is raised if the process returns a non-zero exit code.

        :arg cmd:   The command to run, as a string

        :arg admin: Whether to run with administrative privileges

        :arg ctx:   The installer Context object. Only required if admin is
                    True.
        """

        proc = Process(ctx, cmd, admin=admin)
        proc.popen.wait()

        if proc.popen.returncode != 0:
            raise RuntimeError(cmd)

        stdout = ''
        while True:
            try:
                stdout += proc.stdoutq.get_nowait()
            except queue.Empty:
                break

        return stdout


    @staticmethod
    def check_call(cmd, admin=False, ctx=None):
        """Behaves like subprocess.check_call. Runs the given command, then
        waits until it finishes. An error is raised if the process returns a
        non-zero exit code.

        :arg cmd:   The command to run, as a string

        :arg admin: Whether to run with administrative privileges

        :arg ctx:   The installer Context object. Only required if admin is
                    True.
        """
        proc = Process(ctx, cmd, admin=admin)
        proc.popen.wait()
        if proc.popen.returncode != 0:
            raise RuntimeError(cmd)


    @staticmethod
    def monitor_progress(ctx, cmd, total=None, **kwargs):
        """Runs the given command, and shows a progress bar under the
        assumption that cmd will produce "total" number of lines of output.
        """
        if total is None: label = None
        else:             label = '%'

        with Progress(label=label,
                      fmt='{:.0f}',
                      transform=Progress.percent) as prog:

            proc   = Process(ctx, cmd, **kwargs)
            nlines = 0

            prog.update(nlines, total)

            while proc.popen.returncode is None:

                try:
                    line = proc.stdoutq.get(timeout=1)
                except queue.Empty:
                    continue

                nlines += 1
                prog.update(nlines, total)


    @staticmethod
    def forward_stream(popen, queue, cmd, streamname):
        """Reads lines from stream and pushes them onto queue until popen
        is finished. Logs every line.

        :arg popen:      subprocess.Popen object
        :arg queue:      queue.Queue to push lines onto
        :arg cmd:        string - the command that is running
        :arg streamname: string - 'stdout' or 'stderr'
        """

        # cmd is just used for log messages
        if len(cmd) > 50:
            cmd = cmd[:50] + '...'

        if streamname == 'stdout': stream = popen.stdout
        else:                      stream = popen.stderr

        while popen.returncode is None:
            line = stream.readline().decode('utf-8')
            popen.poll()
            if line == '':
                break
            else:
                queue.put(line)
                log.debug('%s [%s]: %s', cmd, streamname, line.rstrip())

        # process finished, flush the stream
        line = stream.readline().decode('utf-8')
        while line != '':
            queue.put(line)
            log.debug('%s [%s]: %s', cmd, streamname, line)
            line = stream.readline().decode('utf-8')


    @staticmethod
    def popen(cmd, admin=False, ctx=None):
        """Runs the given command via subprocess.Popen, as administrator if
        requested.

        :arg cmd:   The command to run, as a string

        :arg admin: Whether to run with administrative privileges

        :arg ctx:   The installer Context object. Only required if admin is
                    True.

        :returns:   The subprocess.Popen object.
        """

        admin = admin and os.getuid() != 0

        if admin: password = ctx.password
        else:     password = None

        log.debug('Running %s [as admin: %s]', cmd, admin)

        cmd = shlex.split(cmd)

        kwargs = dict(stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)

        if admin: proc = Process.sudo_popen(cmd, password, **kwargs)
        else:     proc = sp.Popen(          cmd, **kwargs)

        return proc


    @staticmethod
    def sudo_popen(cmd, password, **kwargs):
        """Runs "sudo cmd" using subprocess.Popen. Used by Process.popen.
        Assumes that kwargs contains stdin=sp.PIPE
        """

        cmd  = ['sudo', '-S', '-k'] + cmd
        proc = sp.Popen(cmd, **kwargs)
        proc.stdin.write('{}\n'.format(password))
        return proc


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
        download_file(url, 'miniforge.sh', prog.update)
    if not ctx.args.no_checksum:
        sha256('miniforge.sh', checksum)

    # Install
    printmsg('Installing miniconda at {}...'.format(ctx.destdir))
    cmd = 'sh miniforge.sh -b -p {}'.format(ctx.destdir)
    Process.monitor_progress(ctx, cmd, output, admin=ctx.need_admin)

    # Create .condarc config file
    condarc = tw.dedent("""
    # Putting a .condarc file into the root environment
    # directory will override ~/.condarc if it exists,
    # but will not override a system condarc (e.g. at
    # /etc/condarc/condarc). There is currently no
    # workaround for this - see:
    #  - https://github.com/conda/conda/issues/8599
    #  - https://github.com/conda/conda/issues/8804

    # Try and make package downloads more robust
    remote_read_timeout_secs:    240
    remote_connect_timeout_secs: 20
    remote_max_retries:          10
    remote_backoff_factor:       5
    safety_checks:               warn

    # Channel priority is important. In older versions
    # of FSL we placed the FSL conda channel at the
    # bottom (lowest priority) for legacy reasons (to
    # ensure that conda-forge versions of e.g. VTK were
    # preferred over legacy FSL conda versions).
    #
    # https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-channels.html
    channel_priority: strict
    channels:
      - http://18.133.213.73/production/
      - conda-forge
      - defaults
    """)

    with open('.condarc', 'wt') as f:
        f.write(condarc)

    Process.check_call('cp .condarc {}'.format(ctx.destdir),
                       ctx.need_admin, ctx)


def install_fsl(ctx):
    """Install FSL into ctx.destdir (which is assumed to be a miniconda
    installation.

    This function assumes that it is run within a temporary/scratch directory.
    """

    build    = ctx.build
    url      = build['environment']
    checksum = build['sha256']
    output   = build.get('output', None)

    if output == '': output = None
    else:            output = int(output)

    printmsg('Downloading FSL environment specification '
             'from {}...'.format(url))
    download_file(url, 'environment.yml')

    conda = op.join(ctx.destdir, 'bin', 'conda')
    cmd   = conda + ' env update -n base -f environment.yml'

    printmsg('Installing FSL into {}...'.format(ctx.destdir))

    env = os.environ.copy()
    env['FSL_CREATE_WRAPPER_SCRIPTS'] = '1'

    Process.monitor_progress(ctx, cmd, output, admin=ctx.need_admin, env=env)


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


def configure_shell(ctx):
    """Configures the user's shell environment (e.g. ~/.bash_profile). """

    bourne_shells  = ['sh', 'bash', 'zsh', 'dash']
    csh_shells     = ['csh', 'tcsh']

    # we edit the first file that exists
    # in the list of candidate profile files,
    shell_profiles = {'sh'   : ['.profile'],
                      'bash' : ['.bash_profile', '.profile'],
                      'dash' : ['.bash_profile', '.profile'],
                      'zsh'  : ['.zprofile'],
                      'csh'  : ['.cshrc'],
                      'tcsh' : ['.tcshrc']}

    # Do not change the format of these configurations -
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
    """).format(fsldir=ctx.destdir)

    csh_cfg = tw.dedent("""
    # FSL Setup
    setenv FSLDIR {fsldir}
    setenv PATH ${{FSLDIR}}/share/fsl/bin:${{PATH}}
    source ${{FSLDIR}}/etc/fslconf/fsl.csh
    """).format(fsldir=ctx.destdir)

    if ctx.shell not in bourne_shells + csh_shells:
        printmsg('Shell {} not recognised - skipping environment '
                 'setup'.format(ctx.shell), WARNING, EMPHASIS)
        return

    if ctx.shell in bourne_shells: cfg = bourne_cfg
    else:                          cfg = csh_cfg

    # find the profile file to edit
    profile    = None
    candidates = [op.join(ctx.args.homedir, p)
                  for p in shell_profiles[ctx.shell]]
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


def configure_matlab(ctx):
    """Creates/appends FSL configuration code to ~/Documents/MATLAB/startup.m.
    """

    # Do not change the format of this configuration -
    # see in-line comments in configure_shell.
    cfg = tw.dedent("""
    % FSL Setup
    setenv( 'FSLDIR', '{fsldir}' );
    setenv('FSLOUTPUTTYPE', 'NIFTI_GZ');
    fsldir = getenv('FSLDIR');
    fsldirmpath = sprintf('%s/etc/matlab',fsldir);
    path(path, fsldirmpath);
    clear fsldir fsldirmpath;
    """).format(fsldir=ctx.destdir)

    matlab_dir = op.expanduser(op.join(ctx.args.homedir, 'Documents', 'MATLAB'))
    startup_m  = op.join(matlab_dir, 'startup.m')

    if not op.exists(matlab_dir):
        os.makedirs(matlab_dir)

    printmsg('Adding FSL configuration to {}'.format(startup_m))

    patch_file(startup_m, '% FSL Setup', len(cfg.split('\n')), cfg)


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

    tmpf = tempfile.NamedTemporaryFile(
        prefix='new_fslinstaller', delete=False, dir=ctx.args.workdir)
    tmpf.close()
    tmpf = tmpf.name

    download_file(ctx.manifest['installer']['url'], tmpf)

    if not ctx.args.no_checksum:
        sha256(tmpf, ctx.manifest['installer']['sha256'])

    cmd = [sys.executable, tmpf] + sys.argv[1:]
    log.debug('Running new installer: %s', cmd)
    os.execv(sys.executable, cmd)


def overwrite_destdir(ctx):
    """Called by main if the destination directory already exists.  Asks the
    user if they want to overwrite it and, if they say yes, removes the
    existing destination directory. Otherwise exits.
    """

    if not ctx.args.overwrite:
        printmsg('Destination directory [{}] already exists!'
                 .format(ctx.destdir), WARNING, EMPHASIS)
        response = prompt('Do you want to overwrite it [N/y]?',
                          WARNING, EMPHASIS)
        if response.lower() not in ('y', 'yes'):
            printmsg('Aborting installation', ERROR, EMPHASIS)
            sys.exit(1)

    printmsg('Deleting directory {}'.format(ctx.destdir), IMPORTANT)
    Process.check_call('rm -r {}'.format(ctx.destdir), ctx.need_admin, ctx)


def parse_args(argv=None):
    """Parse command-line arguments, returns an argparse.Namespace object. """

    helps = {

        'version'      : 'Print installer version number and exit',
        'listversions' : 'List available FSL versions and exit',
        'dest'         : 'Install FSL into this folder (default: '
                         '{})'.format(DEFAULT_INSTALLATION_DIRECTORY),
        'overwrite'    : 'Delete destination directory without '
                         'asking, if it already exists',
        'no_env'       : 'Do not modify your shell or MATLAB configuration '
                         'implies --no_shell and --no_matlab)',
        'no_shell'     : 'Do not modify your shell configuration',
        'no_matlab'    : 'Do not modify your MATLAB configuration',
        'fslversion'   : 'Install this specific version of FSL',
        'cuda'         : 'Install FSL for this CUDA version (default: '
                         'automatically detected)',

        # Do not automatically update the installer script,
        'no_self_update' : argparse.SUPPRESS,

        # Path to local installer manifest file
        'manifest'       : argparse.SUPPRESS,

        # Print debugging messages
        'debug'          : argparse.SUPPRESS,

        # Disable SHA256 checksum validation of downloaded files
        'no_checksum'    : argparse.SUPPRESS,

        # Store temp files in this directory
        # rather than in a temporary directory
        'workdir'        : argparse.SUPPRESS,

        # Treat this directory as user's home directory,
        # for the purposes of shell configuration. Must
        # already exist.
        'homedir'        : argparse.SUPPRESS,
    }

    parser = argparse.ArgumentParser()

    # regular options
    parser.add_argument('-v', '--version', action='version',
                        version=__version__, help=helps['version'])
    parser.add_argument('-d', '--dest', metavar='DESTDIR',
                        help=helps['dest'])
    parser.add_argument('-o', '--overwrite', action='store_true',
                        help=helps['overwrite'])
    parser.add_argument('-l', '--listversions', action='store_true',
                        help=helps['listversions'])
    parser.add_argument('-e', '--no_env', action='store_true',
                        help=helps['no_env'])
    parser.add_argument('-s', '--no_shell', action='store_true',
                        help=helps['no_shell'])
    parser.add_argument('-m', '--no_matlab', action='store_true',
                        help=helps['no_matlab'])
    parser.add_argument('-V', '--fslversion', default='latest',
                        help=helps['version'])
    parser.add_argument('-c', '--cuda', help=helps['cuda'])

    # hidden options
    parser.add_argument('-k', '--no_checksum', action='store_true',
                        help=helps['no_checksum'])
    parser.add_argument('-w', '--workdir', help=helps['workdir'])
    parser.add_argument('-i', '--homedir', help=helps['homedir'],
                        default=op.expanduser('~'))
    parser.add_argument('-a', '--manifest', default=FSL_INSTALLER_MANIFEST,
                        help=helps['manifest'])
    parser.add_argument('-u', '--no_self_update', action='store_true',
                        help=helps['no_self_update'])

    args = parser.parse_args(argv)

    args.homedir = op.abspath(args.homedir)
    if not op.isdir(args.homedir):
        printmsg('Home directory {} does not exist!'.format(args.homedir),
                 ERROR, EMPHASIS)
        sys.exit(1)

    if os.getuid() == 0:
        printmsg('Running the installer script as root user - disabling '
                 'environment configuration', WARNING, EMPHASIS)
        args.no_env = True

    if args.no_env:
        args.no_shell  = True
        args.no_matlab = True

    if args.workdir is not None:
        args.workdir = op.abspath(args.workdir)
        if not op.exists(args.workdir):
            os.mkdir(args.workdir)

    return args


def config_logging(ctx):
    """Configures logging. Log messages are directed to
    $TMPDIR/fslinstaller.log, or workdir/fslinstaller.log
    """
    if ctx.args.workdir is not None: logdir = ctx.args.workdir
    else:                            logdir = tempfile.gettempdir()

    logfile   = op.join(logdir, 'fslinstaller.log')
    handler   = logging.FileHandler(logfile)
    formatter = logging.Formatter(
        '%(asctime)s %(filename)s:%(lineno)4d: %(message)s', '%H:%M:%S')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)


def main(argv=None):
    """Installer entry point. Downloads and installs miniconda and FSL, and
    configures the user's environment.
    """

    args = parse_args(argv)
    ctx  = Context(args)

    config_logging(ctx)

    log.debug(' '.join(sys.argv))

    if not args.no_self_update:
        self_update(ctx)

    printmsg('FSL installer version:', EMPHASIS, UNDERLINE, end='')
    printmsg(' ' + __version__ + '\n')

    if args.listversions:
        list_available_versions(ctx)
        sys.exit(0)

    ctx.finalise_settings()

    with tempdir(args.workdir):

        if op.exists(ctx.destdir):
           overwrite_destdir(ctx)

        printmsg('\nInstalling FSL into {}\n'.format(ctx.destdir), EMPHASIS)

        install_miniconda(ctx)
        install_fsl(ctx)
        post_install_cleanup(ctx)

    if not args.no_shell:  configure_shell( ctx)
    if not args.no_matlab: configure_matlab(ctx)

    printmsg('\nFSL successfully installed\n', IMPORTANT)
    if not args.no_env:
        printmsg('Open a new terminal, or log out and log back in, '
                 'for the environment changes to take effect.', INFO)


if __name__ == '__main__':
    sys.exit(main())
