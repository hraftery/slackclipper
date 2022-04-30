"""slackclipper.py :: Copy the contents of a Slack thread.

slackclipper uses your personal Slack account to extract the content of a
thread from Slack, allowing you to store it elsewhere.
"""

__author__ = "Heath Raftery <heath@empirical.ee>"

import os
import pathlib
import pickle

LOCAL_STORE_PATH  = pathlib.Path('~/.config/slackclipper/').expanduser()
CREDENTIALS_FILE  = str(LOCAL_STORE_PATH) + "/credentials"

def are_credentials_present():
  """Return true if the local store of slack tokens and cookie can be found.
  """
  try:
    creds = get_credentials_from_store()
    return 'tokens' in creds and 'cookie' in creds
  except:
    return False


def update_credentials_store(creds=None):
  """Use slacktokens to retrieve the user's personal tokens and cookie for
  Slack. Then persist the data to file, overwriting any existing entries.

  :param creds: optionally supply the credentials instead of using
                `slacktokens` to extract them. See `slacktokens`
                documentation for the expected format.
  :raises RuntimeError: failed to extract from Slack. Associated value says why.
  :raises OSError: failed to persist to file. Associated value says why.
  """
  if creds is None:
    try:
      import slacktokens
      creds = slacktokens.get_tokens_and_cookie()
    except Exception as e:
      raise RuntimeError("Failed to extract Slack credentials.") from e
  
  try:
    os.makedirs(LOCAL_STORE_PATH, exist_ok=True)
    with open(CREDENTIALS_FILE, 'wb') as credsFile:
      pickle.dump(creds, credsFile)
  except Exception as e:
    raise OSError("Unable to persist credentials to file.") from e

def get_credentials_from_store():
  """Read the contents of the credentials store and return as a Python object.
  
  May raise an exception is the file cannot be read.
  """
  with open(CREDENTIALS_FILE, 'rb') as credsFile:
    creds = pickle.load(credsFile)
  return creds


def get_token_and_cookie_for_workspace(url):
  """Get the personal token and cookie for the specified workspace.

  :param url: a string containing the workspace URL. Must be formatted like
              "scheme://netloc/". For example: "https://my-workspace.slack.com/".
  :returns: a tuple containing the token and cookie string pair
  :raises KeyError: no token was found for the specified workspace
  """
  creds = get_credentials_from_store()
  if url in creds['tokens']: #TODO: could be more tolerant than exact match
    token = creds['tokens'][url]['token']
  else:
    raise KeyError(f"No token found matching the workspace URL: {url}")
  
  return token, creds['cookie']


def get_name_for_workspace(url):
  """Get the friendly name for the specified workspace.

  :param url: a string containing the workspace URL
  :returns: a string containing the workspace friendly name
  :raises KeyError: no name was found for the specified workspace
  """
  creds = get_credentials_from_store()
  if url in creds['tokens']: #TODO: could be more tolerant than exact match
    return creds['tokens']['name']
  else:
    raise KeyError("No workspace matching that URL.")


def parse_slack_message_link(link):
  """Extract the workspace url, channel ID and timestamp from a Slack message link.
  
  When you "Copy link" in Slack, the URL provided appears to be of the form:
  
      https://<workspace url>/archives/<channel ID>/p<timestamp in microseconds>

  For example:

      https://newwwie.slack.com/archives/C96PDSJ7J/p1651213905220139
  
  This function accepts a string containing such a link, and returns the
  workspace url, channel ID and timestamp extracted, each in a format accepted
  by the Slack API.

  The return format is a tuple containing the url, the channel ID and the timestamp.
  
  :param link: a string containing the message link
  :returns: a tuple containing the parsed elements from the link
  :raises ValueError: unable to parse the link provided
  """
  linkWithoutPercent = link.replace("\%","")
  ERROR_FMT = f"Unexpected link format: %s Got: \"{linkWithoutPercent}\""
  
  from urllib.parse import urlparse

  try:
    scheme, netloc, path, *rest = urlparse(link)
    archives, chId, ts, *rest = path[1:].split("/")
  except Exception as e:
    raise ValueError(ERROR_FMT % ("could not be parsed a URL.")) from e

  if not scheme:
    raise ValueError(ERROR_FMT % ("link must include a scheme (eg. \"http\")."))
  if archives != "archives":
    raise ValueError(ERROR_FMT % ("first part of path must be \"archives\"."))
  elif ts[0] != 'p':
    raise ValueError(ERROR_FMT % ("timestamp part of path must start with 'p'."))
  elif not ts[1:].isnumeric():
    raise ValueError(ERROR_FMT % ("timestamp part of path after 'p' must be numeric."))
  elif len(ts) != 1+10+6:
    raise ValueError(ERROR_FMT % ("timestamp must be 16 digits long."))
  elif rest:
    raise ValueError(ERROR_FMT % ("timestamp must be last part of path."))

  return f"{scheme}://{netloc}/", chId, f"{ts[1:11]}.{ts[11:17]}"


def get_thread_content(link):
  """Query the Slack API for the content of the thread containing the message with the link provided.
    
  :param link: a string containing the message link
  :returns: a string containing the thread content as Markdown
  :raises RuntimeError: failed to query the Slack API. Associated value says why.
  :raises ValueError: unable to parse the link provided. Associated value says why.
  :raises KeyError: unable to find token for the Slack workspace in the link.
  """
  import requests
  from urllib.parse import urlunparse, urlencode
  
  if not are_credentials_present():
    raise RuntimeError("No Slack API credentials found. See update_credentials_store().")

  # might raise ValueError, which we pass on unaltered
  workspace, channel, timestamp = parse_slack_message_link(link)
  
  # might raise KeyError, which we pass on unaltered
  token, cookie = get_token_and_cookie_for_workspace(workspace)

  scheme = "https"
  netloc = "slack.com"
  path = "/api/conversations.replies"
  params = ""
  query = urlencode({'token': token, 'channel': channel, 'ts': timestamp},
                    quote_via=lambda string, *_:string) # avoid encoding already encoded params

  try:
    r =  requests.get("https://slack.com/api/conversations.replies",
                      params = query, # requests handles dicts, but passing a string instead skips encoding
                      cookies= { cookie['name']: cookie['value'] })
  except Exception as e:
    raise RuntimeError("Failed to query Slack API.") from e

  try:
    r.raise_for_status()
  except Exception as e:
    raise RuntimeError("Slack API returned invalid HTTP status.") from e
  
  try:
    data = r.json()
  except Exception as e:
    raise RuntimeError(f"Slack API returned invalid JSON. Got {r.text}") from e

  if not data['ok']:
    raise RuntimeError(f"Slack API return JSON with an \"ok\" flag. Got {data}.")

  # do `jq -r '.messages[] | "**\(.user)**\n\(.text)\n"'`
  ret = ""
  for m in data['messages']:
    ret += f"**{m['user']}**\n{m['text']}\n\n"
  
  return ret


def main():
  # Tried the tkinter method but was rough as guts.
  # No big deal to have this dependency.
  from pyperclip import copy, paste
  
  try:
    content = get_thread_content(paste())
    copy(content)
    print("Done.")
  except Exception as e:
    print(f"Failed: {e}")
    raise # for debugging


def main1():
  # Seems like a heavy way to get the clipboard, but that's what the Internet says.
  from tkinter import Tk
  tk = Tk()
  tk.withdraw()
  
  try:
    content = get_thread_content(tk.clipboard_get())
    
    tk.clipboard_clear()
    tk.clipboard_append(content)
    print("Done. Results are on the clipboard.")
  except Exception as e:
    print(f"Failed: {e}")
    raise
  finally:
    tk.update() # now it stays on the clipboard after the window is closed
    tk.destroy()
