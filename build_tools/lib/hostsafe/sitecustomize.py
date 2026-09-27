"""Keep bare-metal suite runs from writing /var/crash reports.

Ubuntu's system sitecustomize installs apport's excepthook, which writes a
/var/crash report for every Python script that dies with an uncaught
exception. vp.sh puts this directory on PYTHONPATH when a suite runs directly
on a host (local_run.sh, VP_NO_CONTAINER=1), so this module is imported
instead of the system one and the default excepthook stays in place.
Containers never use it: the CI image has no apport.
"""
import sys

sys.excepthook = sys.__excepthook__
