/*
    OpsAgent lab database: Orders
    ---------------------------------------------------------------------------
    Creates a small order-processing database with data shaped for each
    SqlServer.Mcp tool:

      analyze_table              dbo.OrderHeader / dbo.OrderLine: real row counts and sizes,
                                 and a foreign key with no supporting index (OrderLine.OrderId)
      check_index_fragmentation  dbo.AuditEvent: random GUID clustered key, inserted in
                                 batches then thinned out, so it fragments badly
      find_slow_queries          no index on OrderHeader.OrderDate / Status; run
                                 04-slow-query-workload.sql to fill the plan cache
      check_blocking             run 02 and 03 in separate windows

    Matches the sample alert alerts/blocking-orders.json (database Orders,
    object dbo.OrderHeader).

    Requires SQL Server 2022 or later (uses GENERATE_SERIES). Lab use only:
    the first section DROPS any existing database called Orders.
    Runtime: under a minute on a laptop.
*/

SET NOCOUNT ON;
GO

/* ---------------------------------------------------------------------------
   1. Recreate the database
   ------------------------------------------------------------------------- */
USE master;
GO

IF DB_ID(N'Orders') IS NOT NULL
BEGIN
    ALTER DATABASE Orders SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE Orders;
END;
GO

CREATE DATABASE Orders;
GO

-- Simple recovery keeps the log small while generating data.
-- READ_COMMITTED_SNAPSHOT stays OFF (the default) so readers block behind writers in the blocking lab.
ALTER DATABASE Orders SET RECOVERY SIMPLE;
GO

USE Orders;
GO

/* ---------------------------------------------------------------------------
   2. Schema
   ------------------------------------------------------------------------- */
CREATE TABLE dbo.Customer
(
    CustomerId   int IDENTITY(1, 1) NOT NULL CONSTRAINT PK_Customer PRIMARY KEY CLUSTERED,
    CustomerName nvarchar(100)      NOT NULL,
    Email        varchar(200)       NOT NULL,
    Region       varchar(20)        NOT NULL,
    CreatedAt    datetime2(0)       NOT NULL
);

CREATE TABLE dbo.Product
(
    ProductId   int IDENTITY(1, 1) NOT NULL CONSTRAINT PK_Product PRIMARY KEY CLUSTERED,
    ProductName nvarchar(100)      NOT NULL,
    Category    varchar(30)        NOT NULL,
    UnitPrice   decimal(10, 2)     NOT NULL
);

CREATE TABLE dbo.OrderHeader
(
    OrderId        int IDENTITY(1, 1) NOT NULL CONSTRAINT PK_OrderHeader PRIMARY KEY CLUSTERED,
    CustomerId     int                NOT NULL CONSTRAINT FK_OrderHeader_Customer REFERENCES dbo.Customer (CustomerId),
    OrderDate      datetime2(0)       NOT NULL,
    Status         varchar(20)        NOT NULL,
    TotalAmount    decimal(12, 2)     NOT NULL CONSTRAINT DF_OrderHeader_TotalAmount DEFAULT (0),
    ShippingRegion varchar(20)        NOT NULL
);

CREATE NONCLUSTERED INDEX IX_OrderHeader_CustomerId ON dbo.OrderHeader (CustomerId);
-- Deliberately NO index on OrderDate or Status: date-range and status queries scan.

CREATE TABLE dbo.OrderLine
(
    OrderLineId bigint IDENTITY(1, 1) NOT NULL CONSTRAINT PK_OrderLine PRIMARY KEY CLUSTERED,
    OrderId     int                   NOT NULL CONSTRAINT FK_OrderLine_OrderHeader REFERENCES dbo.OrderHeader (OrderId),
    ProductId   int                   NOT NULL CONSTRAINT FK_OrderLine_Product REFERENCES dbo.Product (ProductId),
    Quantity    int                   NOT NULL,
    UnitPrice   decimal(10, 2)        NOT NULL,
    Notes       nvarchar(200)         NULL
);
-- Deliberately NO index on OrderLine.OrderId: joins from OrderHeader scan the whole table.

CREATE TABLE dbo.AuditEvent
(
    AuditEventId uniqueidentifier NOT NULL
        CONSTRAINT DF_AuditEvent_Id DEFAULT (NEWID())
        CONSTRAINT PK_AuditEvent PRIMARY KEY CLUSTERED,   -- random key: page splits on insert
    EventAt      datetime2(3)     NOT NULL,
    EventType    varchar(30)      NOT NULL,
    Payload      nvarchar(400)    NOT NULL
);
GO

/* ---------------------------------------------------------------------------
   3. Data
   CHECKSUM(NEWID(), <column>) is correlated with the row, so the optimiser
   evaluates it per row instead of once for the whole statement.
   ------------------------------------------------------------------------- */

-- 5,000 customers
INSERT dbo.Customer (CustomerName, Email, Region, CreatedAt)
SELECT
    CONCAT(N'Customer ', s.value),
    CONCAT('customer', s.value, '@example.com'),
    CHOOSE(1 + s.value % 5, 'East', 'West', 'North', 'South', 'Central'),
    DATEADD(DAY, -(s.value % 1500), CAST('2026-10-31' AS datetime2(0)))
FROM GENERATE_SERIES(1, 5000) AS s;

-- 500 products
INSERT dbo.Product (ProductName, Category, UnitPrice)
SELECT
    CONCAT(N'Product ', s.value),
    CHOOSE(1 + s.value % 6, 'Hardware', 'Software', 'Office', 'Furniture', 'Networking', 'Accessories'),
    CAST(5 + (s.value * 37) % 495 + 0.99 AS decimal(10, 2))
FROM GENERATE_SERIES(1, 500) AS s;

-- 200,000 orders over the two years before 2026-10-31
INSERT dbo.OrderHeader (CustomerId, OrderDate, Status, ShippingRegion)
SELECT
    1 + ABS(CHECKSUM(NEWID(), s.value)) % 5000,
    DATEADD(MINUTE, -(ABS(CHECKSUM(NEWID(), s.value)) % (730 * 24 * 60)), CAST('2026-10-31T13:00:00' AS datetime2(0))),
    CASE
        WHEN r.pct < 70 THEN 'Shipped'
        WHEN r.pct < 85 THEN 'Delivered'
        WHEN r.pct < 95 THEN 'Pending'
        ELSE 'Cancelled'
    END,
    CHOOSE(1 + s.value % 5, 'East', 'West', 'North', 'South', 'Central')
FROM GENERATE_SERIES(1, 200000) AS s
CROSS APPLY (SELECT ABS(CHECKSUM(NEWID(), s.value)) % 100 AS pct) AS r;

-- 1 to 4 lines per order (about 500,000 rows)
INSERT dbo.OrderLine (OrderId, ProductId, Quantity, UnitPrice, Notes)
SELECT
    o.OrderId,
    p.ProductId,
    1 + ABS(CHECKSUM(NEWID(), o.OrderId, l.value)) % 5,
    p.UnitPrice,
    CASE WHEN (o.OrderId + l.value) % 10 = 0 THEN N'Gift wrap requested' END
FROM dbo.OrderHeader AS o
CROSS APPLY GENERATE_SERIES(1, 1 + o.OrderId % 4) AS l
CROSS APPLY (SELECT 1 + ABS(CHECKSUM(NEWID(), o.OrderId, l.value)) % 500 AS ProductId) AS pick
JOIN dbo.Product AS p ON p.ProductId = pick.ProductId;

-- Order totals from their lines
UPDATE o
SET o.TotalAmount = t.Total
FROM dbo.OrderHeader AS o
JOIN
(
    SELECT OrderId, SUM(Quantity * UnitPrice) AS Total
    FROM dbo.OrderLine
    GROUP BY OrderId
) AS t ON t.OrderId = o.OrderId;
GO

-- 150,000 audit events in 300 small batches. One big INSERT would be sorted by key
-- first and land in order; many batches with random GUIDs split pages all over the index.
DECLARE @batch int = 0;
WHILE @batch < 300
BEGIN
    INSERT dbo.AuditEvent (EventAt, EventType, Payload)
    SELECT
        DATEADD(SECOND, -(@batch * 500 + s.value), CAST('2026-10-31T13:00:00' AS datetime2(3))),
        CHOOSE(1 + s.value % 4, 'Login', 'OrderCreated', 'OrderUpdated', 'Export'),
        REPLICATE(N'x', 200 + s.value % 200)
    FROM GENERATE_SERIES(1, 500) AS s;

    SET @batch += 1;
END;

-- Remove about a third of the rows: leaves half-empty pages (low page density).
DELETE FROM dbo.AuditEvent
WHERE ABS(CHECKSUM(AuditEventId)) % 3 = 0;
GO

/* ---------------------------------------------------------------------------
   4. Optional: a read-only login for SqlServer.Mcp
   ---------------------------------------------------------------------------
   Needs SQL Server authentication enabled ("SQL Server and Windows Authentication
   mode" in Server Properties > Security, then restart the service). Without it,
   use Integrated Security for the lab, and remember your Windows login is
   probably sysadmin, so "read-only" is then only the MCP server's promise.

   Replace the password before running, and never commit the real one: it goes in
   SQLSERVER_CONNECTION as an environment variable, not in a file. The placeholder
   below fails the password policy on purpose.

   Uncomment to run. (No GO separators inside the comment: SSMS can split a
   batch on a GO even inside a block comment. USE works mid-batch.)
   ------------------------------------------------------------------------- */
/*
USE master;
IF SUSER_ID(N'opsagent_reader') IS NULL
    CREATE LOGIN opsagent_reader WITH PASSWORD = N'REPLACE_WITH_A_STRONG_PASSWORD', CHECK_POLICY = ON;

-- SQL Server 2022+: server DMVs such as sys.dm_exec_requests and sys.dm_exec_query_stats.
-- On older versions, or if a tool reports a permission error, use VIEW SERVER STATE instead.
GRANT VIEW SERVER PERFORMANCE STATE TO opsagent_reader;

USE Orders;
IF USER_ID(N'opsagent_reader') IS NULL
    CREATE USER opsagent_reader FOR LOGIN opsagent_reader;

ALTER ROLE db_datareader ADD MEMBER opsagent_reader;
GRANT VIEW DATABASE PERFORMANCE STATE TO opsagent_reader;   -- sys.dm_db_index_physical_stats
*/

/* ---------------------------------------------------------------------------
   5. Check the result
   ------------------------------------------------------------------------- */
USE Orders;
GO

SELECT t.name AS table_name, SUM(ps.row_count) AS row_count, SUM(ps.used_page_count) * 8 / 1024 AS used_mb
FROM sys.tables AS t
JOIN sys.dm_db_partition_stats AS ps ON ps.object_id = t.object_id AND ps.index_id IN (0, 1)
GROUP BY t.name
ORDER BY row_count DESC;

-- Expect PK_AuditEvent well above 30% fragmentation and low page density.
SELECT
    OBJECT_NAME(ips.object_id)              AS table_name,
    i.name                                  AS index_name,
    ips.page_count,
    ips.avg_fragmentation_in_percent,
    ips.avg_page_space_used_in_percent
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'SAMPLED') AS ips
JOIN sys.indexes AS i ON i.object_id = ips.object_id AND i.index_id = ips.index_id
WHERE ips.page_count >= 100
ORDER BY ips.avg_fragmentation_in_percent DESC;
GO
