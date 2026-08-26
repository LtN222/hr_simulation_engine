"""Per-version cache of fact_employment grouped by Employee_Key.

Several functions - relevant experience, internal-move eligibility, career-
momentum scoring - each independently ask "what are this employee's own
employment rows?" by re-filtering the entire fact_employment table on every
call. Grouping it once and reusing that grouping turns each employee's
lookup into an O(1) dict access instead of an O(all employment rows) scan
repeated per employee, per candidate, per call site.

The cache is invalidated by fact_employment's object identity. Every
simulator that adds employment rows does so via `pd.concat(...)`, which
always produces a new DataFrame object, so a genuinely new set of rows
always triggers a rebuild. In-place mutations (attrition closing a row)
change values but not row identity, and don't change the outcome these
callers compute for the currently-active employees they evaluate, so they
don't need to force a rebuild.
"""
import pandas as pd

_EMPTY = pd.DataFrame()


def employment_history_for(state, employee_key):
    """Return this employee's own fact_employment rows, from a shared cache."""
    fact_employment = state.get("fact_employment")
    if fact_employment is None or fact_employment.empty:
        return _EMPTY
    if "Employee_Key" not in fact_employment.columns:
        return _EMPTY

    if state.get("_employment_by_employee_source") is not fact_employment:
        # dict(a_groupby_object) misfires on some pandas versions (it treats
        # the groupby's `.keys` attribute as a mapping's keys() method), so
        # build the dict from explicit iteration instead.
        state["_employment_by_employee"] = {
            key: group for key, group in fact_employment.groupby("Employee_Key")
        }
        state["_employment_by_employee_source"] = fact_employment

    return state["_employment_by_employee"].get(employee_key, _EMPTY)
