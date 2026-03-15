#!/usr/bin/env python3
#
# StripExecutables — NZBGet post-processing extension.
# Removes executable and junk files from completed downloads so that
# Sonarr/Radarr don't refuse to import with "Found executable file".
#

##############################################################################
### NZBGET POST-PROCESSING SCRIPT                                         ###

# Remove executable and junk files from completed downloads.
#
# Strips .exe, .bat, .cmd, .com, .scr, .msi, .vbs, .js, .wsf, .ps1,
# .url, .lnk and other non-media files that trigger Sonarr/Radarr's
# "Found executable file" warning.

###########################################################################
### OPTIONS                                                              ###

# Extensions to remove (comma-separated, case-insensitive).
#StripExtensions=.exe,.bat,.cmd,.com,.scr,.msi,.vbs,.js,.wsf,.ps1,.url,.lnk,.pif,.reg

# Also remove common junk files (nfo, txt, jpg, png, etc).
#StripJunk=no

# Junk extensions (only used if StripJunk=yes).
#JunkExtensions=.nfo,.txt,.jpg,.jpeg,.png,.gif,.bmp,.ico,.xml,.htm,.html

### NZBGET POST-PROCESSING SCRIPT                                         ###
##############################################################################

import os
import sys

# NZBGet exit codes
POSTPROCESS_SUCCESS = 93
POSTPROCESS_NONE = 95
POSTPROCESS_ERROR = 94

# Check we're running inside NZBGet
if "NZBOP_TEMPDIR" not in os.environ:
    print("This script should be called from NZBGet", file=sys.stderr)
    sys.exit(1)

# Get download directory
download_dir = os.environ.get("NZBPP_DIRECTORY", "")
if not download_dir or not os.path.isdir(download_dir):
    print(f"[INFO] Download directory not found: {download_dir}")
    sys.exit(POSTPROCESS_NONE)

# Skip if download failed
status = os.environ.get("NZBPP_TOTALSTATUS", "")
if status != "SUCCESS":
    print(f"[INFO] Skipping — download status is {status}")
    sys.exit(POSTPROCESS_NONE)

# Parse configured extensions
strip_raw = os.environ.get("NZBPO_STRIPEXTENSIONS", ".exe,.bat,.cmd,.com,.scr,.msi,.vbs,.js,.wsf,.ps1,.url,.lnk,.pif,.reg")
strip_exts = set(ext.strip().lower() for ext in strip_raw.split(",") if ext.strip())

strip_junk = os.environ.get("NZBPO_STRIPJUNK", "no").lower() == "yes"
if strip_junk:
    junk_raw = os.environ.get("NZBPO_JUNKEXTENSIONS", ".nfo,.txt,.jpg,.jpeg,.png,.gif,.bmp,.ico,.xml,.htm,.html")
    junk_exts = set(ext.strip().lower() for ext in junk_raw.split(",") if ext.strip())
    strip_exts.update(junk_exts)

removed = []

for root, dirs, files in os.walk(download_dir):
    for fname in files:
        ext = os.path.splitext(fname)[1].lower()
        if ext in strip_exts:
            fpath = os.path.join(root, fname)
            try:
                size = os.path.getsize(fpath)
                os.remove(fpath)
                removed.append(f"{fname} ({size} bytes)")
                print(f"[INFO] Removed: {fname} ({size} bytes)")
            except OSError as e:
                print(f"[WARNING] Failed to remove {fname}: {e}")

if removed:
    print(f"[INFO] Stripped {len(removed)} file(s) from {os.path.basename(download_dir)}")
else:
    print(f"[DETAIL] No executable/junk files found in {os.path.basename(download_dir)}")

sys.exit(POSTPROCESS_SUCCESS)
