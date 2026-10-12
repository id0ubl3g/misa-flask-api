from datetime import timedelta

CREATION_QUOTAS = {
    "1_month": {"weekly": 2, "monthly": 5},
    "6_months": {"weekly": 8, "monthly": 25},
    "1_year": {"weekly": 15, "monthly": 50}
}

QUOTA_WINDOWS = {
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30)
}

STORAGE_LIMITS = {
    "1_month": 5,
    "6_months": 25,
    "1_year": 50
}

ABUSE_LIMIT = "5 per minute"

STALE_JOB_AFTER = timedelta(minutes=10)
