import os

bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = int(os.environ.get("RENDER_WEB_CONCURRENCY", "1"))
worker_class = "sync"
timeout = 120
graceful_timeout = 20
forwarded_allow_ips = ""
secure_scheme_headers = {}
accesslog = "-"
access_log_format = "%(m)s %(s)s %(D)s"
errorlog = "-"
loglevel = "warning"
