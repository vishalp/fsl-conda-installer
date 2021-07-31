#!/usr/bin/env bash
#
# Deploy a new version of the fslinstaller script.  This script is run
# every time a new tag is added to the fsl/conda/installer gitlab
# repository.
#
# First we copy the installer into the deployment directory, denoted by the
# $FSLINSTALLER_DEPLOY_DIRECTORY environment variable.

set -e


# Make sure that the installer version matches the tag
scriptver=$(cat fslinstaller.py | grep "__version__ = " | cut -d " " -f 3 | tr -d "'")

if [ "$scriptver" != "$CI_COMMIT_TAG" ]; then
  echo "Version in fslinstaller.py does not match tag! $scriptver != $CI_COMMIT_TAG"
  exit 1
fi

cp fslinstaller.py $FSLINSTALLER_DEPLOY_DIRECTORY/

# Then we call the update_manifest.py script, which opens a merge request
# on the fsl/conda/manifest repository, to update the latest available
# installer version in the manifest.
#
# The update_manifest.py script uses functionality from fsl-ci-rules, so
# we need to install that before running the script.
python -m pip install --upgrade pip
python -m pip install git+https://git.fmrib.ox.ac.uk/fsl/fsl-ci-rules.git
python ./.ci/update_manifest.py
