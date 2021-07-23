#!/usr/bin/env bash
#
# Deploy a new version of the fslinstaller script.  This script is run
# every time a new tag is added to the fsl/conda/installer gitlab
# repository.
#
# First we copy the installer into the deployment directory, denoted by the
# $FSLINSTALLER_DEPLOY_DIRECTORY environment variable.

# copy the installer to the deploy directory,
# stamping it with the new version number.
PATTERN="s/^__version__ =.*/__version__ = '$CI_COMMIT_TAG'/g"
DEST=$FSLINSTALLER_DEPLOY_DIRECTORY/fslinstaller.py
cat fslinstaller.py | sed "$PATTERN" > $DEST

# Then we call the update_manifest.py script, which opens a merge request
# on the fsl/conda/manifest repository, to update the latest available
# installer version in the manifest.
#
# The update_manifest.py script uses functionality from fsl-ci-rules, so
# we need to install that before running the script.
python -m pip install --upgrade pip
python -m pip install git+git@git.fmrib.ox.ac.uk:/fsl/fsl-ci-rules.git
python ./.ci/update_manifest.py
