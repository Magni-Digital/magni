"""Magni 2.0 pipeline package.

Each module does one job in the daily run:
    ingest    — read the CRM xlsx + inbox.csv into candidate practices
    fetch     — fetch a practice homepage (never raises)
    signals   — objective, individually-true site-weakness detectors
    score     — roll findings into a weakness score + qualify verdict
    observe   — ONE grounded, editable observation per qualified site
    verify    — email verification ladder (syntax → MX → optional API)
    dedupe    — persistent seen-set so a practice never appears twice
    normalize — shared field-cleaning + the dedupe key

run.py is the single entry point that chains them.
"""
