# FSL installer


[![pipeline status](https://git.fmrib.ox.ac.uk/fsl/conda/installer/badges/master/pipeline.svg)](https://git.fmrib.ox.ac.uk/fsl/conda/installer/-/commits/master)
[![coverage report](https://git.fmrib.ox.ac.uk/fsl/conda/installer/badges/master/coverage.svg)](https://git.fmrib.ox.ac.uk/fsl/conda/installer/-/commits/master)


This repository is the home of `fslinstaller.py`, the FSL installer script for
FSL.


The `fslinstaller.py` script in this repository is the successor to the
`fslinstaller.py` script from the fsl/installer> repository.  _This_ version
is for **conda-based** FSL release, from FSL version 6.0.6 onwards.


In normal usage, the `fslinstaller.py` script performs the following tasks:
 1. Downloads a JSON manifest file, which contains information about available
    FSL releases.
 2. Asks the user where they would like to install FSL (hereafter referred to
    as `$FSLDIR`)
 3. Downloads a `miniconda` installer
 4. Installs `miniconda` to `$FSLDIR`
 5. Downloads a YAML file containing a conda environment specification for
    the latest FSL version (or the version requested by the user; hereafter
    referred to as `environment.yml`)
 6. Installs the FSL environment by running:

       `$FSLDIR/bin/conda env update -n base -f environment.yml`

 7. Modifies the user's shell configuration so that FSL is accessible in
    their shell environment.
