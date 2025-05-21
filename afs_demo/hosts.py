import re
from django_hosts import patterns, host

host_patterns = patterns(
    "",
    host(re.sub(r"_", r"-", r"afs_demo"), "afs_demo.urls", name="afs_demo"),
)
