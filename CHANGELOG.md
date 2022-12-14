# FSL installer script release history


# 3.0.1 (Friday 13th December 2022)

 - Minor internal adjustments.


# 3.0.0

 - The installer script will now use `mamba` instead of `conda`, if present,
   for all conda commands.
 - Reverted to a single-step installation process - instead of installing
   base packages separately, the full installation is now performed with
   `conda env update -f <env>.yml`.
 - Use the number of package files saved to `$FSLDIR/pkgs/`to monitor
   and report progress of the main FSL installation, instead of counting
   the number of lines printed to standard output.

# 2.1.1

 - Added hooks to insert FSL license boilerplate into source files.

# 2.1.0

 - More internal changes and enhancements to improve usability in other
   scripts.


# 2.0.1

 - Internal changes to improve usability in other scripts.

# 2.0.0

 - Removed the `--cuda` / `--no_cuda` options.
 - Re-arrange the code to make it installable as a Python library.


# 1.10.2

 - Fix to handling of the `--cuda` / `--no_cuda` options on macOS.


# 1.10.1

 - Small adjustment to how the `devreleases.txt` file is parsed.

# 1.10.0

 - New hidden `--devrelease` and `--devlatest` options, for installing
   development releases.

# 1.9.0

 - Removed/disabled the `--update` option, for updating an existing FSL
   installation. This option may be re-enabled in the future.
 - Removed the hidden `--environment` option.
 - Update the `fslinstaller.py` script to work with the new CUDA package
   arrangement - FSL environment specifications are no longer provided
   for each supported CUDA version. Instead, all CUDA packages are included
   as part of the `linux-64` environment. The `--cuda` option can be used
   to select one set of packages to be installed, and the `--no_cuda` option
   can be used to exclude all CUDA packages from the installation.


# 1.8.0

 - The default FSL installation directory has been changed from `/usr/local/fsl/`
   to `$HOME/fsl`.
 - The fslinstaller now reads `FSLCONDA_USERNAME` and `FSLCONDA_PASSWORD` environment
   variables if a `--username` and `--password` were not supplied (only relevant for
   internal releases).
