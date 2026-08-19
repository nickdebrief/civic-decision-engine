# FastAPI Test-Order Stabilisation

This maintenance correction is not a numbered CDE Platform stage.

## Finding

The reverse governance test order previously failed in Stage 62 with:

`AttributeError: 'HTMLResponse' object has no attribute 'content'`

The demonstrated trigger was the module-level import of
`api.routes.admin_session` in
`tests/test_stage66_1_deliberate_authority_classification.py`. That import
bound the real Starlette `HTMLResponse` before another test installed the
legacy process-global fake response classes.

## Correction

The Stage 66.1 test now imports `_stage66_html` only inside the two tests that
render the Stage 66.1 administrative form. Importing the test module therefore
does not prematurely bind the administrative route or depend on a prior stub
installation.

Fresh-process forward, reverse and mixed-order checks cover the demonstrated
boundary. The correction changes tests only; runtime routes, dependencies,
schemas, governance semantics and production behavior are unchanged.

## Boundary and limitation

This is test-order stabilisation, not complete FastAPI stub isolation. The
repository retains a legacy process-global fake-framework test architecture
outside this correction. It does not claim complete `sys.modules` restoration,
a hermetic application-module sandbox, or framework-equivalent fake responses.

A broader scoped-restoration experiment was evaluated and rejected because it
created duplicate application-module graphs and required disproportionate
call-site changes. Migration to the real FastAPI/Starlette response contract
remains a separate future test-maintenance project.
