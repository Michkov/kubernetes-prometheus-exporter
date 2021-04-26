This is an experimental prometheus exporter for kubernetes jobs.

This polls kubernetes via API using service account (when running in cluster) or using current kubectl config.

Required parameters:
* NAMESPACE - kubernetes namespaces for job monitoring

Optional parameters:
* JOB_LABEL - identitification of job label which should be monitored. Default: app
* KUBERNETES_POLL_INTERVAL - polling interval in seconds. Default: 30 
