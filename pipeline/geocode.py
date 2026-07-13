"""Geocode permit addresses: Census batch API, Nominatim fallback, JSON cache."""
import re

ADDR_RE = re.compile(
    r"^(?P<street>.+),\s*(?P<city>[^,]+),\s*MD\s*(?P<zip>\d{5})(-\d{4})?$")


def split_address(address):
    m = ADDR_RE.match(address)
    if not m:
        return None
    return m.group("street"), m.group("city"), m.group("zip")
