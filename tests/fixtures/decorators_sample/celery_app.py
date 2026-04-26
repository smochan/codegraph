"""Celery fixture for entry-point detection."""
from celery import Celery, shared_task

celery_app = Celery("tasks")


@celery_app.task
def process_payment(amount: int) -> int:
    return amount


@shared_task(bind=True)
def cleanup_files(self, path: str) -> str:
    return path


def _local_helper() -> None:
    pass
