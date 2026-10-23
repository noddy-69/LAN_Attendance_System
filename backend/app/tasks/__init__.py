# Import celery_app so it is available as app.tasks.celery_app
# (needed by the `celery -A app.tasks.celery_app worker` command)
from app.tasks.celery_app import celery_app  # noqa: F401
