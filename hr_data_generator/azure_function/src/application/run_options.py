"""Run options from the app settings: dry run and the as-of date."""

from datetime import date, datetime, time

from src.application.pipeline import validate_mode


def resolve_run_options(mode, dry_run, as_of, now=None):
    """Validate the run options and return (mode, dry_run, today).

    - `dry_run` (HR_SIMULATION_DRY_RUN) runs the whole write and rolls it back;
      it is only allowed for an incremental run.
    - `as_of` (HR_SIMULATION_AS_OF, YYYY-MM-DD, optional) replaces the real
      current date as the pipeline's `today`; a date in the future is rejected.
      Without it `today` is the real current date and time.
    """
    mode = validate_mode(mode)
    now = now or datetime.now()

    if dry_run and mode != "incremental":
        raise ValueError(
            "HR_SIMULATION_DRY_RUN is only allowed for an incremental run "
            "(a full run resets the database; validate it with a real run)."
        )

    if not as_of:
        return mode, bool(dry_run), now

    try:
        as_of_date = date.fromisoformat(str(as_of).strip())
    except ValueError as exc:
        raise ValueError(
            f"HR_SIMULATION_AS_OF must be a date formatted YYYY-MM-DD, got {as_of!r}."
        ) from exc
    if as_of_date > now.date():
        raise ValueError(
            f"HR_SIMULATION_AS_OF {as_of_date.isoformat()} is in the future "
            f"(today is {now.date().isoformat()})."
        )
    return mode, bool(dry_run), datetime.combine(as_of_date, time.min)
