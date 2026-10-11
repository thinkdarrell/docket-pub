from docket.worker.scheduler import build_scheduler
from docket.worker.tasks import TASKS
from docket.worker.health import TASK_UUID_ENV


def test_transcript_pipeline_is_registered_at_10_central():
    sched = build_scheduler("America/Chicago")
    job = sched.get_job("transcript_pipeline")
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "10" and fields["minute"] == "0"
    assert "transcript_pipeline" in TASKS
    assert TASK_UUID_ENV["transcript_pipeline"] == "HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID"
