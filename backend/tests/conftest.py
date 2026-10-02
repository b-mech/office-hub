import pytest


@pytest.fixture(scope="session", autouse=True)
def force_celery_eager_for_tests():
    from app.workers.celery_app import celery_app

    previous_eager = celery_app.conf.task_always_eager
    previous_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = previous_eager
    celery_app.conf.task_eager_propagates = previous_propagates
