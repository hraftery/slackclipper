"""slackclipper_runner.py :: Entry point for slackclipper
"""

__author__ = "Heath Raftery <heath@empirical.ee>"

# Tried the tkinter method for clipboard access but it was rough as guts.
# No big deal to have this dependency.
from pyperclip import copy, paste
from slackclipper import *

try:
  link = paste()
  print(f"Clipping thread for link: {link}")
  content = get_thread_content(paste())
  copy(content)
  print("Done. Results are on the clipboard ready to be pasted wherever you like.")
except Exception as e:
  print(f"Failed. Details of error are below.")
  print(str(e))
  #raise # for debugging

# provide entry point as function, so it can be called from setuptools
def main():
  pass
