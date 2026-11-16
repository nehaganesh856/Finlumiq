# Gunicorn configuration for Finlumiq on Render (Free / Starter tier).
# Render Free tier: 512 MB RAM, shared CPU.
# Using threaded workers avoids the overhead of forking multiple processes.

import multiprocessing

# 2 workers x 4 threads = 8 concurrent request slots with low memory overhead.
# Increase workers to 4 on a paid instance with >= 1 GB RAM.
workers = 2
worker_class = "gthread"
threads = 4

# Render Free tier can be slow to respond on first request (cold start).
# Give workers up to 120 s to handle AI + DB requests before killing them.
timeout = 120

# Graceful shutdown: finish in-flight requests within 30 s.
graceful_timeout = 30

# Keep-alive for load-balancer connections.
keepalive = 5

# Log to stdout so Render captures it.
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Reload on code changes in development (Render ignores this in production).
reload = False
