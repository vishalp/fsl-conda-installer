from fsl.installer.fslinstaller import *

argv=[]
args=parse_args(argv)
ctx=Context(args)

register_installation(ctx)
