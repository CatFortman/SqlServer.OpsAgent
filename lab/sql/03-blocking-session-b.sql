/*
    Blocking lab, window B (and C): blocked sessions
    ---------------------------------------------------------------------------
    Run AFTER 02-blocking-session-a.sql, in a separate SSMS window. Each copy
    you run becomes one more blocked session. It hangs until window A rolls back.

    Pick one statement:
      - The UPDATE always blocks behind window A's exclusive locks.
      - The SELECT blocks too, as long as READ_COMMITTED_SNAPSHOT is OFF on
        Orders (the default; 01-create-orders-lab.sql leaves it off). With RCSI on,
        readers see the last committed version and don't block. That difference
        is worth seeing for yourself once.
*/

USE Orders;
GO

SELECT @@SPID AS blocked_session_id;

-- Option 1: writer blocked by writer
UPDATE dbo.OrderHeader
SET Status = 'Pending'
WHERE OrderId = 500;

-- Option 2: reader blocked by writer (comment out Option 1 to use this instead)
-- SELECT OrderId, Status, TotalAmount
-- FROM dbo.OrderHeader
-- WHERE OrderId BETWEEN 400 AND 600;

/*
    While this hangs, run this in a fourth window to see what check_blocking should see:

    SELECT r.session_id, r.blocking_session_id, r.wait_type, r.wait_time, r.status
    FROM sys.dm_exec_requests AS r
    WHERE r.blocking_session_id <> 0;
*/
