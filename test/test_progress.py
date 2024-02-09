#!/usr/bin/env python
#
# test_progress.py -
#
# Author: Paul McCarthy <pauldmccarthy@gmail.com>
#


import time

import fsl.installer.fslinstaller as fi


def test_progfile():

    with fi.tempdir():
        with fi.Progress(proglabel='prog1', progfile='prog1.txt') as prog:
            for i in range(5):
                prog.update(i + 1, 5)

        exp = '\n'.join(['prog1 {} 5'.format(i + 1) for i in range(5)])
        assert open('prog1.txt', 'rt').read().strip() == exp
