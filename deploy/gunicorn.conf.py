"""Nginx lokalny → Gunicorn; protokół i IP sprawdza pierwszy middleware."""

bind = "127.0.0.1:8000"
workers = 2
worker_class = "sync"
timeout = 120
graceful_timeout = 150
max_requests = 1000
max_requests_jitter = 100
forwarded_allow_ips = ""
secure_scheme_headers = {}
accesslog = "-"
# Nie logujemy query string, adresów e-mail, kodów OTP ani treści formularzy.
access_log_format = "%(h)s %(m)s %(s)s %(D)s"
errorlog = "-"
loglevel = "warning"
capture_output = True
