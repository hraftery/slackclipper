"""slackclipper_runner.py :: Entry point for slackclipper
"""

__author__ = "Heath Raftery <heath@empirical.ee>"

from slackclipper import *
import sys
import argparse
from urllib.parse import urlparse
# Tried the tkinter method of clipboard access, but it was rough as guts.
# No big deal to have this dependency.
from pyperclip import copy, paste


def link_validator(link):
  try:
    # Lots of ways to validate a link, but best for us is "will definitely not work"
    # so that means using the same urlparse as slackclipper, plus a sanity check to
    # rule out lots of false positives like "https://https://https://www.foo.bar" or
    # "http://www.google.com" or "ftp://warez.r.us".
    p = urlparse(link)
    return p.scheme and p.netloc and "slack" in p.netloc.lower()
  except:
    return False


def print_err(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


# provide entry point as function, so it can be called from setuptools
def main():
  pass


parser = argparse.ArgumentParser(
  formatter_class=argparse.RawDescriptionHelpFormatter,
  epilog="Note: this program is not endorsed or authorised in any way by Slack Technologies LLC.",
  description="""Extract the contents of a Slack thread.

Run this prgram after copying the Slack thread link to the clipboard. \
The clipboard will be replaced with the contents of the thread.""")
parser.add_argument('-p', '--pipe', action='store_true',
                    help="read the link from stdin and write the content to stdout, instead of using the clipboard")
parser.add_argument('-u', '--update-credentials', action='store_true',
                    help="instead of clipping a thread, just extract your credentials from Slack and store them for future use")
parser.add_argument('-d', '--debug', action='store_true',
                    help="show stack trace on error")

args = parser.parse_args()

if args.update_credentials or not are_credentials_present():
  if not args.pipe:
    print("Attempting to extract Slack tokens. NOTE: Slack must be closed for this to work.")
    print("You may be prompted for your login password, possibly twice. This is only used")
    print("to retrieve the Slack storage password.")
    print("")
  
  try:
    update_credentials_store()
  except Exception as e:
    print_err("Failed to update credentials. Details of error are below.")
    if not args.debug:
      sys.exit("--> " + str(e.__context__))
    else:
      raise
  else:
    if not args.pipe:
      print("Credentials successfully updated.")
      print("")
    if args.update_credentials:
      sys.exit(0)


try:
  if args.pipe:
    link = sys.stdin.read()
  else:
    link = paste()
  
  if not link_validator(link):
    if args.pipe:
      raise ValueError(f"No valid link found in stdin. Found: {link[:200]}")
    
    print("Clipboard does not seem to contain a link.")
    print("Either copy a link to the clipboard and enter 'y', or enter 'n' to quit.")
    reply = str(input("Would you like to try again? (y/n): ")).lower().strip()
    if reply[0] == 'n':
      sys.exit(0)
  
  if not args.pipe:
    print(f"Clipping thread for link: {link[:200]}")
  content = get_thread_content(link)

  if args.pipe:
    print(content)
  else:
    copy(content)
    print("Done. Results are on the clipboard ready to be pasted wherever you like.")
except Exception as e:
  print_err("Failed. Details of error are below.")
  if not args.debug:
    print_err("--> " + str(e)) # would prefer to print whole exception chain but not sure how to go about that.
  else:
    raise
