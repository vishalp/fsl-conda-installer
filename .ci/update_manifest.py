#!/usr/bin/env python
#
# This script is called when a new version of the fslinstaller.py script is
# tagged. It opens a merge request on the GitLab fsl/conda/manifest project,
# to update the FSL release manifest file so that it contains the new installer.
# version string.
#


import os

from fsl_ci        import (USERNAME,
                           EMAIL,
                           indir,
                           tempdir,
                           sprun)
from fsl_ci.gitlab import (open_merge_request,
                           gen_branch_name)


MANIFEST_PATH = 'fsl/conda/manifest'


COMMIT_MSG = 'MNT: Update fslinstaller version to latest [{tag}] ' \
             'in FSL installer manifest'

MERGE_REQUEST_MSG = """

This MR was automatically opened as a result of a new tag being added to
the fsl/installer> project. It updates the installer version in the FSL
release `manifest.json` file to the latest installer version.
""".strip()


def checkout_and_update_manifest(server, token, tag):

    manifest_url  = f'{server}/{MANIFEST_PATH}'
    branch        = f'mnt/installer{tag}'
    branch        = gen_branch_name(branch, MANIFEST_PATH, server, token)
    sprun(f'git clone {manifest_url} manifest')

    with indir('manifest'):
        sprun(f'git config user.name  {USERNAME}')
        sprun(f'git config user.email {EMAIL}')
        sprun(f'git checkout -b {branch} master')
        update_manifest()
        sprun( 'git add *')
        sprun(f'git commit -m "{COMMIT_MSG}"')
        sprun(f'git push origin {branch}')

    return branch


def main(server=None, token=None, tag=None):

    if server is None: server = os.environ['CI_SERVER_URL']
    if token  is None: token  = os.environ['FSL_CI_API_TOKEN']
    if tag    is None: tag    = os.environ['CI_COMMIT_TAG']

    branch = checkout_and_update_manifest()

    open_merge_request(MANIFEST_PATH,
                       branch,
                       MERGE_REQUEST_MSG,
                       server,
                       token)


if __name__ == '__main__':
    main()
