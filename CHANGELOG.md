# FSL installer script release history


# 3.13.0 (Under development)


 - The `fslinstaller.py` script will now instruct `conda` to install versions of CUDA packages which are compatible with a local GPU, or which are compatible with a CUDA version specified by the new `--cuda X.Y` command-line option.


# 3.12.2 (Friday 14th June 2024)

 - Check for more network errors that may be able to be solved by retrying the
   installation.


# 3.12.1 (Thursday 13th June 2024)

 - If an extra FSL component has already been installed into `$FSLDIR/envs/`
   and a request is made to install it again, it is updated using
   `conda env update`. This functionality is used by the `update_fsl_release`
   command.


# 3.12.0 (Wednesday 12th June 2024)

 - The `fslinstaller.py` script is now capable of installing software into
   separate child environments, within `$FSLDIR/envs/`, to allow for better
   isolation of different software stacks.
 - New `--channel` option, which can be used to install FSL packages from a
   local conda channel.


# 3.11.0 (Wednesday 5th June 2024)

 - The `fslinstaller.py` script now attempts to detect network errors during
   the main installation step - if a network error occurs, the installation
   will be retried up to three times. The number of retries can be changed
   with the `--num_retries` option.
 - New `--throttle_downloads` option, which limits the number of simultaneous
   package downloads, for use when installing over unreliable network
   connections.


# 3.10.0 (Monday 27th May 2024)

 - The `fslinstaller.py` script will now download and install a Miniconda
   installer which matches the Python version that is to be installed as
   part of FSL, if this information is present in the installation manifest
   file.


# 3.9.1 (Tuesday 14th May 2024)

 - Prevent conda from updating itself during installations, as this can
   sometimes cause installation to crash.


# 3.9.0 (Friday 9th February 2024)

 - New `--logfile` option, allowing the log file location to be customised.
 - New `--progress_file` option, which instructs the installer to write
   progress updates to a file for external monitoring.


# 3.8.2 (Tuesday 6th February 2024)

 - Fixed another new issue which was allowing `~/.condarc` settings to override
   `$FSLDIR/.condarc` settings.


# 3.8.1 (Tuesday 6th February 2024)

 - Fixed a new issue installing into locations requiring administrative
   privileges.


# 3.8.0 (Wednesday 31st January 2024)

 - The installer can now be told to use an existing base conda/mamba
   installation instead of downloading/installing its own, via the
   `--miniconda` option, e.g. `fslinstaller.py
   --miniconda=/Users/xyz/miniconda3/`. If the same location is given as the
   destination directory (e.g. `fslinstaller.py --miniconda=~/fsl/
   --dest=~/fsl/`), FSL is installed into the base conda environment, otherwise
   FSL is created as a separate child environment.


# 3.7.0 (Monday 29th January 2024)

 - FSL installations are now registered with a remote server. Basic
   installation and system information is sent as part of the registration
   process. This can be skipped by passing the `--skip_registration` / `-r`
   command-line option.
 - Add another progress reporting mechanism.


# 3.6.0 (Thursday 18th January 2024)

 - Add a new progress reporting mechanism.


# 3.5.11 (Saturday 13th January 2024)

 - Add a trailing newline when appending the FSL configuration to the end of
   the user's shell profile.


# 3.5.10 (Friday 12th November 2023)

 - Make sure that SSL verification is disabled for all downloads, if requested
   via the hidden `--skip_ssl_verify` option.


# 3.5.9 (Wednesday 6th November 2023)

 - Make post-installation failures non-fatal.


# 3.5.8 (Monday 27th November 2023)

 - Set the installation directory to `$FSLDIR` if it is set in the environment.


# 3.5.7 (Friday 22nd September 2023)

 - Allow an existing `ArgumentParser` to be passed to the `parse_args`
   function.


# 3.5.6 (Wednesday 23rd August 2023)

 - Fixed a bug which was affecting `fsl_update_release`, and which would
   cause `None` to be returned instead of the adminsitrator password


# 3.5.5 (Wednesday 9th August 2023)

 - Administrative/maintenance updates.


# 3.5.4 (Wednesday 9th August 2023)

 - Set the `MAMBA_NO_LOW_SPEED_LIMIT` environment variable when calling
   `mamba`, so that it does not abort on slow downloads.


# 3.5.3 (Friday 30th June 2023)

 - Small fix to support programmatic usage.


# 3.5.2 (Friday 23rd June 2023)

 - New `--conda` option which causes the installer to use `conda` instead of
   `mamba`.


# 3.5.1 (Monday 5th June 2023)

 - Print a message on attempts to install versions of FSL older than 6.0.6.


# 3.5.0 (Wednesday 22nd March 2023)

 - Correctly determine the `root` user home directory in case the user
   has requested that the `root` user's shell profile should be modified.
 - New hidden `--debug` option, which enables very verbose output logging
   from `mamba` / `conda`.


# 3.4.2 (Sunday 12th March 2023)

 - Change the default installation directory to `/usr/local/fsl/` when the
   `fslinstaller.py` script is run as the root user. Additionally, do not
   modify the root user's shell profile.


# 3.4.1 (Wednesday 8th March 2023)

 - Make sure that the temporary installation directory is deleted as the root
   user if necessary.


# 3.4.0 (Thursday 2nd March 2023)

 - Fix the conda package cache directory (the `pkgs_dirs` setting) at
   `$FSLDIR/pkgs`, to avoid potential conflicts with user-configured package
   caches.
 - The installation log file is now copied to the user home directory on
   failure.


# 3.3.0 (Friday 27th January 2023)

 - Update the installer to install macOS-M1 FSL builds if available.
 - Exit with a warning if an Intel FSL build is to be installed on a
   M1 machine, and Rosetta emulation is not enabled.


# 3.2.1 (Tuesday 24th January 2023)

 - Unrecognised command-line arguments are ignored - this is to allow for
   forward-compatibility within a self-update cycle.
 - `bash` is used rather than `sh` when calling the miniconda installer
   script.


# 3.2.0 (Sunday 25th December 2022)

 - New hidden `--miniconda` option, allowing an alternate miniconda installer
   to be used.


# 3.1.0 (Saturday 24th December 2022)

 - Allow different progress reporting implementations
 - Clear all `$PYTHON*` environment variables before installing miniconda
   and FSL.


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
