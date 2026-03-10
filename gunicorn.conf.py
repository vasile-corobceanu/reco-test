import multiprocessing

bind = "0.0.0.0:8000"

# Single worker — the scheduler must run in exactly one process.
# Scaling horizontally means running multiple containers, not multiple workers.
workers = 1
threads = 2

# Graceful shutdown
timeout = 120
graceful_timeout = 30

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Preload so the scheduler starts once before forking
preload_app = True