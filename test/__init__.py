#!/usr/bin/env python
#
"""Utility functions used for testing. """


import json
import os
import os.path as op
import contextlib
import threading
import multiprocessing as mp
import functools as ft
import sys
import textwrap as tw
import time
import re
import sys

import fsl.installer.fslinstaller as inst


# py3
try:
    import queue
    import http.server as http
    from io import StringIO
    from unittest import mock

# py2
except ImportError:
    import Queue as queue
    from StringIO import StringIO
    import SimpleHTTPServer as http
    http.HTTPServer = http.BaseHTTPServer.HTTPServer
    http.SimpleHTTPRequestHandler.protocol_version = 'HTTP/1.0'
    import mock


@contextlib.contextmanager
def onpath(dir):
    """Context manager which temporarily adds dir to the front of $PATH. """
    path               = os.environ['PATH']
    os.environ['PATH'] = dir + op.pathsep + path
    try:
        yield
    finally:
        os.environ['PATH'] = path


@contextlib.contextmanager
def indir(dir):
    """Context manager which temporarily changes into dir."""
    prevdir = os.getcwd()
    os.chdir(dir)
    try:
        yield
    finally:
        os.chdir(prevdir)


class HTTPServer(mp.Process):
    """Simple HTTP server which serves files from a specified directory, and
    can accept JSON data via POST requests.

    Intended to be used via the :func:`server` context manager function.
    """


    class Handler(http.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self.posts = kwargs.pop('posts', queue.Queue())
            http.SimpleHTTPRequestHandler.__init__(self, *args, **kwargs)

        @classmethod
        def ctr(cls, posts):
            return ft.partial(cls, posts=posts)

        def do_POST(self):

            nbytes = int(self.headers['Content-Length'])
            data   = json.loads(self.rfile.read(nbytes).decode())

            self.posts.put(data)
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'OK')

    def __init__(self, rootdir):

        mp.Process.__init__(self)
        self.daemon = True
        self.rootdir = rootdir
        self.__postq = mp.Queue()
        self.__posts = []
        handler = HTTPServer.Handler.ctr(self.__postq)
        self.server = http.HTTPServer(('0.0.0.0', 0), handler)
        self.shutdown = mp.Event()

    def stop(self):
        self.shutdown.set()

    @property
    def posts(self):
        while True:
            try:
                self.__posts.append(self.__postq.get_nowait())
            except queue.Empty:
                break
        return list(self.__posts)

    @property
    def port(self):
        return self.server.server_address[1]

    def run(self):
        with indir(self.rootdir):
            while not self.shutdown.is_set():
                self.server.handle_request()
            self.server.shutdown()


@contextlib.contextmanager
def server(rootdir=None):
    """Start a :class:`HTTPServer` on a separate thread to serve files from
    ``rootdir`` (defaults to the current working directory), then shut it down
    afterwards.
    """
    # pause for a bit to allow OS to free
    # resources (in case we are calling
    # server() multiple times in quick
    # succession)
    time.sleep(3)

    if rootdir is None:
        rootdir = os.getcwd()
    srv = HTTPServer(rootdir)
    srv.start()
    srv.url = 'http://localhost:{}'.format(srv.port)
    try:
        yield srv
    finally:
        srv.stop()


class CaptureStdout(object):
    """Context manager which captures stdout and stderr. """

    def __init__(self):
        self.reset()

    def reset(self):
        self.__mock_stdout = StringIO('')
        self.__mock_stderr = StringIO('')
        self.__mock_stdout.mode = 'w'
        self.__mock_stderr.mode = 'w'
        return self

    def __enter__(self):
        self.__real_stdout = sys.stdout
        self.__real_stderr = sys.stderr
        sys.stdout = self.__mock_stdout
        sys.stderr = self.__mock_stderr
        return self


    def __exit__(self, *args, **kwargs):
        sys.stdout = self.__real_stdout
        sys.stderr = self.__real_stderr
        return False

    @property
    def stdout(self):
        self.__mock_stdout.seek(0)
        return self.__mock_stdout.read()

    @property
    def stderr(self):
        self.__mock_stderr.seek(0)
        return self.__mock_stderr.read()


@contextlib.contextmanager
def mock_input(*responses):
    """Mock the built-in ``input`` or ``raw_input`` function so that it
    returns the specified sequence of ``responses``.

    Each response is returned from the ``input`` function in order, unless it
    is a callable, in which case it is called, and then the next non-callable
    response returned. This gives us a hacky way to manipulate things while
    stuck in an input REPL loop.

    An error is raised if input is not called the expected number of times
    """

    resp = iter(responses)
    count = [0]

    def _input(*a, **kwa):
        count[0] += 1
        n = next(resp)
        while callable(n):
            n()
            n = next(resp)
        return n

    if sys.version[0] == '2': target = '__builtin__.raw_input'
    else:                     target = 'builtins.input'

    with mock.patch(target, _input):
        yield

    if count[0] != len(responses):
        raise AssertionError('Expected number of inputs not provided')


def strip_ansi_escape_sequences(text):
    """Does what function name says it does. """
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


@contextlib.contextmanager
def mock_nvidia_smi(cudaver=None, exitcode=0):
    with inst.tempdir(change_into=False) as td:

        if cudaver is None:
            cudaver = '11.2'

        filepath = op.join(td, 'nvidia-smi')
        contents = tw.dedent("""
        #!/usr/bin/env bash

        echo "CUDA Version: {}"
        exit {}
        """).strip()

        def gen(cudaver, exitcode=0):
            with open(filepath, 'wt') as f:
                f.write(contents.format(cudaver, exitcode))
            os.chmod(filepath, 0o755)

        gen(cudaver, exitcode)

        path = op.pathsep.join((td, os.environ['PATH']))
        with mock.patch.dict(os.environ, PATH=path):
            yield gen


def mock_miniconda_installer(filename, pyver=None):
    """Creates a mock miniconda installer which creates a mock $FSLDIR/bin/conda
    command.
    """

    if pyver is None:
        pyver = [str(v) for v in sys.version_info[:2]]
        pyver = '.'.join(pyver)

    mock_miniconda_sh = """
    #!/usr/bin/env bash

    #called like <script> -b -p <prefix>
    prefix=$3

    mkdir -p $prefix/bin/
    mkdir -p $prefix/etc/
    mkdir -p $prefix/pkgs/

    prefix=$(cd $prefix && pwd)

    # called like
    #  - conda env update -p <fsldir> -f <envfile>
    #  - conda env create -p <fsldir> -f <envfile>
    #  - conda clean -y --all
    echo "#!/usr/bin/env bash"                          >> $prefix/bin/conda
    echo 'echo "$@" >> '"$prefix/allcommands"           >> $prefix/bin/conda
    echo 'if   [ "$1" = "clean" ]; then '               >> $prefix/bin/conda
    echo "    touch $prefix/cleaned"                    >> $prefix/bin/conda
    echo 'elif [ "$1" = "env" ]; then '                 >> $prefix/bin/conda
    echo '    envprefix=$4'                             >> $prefix/bin/conda
    echo '    mkdir -p $envprefix/bin/'                 >> $prefix/bin/conda
    echo '    mkdir -p $envprefix/etc/'                 >> $prefix/bin/conda
    echo '    mkdir -p $envprefix/pkgs/'                >> $prefix/bin/conda
    echo '    # copy env file into $prefix - so we'     >> $prefix/bin/conda
    echo '    # can check that this conda command'      >> $prefix/bin/conda
    echo '    # was called. The fslinstaller script'    >> $prefix/bin/conda
    echo '    # independently copies all env files'     >> $prefix/bin/conda
    echo '    # into $FSLDIR/etc/'                      >> $prefix/bin/conda
    echo '    cp "$6" '"$prefix"                        >> $prefix/bin/conda
    echo '    echo "$2" > $envprefix/env_command'       >> $prefix/bin/conda
    echo '    echo "python {pyver}" > $envprefix/pyver' >> $prefix/bin/conda
    echo "fi"                                           >> $prefix/bin/conda
    chmod a+x $prefix/bin/conda
    """.strip()

    mock_miniconda_sh = mock_miniconda_sh.format(pyver=pyver)

    with open(filename, 'wt') as f:
        f.write(mock_miniconda_sh)

    os.chmod(filename, 0o755)
