# FSL installer script release history

# 1.8.0

 - The default FSL installation directory has been changed from `/usr/local/fsl/`
   to `$HOME/fsl`.
 - The fslinstaller now reads `FSLCONDA_USERNAME` and `FSLCONDA_PASSWORD` environment
   variables if a `--username` and `--password` were not supplied (only relevant for
   internal releases).
