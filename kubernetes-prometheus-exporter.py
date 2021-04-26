#!/usr/bin/env python3
""" A simple prometheus exporter for kubernetes.

Scrapes kubernetes on an interval and exposes metrics about jobs.

"""

import logging
import os
import time

from datetime import datetime, timezone

from prometheus_client.core import (
    REGISTRY,
    CounterMetricFamily,
    HistogramMetricFamily,
)
from prometheus_client import start_http_server
from kubernetes import client, config

START = None

NAMESPACE = os.environ["NAMESPACE"]  # Required

JOB_LABEL = os.environ.get("JOB_LABEL", "app")

JOB_CACHE = {}

# In seconds
DURATION_BUCKETS = [
    10,
    30,
    60,  # 1 minute
    180,  # 3 minutes
    480,  # 8 minutes
    1200,  # 20 minutes
    3600,  # 1 hour
    7200,  # 2 hours
]

metrics = {}


def retrieve_jobs(namespace, batch_v1_api):
    data = []
    try:
        data = batch_v1_api.list_namespaced_job(namespace).items
    except client.rest.ApiException:
        logging.error("Unable to get jobs", exc_info=True)
    jobs = []
    for job in data:
        cache_job(job)
    for job in JOB_CACHE.values():
        if job.metadata.creation_timestamp < START:
            continue
        jobs.append(job)
    return jobs


def cache_job(job):
    if job.metadata.name not in JOB_CACHE:
        if job.status.active == 1:
            return
        if JOB_LABEL not in job.metadata.labels:
            return
        JOB_CACHE[job.metadata.name] = job


def get_app_labels(jobs):
    labels = {}
    for job in jobs:
        app_label = job.metadata.labels[JOB_LABEL]
        if app_label not in labels:
            labels[app_label] = []
        labels[app_label].append(job)
    return labels


def kubernetes_jobs_total(jobs):
    app_labels = get_app_labels(jobs)
    for label, data in app_labels.items():
        yield len(data), [label]


def find_applicable_buckets(duration):
    buckets = DURATION_BUCKETS + ["+Inf"]
    for bucket in buckets:
        if duration < float(bucket):
            yield bucket


def kubernetes_job_duration_seconds(app_jobs):
    duration_buckets = DURATION_BUCKETS + ["+Inf"]

    for app, jobs in get_app_labels(app_jobs).items():
        # Initialize with zeros.
        buckets_dict = {}
        for bucket in duration_buckets:
            buckets_dict[bucket] = 0
        durations = 0

        for job in jobs:
            duration = (
                job.status.completion_time - job.status.start_time
            ).total_seconds()
            durations += duration
            for bucket in find_applicable_buckets(duration):
                buckets_dict[bucket] += 1
        buckets = []
        for bucket in duration_buckets:
            buckets.append((str(bucket), buckets_dict[bucket]))
        yield buckets, durations, [app]


def scrape():
    try:
        config.load_incluster_config()
    except config.config_exception.ConfigException:
        config.load_kube_config()
    batch_v1_api = client.BatchV1Api()

    jobs = retrieve_jobs(NAMESPACE, batch_v1_api)
    kubernetes_jobs_total_family = CounterMetricFamily(
        "kubernetes_jobs_total", "Count of all kubernetes jobs", labels=[JOB_LABEL]
    )
    for value, labels in kubernetes_jobs_total(jobs):
        kubernetes_jobs_total_family.add_metric(labels, value)

    kubernetes_job_errors_total_family = CounterMetricFamily(
        "kubernetes_job_errors_total",
        "Count of all kubernetes job errors",
        labels=[JOB_LABEL],
    )
    error_jobs = [job for job in jobs if job.status.succeeded != 1]
    for value, labels in kubernetes_jobs_total(error_jobs):
        kubernetes_job_errors_total_family.add_metric(labels, value)

    kubernetes_job_duration_seconds_family = HistogramMetricFamily(
        "kubernetes_job_duration_seconds",
        "Histogram of kubernetes job durations",
        labels=[JOB_LABEL],
    )
    succeeded_jobs = [job for job in jobs if job.status.succeeded == 1]
    for buckets, duration_sum, labels in kubernetes_job_duration_seconds(
        succeeded_jobs
    ):
        kubernetes_job_duration_seconds_family.add_metric(
            labels, buckets, sum_value=duration_sum
        )

    # Replace this in one atomic operation to avoid race condition to the Expositor
    metrics.update(
        {
            "kubernetes_jobs_total": kubernetes_jobs_total_family,
            "kubernetes_job_errors_total": kubernetes_job_errors_total_family,
            "kubernetes_job_duration_seconds": kubernetes_job_duration_seconds_family,
        }
    )


class Expositor(object):
    """Responsible for exposing metrics to prometheus"""

    def collect(self):
        logging.info("Serving prometheus data")
        for key in sorted(metrics):
            yield metrics[key]


if __name__ == "__main__":
    now = datetime.utcnow()
    START = now.replace(tzinfo=timezone.utc)

    logging.basicConfig(level=logging.INFO)
    for collector in list(REGISTRY._collector_to_names):
        REGISTRY.unregister(collector)
    REGISTRY.register(Expositor())

    # Populate data before exposing over http
    scrape()
    start_http_server(8000)

    while True:
        time.sleep(int(os.environ.get("KUBERNETES_POLL_INTERVAL", "30")))
        scrape()
