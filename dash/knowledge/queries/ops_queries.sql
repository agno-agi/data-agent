-- <query name>current_drift_ledger</query name>
-- <query description>
-- What's my drift debt right now? Prioritized list of unresolved drift
-- with risk-weighted debt scores. Higher scores = more urgent.
-- </query description>
-- <query>
SELECT
    service_name,
    category,
    severity,
    desired_value,
    actual_value,
    blast_radius,
    EXTRACT(DAY FROM NOW() - first_seen_at) AS age_days,
    (CASE severity
        WHEN 'critical' THEN 10 WHEN 'high' THEN 5
        WHEN 'medium' THEN 2 ELSE 1
     END * blast_radius * EXTRACT(DAY FROM NOW() - first_seen_at)
    ) AS debt_score
FROM drift_observations
WHERE resolved_at IS NULL
ORDER BY debt_score DESC
LIMIT 20
-- </query>


-- <query name>drift_debt_trend</query name>
-- <query description>
-- Is our drift getting better or worse over time?
-- Weekly breakdown of resolved vs unresolved drift items.
-- </query description>
-- <query>
SELECT
    DATE_TRUNC('week', observed_at) AS week,
    COUNT(*) FILTER (WHERE resolved_at IS NULL) AS unresolved,
    COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved,
    ROUND(AVG(EXTRACT(DAY FROM COALESCE(resolved_at, NOW()) - first_seen_at)), 1)
        AS avg_age_days
FROM drift_observations
GROUP BY week
ORDER BY week DESC
LIMIT 12
-- </query>


-- <query name>version_triangulation</query name>
-- <query description>
-- Where do desired, actual, and latest versions disagree?
-- Finds triple-mismatches (all three different) and partial mismatches.
-- </query description>
-- <query>
SELECT
    d.service_name,
    d.image_tag AS desired,
    a.image_tag AS actual,
    u.latest AS latest_available,
    u.status AS update_status,
    CASE
        WHEN d.image_tag != a.image_tag AND a.image_tag != u.latest THEN 'triple-mismatch'
        WHEN d.image_tag != a.image_tag THEN 'desired-actual-mismatch'
        WHEN a.image_tag != u.latest THEN 'actual-latest-mismatch'
        ELSE 'aligned'
    END AS alignment
FROM desired_services d
LEFT JOIN actual_services a ON d.service_name = a.service_name
    AND a.observed_at = (SELECT MAX(observed_at) FROM actual_services)
LEFT JOIN update_status u ON d.service_name = u.service
WHERE d.image_tag != a.image_tag OR a.image_tag != u.latest
ORDER BY alignment, d.service_name
-- </query>


-- <query name>orphaned_routes</query name>
-- <query description>
-- Traefik routes pointing at dead or degraded services.
-- Finds services with domains configured but not running.
-- </query description>
-- <query>
SELECT
    d.service_name,
    d.domains,
    a.replicas,
    a.state
FROM desired_services d
LEFT JOIN actual_services a ON d.service_name = a.service_name
    AND a.observed_at = (SELECT MAX(observed_at) FROM actual_services)
WHERE d.domains IS NOT NULL
    AND d.domains != '{}'
    AND (a.service_name IS NULL OR a.replicas LIKE '0/%' OR a.state != 'running')
-- </query>


-- <query name>host_resource_pressure</query name>
-- <query description>
-- Which host is closest to trouble?
-- Shows disk and memory pressure with danger/warning classification.
-- </query description>
-- <query>
SELECT
    host,
    captured_at,
    disk_usage_pct,
    memory_usage_pct,
    docker_services,
    CASE
        WHEN disk_usage_pct > 85 OR memory_usage_pct > 85 THEN 'danger'
        WHEN disk_usage_pct > 70 OR memory_usage_pct > 70 THEN 'warning'
        ELSE 'healthy'
    END AS pressure_level
FROM state_snapshots
WHERE captured_at = (SELECT MAX(captured_at) FROM state_snapshots WHERE host = state_snapshots.host)
ORDER BY GREATEST(disk_usage_pct, memory_usage_pct) DESC
-- </query>


-- <query name>deploy_velocity</query name>
-- <query description>
-- How many deploys happened this week and how did they go?
-- Daily breakdown with success rates.
-- </query description>
-- <query>
SELECT
    DATE_TRUNC('day', occurred_at) AS day,
    COUNT(*) FILTER (WHERE event_type = 'deploy_started') AS started,
    COUNT(*) FILTER (WHERE event_type = 'deploy_succeeded') AS succeeded,
    COUNT(*) FILTER (WHERE event_type = 'deploy_failed') AS failed,
    ROUND(
        COUNT(*) FILTER (WHERE event_type = 'deploy_succeeded') * 100.0 /
        NULLIF(COUNT(*) FILTER (WHERE event_type = 'deploy_started'), 0),
        1
    ) AS success_pct
FROM deploy_events
WHERE occurred_at > NOW() - INTERVAL '7 days'
GROUP BY day
ORDER BY day DESC
-- </query>


-- <query name>crash_loop_detection</query name>
-- <query description>
-- Are any containers crash-looping?
-- Finds containers with > 3 restart events in the last hour.
-- </query description>
-- <query>
SELECT
    container_name,
    COUNT(*) AS restart_count,
    MIN(occurred_at) AS first_restart,
    MAX(occurred_at) AS last_restart,
    EXTRACT(EPOCH FROM MAX(occurred_at) - MIN(occurred_at)) / 60 AS span_minutes
FROM docker_events
WHERE event_type IN ('die', 'start')
    AND occurred_at > NOW() - INTERVAL '1 hour'
GROUP BY container_name
HAVING COUNT(*) > 3
ORDER BY restart_count DESC
-- </query>


-- <query name>update_backlog</query name>
-- <query description>
-- What's been outdated the longest?
-- Lists services with available updates, oldest first.
-- </query description>
-- <query>
SELECT
    service,
    deployed,
    latest,
    status,
    last_checked_at,
    EXTRACT(DAY FROM NOW() - last_checked_at) AS days_since_check,
    update_risk
FROM update_status
WHERE status IN ('UPDATE AVAILABLE', 'UPSTREAM CHANGES')
ORDER BY last_checked_at ASC
LIMIT 20
-- </query>


-- <query name>service_dependency_map</query name>
-- <query description>
-- What services share infrastructure with a given service?
-- Finds shared networks for blast-radius assessment.
-- </query description>
-- <query>
SELECT DISTINCT
    a1.service_name AS source_service,
    a2.service_name AS neighbor_service,
    UNNEST(a1.networks) AS shared_network
FROM actual_services a1
JOIN actual_services a2 ON a1.networks && a2.networks
    AND a1.service_name != a2.service_name
WHERE a1.service_name LIKE '%ghost%'
ORDER BY source_service, neighbor_service
-- </query>


-- <query name>platform_health_score</query name>
-- <query description>
-- What's the overall platform health score?
-- Composite indicator: active drift, OOM events, pending updates, disk, degraded services.
-- </query description>
-- <query>
SELECT
    (SELECT COUNT(*) FROM drift_observations WHERE resolved_at IS NULL) AS active_drift,
    (SELECT COUNT(*) FROM docker_events
        WHERE event_type = 'oom' AND occurred_at > NOW() - INTERVAL '24 hours') AS oom_24h,
    (SELECT COUNT(*) FROM update_status
        WHERE status IN ('UPDATE AVAILABLE', 'UPSTREAM CHANGES')) AS pending_updates,
    (SELECT AVG(disk_usage_pct) FROM state_snapshots
        WHERE captured_at > NOW() - INTERVAL '1 day') AS avg_disk_pct,
    (SELECT COUNT(*) FROM actual_services
        WHERE replicas LIKE '0/%') AS degraded_services
-- </query>
