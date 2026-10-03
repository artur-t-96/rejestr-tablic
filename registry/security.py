import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import RateBucket


@transaction.atomic
def rate_count(key, seconds=60):
    key = hashlib.sha256(key.encode()).hexdigest()
    bucket, _ = RateBucket.objects.get_or_create(key=key, defaults={"start": timezone.now()})
    bucket = RateBucket.objects.select_for_update().get(pk=bucket.pk)
    if bucket.start + timedelta(seconds=seconds) <= timezone.now():
        bucket.start, bucket.count = timezone.now(), 0
    bucket.count += 1
    bucket.save(update_fields=["start", "count"])
    retry = max(1, int((bucket.start + timedelta(seconds=seconds) - timezone.now()).total_seconds()) + 1)
    return bucket.count, retry


def rate_limit(key, limit=60, seconds=60):
    count, _ = rate_count(key, seconds)
    return count <= limit
