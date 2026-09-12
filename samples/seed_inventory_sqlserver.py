#!/usr/bin/env python3
"""Azure SQL Database に在庫サンプル（表・ビュー・読み取り専用ユーザー）を作る。

セットアップ専用のスクリプト。第4章の実行には使わない。

使い方::

    uv run --env-file .env --with pymssql python samples/seed_inventory_sqlserver.py

必要な環境変数（``.env`` に記載する）:

    MSSQL_HOST / MSSQL_PORT / MSSQL_DATABASE
    MSSQL_ADMIN_USER / MSSQL_ADMIN_PASSWORD   管理者（表とユーザーを作る権限）
    MSSQL_USER / MSSQL_PASSWORD               作成する読み取り専用ユーザーとそのパスワード

作成するもの:

    dbo.Inventory           在庫の元データ（12 商品）
    dbo.InventoryOrderView  入荷時点の予測在庫・推奨発注量・アラート理由を計算するビュー
    読み取り専用ユーザー    上記ビューへの SELECT だけを許可

予測式と判定はビュー側で計算する。DeepSeek には計算させない。
"""

from __future__ import annotations

import os
import sys

import pymssql

DATA_ASOF = "2026-09-12"

DDL = [
    "IF OBJECT_ID('dbo.InventoryOrderView', 'V') IS NOT NULL DROP VIEW dbo.InventoryOrderView",
    "IF OBJECT_ID('dbo.Inventory', 'U') IS NOT NULL DROP TABLE dbo.Inventory",
    """
    CREATE TABLE dbo.Inventory (
        ProductCode     NVARCHAR(20)  NOT NULL PRIMARY KEY,
        ProductName     NVARCHAR(100) NOT NULL,
        AvailableStock  INT           NOT NULL,
        AvgDailySales   DECIMAL(10,2) NOT NULL,
        InboundQty      INT           NULL,
        InboundDate     DATE          NULL,
        SafetyStockDays INT           NOT NULL,
        LeadTimeDays    INT           NOT NULL,
        OrderLot        INT           NOT NULL,
        DataAsOf        DATE          NOT NULL
    )
    """,
    """
    CREATE VIEW dbo.InventoryOrderView AS
    WITH base AS (
        SELECT
            i.ProductCode, i.ProductName, i.AvailableStock, i.AvgDailySales,
            i.InboundQty, i.InboundDate, i.SafetyStockDays, i.LeadTimeDays,
            i.OrderLot, i.DataAsOf,
            CAST(ISNULL(i.InboundQty, 0) AS INT) AS InboundQtyFilled,
            CASE
                WHEN i.InboundDate IS NULL THEN i.LeadTimeDays
                WHEN DATEDIFF(day, i.DataAsOf, i.InboundDate) < i.LeadTimeDays THEN i.LeadTimeDays
                ELSE DATEDIFF(day, i.DataAsOf, i.InboundDate)
            END AS DaysUntilArrival
        FROM dbo.Inventory AS i
    ),
    calc AS (
        SELECT
            b.*,
            CAST(FLOOR(
                b.AvailableStock + b.InboundQtyFilled
                - (b.AvgDailySales * (b.DaysUntilArrival + b.SafetyStockDays))
            ) AS INT) AS PredictedStockAtArrival
        FROM base AS b
    )
    SELECT
        c.ProductCode,
        c.ProductName,
        c.AvailableStock,
        c.AvgDailySales,
        c.InboundQty,
        c.InboundDate,
        c.SafetyStockDays,
        c.LeadTimeDays,
        c.OrderLot,
        c.DataAsOf,
        c.PredictedStockAtArrival,
        CASE
            WHEN c.AvgDailySales <= 0 THEN 0
            WHEN c.PredictedStockAtArrival >= 0 THEN 0
            ELSE CAST(CEILING((0 - c.PredictedStockAtArrival) / CAST(c.OrderLot AS DECIMAL(10,2))) * c.OrderLot AS INT)
        END AS RecommendedOrderQty,
        CASE
            WHEN c.AvgDailySales <= 0 THEN 2
            WHEN c.InboundDate IS NULL AND c.AvailableStock < (c.AvgDailySales * c.LeadTimeDays) THEN 1
            WHEN c.PredictedStockAtArrival < 0 THEN 1
            WHEN c.InboundDate IS NULL THEN 2
            WHEN c.PredictedStockAtArrival < (c.AvgDailySales * c.SafetyStockDays) THEN 2
            ELSE 3
        END AS Priority,
        CASE
            WHEN c.AvgDailySales <= 0 THEN N'販売実績が不足しており需要を計算できません'
            WHEN c.InboundDate IS NULL AND c.AvailableStock < (c.AvgDailySales * c.LeadTimeDays)
                THEN N'入荷予定日が未定のまま在庫が不足します'
            WHEN c.PredictedStockAtArrival < 0 THEN N'入荷時点で在庫が不足します'
            WHEN c.InboundDate IS NULL THEN N'入荷予定日が未登録です'
            WHEN c.PredictedStockAtArrival < (c.AvgDailySales * c.SafetyStockDays) THEN N'安全在庫を下回る見込みです'
            ELSE N'発注の必要はありません'
        END AS AlertReason
    FROM calc AS c
    """,
]

# ProductCode, ProductName, AvailableStock, AvgDailySales, InboundQty, InboundDate,
# SafetyStockDays, LeadTimeDays, OrderLot
ROWS = [
    ("SKU-1001", "ステンレスボトル 500ml", 12, 8.0, None, None, 5, 10, 100),
    ("SKU-1002", "折りたたみ傘", 40, 6.0, 200, "2026-09-20", 5, 12, 50),
    ("SKU-1003", "モバイルバッテリー 10000mAh", 30, 12.0, None, None, 5, 14, 60),
    ("SKU-1004", "ノートPCスタンド", 80, 3.5, 40, "2026-09-25", 7, 15, 20),
    ("SKU-1005", "無線イヤホン", 120, 9.0, None, None, 10, 20, 100),
    ("SKU-1006", "USB-Cケーブル 2m", 300, 15.0, 500, "2026-09-26", 14, 21, 500),
    ("SKU-1007", "デスクライト", 60, 0.0, None, None, 10, 18, 30),
    ("SKU-1008", "収納ボックス L", 300, 5.0, 100, "2026-09-30", 10, 10, 100),
    ("SKU-1009", "ハンドタオル 5枚組", 90, 4.0, 60, "2026-10-05", 14, 9, 40),
    ("SKU-1010", "スマホリング", 15, 2.0, 20, "2026-09-28", 10, 14, 20),
    ("SKU-1011", "ノート A5 3冊組", 200, 7.0, None, None, 7, 12, 100),
    ("SKU-1012", "卓上カレンダー 2027", 500, 1.5, None, "2026-09-18", 20, 25, 50),
]


def _require(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} が未設定です")
    return value


def main() -> int:
    host = _require("MSSQL_HOST")
    port = int(_require("MSSQL_PORT"))
    database = _require("MSSQL_DATABASE")
    admin_user = _require("MSSQL_ADMIN_USER")
    admin_password = _require("MSSQL_ADMIN_PASSWORD")
    read_only_user = _require("MSSQL_USER")
    read_only_password = _require("MSSQL_PASSWORD")

    conn = pymssql.connect(
        server=host,
        port=port,
        user=admin_user,
        password=admin_password,
        database=database,
        tds_version="7.4",
        login_timeout=30,
        timeout=120,
        charset="UTF-8",
    )
    conn.autocommit(True)
    cur = conn.cursor()
    print(f"connected: {host} / {database}")

    for statement in DDL:
        cur.execute(statement)
    print("created: dbo.Inventory / dbo.InventoryOrderView")

    cur.executemany(
        "INSERT INTO dbo.Inventory (ProductCode, ProductName, AvailableStock, AvgDailySales,"
        " InboundQty, InboundDate, SafetyStockDays, LeadTimeDays, OrderLot, DataAsOf)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [row + (DATA_ASOF,) for row in ROWS],
    )
    print(f"inserted: {len(ROWS)} rows")

    cur.execute("SELECT COUNT(*) FROM sys.database_principals WHERE name = %s", (read_only_user,))
    if cur.fetchone()[0]:
        cur.execute(f"DROP USER [{read_only_user}]")
    cur.execute(f"CREATE USER [{read_only_user}] WITH PASSWORD = %s", (read_only_password,))
    cur.execute(f"GRANT SELECT ON dbo.InventoryOrderView TO [{read_only_user}]")
    print(f"created: read-only user {read_only_user} (SELECT on dbo.InventoryOrderView only)")

    cur.execute(
        "SELECT ProductCode, ProductName, AvailableStock, PredictedStockAtArrival,"
        " RecommendedOrderQty, Priority, AlertReason"
        " FROM dbo.InventoryOrderView ORDER BY Priority, ProductCode"
    )
    print("\ncode      name                          stock  pred  order  pri  reason")
    for code, name, stock, predicted, order, priority, reason in cur.fetchall():
        print(f"{code}  {name:<28} {stock:>5} {predicted:>5} {order:>6}  {priority:>3}  {reason}")

    conn.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
