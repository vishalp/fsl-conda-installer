#!/usr/bin/env python


import test.test_installer        as ti
import fsl.installer.fslinstaller as fi

from . import (server, mock_nvidia_smi)


def test_installer_cuda_local_gpu():
    assert False


def test_installer_cuda_local_gpu_requested_none():
    assert False


def test_installer_cuda_no_gpu_requested_cuda():
    assert False
