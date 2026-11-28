"""Loaded by pytest before the test modules. A fixed UTC+11 zone (Etc/GMT-11 has a reversed sign)
keeps local-date tests independent of any real place and its daylight saving (D27)."""

import os

os.environ.setdefault("TIME_ZONE", "Etc/GMT-11")
os.environ.setdefault("SITE_BUCKET", "site")  # where the transform puts the dashboard
os.environ.setdefault("GARMIN_FUNCTION", "garmin")  # the tick starts it with the daily runs
