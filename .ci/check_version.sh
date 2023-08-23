#!/usr/bin/env bash

set -e

git fetch origin main
thisver=$(cat fsl/installer/fslinstaller.py |
          grep "__version__ = "             |
          cut -d " " -f 3                   |
          tr -d "'")
mainver=$(git show origin/main:fsl/installer/fslinstaller.py |
          grep "__version__ = "                              |
          cut -d " " -f 3                                    |
          tr -d "'")

if [ "$thisver" = "$mainver" ]; then
  echo "Version has not been updated!"
  echo "Version on main branch: $mainver"
  echo "Version in this MR:     $thisver"
  echo "The version number must be updated before this MR can be merged."
  exit 1
else
  echo "Version on main branch: $mainver"
  echo "Version in this MR:     $thisver"
fi
