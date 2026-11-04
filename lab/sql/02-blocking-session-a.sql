/*
    Blocking lab, window A: the head blocker
    ---------------------------------------------------------------------------
    1. Run this script in one SSMS query window. It opens a transaction, changes
       1,000 orders and leaves the transaction OPEN, holding exclusive locks.
    2. Open one or two more windows and run 03-blocking-session-b.sql in each.
       They will hang: they are blocked by this window.
    3. Now run diagnose, or call check_blocking in MCP Inspector.
    4. Come back here and run the ROLLBACK at the bottom. The other windows finish.

    What the DMVs show (worth knowing before you read the agent's diagnosis):
    this session is idle ("sleeping") with an open transaction, so it does NOT
    appear in sys.dm_exec_requests itself. It shows up only as the
    blocking_session_id of the blocked requests. A head blocker that isn't
    running anything is the classic hard case: the usual culprit is an
    application that opened a transaction and never committed it.
*/

USE Orders;
GO

SELECT @@SPID AS head_blocker_session_id;   -- note this number; it should appear as blocking_session_id

BEGIN TRANSACTION;

UPDATE dbo.OrderHeader
SET Status = 'OnHold'          -- a real change, so the row locks are certainly taken
WHERE OrderId BETWEEN 1 AND 1000;

-- The transaction stays open. Do not close this window without rolling back.

-- When you're done, select and run this line:
-- ROLLBACK TRANSACTION;
