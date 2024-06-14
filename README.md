# FSL installer


[![pipeline status](https://git.fmrib.ox.ac.uk/fsl/conda/installer/badges/main/pipeline.svg)](https://git.fmrib.ox.ac.uk/fsl/conda/installer/-/commits/main)
[![coverage report](https://git.fmrib.ox.ac.uk/fsl/conda/installer/badges/main/coverage.svg)](https://git.fmrib.ox.ac.uk/fsl/conda/installer/-/commits/main)


This repository is the home of `fslinstaller.py`, the installer script for [FSL](https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/).


The `fslinstaller.py` script in this repository is the successor to the `fslinstaller.py` script from the fsl/installer> repository.  _This_ version is for **conda-based** FSL release, from FSL version 6.0.6 onwards.


`fslinstaller.py` is a Python script which can run with any version of Python from 2.7 onwards. Normal usage of `fslinstaller.py` will look like one of the following:

    ```
    python  fslinstaller.py
    python2 fslinstaller.py
    python3 fslinstaller.py
    curl https://some_url/fslinstaller.py | python
    ```


# Customising the FSL installation location

By default, FSL will be installed to your home directory, at `~/fsl/`. The `fslinstaller.py` script will ask for confirmation of the destination directory, or it can be specified via the `-d` option, e.g.:

    ```
    python fslinstaller.py -d /usr/local/fsl/
    ```


# Modifying your shell profile

By default, the `fslinstaller.py` script will add some code to your shell profile (`.profile`, `~/.bash_profile`, `.zprofile`, `.cshrc` or `.tcshrc`, depending on which shell you are using) to make FSL available in your shell by default. This can be disabled via the `-n` / `--no_env` option, e.g.:

    ```
    python fslinstaller.py -n
    ```


# Installing older versions of FSL

By default, the `fslinstaller.py` script will install the latest available FSL version. You can install an older version of FSL (back to 6.0.6) via the `-V` option, e.g.:

    ```
    python fslinstaller.py -V 6.0.6
    ```


# Installing optional FSL components -  _"extras"_

Some FSL versions come with optional components, also known as _"extras"_, that are not installed by default due to download or size limitations. You can use the `-e` / `--extra` option to install these components. For example, if there is an optional FSL component called `optional-package` that you wish to install, you can run:

    ```
    python fslinstaller.py --extra optional-package
    ```


# Installing CUDA libraries

Some FSL tools use CUDA for GPU acceleration. C++ programs such as [eddy](https://git.fmrib.ox.ac.uk/fsl/eddy) are statically linked against the CUDA Toolkit, meaning that target systems only need to have a CUDA driver installed in order to run them.

For Python-based tools which use (e.g.) Pytorch, a copy of the CUDA Toolkit (and related libraries such as cuDNN) is installed from [conda-forge](https://anaconda.org/conda-forge/cuda-version).

By default, the `fslinstaller.py` script will interrogate the local system to see if a CUDA-capable GPU is installed, and will install the most recent compatible CUDA version. The `fslinstaller.py` script will not install the CUDA toolkit at all on systems which do not have a CUDA-capable GPU.

If you wish to install CUDA libraries for a specific CUDA version, you can do so with the `-c` / `--cuda` option, e.g.:

    ```
    python fslinstaller.py --cuda 11.5
    ```

To disable installation of CUDA libraries, you can pass `none`, e.g.:

    ```
    python fslinstaller.py --cuda none
    ```


# Other options

Several advanced options are available - run `python fslinstaller.py -h`, and read the `parse_args` function in the `fslinstaller.py` script for more details on the advanced/hidden options.


# Detailed overview


In normal usage, the `fslinstaller.py` script performs the following tasks:

 1. Downloads the FSL release manifest file from a hard-coded URL, which is a JSON file containing information about available FSL releases.
 2. Asks the user where they would like to install FSL (hereafter referred to as `$FSLDIR`).
 3. Asks the user for their administrator password if necessary.
 4. Downloads a [`miniconda`](https://docs.conda.io/en/latest/miniconda.html), [`miniforge`](https://github.com/conda-forge/miniforge), [`mambaforge`](https://github.com/conda-forge/miniforge), or [`micromamba`](https://mamba.readthedocs.io/en/latest/user_guide/micromamba.html) installer
 5. Installs `miniconda` to `$FSLDIR`.
 6. Downloads YAML files containing conda environment specifications for the latest FSL version (or the version requested by the user; hereafter referred to as `environment.yml`). FSL is nominally installed as a single conda environment, but optional/extra components may be installed as separate conda environments within the `$FSLDIR/envs/` directory.
 7. Installs the FSL environment by running:
       `$FSLDIR/bin/conda env update -n base -f environment.yml`
 8. Installs any extra/optional components requested by the user by running:
       `$FSLDIR/bin/conda env create -p $FSLDIR/envs/<envname> -f extra_environment.yml`
 9. Modifies the user's shell configuration so that FSL is accessible in their shell environment.


# Managing `fslinstaller.py` versions and releases


> This information is for FSL developers/maintainers.


In addition to being published as a self-contained script, the `fslinstaller` script is also built as a Python package, and importable via the `fsl.installer` package.  The conda package is called `fsl-installer`, and is built at the fsl/conda/fsl-installer> repository. Some scripts in the fsl/base> project (`update_fsl_package`and `update_fsl_release`) use functions from the `fsl.installer` package, therefore when making changes you must be careful to preserve API compatibiity.


All releases of `fslinstaller.py` are given a version of the form `major.minor.patch`, for example `1.3.2`.

The fsl/conda/installer> project follows semantic versioning conventions, where:
 - changes to the command-line interface require the major version number to be incremented
 - enhancements and new features require the minor version number to be incremented
 - bug fixes and minor changes require the patch version number to be incremented.

All changes to the `fslinstaller.py` must be accompanied by a change to the `__version__` attribute in the `fslinstaller.py` script.


New versions of the `fslinstaller.py` script can be released simply by creating a new tag, containing the new version identifier, on the fsl/conda/installer> GitLab repository. This will cause the following automated routines to run:

 - The new version of the `fslinstaller.py` script is deployed to a web server, available for download.

 - A merge request is opened on the fsl/conda/fsl-installer> conda recipe repository, causing the new version to be built as a conda package.

 - A merge request is optionally opened on the fsl/conda/manifest> repository, updating the installer version number in the FSL release manifest JSON file.

Note that the tag must be identical to the value of the `__version__` attribute in the `fslinstaller.py` script.
