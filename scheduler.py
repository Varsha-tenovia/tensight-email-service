from datetime import datetime, timezone

from croniter import croniter


def get_next_run(cron_expression):

    now = datetime.now(timezone.utc)

    cron = croniter(
        cron_expression,
        now
    )

    return cron.get_next(datetime)