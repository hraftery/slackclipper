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

      https://newwwie.slack.com/archives/C03FH4UM3/p1650893759330519
  
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
  """Get the content of the thread containing the message with the link provided.
  
  :param link: a string containing the message link
  :returns: a string containing the thread content as Markdown
  :raises RuntimeError: failed to query the Slack API. Associated value says why.
  :raises ValueError: unable to parse the link provided. Associated value says why.
  :raises KeyError: unable to find token for the Slack workspace in the link.
  """
  
  if not are_credentials_present():
    raise RuntimeError("No Slack API credentials found. See update_credentials_store().")

  # might raise ValueError, which we pass on unaltered
  workspace, channel, timestamp = parse_slack_message_link(link)
  
  # might raise KeyError, which we pass on unaltered
  token, cookie = get_token_and_cookie_for_workspace(workspace)

  messages = get_messages(token, cookie, channel, timestamp)

  # do `jq -r '.messages[] | "**\(.user)**\n\(.text)\n"'`
  ret = ""
  for m in messages:
    name = get_display_name(token, cookie, m['user'])
    timestamp = slack_ts_to_datetime_str(m['ts'])
    text = slack_text_to_markdown(m['text'])
    ret += f"**{name or 'Anonymous'}, at {timestamp}:**\n{text}\n\n"
  
  return ret


def get_messages(token, cookie, channel, timestamp):
  """Query the Slack API for the messages in the thread with the timestamp provided.
    
  :param token: as produced by get_token_and_cookie_for_workspace()
  :param cookie: as produced by get_token_and_cookie_for_workspace()
  :param channel: as produced by parse_slack_message_link()
  :param timestamp: as produced by parse_slack_message_link()
  :returns: the "messages" value of the JSON returned by the Slack API
  :raises RuntimeError: failed to query the Slack API. Associated value says why.
  """
  import requests
  from urllib.parse import urlunparse, urlencode

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
    raise RuntimeError(f"Slack API returned JSON without an \"ok\" flag. Got: " + str(data))

  return data['messages']

# Create globals, just so we can use @functools.cache on get_display_name, 
# which would otherwise bork with "unhashable type: 'dict'".
gToken = None
gCookie = None
def get_display_name(token, cookie, user):
  """Query the Slack API (or a local cache) for the display name of the given user
  
  :param token: as produced by get_token_and_cookie_for_workspace()
  :param cookie: as produced by get_token_and_cookie_for_workspace()
  :param user: the 'user' field of a conversations.replies API call
  :returns: a string containing the display name field of the user record
  :raises RuntimeError: failed to query the Slack API. Associated value says why.
  """
  global gToken
  global gCookie
  gToken = token
  gCookie = cookie
  return get_display_name_with_cache(user)

import functools
@functools.cache
def get_display_name_with_cache(user):
  """Helper function for get_display_name(). Do not call directly.
  """
  import requests
  from urllib.parse import urlunparse, urlencode

  global gToken
  global gCookie

  query = urlencode({'token': gToken, 'user': user},
                    quote_via=lambda string, *_:string) # avoid encoding already encoded params
  
  try:
    r =  requests.get("https://slack.com/api/users.info",
                      params = query, # requests handles dicts, but passing a string instead skips encoding
                      cookies= { gCookie['name']: gCookie['value'] })
  except Exception as e:
    raise RuntimeError("Failed to query Slack API: " + str(e)) from e

  try:
    r.raise_for_status()
  except Exception as e:
    raise RuntimeError("Slack API returned invalid HTTP status.") from e
  
  try:
    data = r.json()
  except Exception as e:
    raise RuntimeError(f"Slack API returned invalid JSON. Got {r.text}") from e

  if not data['ok']:
    raise RuntimeError(f"Slack API returned JSON without an \"ok\" flag. Got: " + str(data))

  # I don't know why but display_name is often blank. real_name looks like a good fall back.
  return data['user']['profile']['display_name'] or data['user']['profile']['real_name']


def slack_ts_to_datetime_str(ts_str):
  """Convert a Slack API ts value into a human-readable date-time string.

  The format of the ts field is obscure, but explained here:
  https://stackoverflow.com/a/77376854/3697870

  Essentially it is "<unix time>.<unique sequence number>".
  
  :param ts_str: the string as appears in a Slack API response.
  :returns: a string containing the timestamp in "YYYY-MM-DD HH:MM:SS" format
  :raises ValueError: input could not be parsed
  """
  from datetime import datetime, timezone

  unix_time_str = ts_str.partition('.')[0]

  try:
    unix_time = int(unix_time_str)
    datetime_str = datetime.fromtimestamp(unix_time, timezone.utc) \
                           .strftime('%Y-%m-%d %H:%M:%S')
  except Exception as e:
    raise ValueError("Input could not be parsed: " + str(e)) from e
  
  return datetime_str

def slack_text_to_markdown(text):
  """Parse a Slack API text value, converting links and references into Markdown.

  Surprisingly, the text value turns out to be in a format that Slack call `mrkdwn`:
  https://api.slack.com/reference/surfaces/formatting

  Not confusingly at all, it's like Markdown, except without the vowels and also
  a bit different. For example, bold is single '*', italic is single '_', urls are
  in <url|text> format, emoji are in :colon: format, links to channels are <#channel>,
  mentions are <@user_id>, and '&', '<' and '>' are escaped to their HTML entities.
  
  :param text: the string as appears in a Slack API response.
  :returns: the same as `text`, except urls are in Markdown format, user_ids are
            converted to display names, channel links and mentions are turned into
            links (only for formatting - they don't have a url), emoji are emojized,
            and escapes are unescaped.
  :raises ValueError: input could not be parsed
  """
  import re
  import emoji

  def mention_match_to_display_name(match):
    # We assume get_display_name() has already been called so we can use the globals
    global gToken
    global gCookie
    if gToken == None or gCookie == None:
      raise RuntimeError("get_display_name() called out of order. This is a bug.")

    s = match.group(1) #.partition('|')[0] # often there's an empty | field after the id
    s = get_display_name(gToken, gCookie, s)
    return f"[@{s}]"

  def asterisk_match_to_bold(match):
    if match.group(0).startswith('`') and match.group(0).endswith('`'):
      return match.group(0) # Ignore if within code block
    else:
      return "**" # Otherwise turn mrkdwn bold into Markdown bold

  # Unfortunately, it looks like whether the asterisk marks a bold section or not
  # is lost in the text we get from the Slack API. Even checking the asterisk is
  # next to a word doesn't seem to help. So the best we can do is convert them
  # all, even though some might just be a literal asterisk.
  text = re.sub(r"`.*?`|\*", asterisk_match_to_bold, text) # bold
  # Alas channels are specified by ID, not name, so these look a bit crap for now.
  text = re.sub(r"<#(.*?)>", r"[#\1]", text) # channel links
  text = re.sub(r"<@(.*?)>", mention_match_to_display_name, text) # mentions
  text = re.sub(r"<(.*?)\|(.*?)>", r"[\2](\1)", text) # URLS
  text = emoji.emojize(text, language='alias') # :emoji: to their glyphs
  text = text.replace("&amp;", "&") # & escape
  text = text.replace("&lt;", "<") # < escape
  text = text.replace("&gt;", ">") # > escape

  return text
