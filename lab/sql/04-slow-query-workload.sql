/*
    Slow-query lab: fill the plan cache
    ---------------------------------------------------------------------------
    find_slow_queries reads sys.dm_exec_query_stats, which only knows about
    queries that have run since the plan cache was last cleared (a restart
    clears it). This script runs a few deliberately inefficient queries
    several times each, so there is something to find.

    "GO 20" repeats the batch 20 times. It works in SSMS and sqlcmd.
    Runtime: a minute or two.
*/

USE Orders;
GO

-- 1. Non-sargable date filter: YEAR() on the column prevents an index seek, and
--    there's no index on OrderDate or Status anyway. Full scan of OrderHeader.
SELECT COUNT(*) AS pending_2026
FROM dbo.OrderHeader
WHERE YEAR(OrderDate) = 2026
  AND Status = 'Pending';
GO 20

-- 2. Join on the unindexed foreign key OrderLine.OrderId: scans OrderLine (~500k rows).
SELECT TOP (20) c.CustomerName, SUM(ol.Quantity * ol.UnitPrice) AS lifetime_value
FROM dbo.Customer AS c
JOIN dbo.OrderHeader AS o ON o.CustomerId = c.CustomerId
JOIN dbo.OrderLine AS ol ON ol.OrderId = o.OrderId
WHERE c.Region = 'East'
GROUP BY c.CustomerName
ORDER BY lifetime_value DESC;
GO 10

-- 3. Leading-wildcard LIKE: can't use any index, reads every Notes value.
SELECT COUNT(*) AS gift_lines
FROM dbo.OrderLine
WHERE Notes LIKE N'%gift%';
GO 10

-- 4. A cheap query for contrast: clustered index seek on the primary key.
SELECT OrderId, Status, TotalAmount
FROM dbo.OrderHeader
WHERE OrderId = 12345;
GO 50

/*
    Check what find_slow_queries should see once it's ported (#3 in SqlServer.Mcp):

    SELECT TOP (10)
        qs.execution_count,
        qs.total_worker_time / qs.execution_count AS avg_cpu_microseconds,
        SUBSTRING(st.text, 1, 200)              AS query_text
    FROM sys.dm_exec_query_stats AS qs
    CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
    ORDER BY avg_cpu_microseconds DESC;
*/
