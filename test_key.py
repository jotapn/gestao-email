"""Test how python-decouple reads the private key."""
import os
from decouple import config

# Simulate Coolify env: literal \n
raw = (
    "-----BEGIN PRIVATE KEY-----" + chr(92) + "n"
    "MIITEST" + chr(92) + "n"
    "-----END PRIVATE KEY-----" + chr(92) + "n"
)
os.environ["TEST_PK_DECOUPLE"] = raw

# Read through decouple (same as settings.py does)
val = config("TEST_PK_DECOUPLE", default="")
print("os.environ gives:", repr(raw))
print("decouple gives:  ", repr(val))
print("Are they equal?  ", raw == val)
print()

# Now test: what if decouple already interprets \n?
print("decouple has real newlines:", "\n" in val)
print("decouple has literal backslash-n:", (chr(92) + "n") in val)
